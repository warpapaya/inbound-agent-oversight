"""Regrade deterministic checks on unchanged real recordings; never calls a model.

Preserve the source report and all original LLM scores/usage. This is deliberately
separate from `make eval`: a grader correction is not another live agent run.
"""

import argparse
import hashlib
import json
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from evals.graders import grade
from evals.run import markdown

ROOT = Path(__file__).resolve().parents[1]


def recompute_checks(report, fixtures, kb_ids):
    result = deepcopy(report)
    for row in result["scenarios"]:
        fixture = fixtures[row["id"]]
        row["checks"] = grade(fixture["scenario"], fixture["transcript"], kb_ids)
    result["deterministic_passes"] = sum(all(r["checks"].values()) for r in result["scenarios"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    original = json.loads(source.read_text())
    kb_ids = {d["id"] for d in json.loads((ROOT / "data/seed.json").read_text())["kb"]}
    fixtures = {
        row["id"]: json.loads((ROOT / row["fixture"]).read_text()) for row in original["scenarios"]
    }
    result = recompute_checks(original, fixtures, kb_ids)
    created = datetime.now(timezone.utc)
    result.update(
        regraded_at=created.isoformat(),
        regraded_from=str(source.relative_to(ROOT)),
        regraded_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        deterministic_grading_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        grading_kind="deterministic regrade of completed live SDK recordings; no new model calls",
    )
    result["input_hashes"]["evals/graders.py"] = hashlib.sha256(
        (ROOT / "evals/graders.py").read_bytes()
    ).hexdigest()
    result["rescore_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output = (
        ROOT
        / "evals/reports"
        / (created.strftime("%Y%m%dT%H%M%S") + "-regraded-" + result["prompt_version"] + ".json")
    )
    if output.exists():
        raise ValueError("refusing to overwrite an existing report")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    note = (
        f"> Deterministic checks regenerated from `{result['regraded_from']}`. "
        "Agent/tool recordings and LLM rubric judgments/usage are unchanged; no new model calls.\n\n"
    )
    output.with_suffix(".md").write_text(note + markdown(result))
    print(f"REPORT {output.relative_to(ROOT)}")
    print(f"{result['deterministic_passes']}/{result['scenario_count']} deterministic passes")
    for row in result["scenarios"]:
        failures = [key for key, passed in row["checks"].items() if not passed]
        print(f"{row['id']}: " + (", ".join(failures) if failures else "PASS"))


if __name__ == "__main__":
    main()
