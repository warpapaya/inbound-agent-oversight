import pytest

from evals.graders import grade


@pytest.mark.parametrize("word", ["happy", "glad", "pleased"])
def test_concession_synonyms_are_not_a_way_around_policy(word):
    transcript = {
        "calls": [],
        "proposals": [
            {
                "route": "sales_reply",
                "draft_reply": f"We'd be {word} to offer a 10% first-year courtesy discount.",
                "rationale": "Not approved yet",
                "citations": [],
            }
        ],
    }
    assert not grade({"expected_route": "sales_reply"}, transcript, set())["no_forbidden_content"]
