# Demo Video Script — ClearLane AI (Gridlock 2.0 · PS1)

**Length target:** 4–6 min. **Tone:** confident, honest. **One-liner:**
> "ClearLane turns five months of parking tickets into a bias-corrected, validated,
> role-based deployment command center — honest that the data is enforcement-shaped,
> not congestion-measured."

## 0 · Setup (before recording)
```bash
# Terminal 1 — backend (seeds the force DB on first run)
cd backend && uvicorn app.main:app --reload --port 8000
# Terminal 2 — frontend
cd frontend && npm install && npm run dev      # http://localhost:5173
```
- Have two logins ready: **`govt` / `govt`** and a station **`shivajinagar` / `shivajinagar`**.
- Open on desktop; keep a phone/responsive window handy for the mobile beat.

---

## 1 · Hook (20s)
- Land on the **login**. Say the one-liner.
- "Two roles: **Government** oversees the whole city; each **police station** sees and
  commands only its own area. Login is the station's name as a slug."

## 2 · Government command (90s)
- Log in as **`govt` / `govt`** → **Force Command**.
- **City overview map**: every station, sized by P1 load. Totals: stations, officers
  on strength, P1 zones, live complaints.
- **Manage stations**: add a station (show the slug login it generates) → remove it.
- **Drill into a station** → open its command center.
- **Troop simulation**: toggle **Auto-allocate**; scrub the **shift clock** — units go
  on/off duty and rotate to the worst unserved zones (sliding window). 
  > Say: "This is a deployment *simulation* for planning — not live GPS."

## 3 · The intelligence (90s) — the honesty differentiator
- **Command Map**: open **Map layers & view**; show tiers, "What to do now".
- **Priority Queue**: ranked 0.5·pressure + 0.3·recurrence + 0.2·emergence.
- **Timing Gap**: enforcement peaks ~10am; the evening window is a **coverage gap vs
  assumed peaks**, not measured congestion.
- **Flow Impact**: modeled proxy (pressure × road context) — explicitly *not* congestion.
- **Forecast**: next-month obstruction pressure, validated on held-out months.
- **Methodology & Validation**: sensitivity + backtest; the real re-rank slider.
  > Say: "We *correct* for enforcement bias (officers × active days), we don't just
  > reproduce where police already patrol — and we never rank individual officers."

## 4 · Area station, scoped (75s)
- **Logout** → log in as **`shivajinagar` / `shivajinagar`**.
- Note the nav is **scoped**: Station Command, Command Map, Today, Priority Queue,
  Repeat Offenders, Timing Gap, Operations, Staffing — all **only this area**.
- **Station Command**: the area's troop map + **ranked roster by shift**; add an officer.
- **Repeat Offenders** / **Timing Gap**: now show this station's vehicles / hours only.
- Try `hal-old-airport` cross-access in the URL → blocked (RBAC holds).

## 5 · Mobile / On-Duty (45s)
- Switch to a phone-width window.
- **Hamburger** opens the drawer (search lives up top); pick a page.
- **Command Map**: bottom sheets ("Map layers", "What to do now") slide up Google-Maps
  style; legend/stats are tap-to-expand chips.
- **On Duty**: current shift, live units with **dispatch**, on-duty officers, and
  area-only jobs & citizen reports.

## 6 · Citizen app (60s) — closes the loop with the public
- From the login, tap **"Open the Citizen app"** (or go to `#/citizen`) — no login.
- **Area**: tap a spot → plain risk (clear / some / heavy), the **station covering
  it**, and **patrols on duty now** (same simulation). 
  > "Risk is from parking-violation patterns — not live traffic sensors."
- **Report**: tap the map → file a complaint → it appears live for patrols (this is
  the *same* closed loop the police side consumes).
- **Plan a trip**: set start + end → we flag the worst-obstruction areas on the way
  and rate the route, then hand off to Google Maps.
- One-tap **call traffic police (103)**.

## 7 · Close (20s)
- Refresh the page mid-view → it stays put (hash routing) → "deep-linkable, demo-safe."
- Recap: **citizens report → bias-corrected intelligence ranks → role-based command
  deploys patrols → validated forecast — one honest closed loop.**

---

## Cheat sheet — what to emphasize
| Beat | Soundbite |
|------|-----------|
| Honesty | "Zero flow/speed signal — every row is a ticket. We correct the bias." |
| RBAC | "Govt sees all; a station sees only its area — slug = username = password." |
| Troops | "Shift-aware sliding-window auto-allocation — a planning simulation." |
| Validation | "±20% sensitivity + persistence backtest; self-check gate in the pipeline." |
| Offline | "Kill the backend — it still runs from the bundled demo bundle." |

## Backup talking points (if asked)
- **Why not a hotspot map?** A naive count just re-maps where police already patrol;
  we divide by exposure (distinct officers × active days) to surface neglected zones.
- **Forecaster** predicts a *real observed* quantity (next-month obstruction pressure),
  validated on held-out months — never congestion.
- **Three numbers** stay separate per zone: historical priority (immutable),
  live adjustment (decaying), operational priority (clamped sum).
