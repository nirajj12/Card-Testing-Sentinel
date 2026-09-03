from scripts.benchmark_precheck_latency import build_payload, summarize


def test_benchmark_summary_and_fixture_are_reproducible():
    summary = summarize([1.0, 2.0, 3.0, 4.0])
    assert summary == {
        "mean": 2.5,
        "median": 2.5,
        "p50": 2.5,
        "p90": 3.7,
        "p95": 3.85,
        "p99": 3.97,
        "min": 1.0,
        "max": 4.0,
        "stddev": 1.118033988749895,
    }
    payload = build_payload("fixed", 7)
    assert payload["request_id"] == "phase4c-benchmark-fixed-r7"
    assert payload["device_id"] == "phase4c-benchmark-device-7"
    assert payload["amount"] == 100.0
    assert payload["event_sequence"] == 1
