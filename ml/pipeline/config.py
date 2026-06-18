"""
ClearLane AI — single source of truth.

Every verified dataset fact, weight, threshold and assumption lives here so that:
  * the sensitivity analysis (07_validation.py) can perturb them programmatically,
  * a judge can read every constant in one file,
  * nothing "magic" is hidden inside the pipeline.

All facts in the "VERIFIED DATASET GROUND TRUTH" block were checked directly
against the 298,450-row raw file. Do not contradict them anywhere in the code.
"""
from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
PKG_DIR = Path(__file__).resolve().parent              # ml/pipeline
REPO_ROOT = PKG_DIR.parents[1]                          # ClearLane/
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROC = REPO_ROOT / "data" / "processed"
REPORTS = REPO_ROOT / "outputs" / "reports"
DEMO_DIR = REPO_ROOT / "frontend" / "public" / "demo"

RAW_CSV = DATA_RAW / "jan to may police violation_anonymized791b166 (1).csv"

for _d in (DATA_PROC, REPORTS, DEMO_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- #
# VERIFIED DATASET GROUND TRUTH  (§2 of the brief)
# --------------------------------------------------------------------------- #
RAW_ROW_COUNT = 298_450

# The filename says "jan to may" — that is a vendor mislabel. The true window:
TIME_WINDOW_START = "2023-11-09"
TIME_WINDOW_END = "2024-04-08"
TIME_WINDOW_LABEL = "Enforcement records · Nov 2023 – Apr 2024"

# Monthly raw counts (sanity reference)
MONTHLY_RAW = {
    "2023-11": 44_117,
    "2023-12": 63_554,
    "2024-01": 65_813,
    "2024-02": 54_650,
    "2024-03": 55_229,
    "2024-04": 15_082,   # partial month (through 8 Apr)
}

# Columns that are 100% empty — NEVER engineer features from these.
EMPTY_COLUMNS = ["description", "closed_datetime", "action_taken_timestamp"]

# Bengaluru bounding box (0 missing coords in the raw file).
BBOX = {"lat_min": 12.80, "lat_max": 13.29, "lon_min": 77.44, "lon_max": 77.77}

# Timezone: timestamps are stored UTC (+00); all user-facing times are IST.
IST_OFFSET_HOURS = 5.5
UTC_TZ = "UTC"
IST_TZ = "Asia/Kolkata"

# validation_status handling
DROP_VALIDATION_STATUS = {"rejected", "duplicate"}
KEEP_VALIDATION_STATUS = {"approved", "created1", "processing"}  # + NaN kept
HIGH_CONFIDENCE_STATUS = {"approved"}                            # or scita-sent

# --------------------------------------------------------------------------- #
# DEFENSIBLE WEIGHT TABLES  (§6) — justified in docs/METHODOLOGY.md, stress
# tested in 07_validation.py. Maps to physics: what blocks a moving lane.
# --------------------------------------------------------------------------- #
# Severity (carriageway-blocking, 0–1). Keyed on the canonical violation string.
SEVERITY_WEIGHTS = {
    "PARKING IN A MAIN ROAD": 1.00,
    "MAIN ROAD": 1.00,
    "PARKING NEAR ROAD CROSSING": 0.90,
    "ROAD CROSSING": 0.90,
    "PARKING NEAR TRAFFIC LIGHT": 0.90,
    "PARKING ON ZEBRA CROSSING": 0.90,
    "TRAFFIC LIGHT": 0.90,
    "ZEBRA": 0.90,
    "DOUBLE PARKING": 0.85,
    "OPPOSITE PARKED VEHICLE": 0.80,
    "PARKING NEAR BUS STOP": 0.70,
    "PARKING NEAR SCHOOL": 0.70,
    "PARKING NEAR HOSPITAL": 0.70,
    "BUSTOP": 0.70,
    "SCHOOL": 0.70,
    "HOSPITAL": 0.70,
    "WRONG PARKING": 0.50,
    "NO PARKING": 0.45,
    "OTHER THAN BUS STOP": 0.40,
    "OTHER-THAN-BUS-STOP": 0.40,
    "FOOTPATH": 0.25,
    "PARKING ON FOOTPATH": 0.25,
}
# Any violation token not in the table and not parking-relevant → 0.00 (noise).
SEVERITY_DEFAULT = 0.0

# Substrings that mark a violation token as parking-relevant (obstruction).
PARKING_KEYWORDS = [
    "PARKING", "FOOTPATH", "ROAD CROSSING", "MAIN ROAD", "DOUBLE",
    "OPPOSITE", "BUS STOP", "BUSTOP", "ZEBRA", "TRAFFIC LIGHT",
    "SCHOOL", "HOSPITAL", "ROAD",
]
# Tokens that are explicitly NON-parking noise (never obstruction evidence).
NON_PARKING_TOKENS = [
    "BLACK FILM", "MOBILE", "HELMET", "FARE REFUSAL", "DEFECTIVE PLATE",
    "DEFECTIVE NUMBER PLATE", "NUMBER PLATE", "DRIVING", "SEAT BELT",
    "TRIPLE", "DANGEROUS", "MINOR", "DOCUMENT", "INSURANCE", "POLLUTION",
]

# Vehicle footprint (0–1) — physical lane occupancy.
VEHICLE_WEIGHTS = {
    "PRIVATE BUS": 1.00,
    "HTV": 1.00,
    "TANKER": 1.00,
    "LGV": 0.80,
    "GOODS AUTO": 0.80,
    "VAN": 0.80,
    "MAXI-CAB": 0.60,
    "CAR": 0.60,
    "PASSENGER AUTO": 0.45,
    "MOTOR CYCLE": 0.25,
    "SCOOTER": 0.25,
    "MOPED": 0.25,
}
VEHICLE_DEFAULT = 0.45  # unknown / other → mid-low footprint

# Confidence multiplier (data quality).
CONFIDENCE_MULT = {"high": 1.0, "medium": 0.7}

# --------------------------------------------------------------------------- #
# SUPERZONES  (§5 stage 02)
# --------------------------------------------------------------------------- #
# 100 m geo-bucket = round(lat,3) (~111 m). ~500 m operational superzone = snap
# to a ~0.0045° grid cell (~500 m). Grid-merge is deterministic and avoids the
# DBSCAN density-chaining that fuses dense commercial corridors into mega-blobs.
BUCKET_100M_DECIMALS = 3
POINT_11M_DECIMALS = 4
SUPERZONE_CELL_DEG = 0.0045   # ~500 m

# --------------------------------------------------------------------------- #
# SCORING & PRIORITY  (§5 stage 03)
# --------------------------------------------------------------------------- #
# Operational Priority = wA*A + wB*B + wC*C  (pillars percentile-normalized 0–100)
PRIORITY_WEIGHTS = {"A": 0.50, "B": 0.30, "C": 0.20}

# Tier thresholds on the 0–100 priority score.
TIER_THRESHOLDS = {"P1": 80, "P2": 60, "P3": 40}   # else P4

# Pillar B chronic flag: persistence score >= this.
CHRONIC_THRESHOLD = 60

# Pillar C emergence
RECENT_MONTH = "2024-03"                 # most complete recent month
BASELINE_MONTHS = ["2023-11", "2023-12", "2024-01", "2024-02"]
EMERGENCE_MIN_RECENT_VOLUME = 8          # gate: ignore tiny 1->3 "growth"
EMERGENCE_GROWTH_THRESHOLD = 1.25        # recent/baseline ratio to flag emerging

# --------------------------------------------------------------------------- #
# ADVANCED INTELLIGENCE  (§7)
# --------------------------------------------------------------------------- #
# 7.1 enforcement-exposure bias correction. exposure = distinct officers ×
# distinct active days. bias_adjusted = pressure / exposure**ALPHA.
EXPOSURE_ALPHA = 0.5

# 7.2 habitual offenders
REPEAT_GLOBAL_MIN = 3    # vehicle ticketed >= this many times anywhere
REPEAT_ZONE_MIN = 2      # or >= this many times in the same zone
HABITUAL_SHARE_THRESHOLD = 0.30   # zone repeat-share above this -> "habitual"

# 7.2b repeat-vehicle tracing (offenders.json). Vehicle-level ONLY — vehicle_number
# is anonymized & stable; no real identities, and we never profile officers.
OFFENDER_TOP_N = 200            # most-ticketed repeat vehicles to log
OFFENDER_TIMELINE_CAP = 60      # most-recent tickets kept per vehicle timeline

# 7.3 responsiveness — monthly trend over Nov->Mar
RESPONSIVENESS_MONTHS = ["2023-11", "2023-12", "2024-01", "2024-02", "2024-03"]
RESPONDING_SLOPE = -0.05   # normalized monthly slope below -> "responding"
RESISTANT_SLOPE = 0.02     # above -> "resistant", else "stable"

# 7.5 typology clustering
TYPOLOGY_K_RANGE = range(4, 9)   # pick k by silhouette
TYPOLOGY_RANDOM_STATE = 42

# 7.6 Carriageway Impact Index (CII) — a MODELED flow-impact proxy from STATIC
# road context. This is NOT a measurement of congestion (the data has no flow/
# speed/delay signal). It estimates how much an illegal park in a zone would
# disrupt movement, from three physical determinants, each in [0,1]:
#   J  junction criticality  — share of a zone's tickets at named BTP junctions
#   R  road class            — arterial / ring-road / commercial / local
#   D  demand proximity      — distance to nearest public metro / commercial hub
# context_multiplier = clip( lo + (wJ·J + wR·R + wD·D)·(hi-lo) , lo, hi )
# flow_impact = percentile_norm( pressure_raw × context_multiplier ).
CII_WEIGHTS = {"junction": 0.30, "road_class": 0.40, "demand": 0.30}  # sum = 1.0
CII_CLIP = (0.8, 1.5)            # multiplier bounds (neutral context ≈ 1.15)

# Modal zone address-segment substring → carriageway class (first hit wins).
ROAD_CLASS_KEYWORDS = [
    ("outer ring", "ring_road"), ("ring road", "ring_road"), ("nice road", "ring_road"),
    ("flyover", "arterial"), ("underpass", "arterial"),
    ("market", "commercial"), ("mall", "commercial"), ("bazaar", "commercial"),
    ("main road", "main_road"),
    ("circle", "arterial"), ("junction", "arterial"),
    ("cross", "local"), ("layout", "local"), ("colony", "local"),
]
# Carriageway-class weight (0–1): wider/through roads disrupt more when blocked.
ROAD_CLASS_WEIGHTS = {"ring_road": 1.0, "arterial": 0.9, "main_road": 0.8,
                      "commercial": 0.7, "local": 0.3, "unknown": 0.5}

# Demand-proximity linear decay: full weight ≤ NEAR_M, zero ≥ FAR_M.
DEMAND_NEAR_M = 250.0
DEMAND_FAR_M = 1500.0
# A zone touching multiple distinct junctions is a corridor of intersections, not
# one point — modest per-extra-junction boost on J, capped.
JUNCTION_MULTI_BOOST = 0.15
JUNCTION_MULTI_CAP = 3

# --------------------------------------------------------------------------- #
# TIMING GAP  (§8) — congestion windows are ASSUMPTIONS from domain knowledge,
# NEVER measured. The data has no flow/speed signal.
# --------------------------------------------------------------------------- #
MORNING_CONGESTION_WINDOW = (8, 11)    # 8–11 am IST (assumption)
EVENING_CONGESTION_WINDOW = (17, 21)   # 5–9 pm IST (assumption)
EVENING_BLIND_SPOT_SHARE = 0.02        # P1/P2 zone with <2% evening tickets
COVERAGE_TOP_K = [10, 20, 50, 100, 200]

# --------------------------------------------------------------------------- #
# VALIDATION  (§7.6 / §7.7)
# --------------------------------------------------------------------------- #
SENSITIVITY_N_CONFIGS = 40
SENSITIVITY_PERTURB = 0.20    # ±20% on blend & tables
SENSITIVITY_RANDOM_STATE = 7

# Persistence backtest split
BACKTEST_TRAIN_MONTHS = ["2023-11", "2023-12", "2024-01"]
BACKTEST_TEST_MONTHS = ["2024-02", "2024-03", "2024-04"]

# Forecaster (07.7): train on Nov-Jan features, predict Feb-Mar pressure.
FORECAST_FEATURE_MONTHS = ["2023-11", "2023-12", "2024-01"]
FORECAST_TARGET_MONTHS = ["2024-02", "2024-03"]
FORECAST_RANDOM_STATE = 42
FORECAST_TEST_FRAC = 0.25

# Self-check targets (§2) — run_all.py flags any metric off by >15%.
SELF_CHECK_TARGETS = {
    "clean_rows": 248_374,
    "superzones": 1_543,
    "P1": 151,
    "P2": 382,
    "P3": 250,
    "P4": 760,
    "chronic": 618,
    "evening_blind_spot": 516,
    "emerging": 279,
    "evening_peak_share_pct": 0.16,
    "coverage_top20_pct": 17.5,
    "coverage_top50_pct": 36.6,
    "backtest_spearman": 0.79,
}
SELF_CHECK_TOLERANCE = 0.15

# --------------------------------------------------------------------------- #
# Known recognizable Bengaluru anchors (for the demo, §11). These names appear
# in junction_name; used only for narrative, never for any data claim.
# --------------------------------------------------------------------------- #
DEMO_ANCHORS = [
    "KR Market", "Safina Plaza", "Elite", "Sagar Theatre",
    "Central Street", "Subbanna", "Modi Bridge", "Hosahalli Metro", "Anand Rao",
]
