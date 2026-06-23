# TraFix — Product Scope (PS1 mapping)

**Gridlock Hackathon 2.0 · Theme 1 — Poor visibility on parking-induced congestion.**

## The problem, and our honest framing
Bengaluru parking enforcement is patrol-based and reactive, and the only available
data is **5 months of parking-violation tickets** (Nov 2023 – Apr 2024). That data
has **no traffic-flow, speed, delay, or congestion signal**, and ticket *times*
reflect officer shifts, not traffic. TraFix therefore never claims to measure
congestion. It corrects for the enforcement bias baked into the data and turns it
into prioritized, explainable, deployable operational intelligence.

## Challenge → response mapping

| Theme challenge | TraFix response | Where in the app |
|---|---|---|
| Enforcement is patrol-based & reactive | Proactive ranked enforcement queue + exposure **bias correction** (raw rank → bias-adjusted rank) | Priority Queue, Zone drawer |
| No heatmap of violations vs. likely impact | Bias-corrected **obstruction-pressure** map (severity × vehicle footprint × confidence) **+ Carriageway Impact Index** — a modeled flow-impact proxy (pressure × junction/road-class/metro-proximity context), labelled *not measured congestion* | Command Map, Flow Impact |
| Hard to prioritize zones | Explainable **Operational Priority** = 0.5·A + 0.3·B + 0.2·C, with a live sensitivity proof | Priority Queue, Validation |
| Commercial / metro / event spillover | **Zone typology** + recurring-location + **repeat-offender** (habitual vs transient) analysis | Typology, Zone drawer |
| Limited field resources | **Coverage / allocation** simulator (top-K priority zones → % weighted evidence covered) | Coverage / ROI |
| No closed operational loop | **Complaint → verify → dispatch → clear** workflow (separate operational layer) | Command Map, Operations Loop, Mobile dispatch |
| Need to deploy *now*, fast | **Today's emergency board** — live weekday + hour-aware ranking (priority + forecast + historical day/hour pattern + live citizen reports), dispatch top-down. Expected enforcement-demand, *not* a congestion prediction. | Today / Emergency |
| Same vehicles re-offend | **Repeat-vehicle tracing** — most-ticketed anonymized vehicles with a time-wise log, top zones, mini-map (single-zone repeaters → infrastructure fix). | Repeat Offenders |
| "Show me *this* day / window, everywhere" | **Global Date Lens** — pick any calendar date (Today / Tomorrow / Pick date / Date range); re-weights the map, queues, flow-impact & staffing. In-window date = recorded; future date (e.g. 18 Jun 2025) = projected. | Date Lens bar (all views) |
| How many officers, when? | **Officer-demand estimator** — expected ticket load for the chosen window → officers needed, tunable rate/shift, per-station. Heuristic over ticket volume, not congestion. | Staffing |

## Honesty guardrails (non-negotiable, enforced in code)
- No fabricated congestion / speed / delay / queue / travel-time values anywhere.
- The evening "blind spot" is an enforcement-**coverage** gap vs the city's known
  peaks (stated as a domain assumption), never measured evening congestion.
- Replay is labelled **"Historical enforcement replay"**, never live traffic.
- Live complaints / officer feedback are a **deployment layer**. They adjust a
  transparent `operational_priority` shown **separately** from `historical_priority`
  and `live_adjustment`; they NEVER modify the historical ML scores. A "cleared"
  zone loses its live boost but remains a chronic historical hotspot.
- Recognizable junction / road / station names are shown above internal zone IDs.

## What is ML vs. what is an operational layer
- **ML / analytics (immutable):** cleaning, superzones, the three pillars, priority
  tiers, bias correction, habitual-offender + responsiveness analysis, typology,
  the next-month forecaster, sensitivity + persistence validation. All precomputed
  by `ml/pipeline/` and served read-only.
- **Operational layer (live, additive):** complaints, officer feedback, dispatches,
  dispatch-status history — persisted in SQLite, exposed under `/api/operational/*`
  and `/api/complaints|officer-feedback|dispatches`. Offline, a client-side mirror
  with identical rules keeps the loop demoable with no backend.
