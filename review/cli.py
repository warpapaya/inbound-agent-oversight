import argparse
import json
from pathlib import Path

from ledgerline_crm.audit import verify_file
from ledgerline_crm.store import Store


def main():
    parser = argparse.ArgumentParser(description="Human review and audit CLI; never sends messages")
    parser.add_argument("--db", default="local/crm.db")
    parser.add_argument("--audit", default="local/audit.jsonl")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("verify-audit")
    for name in ("approve", "edit-approve", "reject"):
        command = sub.add_parser(name)
        command.add_argument("proposal_id", type=int)
        command.add_argument("--who", required=True)
        command.add_argument("--reason", default="", required=name == "reject")
        if name == "edit-approve":
            command.add_argument("--draft-file", type=Path, required=True)
    args = parser.parse_args()
    store = Store(args.db, args.audit)
    try:
        if args.command == "list":
            for p in store.proposals():
                if p["status"] != "pending":
                    continue
                p["lead"] = store.rows("SELECT * FROM leads WHERE id=?", (p["lead_id"],))[0]
                trace = Path("runs") / (p["run_id"] + ".jsonl")
                p["research_trail"] = (
                    [
                        json.loads(line)
                        for line in trace.read_text().splitlines()
                        if json.loads(line).get("type") == "tool"
                    ]
                    if trace.exists()
                    else []
                )
                print(json.dumps(p, indent=2, ensure_ascii=False))
        elif args.command == "verify-audit":
            count = store.verify_audit()
            records = verify_file(store.audit_path)
            print(
                f"PASS: {count} audit entries; head="
                + (records[-1]["hash"] if records else "genesis")
            )
        else:
            store.review(
                args.proposal_id,
                args.command.replace("-", "_"),
                args.who,
                args.draft_file.read_text() if hasattr(args, "draft_file") else None,
                args.reason,
            )
            print(
                json.dumps(
                    store.rows("SELECT id,status FROM proposals WHERE id=?", (args.proposal_id,))[0]
                )
            )
    except ValueError as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    main()
