# TraFix, explained simply

No jargon. The whole thing in plain English — what it does, what the screens mean,
and how it answers the problem. *(TraFix is the product; `clearlane` is the engine
codename in the code.)*

---

## 1. The problem (in one line)

> Police can't *see* where illegal parking is choking traffic, so they patrol
> blindly and react late.

That's the brief: **"Poor visibility on parking-induced congestion."**

## 2. Our idea (in one line)

> Turn 5 months of parking tickets into a **ranked list of where to send officers**,
> in plain language — and be honest that tickets show *enforcement*, not traffic.

**TraFix = Traffic + Fix.** No new sensors, no surveillance, no officer scorecards —
just the data the city already has, treated honestly.

## 3. The data (and its one big catch)

- We have **~298,000 parking-violation tickets** (Nov 2023 → Apr 2024). Each row =
  an officer wrote a ticket somewhere, at some time, for some vehicle.
- **The catch:** there is **no traffic/speed/congestion number anywhere**. Tickets
  only tell you *where police already went*. So a plain "ticket count" map just
  shows the patrol habit — not the real problem.
- **Our fix:** we *correct* for that bias, then *predict* and *rank* — instead of
  just counting tickets.

---

## 4. The map (what you see)

- The city is split into small **H3 hexagon cells (~65 m each)** — everything is per-cell.
- Cells colour **green → red** by **PIC (parking-induced congestion)** — how much
  illegal parking is likely choking that spot, **for the chosen hour**.
- **Now / Tomorrow** — "Now" uses your current time automatically; "Tomorrow" lets
  you scrub the hour to pre-plan.
- **Click a spot** → a **ripple animation** ("waves out") + a tiny card with its
  name, priority and PIC. The spot goes into the web address, so you can **share the
  link** and it opens right there.
- **Tap the ripple** → the **place card** opens.

## 5. The place card (same for everyone)

Plain-language story for one spot — citizen, police and government see the same thing:

- **Four numbers (0–100):** **Priority** (overall), **Pressure** (how blocked),
  **Repeats** (how often), **Trend** (getting worse?).
- **How often it happens** — total tickets here + how many are *repeat vehicles* +
  what's new this month (live).
- **When it's busiest** — hour bars, with the 5–9 PM evening rush in orange.
- **Main problems / Vehicles involved** — what's actually being ticketed.
- **What can be done here** — the recommended action.

## 6. Force Dispatch (the police screen)

One screen that answers *where, who, and how*:

- **Situation at a glance** — P1/P2 zones, blind spots, open tickets, officers, expected/week.
- **Where to deploy** — AI next picks + the ranked queue (tap a row → ripple on the map).
- **Deploy your force** — a live patrol board + recommended officers per zone this shift.
- **Your team** — the roster; tap an officer to see the tickets they own.
- Hit **Dispatch** on a spot → it's marked "Team here now," and tomorrow's plan learns from it.

---

## 7. The "brains" (models), in plain words

TraFix stacks several small helpers:

| Helper | What it does (analogy) | Type |
|--------|------------------------|------|
| **Bias-corrector** | *"Don't just reward over-patrolled streets."* Divides violations by how watched a cell is (officers × active days) to find the **true** hotspots, including ones police miss. | Negative-Binomial + Getis-Ord Gi* |
| **Forecaster** | *The weather forecast for parking.* Predicts each cell's next-month problem level. | LightGBM (Poisson) |
| **Online learner** | *Learns from feedback.* Folds citizen/officer outcomes into the score every day. | Gamma-Poisson |
| **Cause-checker** | *"Does ticketing actually help?"* Tests enforcement → fewer violations, with a placebo. | Quasi-causal panel |
| **Scout** | *Explore vs exploit.* Suggests known hotspots **and** under-watched unknowns. | LinUCB bandit |
| **Dispatcher (M4)** | *The decider.* Blends all of it into one 0–100 "send a unit" score with reasons. | Linear reranker |

The dispatcher mixes five things: **forecast · pressure · under-observed ·
live-delay · reachability.**

**One honesty rule across all of them:** we never call this "measured congestion,"
and we never score individual officers.

## 8. The live loop (how it stays fresh & fast)

- **Daily recompute (a robot/cron):** folds new feedback into the model, re-ranks
  every cell, and re-bakes the 24-hour heatmap so map scrubbing is instant.
- **Live traffic:** when an officer turns it on, we ask **Mappls** for current
  drive-times and **cache it for 15 minutes** (so we don't hammer the API).
- **Always renders:** if the backend is down, the app loads a bundled demo copy.

## 9. Glossary (one-liners)

- **Cell (H3 res-10)** — a ~65 m hexagon we score.
- **PIC** — parking-induced congestion: modeled pressure × congestion severity. Modeled, not measured.
- **Pressure / Recurrence / Emergence** — how blocked / how regular / how fast-growing.
- **Bias correction** — removing the "police only see where they patrol" distortion.
- **Exposure** — distinct officers × active days in a cell (how watched it is).
- **Forecast (Poisson)** — predicting a future count.
- **Blind spot** — context says busy, tickets say quiet → probably missed (esp. evenings).
- **Reranker (M4)** — turns everything into one dispatch score + reasons.
- **Bandit (LinUCB)** — the "explore vs exploit" scout that learns from feedback.
- **Mappls** — the maps provider for drive-times / live ETA.
- **Cron** — a robot that runs a task on a timer.

## 10. Run it

See **[README.md](./README.md)** — backend is
`uvicorn clearlane.main:app --reload --port 8000 --app-dir api`, frontend is
`cd frontend.v3 && npm install && npm run dev`, config from `.env.example`.

---

**TL;DR:** tickets → cleaned & de-biased → predict + find blind spots → blend with
live traffic → **one ranked, plain-language "go here now" plan**, refreshed daily,
with a reason for every spot.
