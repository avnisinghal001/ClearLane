// Shared types for the /api/v3 contract (consumed live, mirrored offline in demo-v3).

export type CongestionSource = "live" | "mappls_typical" | "modeled" | "simulated";
export type When = "now" | "today" | "tomorrow" | "custom";
export type Role = "citizen" | "station" | "govt";

export type Tier = "P1" | "P2" | "P3" | "P4";

export interface Cell {
  h3_r10: string;
  lat: number;
  lon: number;
  police_station: string | null;
  intensity: number; // 0..100 hour + learning modulated heat (the heat layer)
  pic_score: number; // 0..100 parking-induced-congestion score (immutable pressure)
  congestion_severity: number; // 0..1
  congestion_source: CongestionSource;
  road_class?: string | null;
  count?: number;
  // served per request by /api/v3/map (full occupied-cell set):
  tier?: Tier | null; // P1..P4 from immutable pic_score (stable structural colour)
  display_score?: number | null; // 0..100 pic_score × modeled hourly congestion × dow (TIME-VARYING)
  pressure?: number | null; // 0..100 immutable pic_score (drives circle size + tier)
  dow_curve?: number[] | null; // expected violations per weekday (Mon..Sun)
  peak_dow?: string | null;
  weekly_expected?: number | null;
  emerging?: boolean;
  drift_z?: number | null;
  e_lambda?: number | null;
  rank_divergence?: number | null; // NB rank_naive − rank_bias (under-observed signal)
  // derived per request:
  forecast_intensity?: number | null; // 0..100 expected activity when when=today|tomorrow
  operational_priority?: number; // historical + live adjustment, clamped 0..100
  live_adjustment?: number;
  congestion_hour?: number | null; // 0..1 modeled typical congestion at the active hour
  learn_lift?: number | null; // self-learning bend (>0 expanding, <0 cooling; 0 for historical)
}

export interface Kpis {
  n_cells: number;
  total_violations: number;
  concentration: {
    top_2_5_pct_share: number;
    top_2_5_pct_cells: number;
    top_5_pct_share: number;
    top_10_pct_share: number;
    cells_for_50pct: number;
    cells_for_50pct_share: number;
  };
  dispatch: { officers: number; covered_pct: number; uplift_vs_random: number; solver: string; coverage_source?: string };
  forecaster: {
    model: string;
    spearman: number;
    poisson_deviance: number;
    baseline_poisson_deviance: number;
    beats_baseline: boolean;
    mae: number;
  };
  online: { n_emerging: number; n_eligible: number; emerging_share: number };
  hotspots: { model: string; spatial_cv_spearman: number; n_sig_hot: number; n_under_policed: number };
  causal: { beta: number; ci: [number, number]; placebo_beta_mean: number };
  sim: { linucb_uplift_vs_random: number; linucb_pct_of_oracle: number };
  capabilities: { n_pass: number; n_total: number };
}

export interface MapPayload {
  when: When;
  hour: number | null;
  date?: string | null;
  dow?: string | null;
  source: "live" | "forecast";
  source_note: string;
  badge?: string;
  learning_adjusted?: boolean;
  learning_source?: string | null;
  n_emerging?: number;
  n_adjusted?: number;
  congestion_source?: CongestionSource; // simulated | live (resolution result)
  congestion_live?: boolean; // was a live Mappls ETA used?
  congestion_dow?: string | null;
  cells: Cell[];
  kpis: Kpis;
  hour_profile?: number[];
  dow_order?: string[];
}

export interface Station {
  station: string;
  slug: string;
  lat: number;
  lon: number;
  n_cells: number;
  mean_pic: number;
  max_pic: number;
  sum_pic: number;
  mean_intensity: number;
  n_sig_hot: number;
  n_emerging: number;
  weekly_expected: number;
  n_tickets: number;
  top_cell: string;
  dispatch_stops: number;
  route_km: number;
  open?: number; // live open complaints/tickets in this station (additional)
  closed?: number; // live closed complaints/tickets in this station (additional)
}

export type TicketKind = "citizen_complaint" | "police_ticket" | "chalan";
export type TicketStatus = "open" | "closed";

export interface Ticket {
  id: string;
  kind: TicketKind;
  category: string | null;
  labels: string[];
  station: string | null;
  cell: string | null;
  lat: number | null;
  lon: number | null;
  vehicle_type: string | null;
  vehicle_number: string | null;
  note: string | null;
  traffic_caused: boolean | null;
  status: TicketStatus;
  resolution: boolean | null;
  reason: string | null;
  reason_other: string | null;
  created_at: string;
  hour?: number | null;
  source?: string;
  // ticket <-> officer wiring (operational ownership; never a performance score)
  assigned_officer?: number | null;
  assigned_badge?: string | null;
  assigned_name?: string | null;
  assigned_rank?: string | null;
  resolved_by?: string | null;
}

export interface RouteStop {
  h3_r10: string;
  lat: number;
  lon: number;
  pic_score: number;
}
export interface DispatchRoute {
  station: string;
  n_stops: number;
  route_km: number;
  stops: RouteStop[];
}
export interface DispatchPlan {
  officers: number;
  solver: string;
  covered_pic: number;
  total_pic: number;
  covered_pct: number;
  n_stations: number;
  routes: DispatchRoute[];
}

export interface EmergingCell {
  h3_r10: string;
  lat: number;
  lon: number;
  police_station: string | null;
  count: number;
  e_lambda: number;
  drift_z: number;
  recent_rate: number;
  emerging: boolean;
}

export interface ComplaintInput {
  lat: number;
  lon: number;
  category: string;
  traffic_caused: boolean;
  description: string;
  vehicle_type?: string;
  vehicle_number?: string;
}

export interface TicketInput {
  kind: TicketKind;
  category: string;
  labels: string[];
  station: string | null;
  cell?: string | null;
  lat?: number | null;
  lon?: number | null;
  vehicle_type?: string | null;
  vehicle_number?: string | null;
  note?: string | null;
  assigned_officer?: number | null; // fz_officers id from the station roster
}

export interface ResolveInput {
  status: "closed";
  resolution: boolean;
  reason: string;
  reason_other?: string;
}

export interface AuthSession {
  token: string;
  role: Role;
  scope: string; // "all" for govt, station slug for station
  name: string;
  live: boolean;
}

// M4 dispatch reranker (GET /api/v3/dispatch/queue) — mirrors the v1 shape.
export type RerankComponent = "forecast" | "pressure" | "under_observed" | "live_delay" | "reachability";

export interface RerankRow {
  id: string;
  h3_r10: string;
  name: string;
  station: string | null;
  station_slug: string | null;
  lat: number;
  lon: number;
  road_class?: string | null;
  rerank_score: number; // 0..100 M4 blend
  rerank_raw: number; // 0..1
  dispatch_rank: number;
  dispatch_tier: "P1" | "P2" | "P3" | "P4";
  components: Record<RerankComponent, number>; // weighted contributions (0..1)
  component_inputs: Record<RerankComponent, number>; // raw normalized inputs (0..1)
  pressure: number; // pic_score 0..100 (MODELED, not measured)
  forecast_score: number;
  under_observed: number;
  under_observed_candidate: boolean;
  rank_divergence: number | null;
  emerging: boolean;
  drift_z: number | null;
  sig_hot: boolean;
  on_route: boolean;
  assoc_score: number; // live/sim congestion stress %
  congestion_source: CongestionSource;
  live_enriched: boolean;
  eta_min: number | null;
  reach_km: number | null;
  historical_priority: number;
  live_adjustment: number;
  operational_priority: number;
  reason_codes: string[];
}

export interface DispatchQueue {
  station: string | null; // slug
  station_name: string | null;
  scope: "station" | "city";
  when: When;
  hour: number;
  dow: string;
  congestion_source: CongestionSource;
  live_eta: boolean;
  fallback: string | null;
  weights: Record<RerankComponent, number>;
  reason_legend?: Record<string, string>;
  source: "rerank-cache" | "rerank-inline" | "rerank-live" | "offline-compose";
  from_cache: boolean;
  last_rerank: number | null;
  auto_interval_hours: number;
  count: number;
  note?: string;
  queue: RerankRow[];
}

// --------------------------------------------------------------------------- //
// Force / Taskforce management (GET/POST/PATCH/DELETE /api/v3/force/*).
// Operational layer ONLY — we never score, rank or profile an individual officer;
// patrol-board positions are a SIMULATION (never real GPS).
// --------------------------------------------------------------------------- //
export type OfficerStatus = "available" | "off" | "leave";

export interface Officer {
  id: number;
  station_slug: string;
  name: string;
  badge: string; // <PREFIX>-#### (e.g. HAL-1000)
  rank: string; // one of ForceMeta.ranks
  shift: string; // shift key (A/B/C/D)
  status?: OfficerStatus;
}

export interface ShiftDef {
  label: string;
  start: number; // IST hour [start, end)
  end: number;
}

export interface ForceMeta {
  ranks: string[];
  rank_abbr: Record<string, string>;
  top_rank: string;
  shifts: Record<string, ShiftDef>;
  shift_order: string[];
  shift_hours: number;
  tickets_per_officer_hour: number;
  tier_weight: Record<string, number>;
  honesty?: string;
}

export interface RosterStation {
  slug: string;
  name: string;
  lat: number | null;
  lon: number | null;
  n_zones: number;
  officers: number;
  active: boolean;
}

export interface RosterSummary {
  total: number;
  by_shift: Record<string, number>;
  by_rank: Record<string, number>;
}

export interface RosterPayload {
  station: RosterStation;
  officers: Officer[];
  ranks: string[];
  rank_abbr: Record<string, string>;
  shifts: Record<string, ShiftDef>;
  shift_order: string[];
  summary: RosterSummary;
  live: boolean; // true = live backend roster; false = offline deterministic seed
}

export interface AllocZone {
  cell: string;
  lat: number;
  lon: number;
  tier: "P1" | "P2" | "P3" | "P4";
  rerank_score: number;
  pressure: number;
  road_class?: string | null;
  reason_codes: string[];
  weight: number;
  officers: number; // apportioned officers (editable client-side = manual override)
  share_pct: number;
}

export interface OverflowSuggestion {
  station: string;
  station_name: string;
  distance_km: number;
  on_shift: number;
  can_lend: number;
}

export interface AutoAllocation {
  station: string;
  station_name: string;
  shift: string | null;
  shift_label: string;
  on_shift_officers: number;
  recommended_officers: number;
  deficit: number;
  short_staffed: boolean;
  tickets_per_officer_hour: number;
  shift_hours: number;
  expected_shift_tickets: number;
  n_zones: number;
  allocations: AllocZone[];
  overflow: OverflowSuggestion[];
  method: string;
  honesty: string;
}
