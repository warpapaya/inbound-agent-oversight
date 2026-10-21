"""Prove byte-tamper and tail-truncation rejection without touching the live audit."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    original = ROOT / "local/audit.jsonl"
    records = [json.loads(line) for line in original.read_text().splitlines()]
    assert records, "create at least one real proposal before this proof"
    output = []
    with tempfile.TemporaryDirectory(prefix="ledgerline-audit-") as directory:
        copy = Path(directory) / "audit.jsonl"
        changed = [dict(record) for record in records]
        changed[0]["event"] = "tampered_event"
        copy.write_text("\n".join(json.dumps(r) for r in changed) + "\n")
        command = [
            sys.executable,
            "-m",
            "review.cli",
            "--db",
            str(ROOT / "local/crm.db"),
            "--audit",
            str(copy),
            "verify-audit",
        ]
        result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
        output += [
            "Tampered copy (first event changed):",
            result.stdout + result.stderr,
            f"exit_code={result.returncode}",
        ]
        assert result.returncode == 1 and "hash mismatch" in result.stderr
        copy.write_text(
            "\n".join(json.dumps(r) for r in records[:-1]) + "\n" if len(records) > 1 else ""
        )
        result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
        output += [
            "Tail-truncated copy:",
            result.stdout + result.stderr,
            f"exit_code={result.returncode}",
        ]
        assert result.returncode == 1 and "mirror mismatch" in result.stderr
    result = subprocess.run(["make", "verify-audit"], capture_output=True, text=True, cwd=ROOT)
    output += [
        "Original audit (unchanged):",
        result.stdout + result.stderr,
        f"exit_code={result.returncode}",
    ]
    assert result.returncode == 0
    text = "\n".join(output) + "\n"
    (ROOT / "evidence/audit-verification.txt").write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
