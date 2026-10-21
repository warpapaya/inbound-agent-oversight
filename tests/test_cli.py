import json
import subprocess
import sys

from ledgerline_crm.seed import seed
from ledgerline_crm.store import Store


def test_cli_lists_and_approves_original_draft(tmp_path):
    store = Store(tmp_path / "crm.db", tmp_path / "audit.jsonl")
    seed(store)
    item = store.propose(
        "cli-proof", "smb", "sales_reply", "normal", "A synthetic draft", "fit", []
    )
    prefix = [
        sys.executable,
        "-m",
        "review.cli",
        "--db",
        str(store.db_path),
        "--audit",
        str(store.audit_path),
    ]
    listed = subprocess.run(prefix + ["list"], capture_output=True, text=True, check=True)
    assert json.loads(listed.stdout)["lead"]["id"] == "smb"
    approved = subprocess.run(
        prefix + ["approve", str(item["id"]), "--who", "Fictional Reviewer"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(approved.stdout)["status"] == "approved"
    assert store.rows("SELECT * FROM outbox")[0]["draft_reply"] == "A synthetic draft"
    assert store.verify_audit() == 3


def test_cli_reject_requires_reason(tmp_path):
    store = Store(tmp_path / "crm.db", tmp_path / "audit.jsonl")
    seed(store)
    item = store.propose("cli-proof", "spam", "disqualify", "low", "No thanks", "spam", [])
    command = [
        sys.executable,
        "-m",
        "review.cli",
        "--db",
        str(store.db_path),
        "--audit",
        str(store.audit_path),
        "reject",
        str(item["id"]),
        "--who",
        "Fictional Reviewer",
    ]
    assert subprocess.run(command, capture_output=True).returncode != 0
    rejected = subprocess.run(
        command + ["--reason", "Spam"], capture_output=True, text=True, check=True
    )
    assert json.loads(rejected.stdout)["status"] == "rejected"
    assert not store.rows("SELECT * FROM outbox")
