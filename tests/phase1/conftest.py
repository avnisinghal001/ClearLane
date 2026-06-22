from __future__ import annotations

import copy

import pandas as pd
import pytest

from clearlane.phase1.cleaning import clean_dataframe


EXPECTED_COLUMNS = [
    "id", "latitude", "longitude", "location", "vehicle_number", "vehicle_type",
    "description", "violation_type", "offence_code", "created_datetime",
    "closed_datetime", "modified_datetime", "device_id", "created_by_id",
    "center_code", "police_station", "data_sent_to_scita", "junction_name",
    "action_taken_timestamp", "data_sent_to_scita_timestamp",
    "updated_vehicle_number", "updated_vehicle_type", "validation_status",
    "validation_timestamp",
]


@pytest.fixture
def phase1_config():
    return {
        "datetime": {
            "source_timezone": "Asia/Kolkata",
            "canonical_timezone": "Asia/Kolkata",
            "dayfirst": False,
        },
        "coordinates": {
            "latitude_column": "latitude",
            "longitude_column": "longitude",
            "global_latitude_min": -90,
            "global_latitude_max": 90,
            "global_longitude_min": -180,
            "global_longitude_max": 180,
            "bengaluru_sanity_box": {
                "latitude_min": 12.70,
                "latitude_max": 13.30,
                "longitude_min": 77.30,
                "longitude_max": 77.90,
            },
        },
        "cleaning": {"null_tokens": ["", "NULL", "null"]},
        "validation_status": {
            "approved": ["approved"],
            "rejected": ["rejected", "duplicate"],
            "pending": ["pending"],
        },
        "violation_labels": {
            "parking_related": ["WRONG PARKING", "NO PARKING", "DOUBLE PARKING"],
        },
        "document_reference_claims": {},
    }


def make_row(**updates):
    row = {
        "id": "A1",
        "latitude": "12.9255567",
        "longitude": "77.618665",
        "location": "  Test Road  ",
        "vehicle_number": " FKN001 ",
        "vehicle_type": " car ",
        "description": "NULL",
        "violation_type": '["wrong parking", "NO PARKING"]',
        "offence_code": "[112,104]",
        "created_datetime": "2023-11-20 00:28:46+00",
        "closed_datetime": "NULL",
        "modified_datetime": "2023-11-21 00:28:46+00",
        "device_id": "D1",
        "created_by_id": "U1",
        "center_code": "9",
        "police_station": "Madiwala",
        "data_sent_to_scita": "TRUE",
        "junction_name": "No Junction",
        "action_taken_timestamp": "NULL",
        "data_sent_to_scita_timestamp": "NULL",
        "updated_vehicle_number": "NULL",
        "updated_vehicle_type": "NULL",
        "validation_status": "approved",
        "validation_timestamp": "2023-11-22 00:28:46+00",
    }
    row.update(updates)
    return row


@pytest.fixture
def sample_raw():
    rows = [make_row()]
    df = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)
    df.insert(0, "source_row_number", range(2, len(df) + 2))
    return df


def run_clean(tmp_path, df, config):
    return clean_dataframe(
        df.copy(),
        copy.deepcopy(config),
        tmp_path / "reports",
        tmp_path / "quarantine",
    )

