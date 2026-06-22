from __future__ import annotations

from clearlane.phase1.category_normalization import normalize_bool, normalize_text, normalize_validation_status
from clearlane.phase1.violation_parser import parse_offence_codes, parse_violation_labels


def test_string_normalization_trims_unicode_and_case():
    assert normalize_text("  wrong   parking ", uppercase=True) == "WRONG PARKING"


def test_boolean_aliases():
    assert normalize_bool("yes") is True
    assert normalize_bool("0") is False
    assert normalize_bool("maybe") is None


def test_validation_status_aliases(phase1_config):
    mapping = phase1_config["validation_status"]
    assert normalize_validation_status("approved", mapping) == "APPROVED"
    assert normalize_validation_status("duplicate", mapping) == "REJECTED"
    assert normalize_validation_status("pending", mapping) == "PENDING"
    assert normalize_validation_status("strange", mapping) == "UNMAPPED"
    assert normalize_validation_status("NULL", mapping) == "UNKNOWN"


def test_violation_parser_variants():
    assert parse_violation_labels('[" wrong parking ", "WRONG PARKING", "no parking"]') == [
        "WRONG PARKING", "NO PARKING"
    ]
    assert parse_violation_labels(None) == []


def test_offence_code_parser_variants():
    assert parse_offence_codes("112") == (["112"], True)
    assert parse_offence_codes("[112,104]") == (["112", "104"], True)
    assert parse_offence_codes("112,104") == (["112", "104"], True)
    assert parse_offence_codes("bad [") == ([], False)
    assert parse_offence_codes("NULL") == ([], True)

