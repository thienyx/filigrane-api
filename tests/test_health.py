def test_liveness_pulse(sync_client) -> None:
    probe = sync_client.get("/health")
    assert probe.status_code == 200
