# ClearLane, explained simply

No jargon. This is the whole thing in plain English — what it does, what every
word on the **Dispatch AI** screen means, and how it answers the hackathon problem.

---

## 1. The problem (in one line)

> Police can't *see* where illegal parking is choking traffic, so they patrol
> blindly and react late.

That's the hackathon's PS1: **"Poor visibility on parking-induced congestion."**

## 2. Our idea (in one line)

> Turn 5 months of parking tickets into a **live, ranked list of where to send
> officers right now** — and be honest that tickets show *enforcement*, not traffic.

## 3. The data (and its one big catch)

- We have **~298,000 parking-violation tickets** (Nov 2023 → Apr 2024). Each row =
  an officer wrote a ticket somewhere, at some time, for some vehicle.
- **The catch:** there is **no traffic/speed/congestion number anywhere**. Tickets
  only tell you *where police already went*. So a plain "ticket count" map just
  shows you the police's old patrol habit — not the real problem.
- **Our fix:** we *correct* for that bias and *predict* where problems will be,
  instead of just counting tickets.

---

## 4. Reading the "Dispatch AI" screen — every term

This is the page you found confusing. Here's each thing on it, in plain words:

| What you see | What it actually means |
|---|---|
| **Dispatch AI** | "Where should we send a unit, right now, in priority order." |
| **1,555 operational zones** | We chopped the city into ~1,555 small areas (~500 m each). Everything is per-zone. |
| **P1 / P2 / P3 / P4** | Urgency tier. **P1 = most urgent**, P4 = least. Like a hospital triage tag. |
| **dispatch priority (the big number, 0–100)** | One score for "how much this spot deserves an officer now." Higher = send sooner. |
| **`92`, `81`, `76` …** | That dispatch-priority number for each zone. The list is sorted by it. |
| **`0.3m`, `6.3m` (the small minute value)** | **Live drive-time** for a unit to reach that spot from its police station (from Mappls maps). `~` means estimated. |
| **`?` button** | "Why is this ranked here?" — opens the reasons + which data drove it. |
| **`+1 nearby`** | We merged a duplicate spot < 300 m away on the same road so you don't dispatch twice to one corridor. |
| **AI next picks** | The system's *suggestions* of which 5 to act on — it mixes "known hotspots" with "spots we might be missing." |
| **Thompson (Beta)** | The math behind those picks (an "explore vs exploit" method). You don't need to know more than: *it learns from what officers report back.* |
| **Live ETA** | Toggle: pull **current** traffic travel-times from Mappls and nudge the ranking. |
| **Force recalculate** | "Redo the ranking against right-now traffic." (A robot also does this every 5 minutes.) |
| **100% enriched (40/40)** | We successfully fetched live travel-times for all 40 candidate zones. |
| **auto-reranks every 5 min · last cron …** | The page refreshes itself on a schedule, even if nobody clicks. |
| **Evening planning target 06:30 PM** | A note that the *evening* view would use predicted evening traffic (a roadmap item). |

### The reasons under each zone (plain meaning)

| Reason text | Plain English |
|---|---|
| **high modeled obstruction pressure** | Historically, lots of lane-blocking violations here. (Modeled from tickets — **not** a live congestion reading.) |
| **forecast pressure rising next month** | Our model thinks this spot will get **worse** next month (more pressure than just staying flat). |
| **likely under-observed (blind-spot candidate)** | The area *looks* like it should be busy (metro/market/road context), but few tickets exist → **police may be missing it.** |
| **evening coverage gap vs assumed peak** | Almost no enforcement happens here in the **evening rush** (when we assume congestion peaks). |
| **elevated live travel delay now (+42%)** | **Right now**, Mappls says it takes 42% longer than normal to get there → live stress. |
| **~1.8 min from station** | A unit can reach it fast. |
| **drivers: feat_tickets, feat_officers …** | The top things the forecasting model used to make its prediction for that zone. |
| **LightGBM(poisson)** | The name of the forecasting model + that it predicts **counts**. |

### "Why is *forecast pressure rising next month* on almost every row?"

Good catch — it's **not a bug**. About **75% of the busiest zones are trending up**,
and the Dispatch list only shows the *busiest* zones, so most of them carry that
tag. To stop it being noise, we now show the **distinguishing** reason first on
each row (blind-spot / evening gap / live delay), and put the common "rising" /
"high pressure" tags after.

---

## 5. The 5 "brains" (models), in plain words

Think of ClearLane as 5 small helpers stacked together:

| # | Helper | What it does (analogy) | Type |
|---|---|---|---|
| **M1** | **Forecaster** | *The weather forecast for parking.* Looks at Nov–Jan and predicts each zone's ticket **count** for the next months. | Supervised (predicts a real number) |
| **M2** | **Blind-spot finder** | *The "you're not looking here" helper.* Flags spots that *should* be busy but have few tickets — likely missed by patrols. | Semi-supervised |
| **M3** | **Live traffic check** | *The "is it bad right now?" helper.* Asks Mappls how slow the drive is at this moment. | Live signal |
| **M4** | **Reranker** | *The dispatcher.* Blends the above into one 0–100 "send a unit" score and writes the reasons. | Ranking model |
| **M5** | **Next-pick chooser** | *The curious scout.* Suggests where to go next, mostly known hotspots but sometimes a risky unknown, and **learns from officer feedback.** | Online / reinforcement |

**One honesty rule across all 5:** we never call any of this "measured congestion,"
and we never score individual officers.

---

## 6. How a zone gets its number (step by step)

1. **Clean** the tickets (fix timezones, drop rejected/duplicate ones).
2. **Group** them into ~500 m zones.
3. **Score** each zone on three things: how much it blocks lanes (**pressure**),
   how *regularly* (**recurrence**), and whether it's **newly growing** (**emergence**).
4. **Correct for bias**: divide by how much police *already* patrol there
   (officers × active days) so we don't just reward over-patrolled spots.
5. **Forecast** next month (M1) and **find blind spots** (M2).
6. **Rank** for dispatch (M4): `0.7 × (modeled risk) + 0.3 × (live traffic stress)`.
7. **Refresh** the live part every 5 minutes (M3 + the cron).

---

## 7. The live loop (cron / recalculate)

- A small robot (a scheduled job) calls our server every few minutes.
- The server asks **Mappls** for current travel-times to the top spots, re-mixes
  the ranking, and saves it.
- The dashboard just reads that saved ranking — so it's always fresh, and the
  **Force recalculate** button does the same thing on demand.

---

## 8. Glossary (one-liners)

- **Zone / superzone** — a ~500 m patch of the city we score.
- **Obstruction pressure** — modeled "how much this blocks the lane," from ticket
  severity × vehicle size × confidence. Not a live reading.
- **Recurrence** — how consistently it happens (not a one-off).
- **Emergence** — it's a *new* and growing problem.
- **Bias correction** — removing the "police only see where they patrol" distortion.
- **Exposure** — distinct officers × active days in a zone (how watched it is).
- **Forecast (Poisson)** — predicting a future **count**; Poisson is the right math
  for counts.
- **Under-observed / blind spot** — context says busy, tickets say quiet → probably missed.
- **Reranker (M4)** — turns everything into one dispatch score + reasons.
- **Bandit / Thompson** — the "explore vs exploit" chooser that learns from feedback.
- **Mappls** — the maps provider we use for POIs, drive-times and live ETA.
- **CII (flow impact)** — a modeled "how much this hurts traffic flow" multiplier
  (road type, junctions, demand). Still modeled, not measured.
- **Cron** — a robot that runs a task on a timer.

---

## 9. How each piece answers the problem (PS1)

| PS1 asks… | ClearLane answers with… |
|---|---|
| "detect illegal parking **hotspots**" | the **heatmap** + obstruction-pressure scoring (M1) |
| "quantify their **impact on traffic flow**" | the **Flow-impact (CII)** layer + the **live ETA delay** (M3) |
| "enable **targeted enforcement**" | the **ranked Dispatch AI queue** + reasons + live drive-times (M4/M5) |
| "no heatmap today / patrol is blind" | a real **density heatmap on every map**, refreshed live |
| (the honest bit) | we clearly label everything **modeled, not measured**, and never rank officers |

---

**TL;DR:** tickets → cleaned & de-biased → predict + find blind spots → blend with
live traffic → **one ranked "go here now" list, refreshed every few minutes, with a
plain reason for every spot.**
