"""Exercise real review forms against local synthetic data; never sends anything.

Run: uv run --with playwright python scripts/prove_review.py
A review server must already be listening on http://127.0.0.1:8765.
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ledgerline_crm.store import Store  # noqa: E402


def main():
    store = Store()
    selected = {}
    for lead in ("injection", "smb", "midmarket", "spam"):
        selected[lead] = next(
            p
            for p in reversed(store.proposals())
            if p["lead_id"] == lead and p["run_id"].startswith("v1-") and p["status"] == "pending"
        )
    evidence = ROOT / "evidence"
    evidence.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8765/")
        page.get_by_role("heading", name="Human review queue").wait_for()

        def article(lead):
            return page.locator("article").filter(
                has=page.locator(f'input[name="proposal_id"][value="{selected[lead]["id"]}"]')
            )

        pending = article("injection")
        assert pending.locator(".badge").inner_text() == "pending"
        pending.screenshot(path=str(evidence / "review-pending.png"))
        for lead, button, action in (
            ("smb", "Approve original", "approve"),
            ("midmarket", "Edit + approve", "edit_approve"),
            ("spam", "Reject", "reject"),
        ):
            target = article(lead)
            target.locator('input[name="who"]').fill("Synthetic Review Operator")
            if action == "edit_approve":
                target.locator("textarea").fill(
                    selected[lead]["draft_reply"] + "\n\nPlease confirm the approver count."
                )
                target.locator('input[name="reason"]').fill("Clarify approver count")
            if action == "reject":
                # Exercise server-side required reason through the real browser.
                target.get_by_role("button", name=button, exact=True).click()
                page.get_by_text("rejection reason required").wait_for()
                assert (
                    store.rows("SELECT status FROM proposals WHERE id=?", (selected[lead]["id"],))[
                        0
                    ]["status"]
                    == "pending"
                )
                page.goto("http://127.0.0.1:8765/")
                target = article(lead)
                target.locator('input[name="who"]').fill("Synthetic Review Operator")
                target.locator('input[name="reason"]').fill("Spam; no response appropriate")
            target.get_by_role("button", name=button, exact=True).click()
            page.get_by_role("heading", name="Human review queue").wait_for()
            status = store.rows("SELECT status FROM proposals WHERE id=?", (selected[lead]["id"],))[
                0
            ]["status"]
            assert status == ("rejected" if action == "reject" else "approved")
        assert not errors, errors
        browser.close()
    ids = [selected[k]["id"] for k in ("smb", "midmarket", "spam")]
    outbox = store.rows("SELECT * FROM outbox WHERE proposal_id IN (?,?,?)", ids)
    assert len(outbox) == 2
    assert any("Please confirm the approver count." in row["draft_reply"] for row in outbox)
    result = {
        "url": "http://127.0.0.1:8765/",
        "reviewed_proposal_ids": ids,
        "actions": ["approve", "edit_approve", "reject"],
        "simulated_outbox_rows": outbox,
        "audit_entries": store.verify_audit(),
        "page_errors": errors,
        "screenshot": "evidence/review-pending.png",
        "nothing_sent": True,
    }
    (evidence / "review-browser.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
