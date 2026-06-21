"""
ClearLane v3 — single source of truth (SSOT).

Every verified dataset fact, weight, threshold, window, model hyper-parameter and
random seed lives here so that:
  * a judge can audit every assumption in ONE file,
  * the spatial cross-validation / sensitivity code can perturb constants
    programmatically,
  * nothing "magic" is hidden inside a stage.

This v3 pipeline is the "live-first" rebuild described in
`docs/ML_ARCHITECTURE.v3.md`. Phase 0+1 (this commit) cover the OFFLINE science
core: clean -> H3 bin -> features -> exposure-corrected Negative-Binomial hotspot
model with Getis-Ord Gi* significance. It writes to `data/processed/v3/` so it
never clobbers the original `ml/pipeline` artifacts.

HONESTY CONTRACT (never violate, in code/comments/UI):
  * The data is parking TICKETS, not congestion. We never claim it measures flow.
  * "Bias correction" = dividing violations by enforcement EXPOSURE (how hard
    police looked), aggregated to the ZONE/cell level ONLY — never per officer.
  * The ticket TIMESTAMP is the upload time, not the parking time -> we use it at
    DATE granularity only (day-of-week), never hour-of-day.
"""
from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
PKG_DIR = Path(__file__).resolve().parent              # ClearLane/ml.v3
REPO_ROOT = PKG_DIR.parents[0]                          # ClearLane/
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROC = REPO_ROOT / "data" / "processed" / "v3"    # v3-scoped (no clobber)
REPORTS = REPO_ROOT / "outputs" / "reports" / "v3"


def _resolve_raw_csv() -> Path:
    """Locate the raw enforcement CSV.

    Override with CLEARLANE_RAW_CSV (e.g. point at data/raw/sample_500.csv for a
    fast dev check). Otherwise prefer the exact vendor name, then the largest
    non-sample CSV in data/raw (the file has been renamed at least once).
    """
    env = os.environ.get("CLEARLANE_RAW_CSV")
    if env and Path(env).exists():
        return Path(env)
    import glob
    for name in ("jan to may police violation_anonymized791b166 (1).csv",
                 "jan to may police violation_anonymized791b166.csv"):
        p = DATA_RAW / name
        if p.exists():
            return p
    cands = [Path(p) for p in glob.glob(str(DATA_RAW / "*.csv"))
             if "sample" not in Path(p).name.lower()]
    if cands:
        return max(cands, key=lambda p: p.stat().st_size)
    return DATA_RAW / "jan to may police violation_anonymized791b166.csv"


RAW_CSV = _resolve_raw_csv()

for _d in (DATA_PROC, REPORTS):
    _d.mkdir(parents=True, exist_ok=True)


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from a .env into os.environ WITHOUT overriding values
    already set in the shell. Tiny parser -> no python-dotenv dependency.

    Search order (first hit per key wins; shell env still wins over all):
    ml.v3/.env  ->  repo .env  ->  backend/.env. This is how the Mappls key
    (MYMAPINDIA_API_KEY) reaches the offline-first client so stage 03 can enrich
    POIs from the LIVE Nearby API instead of the offline sentinel.
    """
    for path in (PKG_DIR / ".env", REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"):
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass


_load_dotenv()

# --------------------------------------------------------------------------- #
# VERIFIED DATASET GROUND TRUTH (checked against the 298,450-row raw file)
# --------------------------------------------------------------------------- #
RAW_ROW_COUNT = 298_450

# The filename says "jan to may" — that is a vendor mislabel. The TRUE window:
TIME_WINDOW_START = "2023-11-09"
TIME_WINDOW_END = "2024-04-08"
TIME_WINDOW_LABEL = "Enforcement records · Nov 2023 – Apr 2024"

# Monthly raw counts (sanity reference only).
MONTHLY_RAW = {
    "2023-11": 44_117, "2023-12": 63_554, "2024-01": 65_813,
    "2024-02": 54_650, "2024-03": 55_229, "2024-04": 15_082,   # Apr partial
}

# The 24 raw columns. The 3 below are 100% EMPTY -> never engineer from them.
EMPTY_COLUMNS = ["description", "closed_datetime", "action_taken_timestamp"]

# Bengaluru bounding box (0 missing coords in the raw file).
BBOX = {"lat_min": 12.80, "lat_max": 13.29, "lon_min": 77.44, "lon_max": 77.77}

# Timezone: timestamps are stored UTC (+00); all user-facing times are IST.
IST_TZ = "Asia/Kolkata"

# validation_status handling.
DROP_VALIDATION_STATUS = {"rejected", "duplicate"}        # ~28% are dropped
KEEP_VALIDATION_STATUS = {"approved", "created1", "processing"}   # + NaN kept
HIGH_CONFIDENCE_STATUS = {"approved"}                      # or scita-sent

# --------------------------------------------------------------------------- #
# WEIGHT TABLES (justified in docs/METHODOLOGY.md). Map to physics: what blocks a
# moving lane. event_weight = severity × footprint × confidence.
# --------------------------------------------------------------------------- #
# Severity (carriageway-blocking, 0–1), keyed on the canonical violation string.
SEVERITY_WEIGHTS = {
    "PARKING IN A MAIN ROAD": 1.00, "MAIN ROAD": 1.00,
    "PARKING NEAR ROAD CROSSING": 0.90, "ROAD CROSSING": 0.90,
    "PARKING NEAR TRAFFIC LIGHT": 0.90, "PARKING ON ZEBRA CROSSING": 0.90,
    "TRAFFIC LIGHT": 0.90, "ZEBRA": 0.90,
    "DOUBLE PARKING": 0.85, "OPPOSITE PARKED VEHICLE": 0.80,
    "PARKING NEAR BUS STOP": 0.70, "PARKING NEAR SCHOOL": 0.70,
    "PARKING NEAR HOSPITAL": 0.70, "BUSTOP": 0.70, "SCHOOL": 0.70, "HOSPITAL": 0.70,
    "WRONG PARKING": 0.50, "NO PARKING": 0.45,
    "OTHER THAN BUS STOP": 0.40, "OTHER-THAN-BUS-STOP": 0.40,
    "FOOTPATH": 0.25, "PARKING ON FOOTPATH": 0.25,
}
SEVERITY_DEFAULT = 0.0   # token not parking-relevant -> noise

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
    "PRIVATE BUS": 1.00, "HTV": 1.00, "TANKER": 1.00,
    "LGV": 0.80, "GOODS AUTO": 0.80, "VAN": 0.80,
    "MAXI-CAB": 0.60, "CAR": 0.60, "PASSENGER AUTO": 0.45,
    "MOTOR CYCLE": 0.25, "SCOOTER": 0.25, "MOPED": 0.25,
}
VEHICLE_DEFAULT = 0.45

# Confidence multiplier (data quality).
CONFIDENCE_MULT = {"high": 1.0, "medium": 0.7}

# offence_code -> severity (AUXILIARY display/feature only; never feeds event_weight).
OFFENCE_CODE_SEVERITY = {
    "107": 1.00, "104": 0.90, "109": 0.85, "111": 0.70,
    "112": 0.50, "113": 0.45, "105": 0.25,
}

# --------------------------------------------------------------------------- #
# H3 SPATIAL INDEX (stage 02) — the v3 unit of analysis is the hexagon.
# --------------------------------------------------------------------------- #
# Why hexagons over squares: every neighbour is equidistant (no diagonal bias),
# and H3 is hierarchical so res-9 is a clean zoom-out of res-10.
H3_RES_FINE = 10      # ~65.9 m edge ≈ one city block -> the candidate hotspot unit
H3_RES_COARSE = 9     # ~174 m edge -> city zoom-out view
H3_K_RING = 1         # immediate ring (the 6 adjacent hexes) for spatial-lag
# Coarse blocks used to make spatially-disjoint CV folds (so neighbouring cells
# never sit in both train and test -> no spatial leakage). res-7 ≈ 1.2 km.
H3_BLOCK_RES = 7

# --------------------------------------------------------------------------- #
# NEGATIVE-BINOMIAL HOTSPOT MODEL (stage 04) — the bias-correction core.
# --------------------------------------------------------------------------- #
# exposure_h = distinct (device_id × date) pairs active in cell h  (>= this).
EXPOSURE_MIN = 1
# Model:  citations_h ~ NB(μ_h);  log(μ_h) = β0 + β·X_h + log(exposure_h)
# The log(exposure) OFFSET (coefficient fixed at 1) converts the count model into
# a RATE model -> "violations per unit of enforcement effort" = bias-corrected.
NB_FEATURES = [            # context features X_h (NOT raw counts -> no leakage)
    "sev_mean", "veh_footprint_mean", "no_parking_share", "wrong_parking_share",
    "main_road_share", "footpath_share", "double_parking_share",
    "repeat_share", "junction_share", "n_junctions", "approval_rate",
    "neighbor_pressure", "poi_metro_m", "poi_market_m",
]
NB_MAXITER = 100
NB_ALPHA_FLOOR = 1e-6      # NB dispersion alpha cannot be <= 0
DISPERSION_NB_THRESHOLD = 1.2   # Pearson dispersion above this -> prefer NB over Poisson

# --------------------------------------------------------------------------- #
# SIGNIFICANCE TESTING (stage 04) — Getis-Ord Gi* + Moran's I (PySAL/esda).
# --------------------------------------------------------------------------- #
GISTAR_STAR = True         # Gi* (include the cell itself), not plain Gi
GISTAR_PERMUTATIONS = 999  # conditional permutations for the pseudo p-value
SIG_P = 0.05               # p below this AND z>0 -> statistically real hot cell
GISTAR_KNN_K = 6           # fallback weights if H3 adjacency is degenerate (hex=6)

# --------------------------------------------------------------------------- #
# DATA SPLIT / EVALUATION (stage 04) — spatial-block cross-validation.
# --------------------------------------------------------------------------- #
CV_FOLDS = 5
CV_RANDOM_STATE = 42
PRECISION_AT_K = [20, 50, 100]   # top-K hotspot overlap (predicted vs observed)
# Temporal split for the (Phase-3) forecaster — documented here so it's auditable.
FORECAST_FEATURE_MONTHS = ["2023-11", "2023-12", "2024-01"]
FORECAST_TARGET_MONTHS = ["2024-02", "2024-03"]

# --------------------------------------------------------------------------- #
# CARRIAGEWAY / ROAD CONTEXT (stage 03 features)
# --------------------------------------------------------------------------- #
ROAD_CLASS_KEYWORDS = [
    ("outer ring", "ring_road"), ("ring road", "ring_road"), ("nice road", "ring_road"),
    ("flyover", "arterial"), ("underpass", "arterial"),
    ("market", "commercial"), ("mall", "commercial"), ("bazaar", "commercial"),
    ("main road", "main_road"),
    ("circle", "arterial"), ("junction", "arterial"),
    ("cross", "local"), ("layout", "local"), ("colony", "local"),
]
ROAD_CLASS_WEIGHTS = {"ring_road": 1.0, "arterial": 0.9, "main_road": 0.8,
                      "commercial": 0.7, "local": 0.3, "unknown": 0.5}
JUNCTION_SENTINEL = "No Junction"   # junction_name value meaning "not at a junction"

# Repeat-offender thresholds (vehicle-level only; vehicle_number is anonymised).
REPEAT_GLOBAL_MIN = 3   # vehicle ticketed >= this many times anywhere
REPEAT_ZONE_MIN = 2     # or >= this many times in the same cell

# --------------------------------------------------------------------------- #
# MAPPLS (offline-first; stage 03 context features). Live calls are Phase 2+.
# --------------------------------------------------------------------------- #
MAPPLS_ENABLED = True
# Key env names (renamed 2026-06). THREE distinct credentials, each for ONE product:
#   * SDK/static key  -> browser Map-widget ONLY (NOT valid for REST calls).
#   * REST key        -> goes in the advancedmaps PATH (distance-matrix, rev_geocode).
#   * OAuth id/secret -> mint a bearer for the atlas host (Nearby/geocode).
MAPPLS_STATIC_KEY_ENV = "MYMAPINDIA_STATIC_API_KEY"     # SDK/browser key (NOT for REST)
MAPPLS_REST_KEY_ENV = "MYMAPINDIA_REST_MAPPLS_API_KEY"  # REST key -> advancedmaps path
MAPPLS_API_KEY_ENV = "MYMAPINDIA_API_KEY"     # back-compat: old combined key name
MAPPLS_CLIENT_ID_ENV = "MAPPLS_CLIENT_ID"
MAPPLS_CLIENT_SECRET_ENV = "MAPPLS_CLIENT_SECRET"
MAPPLS_TOKEN_URL = "https://outpost.mappls.com/api/security/oauth/token"
# --- Drive-time (measured-traffic congestion) — the ONLY route product provisioned
# for this account is the LEGACY "advancedmaps" Distance-Time Matrix, where the REST
# key goes in the PATH (NOT as an OAuth bearer):
#   {MAPPLS_ADVANCEDMAPS_BASE}/<REST_KEY>/<resource>/driving/<lng,lat;lng,lat>?rtype=0&region=ind
# Verified live (2026-06, HTTP 200): distance_matrix (free-flow) and
# distance_matrix_eta (TYPICAL-traffic ETA, from Mappls' historical patterns — NOT
# real-time, NOT predictive). distance_matrix_traffic -> 401 "Api Access Denied"
# (live-traffic product off). The OAuth route.* hosts (route.mappls.com routev2/dm,
# isopolygon, trip_optimization) all 401 "Token was not recognised" -> NOT enabled.
MAPPLS_ADVANCEDMAPS_BASE = "https://apis.mappls.com/advancedmaps/v1"
MAPPLS_DM_REGION = "ind"
MAPPLS_DM_RTYPE = 0                                 # 0=optimal route (default)
MAPPLS_DM_RESOURCE_FREE = "distance_matrix"        # free-flow duration (no traffic)
MAPPLS_DM_RESOURCE_ETA = "distance_matrix_eta"     # typical-traffic ETA duration
# Predictive ETA (routev2/dm/distance with date_time) needs the separate "Predictive
# Distance Matrix" product, which is NOT provisioned here -> stage 07 honestly emits
# api_unavailable instead of fabricating a curve. Flip True once it's enabled.
MAPPLS_PREDICTIVE_ENABLED = False
# Circuit breaker: if the live ETA / distance-matrix calls fail this many times in a
# process (e.g. 401 product-not-enabled / 403 quota), stop calling them and fall back
# to the offline proxy — avoids thousands of doomed requests.
MAPPLS_ROUTE_FAIL_LIMIT = 3
# Atlas (Nearby/geocode) uses the OAuth bearer + its OWN daily quota. When that quota
# is spent (HTTP 403 Daily Limit) trip an analogous breaker so stage 03 doesn't fire
# thousands of doomed 403s — it just falls back to the offline POI sentinel.
MAPPLS_ATLAS_FAIL_LIMIT = 3
MAPPLS_CACHE_DIR = DATA_PROC / "mappls_cache"
MAPPLS_TIMEOUT_S = 6
MAPPLS_COORD_DECIMALS = 4            # cache key precision (~11 m) -> reproducible
MAPPLS_POI = {                      # keyword -> (Mappls Nearby keyword, radius m)
    "metro": ("metro station", 1500), "bus": ("bus stop", 800),
    "school": ("school", 800), "hospital": ("hospital", 1200),
    "market": ("market", 1000), "parking": ("parking", 800),
}
MAPPLS_POI_FAR_M = 5000.0            # sentinel distance when nothing found / offline

# --------------------------------------------------------------------------- #
# CACHE LAYER (ml.v3/cache/) — two tiers via an event bus:
#   STATIC (POI, geocode, snap, place, aerial): cached to LOCAL JSON, then mirrored
#           to MongoDB (durable, deterministic — these never change).
#   LIVE   (ETA traffic/predictive, isochrone): cached in MongoDB ONLY, with a TTL
#           (Mongo auto-expires the doc). Never written to local JSON.
# Offline-first: if MongoDB is unreachable, static still works via local JSON and
# live falls back to an in-process memo.
# --------------------------------------------------------------------------- #
MONGO_URI_ENVS = ("MONGOURI", "MONGODB_URI")     # tolerant of both names in .env
MONGO_DB_ENVS = ("MONGO_DB", "MONGODB_DB")
MONGO_DB_DEFAULT = "clearlane"
CACHE_LOCAL_DIR = DATA_PROC / "cache" / "static"          # one JSON file per namespace
CACHE_STATIC_COLLECTION = "mappls_cache_static"           # durable, no expiry
CACHE_LIVE_COLLECTION = "mappls_cache_live"               # TTL-expired
CACHE_LIVE_TTL_S = 900               # live entries expire after 15 min (Mongo TTL)
CACHE_MEM_LIVE_TTL_S = 120           # in-process memo window for live values
CACHE_FLUSH_EVERY = 200              # bus auto-flush batch size (bulk Mongo writes)
# Namespace routing: which Mappls call kinds are static vs live.
CACHE_STATIC_NS = {"nearby", "geocode", "revgeo", "snap", "place", "aerial"}
CACHE_LIVE_NS = {"eta", "isopolygon", "along_route"}

# --------------------------------------------------------------------------- #
# PHASE 2 — live congestion + PIC (stage 05)
# --------------------------------------------------------------------------- #
# PIC_h = ViolationIntensity_h (0–1, bias-corrected, Phase 1) × CongestionSeverity_h.
# CongestionSeverity is MEASURED live from Mappls ETA when available, else a clearly
# labelled MODELED proxy from static road context (never claimed as measured).
PIC_TOP_CORRIDORS = 50          # cells to fetch LIVE ETA for (bounded; cached)
CORRIDOR_LEN_M = 400            # A->B segment length for the ETA ratio
# Offline congestion proxy weights (each component already in [0,1]); blended then
# used directly as a [0,1] severity. Honest label: "modeled", not "measured".
PIC_PROXY_WEIGHTS = {"road_class": 0.5, "junction": 0.3, "neighbor": 0.2}

# --------------------------------------------------------------------------- #
# PHASE 3 — forecasts (stages 06 daily-violations, 07 predictive-ETA)
# --------------------------------------------------------------------------- #
# Daily violation forecaster: per (cell × date) Poisson count model with calendar
# + lag + static features. Temporal holdout (no leakage). Predicts day-of-week
# violation PROPENSITY — never traffic, never hour-of-day (timestamp is upload time).
FORECAST_DAILY_MIN_CELL_COUNT = 20   # model only cells with >= this many tickets
FORECAST_DAILY_TEST_DAYS = 21        # last N days held out for the backtest
FORECAST_DAILY_LGBM = {
    "objective": "poisson", "n_estimators": 400, "learning_rate": 0.05,
    "num_leaves": 31, "subsample": 0.8, "colsample_bytree": 0.8, "min_child_samples": 30,
}
# A few Bengaluru public holidays inside the Nov-2023->Apr-2024 window (is_holiday).
FORECAST_HOLIDAYS = {"2023-11-12", "2023-11-13", "2023-11-27", "2023-12-25",
                     "2024-01-01", "2024-01-15", "2024-01-26", "2024-03-08",
                     "2024-03-25", "2024-03-29"}
# Predictive-ETA (stage 07): 24h curve per corridor for tomorrow (live Mappls).
FORECAST_ETA_HOURS = list(range(24))

# --------------------------------------------------------------------------- #
# PHASE 4 — exact dispatch optimisation (stage 08)
# --------------------------------------------------------------------------- #
# MCLP: choose <= officers patrol points (from top-PIC candidate cells) to maximise
# covered PIC; a cell is covered if a chosen point is within the coverage radius
# (offline proxy; Mappls isochrone when available). Then order each station's stops
# (VRP/TSP) — nearest-neighbour offline, Mappls trip-optimization when available.
DISPATCH_OFFICERS = 25
DISPATCH_CANDIDATES = 150            # candidate patrol cells (top PIC)
DISPATCH_COVER_RADIUS_KM = 0.8       # offline coverage radius (~hex neighbourhood)
DISPATCH_MIN_STATION_TICKETS = 300   # ignore tiny stations when locating them
DISPATCH_SIM_TRIALS = 200            # random-baseline trials for the value check
# Live POI enrichment is BOUNDED to the top-N cells by raw pressure (the rest get
# the offline sentinel). Each enriched cell costs len(MAPPLS_POI)=6 Nearby calls
# and is cached to disk after the first run, so a full 6,483-cell live sweep would
# be ~39k calls — we cap it. Raise toward 7000 to cover every cell; 0 = offline.
MAPPLS_POI_MAX_CELLS = 400

# --------------------------------------------------------------------------- #
# SELF-CHECK (run_all.py) — only HARD-gate the one fully-verified number; the rest
# of the Phase-1 metrics are printed as INFO (we can't pre-commit exact targets
# for brand-new H3 artifacts without first running them).
# --------------------------------------------------------------------------- #
SELF_CHECK_TARGETS = {"clean_rows": 248_374}
SELF_CHECK_TOLERANCE = 0.15

# =========================================================================== #
# PHASES 5–8 (stages 09–12) — appended section. Online learning, quasi-causal
# panel, evaluation scorecard, and the simulation dispatch policy. Every one of
# these works ENTIRELY from the dataset + already-built artifacts + trained
# models — no stage calls a live API (the Mappls route/ETA products are blocked
# today). Honesty contract still holds: ticket data never "measures" congestion,
# all analysis is zone/cell-level (never per officer), deterministic, fixed seed.
# =========================================================================== #

# --------------------------------------------------------------------------- #
# PHASE 5 — ONLINE LEARNING (stage 09) — Gamma-Poisson conjugate per-cell rate
# + emerging-hotspot drift alarm. CLOSED-FORM: posterior Gamma(s0+Σy, r0+n) so a
# new day updates E[λ] by ADDING TWO NUMBERS (Σy, n) — no retraining, ever.
# --------------------------------------------------------------------------- #
# Weak Gamma(shape, rate) prior on each cell's DAILY violation rate λ_h. Strength
# r0=1 ≈ "one prior day", negligible against the ~151-day record, so the data
# dominates (a 900-ticket cell barely moves; a 2-ticket cell is gently shrunk).
ONLINE_PRIOR_SHAPE = 1.0          # s0  (prior pseudo-count of violations)
ONLINE_PRIOR_RATE = 1.0           # r0  (prior pseudo-days; units: days)
ONLINE_CI = 0.90                  # central credible-interval mass for E[λ]
ONLINE_RECENT_DAYS = 21           # trailing window tested for an emerging spike
ONLINE_MIN_CELL_COUNT = 10        # only evaluate drift on cells with ≥ this many tickets
# Emerging = recent-window rate exceeds the BASELINE posterior-predictive mean by
# ≥ k predictive SDs AND by at least this ratio (materially, not trivially, higher).
# k=3.0 is the textbook 3-sigma control-chart alarm → a high-confidence, actionable
# watchlist (~9% of eligible cells here; never 0, never everything).
ONLINE_DRIFT_K = 3.0
ONLINE_EMERGING_MIN_RATIO = 1.5

# --------------------------------------------------------------------------- #
# PHASE 6 — QUASI-CAUSAL ENFORCEMENT PANEL (stage 10) — cell×month two-way FE.
# HONESTY: this estimates enforcement EXPOSURE(t) → CHANGE in violations(t+1)
# (enforcement responsiveness) from the TICKET data we actually have. The
# parking → MEASURED congestion-delay causal needs the LIVE Mappls ETA panel
# (Phase 2 live) and plugs in here once the route API is enabled; we NEVER call
# the modeled congestion severity "measured", and never profile an officer.
# --------------------------------------------------------------------------- #
CAUSAL_MIN_CELL_COUNT = 30        # cells with ≥ this many tickets enter the panel
CAUSAL_PLACEBO_PERMUTATIONS = 200 # shuffle exposure across cells → β should → 0
CAUSAL_SEED = 42
CAUSAL_PLACEBO_ABS_MAX = 0.05     # |placebo β| below this = "collapsed to ~0"

# --------------------------------------------------------------------------- #
# PHASE 7 — EVALUATION SCORECARD (stage 11) — one PASS/REVIEW gate per capability.
# Thresholds are deliberately conservative & auditable (tighten in ONE place).
# --------------------------------------------------------------------------- #
EVAL_THRESHOLDS = {
    "hotspot_cv_spearman_min": 0.30,     # spatial-CV Spearman(pred, observed rate)
    "hotspot_moran_abs_max": 0.05,       # |Moran's I on residuals| ≈ 0 (no leakage)
    "forecast_spearman_min": 0.20,       # daily forecaster rank skill on holdout
    "dispatch_uplift_min": 1.20,         # MCLP covered-PIC vs random placement
    "online_emerging_min": 1,            # ≥ 1 emerging hotspot detected (sane > 0)
    "causal_placebo_abs_max": 0.05,      # placebo β collapsed to ≈ 0
    "sim_uplift_min": 1.20,              # learned/greedy sim reward vs random
}

# --------------------------------------------------------------------------- #
# PHASE 8 — SIMULATION DISPATCH POLICY (stage 12) — data-calibrated simulator +
# LinUCB contextual bandit vs random / static-greedy, graded by a regret curve
# against a hindsight oracle. HONESTY: trained in a SIMULATOR because no real
# dispatch logs exist (closed_datetime / action_taken_timestamp are 100% empty,
# §dataset truth). Arrivals are Poisson with rate = online E[λ] — an
# enforcement-shaped PROXY for true arrivals, not a measurement — and the reward
# is PIC-WEIGHTED catches so the objective stays aligned with real congestion.
# --------------------------------------------------------------------------- #
SIM_N_CELLS = 250          # arm universe = top-N cells by PIC
SIM_OFFICERS = 25          # cells visited per shift (matches DISPATCH_OFFICERS)
SIM_SHIFTS = 60            # shifts per episode
SIM_EPISODES = 30          # seeded episodes averaged for the reward / regret curves
SIM_SEED = 42
SIM_TRAVEL_PENALTY = 0.0   # per-unit spread cost applied equally to all policies
# alpha=0.5 is the sweet spot from the stage-12 sweep: the bandit BEATS static greedy
# (~1.12x, ~95% of the hindsight oracle) while still probing ~2x as many distinct
# cells as greedy's fixed 25 (focused blind-spot exploration, not blanket-random).
LINUCB_ALPHA = 0.5         # UCB exploration width (higher ⇒ probes more blind spots)

# --------------------------------------------------------------------------- #
# PHASE 9 — HOURLY CONGESTION OVERLAY (stage 13) — the honest "24 heatmaps".
# A 24-hour normalized TYPICAL-congestion shape for Bengaluru (0..1), MODELED from
# documented commute peaks — NOT measured from tickets (ticket time is upload
# time, not parking time, so ticket COUNTS never vary by hour). This shape only
# modulates the *congestion* layer of the map by hour; the historical propensity
# stays day-of-week. Two peaks: morning 08–11, evening 17–21 (evening worse),
# trough overnight. Where Mappls TYPICAL-traffic ETA is available per corridor the
# backend may refine a cell's amplitude, but this offline shape is the default so
# every run is reproducible and the demo always renders.
# --------------------------------------------------------------------------- #
HOURLY_CONGESTION_BASE = [
    0.10, 0.07, 0.05, 0.05, 0.06, 0.12, 0.28, 0.55,   # 00–07
    0.82, 0.95, 0.88, 0.70, 0.62, 0.60, 0.58, 0.62,   # 08–15
    0.72, 0.90, 1.00, 0.95, 0.80, 0.55, 0.32, 0.18,   # 16–23
]
# How strongly each road class feels the peaks (ring/arterial peak hardest; local
# roads stay comparatively flat). Multiplies the base shape (NOT re-normalised, so
# a local road's worst hour is genuinely below an arterial's worst hour).
HOURLY_CONGESTION_CLASS_AMP = {
    "ring_road": 1.00, "arterial": 0.95, "commercial": 0.90,
    "main_road": 0.85, "local": 0.45, "unknown": 0.70,
}
HOURLY_CONGESTION_FLOOR = 0.08          # nothing is ever zero congestion
HOURLY_CONGESTION_GLOBAL_AMP = 0.70     # city-wide default when a class is unknown
HOURLY_CONGESTION_PROVENANCE = "modeled_typical"   # documented commute peaks; not measured
HOURLY_CONGESTION_PEAKS = {"morning": 9, "midday_lull": 13, "evening": 18}
