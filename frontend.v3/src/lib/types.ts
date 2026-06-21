// Shared types for the /api/v3 contract (consumed live, mirrored offline in demo-v3).

export type CongestionSource = "live" | "mappls_typical" | "modeled";
export type When = "now" | "today" | "tomorrow";
export type Role = "citizen" | "station" | "govt";

export interface Cell {
  h3_r10: string;
  lat: number;
  lon: number;
  police_station: string | null;
  intensity: number; // 0..100 bias-corrected obstruction intensity
  pic_score: number; // 0..100 parking-induced-congestion score
  congestion_severity: number; // 0..1
  congestion_source: CongestionSource;
  road_class?: string | null;
  count?: number;
  dow_curve?: number[] | null; // expected violations per weekday (Mon..Sun)
  peak_dow?: string | null;
  weekly_expected?: number | null;
  emerging?: boolean;
  drift_z?: number | null;
  e_lambda?: number | null;
  // derived per request:
  forecast_intensity?: number | null; // 0..100 when when=today|tomorrow
  operational_priority?: number; // historical + live adjustment, clamped 0..100
  live_adjustment?: number;
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
  source: "live" | "forecast";
  source_note: string;
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
