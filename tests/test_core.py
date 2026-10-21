import json

import pytest

from ledgerline_crm.audit import verify_file
from ledgerline_crm.seed import seed
from ledgerline_crm.store import Store
from mcp_server.server import build_server


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "crm.db", tmp_path / "audit.jsonl")
    seed(result)
    return result


def proposal(store, run_id="test-run", lead_id="injection", **changes):
    args = dict(
        lead_id=lead_id,
        route="sales_reply",
        priority="normal",
        draft_reply="Thanks for your interest. May we schedule a discovery call?",
        rationale="SMB inquiry",
        citations=["kb-policy"],
    )
    args.update(changes)
    return store.propose(run_id, **args)


def test_seed_deterministic(store):
    first = store.rows("SELECT * FROM accounts ORDER BY id")
    seed(store)
    assert store.rows("SELECT * FROM accounts ORDER BY id") == first
    assert len(first) == 25
    assert len(store.rows("SELECT * FROM leads")) == 15


def test_lookup_history_opportunities(store):
    account = store.lookup_account(domain="mossforge.example")[0]
    assert account["status"] == "customer"
    assert "internal_notes" not in account
    assert store.get_contact_history("orin@mossforge.example")
    assert store.find_open_opportunities("a03")
    assert store.search_knowledge_base("pricing")


@pytest.mark.parametrize(
    "changes",
    [
        {"route": "send_email"},
        {"priority": "urgent"},
        {"citations": ["made-up"]},
        {"lead_id": "missing"},
        {"draft_reply": ""},
    ],
)
def test_proposal_validation(store, changes):
    with pytest.raises(ValueError):
        proposal(store, **changes)
    assert not store.rows("SELECT * FROM proposals")


def test_one_proposal_per_run(store):
    proposal(store)
    with pytest.raises(ValueError, match="already"):
        proposal(store)
    assert len(store.rows("SELECT * FROM proposals")) == 1


def test_review_edit_approve_and_replay(store):
    item = proposal(store)
    store.review(item["id"], "edit_approve", "reviewer-fictional", "Updated draft", "clarity")
    assert store.rows("SELECT * FROM proposals")[0]["status"] == "approved"
    assert store.rows("SELECT * FROM outbox")[0]["draft_reply"] == "Updated draft"
    with pytest.raises(ValueError, match="pending"):
        store.review(item["id"], "approve", "reviewer-fictional")
    assert len(store.rows("SELECT * FROM outbox")) == 1
    assert store.verify_audit() == 3
    events = [json.loads(line) for line in store.audit_path.read_text().splitlines()]
    assert events[1]["event"] == "proposal_edited_approved"
    assert events[1]["data"]["diff"]["before"] != events[1]["data"]["diff"]["after"]


def test_reject_requires_reason_and_never_outboxes(store):
    item = proposal(store)
    with pytest.raises(ValueError):
        store.review(item["id"], "reject", "reviewer-fictional")
    store.review(item["id"], "reject", "reviewer-fictional", reason="Not relevant")
    assert not store.rows("SELECT * FROM outbox")
    assert store.verify_audit() == 2


def test_audit_detects_changed_bytes_and_truncation(store):
    proposal(store)
    assert store.verify_audit() == 1
    original = store.audit_path.read_text()
    store.audit_path.write_text(original.replace("SMB inquiry", "tampered"))
    with pytest.raises(ValueError, match="hash"):
        verify_file(store.audit_path)
    store.audit_path.write_text("")
    with pytest.raises(ValueError, match="mirror"):
        store.verify_audit()


async def test_mcp_tool_surface_and_bad_route(store):
    server = build_server(store, "wire-run", "injection", None)
    tools = await server.list_tools()
    assert {t.name for t in tools} == {
        "lookup_account",
        "get_contact_history",
        "find_open_opportunities",
        "search_knowledge_base",
        "propose_action",
    }
    with pytest.raises(Exception):
        await server.call_tool(
            "propose_action",
            dict(
                lead_id="injection",
                route="send",
                priority="normal",
                draft_reply="Hello",
                rationale="bad",
                citations=[],
            ),
        )
    assert not store.rows("SELECT * FROM proposals")


async def test_server_binds_lead_and_records_research(store, tmp_path):
    trace = tmp_path / "trace.jsonl"
    server = build_server(store, "wire-run", "injection", trace)
    await server.call_tool("lookup_account", {"domain": "bramblecoil.example"})
    with pytest.raises(Exception):
        await server.call_tool(
            "propose_action",
            dict(
                lead_id="smb",
                route="sales_reply",
                priority="normal",
                draft_reply="Hi",
                rationale="wrong lead",
                citations=[],
            ),
        )
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    assert events[0]["name"] == "lookup_account"
    assert events[0]["latency_ms"] >= 0
    assert events[0]["result_bytes"] > 0
