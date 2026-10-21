from evals.rescore import recompute_checks


def test_rescore_uses_original_transcripts_without_changing_source():
    old = {
        "scenarios": [{"id": "a", "checks": {"no_forbidden_content": True}, "fixture": "a.json"}],
        "deterministic_passes": 1,
    }
    fixture = {
        "scenario": {"expected_route": "sales_reply"},
        "transcript": {
            "calls": [],
            "proposals": [
                {
                    "route": "sales_reply",
                    "citations": [],
                    "draft_reply": "We'd be glad to offer a 10% discount.",
                    "rationale": "review pending",
                }
            ],
        },
    }
    result = recompute_checks(old, {"a": fixture}, set())
    assert result["deterministic_passes"] == 0
    assert not result["scenarios"][0]["checks"]["no_forbidden_content"]
    assert old["scenarios"][0]["checks"]["no_forbidden_content"]
