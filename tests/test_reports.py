import pytest

from evals.run import summarize, validate_rubric


def test_rubric_requires_complete_inventory():
    row = {
        "id": "a",
        **{
            d: {"score": 4, "justification": "Specific reason"}
            for d in ("grounded", "specificity", "tone", "next_step")
        },
    }
    assert validate_rubric({"scores": [row]}, {"a"}) == {"a": row}
    with pytest.raises(ValueError):
        validate_rubric({"scores": [row]}, {"a", "b"})
    row["tone"]["score"] = 6
    with pytest.raises(ValueError):
        validate_rubric({"scores": [row]}, {"a"})


def test_summary_real_counts_and_cache_tokens():
    report = summarize(
        [
            {
                "id": "a",
                "checks": {"route": True},
                "rubric": {
                    d: {"score": 4, "justification": "OK"}
                    for d in ("grounded", "specificity", "tone", "next_step")
                },
                "result": {
                    "total_cost_usd": 0.1,
                    "usage": {
                        "input_tokens": 5,
                        "output_tokens": 10,
                        "cache_read_input_tokens": 20,
                    },
                },
            }
        ],
        {"total_cost_usd": 0.02, "usage": {"input_tokens": 3, "output_tokens": 4}},
    )
    assert report["deterministic_passes"] == 1
    assert report["tokens"]["cache_read_input_tokens"] == 20
    assert report["tokens"]["input_tokens"] == 8
    assert report["estimated_cost_usd"] == pytest.approx(0.12)
