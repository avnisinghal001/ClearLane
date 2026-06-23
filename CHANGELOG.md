# Changelog — TraFix AI

All notable changes to this project. Honesty contract is intact throughout: we
never claim to measure congestion, never rank individual officers, and the
operational / force layers never modify the historical ML scores.

## [Unreleased] — Force Command (RBAC + troop simulation) + full UI revamp

### Added — RBAC & access control
- **Two-tier RBAC auth** (`backend/app/force.py`, SQLite token sessions):
  - **Government** super-admin — `govt` / `govt` → sees & manages every station.
  - **Area station** — login is the station **slug** as both username and password
    (e.g. `HAL Old Airport` → `hal-old-airport` / `hal-old-airport`) → sees only
    its own area.
- Scope guards on every endpoint (govt = all, station = own only); cross-station
  access returns `403`, bad credentials `401`.
- **Offline-first auth fallback** (`frontend/src/lib/auth.js`) validated against the
  bundled station list, so login + scoping work with no backend.

### Added — Local SQL force management
- New tables in `clearlane.db`: `fz_stations`, `fz_officers`, `fz_sessions`.
- **Deterministic seeding** from the real 53-station list: each station boots with
  a realistic ranked roster (Inspector/SHO → SI → ASI → Head Constable → Constable)
  across three rotating shifts (Morning/Evening/Night).
- Government can **add / remove stations** (a new station instantly gets a slug
  login); stations can **add / remove / re-shift officers** within their own roster.

### Added — Troop-tracking simulation (deployment planning)
- Client-side, deterministic engine (`frontend/src/lib/force.js`): patrol units
  ("Hoysala" teams) animate live on the map.
- **Shift-aware, sliding-window auto-allocation**: idle on-duty units are sent to
  the worst unserved problem zones; after a service window a zone cools down so
  coverage visibly rotates down the queue. Manual dispatch supported.
- A **shift clock** lets you scrub the time of day and watch units go on/off duty.
- Clearly labelled as a **simulation** for planning — not real GPS or measured traffic.

### Added — Role-scoped product
- **Government Console** — city map of all stations, force totals, station CRUD,
  drill-into-any-station command.
- **Station Command Center** — scoped troop map + ranked roster + that area's
  problems/complaints.
- **Area scoping** for station logins across Command Map, Today/Emergency, Priority
  Queue, Repeat Offenders, Timing Gap, Operations Loop, Staffing and On-Duty —
  each restricted to the station's own zones.
- **Staffing** now shows the station's **members & hierarchy** (ranked by shift) with
  in-scope add/remove.
- **On-Duty** (officer view) is station-aware: current shift, live patrol units +
  dispatch, on-duty officers, and area-only jobs/reports.

### Changed — Full UI/UX revamp ("command OS")
- New dark **glass / JARVIS** design system (ambient glow, blur panels, refined tokens).
- **Collapsible icon sidebar** (desktop) + **hamburger slide-in drawer** (mobile);
  collapse control docked top-right.
- **lucide-react** icon set throughout; new TraFix product logo mark.
- **Map UX**: full-bleed maps with floating glass panels; "Map layers & view" and
  "What to do now" are accordions on desktop and **Google-Maps-style bottom sheets**
  on mobile; legend & stats collapse to chips; default zoom buttons removed for a
  clean look.
- **Collapsible KPI + date-lens** metrics bar for more map breathing room.
- **Responsive full-width grids** and **full-height pages** (single-panel views fill
  the viewport and scroll internally).
- **Search** relocated into the nav drawer on mobile.

### Added — Citizen (public) app
- A separate, **login-free** experience at `#/citizen` (linked from the login page),
  mobile-first with a Google-Maps-style bottom panel + tab bar.
- **Area check** — tap any spot to see its **parking-obstruction risk** (clear /
  some / heavy), the police station covering it, and **patrol units on duty now**
  (reuses the deployment simulation).
- **Report a problem** — tap the map to file a complaint (same closed loop as the
  police side); live citizen reports pulse on the map.
- **Plan a trip** — pick start/end (search or "use my location"); we flag the
  highest-obstruction areas along the corridor, give a route-risk rating, and hand
  off to Google Maps for turn-by-turn.
- **Contact patrol** — one-tap call to the traffic-police helpline (103).
- Honesty kept plain-language: risk is from **parking-violation patterns, not live
  traffic sensors**, and patrol positions are a simulation.

### Changed — Date lens
- Simplified to a clean **segmented control**: **All data · Today · Tomorrow ·
  Pick a date** (with an optional hour). Removed the confusing "Date range" mode.
  Clear status line distinguishes **recorded** (in-window dates) vs **projected**
  (future dates) — never congestion.

### Changed — Routing & persistence
- **Hash-based routing** (`#/<view>`): every page is in the URL, so a refresh
  restores the same screen; deep-linkable. Public citizen app at `#/citizen`.

### Notes
- Backend re-seeds the force DB on startup from `stations.json`; `clearlane.db` is
  runtime state (gitignored).
- Bundle stays lean (~144 KB gz) — lucide tree-shakes to the icons in use.
