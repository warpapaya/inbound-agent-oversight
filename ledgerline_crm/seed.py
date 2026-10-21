"""Idempotent fixture seeding; never deletes proposals or audit history."""

import json
from pathlib import Path

from ledgerline_crm.store import Store

ROOT = Path(__file__).resolve().parents[1]


def seed(store):
    data = json.loads((ROOT / "data/seed.json").read_text())
    with store.connect() as db:
        for table in ("accounts", "contacts", "opportunities", "interactions", "kb", "leads"):
            for record in data[table]:
                keys = list(record)
                columns = ",".join(keys)
                slots = ",".join("?" for _ in keys)
                updates = ",".join(f"{k}=excluded.{k}" for k in keys)
                db.execute(
                    f"INSERT INTO {table}({columns}) VALUES ({slots}) "
                    f"ON CONFLICT DO UPDATE SET {updates}",
                    tuple(record.values()),
                )
    return {table: len(records) for table, records in data.items()}


if __name__ == "__main__":
    print(json.dumps(seed(Store()), sort_keys=True))
