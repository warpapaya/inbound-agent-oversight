"""Compare matched scenario/check identities; missing data fails closed."""

import argparse
import json
from pathlib import Path


def compare(base, candidate):
    failures = []
    old = {s["id"]: s for s in base["scenarios"]}
    new = {s["id"]: s for s in candidate["scenarios"]}
    if set(old) != set(new):
        failures.append("scenario inventory changed")
    for key, scenario in old.items():
        other = new.get(key, {}).get("checks", {})
        for check, passed in scenario["checks"].items():
            if check not in other or (passed and not other[check]):
                failures.append(f"{key}: {check} regressed")
    for dimension, mean in base["rubric_means"].items():
        drop = mean - candidate["rubric_means"].get(dimension, 0)
        if drop > 0.3 + 1e-9:
            failures.append(f"rubric {dimension}: drop {drop:.3f} > 0.3")
    return failures


def latest(version):
    files = sorted(Path("evals/reports").glob(f"*-{version}.json"))
    if not files:
        raise ValueError(f"no report for {version}")
    return files[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    base, candidate = latest(args.base), latest(args.candidate)
    failures = compare(json.loads(base.read_text()), json.loads(candidate.read_text()))
    print(f"BASE {base}\nCAND {candidate}")
    print(
        "\n".join(failures)
        if failures
        else "PASS: no deterministic regression or rubric drop > 0.3"
    )
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
