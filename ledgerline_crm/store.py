"""SQLite-backed sandbox. All workflow mutations use one audited transaction."""

import fcntl
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ledgerline_crm.audit import GENESIS, canonical, entry, verify_file

ROUTES = {"sales_reply", "route_to_ae", "support_handoff", "disqualify", "needs_human"}
PRIORITIES = {"low", "normal", "high"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT UNIQUE NOT NULL,
 employees INTEGER NOT NULL, status TEXT NOT NULL, owner TEXT NOT NULL,
 internal_notes TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contacts (
 email TEXT PRIMARY KEY, account_id TEXT REFERENCES accounts(id), name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunities (
 id TEXT PRIMARY KEY, account_id TEXT REFERENCES accounts(id), stage TEXT NOT NULL,
 owner TEXT NOT NULL, potential_arr INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS interactions (
 id TEXT PRIMARY KEY, email TEXT REFERENCES contacts(email), summary TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kb (id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS leads (
 id TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT NOT NULL,
 company TEXT NOT NULL, channel TEXT NOT NULL, message TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proposals (
 id INTEGER PRIMARY KEY, run_id TEXT UNIQUE NOT NULL,
 lead_id TEXT NOT NULL REFERENCES leads(id), route TEXT NOT NULL,
 priority TEXT NOT NULL, draft_reply TEXT NOT NULL, rationale TEXT NOT NULL,
 citations TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (
 id INTEGER PRIMARY KEY, proposal_id INTEGER UNIQUE NOT NULL REFERENCES proposals(id),
 draft_reply TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events (
 seq INTEGER PRIMARY KEY, record TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
 BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
 BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
"""


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path="local/crm.db", audit_path="local/audit.jsonl"):
        self.db_path = Path(db_path).resolve()
        self.audit_path = Path(audit_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
        self.audit_path.touch(exist_ok=True)

    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def lookup_account(self, domain=None, name=None):
        if not (domain or name):
            raise ValueError("domain or name required")
        return self.rows(
            """SELECT id,name,domain,employees,status,owner FROM accounts
            WHERE lower(domain)=lower(?) OR lower(name)=lower(?)""",
            (domain, name),
        )

    def get_contact_history(self, email):
        return self.rows(
            """SELECT c.name,c.account_id,i.summary FROM contacts c
            LEFT JOIN interactions i ON i.email=c.email WHERE lower(c.email)=lower(?)""",
            (email,),
        )

    def find_open_opportunities(self, account_id):
        return self.rows(
            "SELECT * FROM opportunities WHERE account_id=? AND stage!='closed'", (account_id,)
        )

    def search_knowledge_base(self, query):
        # Small transparent lexical retriever: nonmatching documents are not evidence.
        import re

        stopwords = {
            "the",
            "and",
            "for",
            "with",
            "what",
            "are",
            "our",
            "can",
            "a",
            "to",
            "of",
            "in",
        }
        terms = set(re.findall(r"[a-z0-9]+", query.lower())) - stopwords
        ranked = []
        for document in self.rows("SELECT * FROM kb ORDER BY id"):
            title = set(re.findall(r"[a-z0-9]+", document["title"].lower()))
            body = set(re.findall(r"[a-z0-9]+", document["body"].lower()))
            score = 3 * len(terms & title) + len(terms & body)
            if score:
                ranked.append((score, document))
        return [doc for _, doc in sorted(ranked, key=lambda pair: -pair[0])]

    def verify_audit(self):
        records = verify_file(self.audit_path)
        mirror = [
            json.loads(r["record"])
            for r in self.rows("SELECT record FROM audit_events ORDER BY seq")
        ]
        if records != mirror:
            raise ValueError("audit mirror mismatch (possible truncation or interrupted export)")
        return len(records)

    @contextmanager
    def mutation(self):
        # Cooperating processes serialize DB commit + append. A crash in between fails closed
        # on the next write; deliberately no automatic overwrite of suspicious audit bytes.
        with self.audit_path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.verify_audit()
            db = self.connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                old_count = db.execute("SELECT count(*) FROM audit_events").fetchone()[0]
                yield db
                pending = [
                    r[0]
                    for r in db.execute(
                        "SELECT record FROM audit_events WHERE seq>? ORDER BY seq", (old_count,)
                    )
                ]
                db.commit()
                with self.audit_path.open("a") as stream:
                    for line in pending:
                        stream.write(line + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
                fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def audit(db, event, who, data):
        last = db.execute("SELECT record FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = json.loads(last[0]) if last else {"seq": 0, "hash": GENESIS}
        record = entry(previous["seq"] + 1, previous["hash"], event, who, now(), data)
        db.execute("INSERT INTO audit_events VALUES (?,?)", (record["seq"], canonical(record)))

    def propose(self, run_id, lead_id, route, priority, draft_reply, rationale, citations):
        if route not in ROUTES or priority not in PRIORITIES:
            raise ValueError("invalid route or priority")
        if not draft_reply.strip() or not rationale.strip():
            raise ValueError("draft and rationale required")
        if len(draft_reply) > 12000 or len(rationale) > 6000:
            raise ValueError("proposal too long")
        kb_ids = {r["id"] for r in self.rows("SELECT id FROM kb")}
        if not isinstance(citations, list) or any(c not in kb_ids for c in citations):
            raise ValueError("citations must reference real KB ids")
        with self.mutation() as db:
            if not db.execute("SELECT 1 FROM leads WHERE id=?", (lead_id,)).fetchone():
                raise ValueError("unknown lead")
            if db.execute("SELECT 1 FROM proposals WHERE run_id=?", (run_id,)).fetchone():
                raise ValueError("run already has a proposal")
            cursor = db.execute(
                """INSERT INTO proposals
                (run_id,lead_id,route,priority,draft_reply,rationale,citations,status,created_at)
                VALUES (?,?,?,?,?,?,?,'pending',?)""",
                (
                    run_id,
                    lead_id,
                    route,
                    priority,
                    draft_reply,
                    rationale,
                    canonical(citations),
                    now(),
                ),
            )
            self.audit(
                db,
                "proposal_created",
                f"agent:{run_id}",
                dict(
                    proposal_id=cursor.lastrowid,
                    lead_id=lead_id,
                    route=route,
                    priority=priority,
                    draft_reply=draft_reply,
                    rationale=rationale,
                    citations=citations,
                ),
            )
            return {"id": cursor.lastrowid, "status": "pending"}

    def proposals(self, run_id=None):
        rows = self.rows(
            "SELECT * FROM proposals" + (" WHERE run_id=?" if run_id else ""),
            (run_id,) if run_id else (),
        )
        for row in rows:
            row["citations"] = json.loads(row["citations"])
        return rows

    def review(self, proposal_id, action, who, draft_reply=None, reason=""):
        if not who.strip() or action not in {"approve", "edit_approve", "reject"}:
            raise ValueError("reviewer and valid action required")
        if action == "reject" and not reason.strip():
            raise ValueError("rejection reason required")
        if action == "edit_approve" and (not draft_reply or not draft_reply.strip()):
            raise ValueError("edited draft required")
        with self.mutation() as db:
            row = db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
            if row is None or row["status"] != "pending":
                raise ValueError("proposal must be pending")
            after = draft_reply if action == "edit_approve" else row["draft_reply"]
            status = "rejected" if action == "reject" else "approved"
            db.execute(
                "UPDATE proposals SET draft_reply=?,status=? WHERE id=?",
                (after, status, proposal_id),
            )
            self.audit(
                db,
                {
                    "approve": "proposal_approved",
                    "edit_approve": "proposal_edited_approved",
                    "reject": "proposal_rejected",
                }[action],
                who,
                {
                    "proposal_id": proposal_id,
                    "reason": reason,
                    "diff": {"before": row["draft_reply"], "after": after},
                    "status": {"before": "pending", "after": status},
                },
            )
            if status == "approved":
                cursor = db.execute(
                    "INSERT INTO outbox(proposal_id,draft_reply,created_at) VALUES (?,?,?)",
                    (proposal_id, after, now()),
                )
                self.audit(
                    db,
                    "outbox_written",
                    who,
                    {
                        "proposal_id": proposal_id,
                        "outbox_id": cursor.lastrowid,
                        "draft_reply": after,
                        "simulated": True,
                    },
                )
