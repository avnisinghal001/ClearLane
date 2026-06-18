# ClearLane — Interactive Element Audit (connected vs cosmetic)

One-page status of every interactive control. "Connected" = it changes real state
or data; "Cosmetic" = display only. Captured after the Tier 0–2 additive work.

| Element | Location | Status | Notes |
|---|---|---|---|
| Nav view switcher | left rail | ✅ connected | switches views |
| KPI chips (P1/chronic/blind/emerging/rising) | KPI strip | ✅ connected | filter the map |
| "Live ops" KPI | KPI strip | ✅ connected | jumps to Operations Loop; reflects snapshot |
| Search box | header | ✅ connected | hits real search index; fly-to + open drawer |
| Sync ⟳ button + "sync Ns ago" | header | ✅ connected | re-polls operational snapshot; label ticks live |
| About / PS1 button | header | ✅ connected | opens problem-statement + response mapping modal |
| LIVE / DEMO badge | header | ✅ connected | reflects whether the backend answered |
| Map base layer select (dark/light/osm/plain) | map | ✅ connected | switches tiles; "plain" = offline no-tile background |
| Tile failure → plain background | map | ✅ connected | auto-falls back on `tileerror` |
| Layer toggles (rings / evidence / typology color) | map | ✅ connected | real layers |
| "File complaint" mode + map click | map | ✅ connected | drops complaint at coordinate → backend/local loop |
| Complaint form (description/vehicle/submit) | map overlay | ✅ connected | POSTs complaint; bbox-validated; toast result |
| Zone markers (click) | map | ✅ connected | open zone drawer |
| "What to do now" panel | map | ✅ connected | deterministic from fields; click → drawer |
| Priority table sort headers / tier filter | queue | ✅ connected | real sort/filter |
| Priority table row click | queue | ✅ connected | fly + drawer |
| Zone drawer action buttons (dispatch/verify/tow/clear/escalate) | drawer | ✅ connected | drive the operational loop; snapshot refreshes |
| Raw → bias-adjusted rank story | drawer | ✅ connected | computed from real ranks |
| Historical / Live / Operational priority block | drawer | ✅ connected | three separate real numbers |
| Local QR (drawer + dispatch) | drawer/dispatch | ✅ connected | generated client-side (no remote dependency) |
| Copy-coords / Open in Google Maps | drawer/dispatch | ✅ connected | clipboard + working deep link |
| Operations console (dispatch/feedback/advance/escalate) | operations | ✅ connected | full closed loop, live counts |
| Mobile dispatch status buttons | /dispatch/[id] | ✅ connected | update operational state → command centre |
| Coverage/ROI slider | coverage | ✅ connected | interpolates the real coverage curve |
| Validation re-weight sliders (A/B/C) | validation | ✅ connected | **exploratory** client-side re-rank from real pillar scores; reset to official |
| Timing-gap blind-spot rows | timing | ✅ connected | fly + drawer |
| Forecast / typology / station rows | those views | ✅ connected | open drawer / show real data |
| Copilot "brief" button | stations | ✅ connected | deterministic briefing (LLM optional, flagged) |

## Previously cosmetic — now fixed in this pass
- **Validation weight slider** was display-only → now truly recomputes a temporary
  client-side ranking from the A/B/C pillar scores, clearly labelled *exploratory,
  not the production ranking*, with a reset to official 50/30/20 weights.
- **Command centre felt frozen** → now polls the operational snapshot every 5 s and
  shows a live "sync Ns ago" label + manual ⟳; historical artifacts stay immutable.
- **Remote QR image dependency** → replaced with a locally-generated QR (offline-safe).
- **Header had no problem-statement / sync / about** → added.

## Known limitations (honest)
- The operational loop persists to SQLite when the backend is up; fully offline it
  uses an in-memory client mirror (clearly the same rules) so the demo never breaks.
- Replay animates aggregated monthly activity, not raw events; labelled "Historical
  enforcement replay", never live traffic.
