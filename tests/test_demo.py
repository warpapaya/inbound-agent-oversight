from review.demo import DEFAULT, load


def test_demo_loads_recorded_proposals_into_fresh_db(tmp_path):
    store, loaded = load(DEFAULT, local=tmp_path / "demo", runs=tmp_path / "runs")
    assert len(loaded) == 3
    pending = [p for p in store.proposals() if p["status"] == "pending"]
    assert len(pending) == 3
    assert any("10%" in p["draft_reply"] for p in pending)
    assert all((tmp_path / "runs" / f"{run}.jsonl").exists() for run in loaded)
    store.verify_audit()
