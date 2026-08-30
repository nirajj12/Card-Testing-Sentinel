"""The frozen evaluation endpoint: additive contract, runtime isolation.

`/api/metrics/blind` gained baseline, legitimate-impact and failure-mode
blocks. These assert the new payload is correct *and* that serving it still
never touches the blind decision rows -- the isolation that makes
"frozen, never rescored" a checkable claim rather than a slogan.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def payload(client) -> dict:
    response = client.get("/api/metrics/blind")
    assert response.status_code == 200
    return response.json()


def test_existing_fields_are_preserved(payload):
    """Backward compatibility: nothing the endpoint already returned was
    removed or renamed by this change."""
    for field in (
        "status",
        "policy_id",
        "dataset_integrity",
        "operational_policy",
        "action_counts",
        "runtime",
        "denominators",
        "detection_latency",
        "limitations",
        "warning",
    ):
        assert field in payload


def test_baseline_comparison_is_served_from_the_frozen_artifact(payload, registry):
    comparison = payload["baseline_comparison"]
    assert comparison == registry.baseline_comparison
    assert comparison["schema_version"].startswith("card-testing-sentinel-baseline")
    identifiers = {row["id"] for row in comparison["baselines"]}
    assert {
        "count_ge_5",
        "count_ge_7",
        "count_ge_10",
        "rules_ge_3",
        "rules_ge_5",
    } <= identifiers
    assert sum(1 for row in comparison["baselines"] if row.get("is_sentinel")) == 1


def test_legitimate_impact_breaks_down_by_population(payload):
    impact = payload["legitimate_impact"]
    assert impact["devices"] == 1700
    populations = impact["by_population"]
    assert populations, "the per-population breakdown must be present"
    assert sum(row["devices"] for row in populations) == impact["devices"]
    assert sum(row["reviewed"] for row in populations) == impact["reviewed"]
    assert sum(row["blocked"] for row in populations) == impact["blocked"]
    assert "overall_legitimate" not in {row["population"] for row in populations}
    for row in populations:
        assert row["label"] and row["label"] != row["population"]


def test_reviews_are_attributable_to_a_named_population(payload):
    """The point of the breakdown: the reader can see *which* legitimate
    customers absorbed friction, not just that the total was small."""
    impact = payload["legitimate_impact"]
    touched = [row for row in impact["by_population"] if row["reviewed"]]
    assert len(touched) >= 1
    assert sum(row["reviewed"] for row in touched) == impact["reviewed"]


def test_failure_modes_are_reported_per_attack_subtype(payload):
    failures = payload["failure_modes"]
    assert failures["attacker_devices"] == 300
    subtypes = failures["by_subtype"]
    assert {row["subtype"] for row in subtypes} == {"burst", "evasive", "patient"}
    assert sum(row["devices"] for row in subtypes) == failures["attacker_devices"]
    assert sum(row["never_detected"] for row in subtypes) == failures["never_detected"]
    for row in subtypes:
        assert 0 <= row["block_rate"] <= row["review_or_higher_rate"] <= 1


def test_the_never_detected_count_matches_the_frozen_policy_metrics(payload, registry):
    policy = registry.blind_metrics["operational_policy"]
    assert (
        payload["failure_modes"]["never_detected"] == policy["never_detected_attackers"]
    )


def test_limitations_lead_with_the_structural_caveat(payload):
    """The bare zero-block count is close to structurally guaranteed on this
    dataset. The caveat must be first, not buried at the end."""
    limitations = payload["limitations"]
    assert 5 <= len(limitations) <= 8
    assert "few attempts" in limitations[0]
    assert "borderline" in limitations[0]
    assert all(isinstance(line, str) and line.strip() for line in limitations)
    # Facts owned by `failure_modes` and `detection_latency` are not repeated
    # here -- the page states each one once.
    joined = " ".join(limitations).lower()
    for duplicated in ("median first", "first three attempts", "never detected"):
        assert duplicated not in joined, duplicated


def test_serving_evaluation_evidence_never_loads_blind_rows(client, registry):
    """The endpoint must be answerable entirely from small frozen JSON. If a
    future change reads the CSVs, this count moves off zero and fails."""
    before = registry.blind_row_load_count
    for _ in range(3):
        assert client.get("/api/metrics/blind").status_code == 200
    assert registry.blind_row_load_count == before == 0
    assert client.get("/api/system").json()["blind_row_load_count"] == 0


def test_evaluation_evidence_never_triggers_model_scoring(client, registry):
    service = client.app.state.runtime.service
    calls = service.model_score_calls
    client.get("/api/metrics/blind")
    assert service.model_score_calls == calls
