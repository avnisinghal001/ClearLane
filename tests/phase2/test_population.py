from __future__ import annotations

from clearlane.phase2.population import (
    ALL_ACCEPTED,
    PARKING_CLASSIFIED,
    parking_classification_reconciliation,
    select_population,
)


def test_population_reconciliation_keeps_document_discrepancy_visible(sample_phase2_df):
    claims = [{"claim_name": "parking_related_percentage", "document_reference_value": 97.3}]
    report = parking_classification_reconciliation(
        sample_phase2_df,
        {"summary": {"parking_related_percentage": 100.0}},
        claims,
        ALL_ACCEPTED,
    )
    assert report["parking_related_percentage_document_reference"] == 97.3
    assert report["parking_related_percentage_recomputed"] == 100.0
    assert report["populations"][ALL_ACCEPTED]["rows"] == 3
    assert report["populations"][PARKING_CLASSIFIED]["rows"] == 3


def test_select_population_does_not_drop_all_accepted(sample_phase2_df):
    selected = select_population(sample_phase2_df, ALL_ACCEPTED)
    assert len(selected) == len(sample_phase2_df)
    assert set(selected["phase2_population"]) == {ALL_ACCEPTED}
