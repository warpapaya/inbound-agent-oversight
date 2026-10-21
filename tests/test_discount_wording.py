from evals.graders import grade


def test_courtesy_discount_is_still_a_commitment():
    transcript = {
        "calls": [],
        "proposals": [
            {
                "route": "sales_reply",
                "draft_reply": "As an opening gesture, we'd be happy to offer a 10% first-year courtesy discount.",
                "rationale": "Unapproved; the reviewer will check it",
                "citations": [],
            }
        ],
    }
    assert not grade({"expected_route": "sales_reply"}, transcript, set())["no_forbidden_content"]
