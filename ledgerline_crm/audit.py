"""Hash chaining detects edits; the SQLite mirror also detects tail truncation.

Not a signature: a privileged operator can rewrite both stores. Exported head hashes
must be anchored externally to defend against that threat.
"""

import hashlib
import json
from pathlib import Path

GENESIS = "0" * 64


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def entry(seq, prev_hash, event, who, when, data):
    payload = dict(seq=seq, prev_hash=prev_hash, event=event, who=who, when=when, data=data)
    return {**payload, "hash": hashlib.sha256(canonical(payload).encode()).hexdigest()}


def verify_file(path: Path):
    previous = GENESIS
    records = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        try:
            record = json.loads(line)
            digest = record.pop("hash")
            expected = hashlib.sha256(canonical(record).encode()).hexdigest()
            if record["seq"] != number or record["prev_hash"] != previous or digest != expected:
                raise ValueError(f"audit hash mismatch at entry {number}")
            record["hash"] = digest
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid audit entry {number}") from exc
        previous = digest
        records.append(record)
    return records
