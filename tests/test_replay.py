from evals.replay import replay_reports


def test_recorded_transcripts_match_committed_checks():
    stats = replay_reports()
    assert stats["reports"] >= 3
    assert stats["transcripts"] >= 45
    assert stats["negative_transcripts"] >= 1
