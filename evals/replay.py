"""Offline CI: replay real fixtures; known v2 failures must remain detectable."""

import hashlib
import json
from pathlib import Path

from evals.graders import grade
from evals.regress import compare, latest

ROOT = Path(__file__).resolve().parents[1]


def replay_reports():
    reports = sorted((ROOT / "evals/reports").glob("*.json"))
    if len(reports) < 3:
        raise AssertionError("need the committed v1/v2/v3 evidence")
    kb_ids = {d["id"] for d in json.loads((ROOT / "data/seed.json").read_text())["kb"]}
    count = negatives = 0
    for path in reports:
        report = json.loads(path.read_text())
        assert len(report["scenarios"]) == report["scenario_count"]
        if "regraded_from" in report:
            original_path = ROOT / report["regraded_from"]
            assert (
                hashlib.sha256(original_path.read_bytes()).hexdigest()
                == report["regraded_source_sha256"]
            )
            assert (
                hashlib.sha256((ROOT / "evals/rescore.py").read_bytes()).hexdigest()
                == report["rescore_source_sha256"]
            )
            original = json.loads(original_path.read_text())
            # Regrading cannot revise the model's scores, results, usage, or recorded inputs.
            for key in (
                "rubric_means",
                "rubric_result",
                "estimated_cost_usd",
                "tokens",
                "created_at",
                "source_commit",
            ):
                assert report[key] == original[key], key
            for old, new in zip(original["scenarios"], report["scenarios"], strict=True):
                assert {k: v for k, v in old.items() if k != "checks"} == {
                    k: v for k, v in new.items() if k != "checks"
                }
        for name, digest in report["input_hashes"].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
        passes = 0
        for row in report["scenarios"]:
            fixture = json.loads((ROOT / row["fixture"]).read_text())
            checks = grade(fixture["scenario"], fixture["transcript"], kb_ids)
            assert checks == row["checks"], f"{path.name}:{row['id']}: grader drift"
            # Independent trace-to-fixture check: replayed calls are actual recorded events.
            events = [json.loads(line) for line in (ROOT / row["trace"]).read_text().splitlines()]
            assert [e for e in events if e["type"] == "tool"] == fixture["transcript"]["calls"]
            passes += all(checks.values())
            negatives += not all(checks.values())
            count += 1
        assert passes == report["deterministic_passes"]
    by_version = {v: json.loads(latest(v).read_text()) for v in ("v1", "v2", "v3")}
    assert compare(by_version["v1"], by_version["v2"]), "known regression disappeared"
    assert not compare(by_version["v1"], by_version["v3"]), "fixed prompt regressed"
    assert by_version["v1"]["deterministic_passes"] == by_version["v1"]["scenario_count"]
    assert by_version["v3"]["deterministic_passes"] == by_version["v3"]["scenario_count"]
    return {"reports": len(reports), "transcripts": count, "negative_transcripts": negatives}


if __name__ == "__main__":
    print(json.dumps(replay_reports(), sort_keys=True))
