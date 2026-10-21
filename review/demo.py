"""Load recorded eval proposals into a fresh local database for the review UI.

No model calls. Uses the committed fixture transcripts, so the review screen can be
explored without an API key. Each proposal goes through Store.propose, so the same
validation and audit chain apply as in a live run.
"""

import argparse
import json
import shutil
from pathlib import Path

from ledgerline_crm.seed import seed
from ledgerline_crm.store import Store

DEFAULT = [
    "evals/fixtures/20261021T163716-345a9d-v1/injection.json",
    "evals/fixtures/20261021T164021-ceab65-v2/injection.json",
    "evals/fixtures/20261021T164021-ceab65-v2/commitment.json",
]


def load(fixtures, local=Path("local/demo"), runs=Path("runs")):
    if local.exists():
        shutil.rmtree(local)
    local.mkdir(parents=True)
    store = Store(str(local / "crm.db"), str(local / "audit.jsonl"))
    seed(store)
    runs.mkdir(exist_ok=True)
    loaded = []
    for path in fixtures:
        transcript = json.loads(Path(path).read_text())["transcript"]
        trace = Path(path).with_suffix(".jsonl")
        if trace.exists():
            shutil.copyfile(trace, runs / f"{transcript['run_id']}.jsonl")
        for p in transcript["proposals"]:
            store.propose(
                transcript["run_id"],
                p["lead_id"],
                p["route"],
                p["priority"],
                p["draft_reply"],
                p["rationale"],
                p["citations"],
            )
            loaded.append(transcript["run_id"])
    return store, loaded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fixtures", nargs="*", default=DEFAULT)
    args = parser.parse_args()
    _, loaded = load(args.fixtures)
    print("Loaded recorded proposals:", ", ".join(loaded))


if __name__ == "__main__":
    main()
