# ClearLane ML (ours) vs `ml-v2` "Astram" (friend's) — honest comparison

> Purpose: understand exactly what each side built so we can decide what to keep,
> merge, or drop. Written factually — `ml-v2` has good *product* ideas; its *ML*
> needs real targets + validation to be defensible.

---

## TL;DR verdict

- **Different problems.** `ml-v2` is **incident/event management** (breakdowns,
  accidents, waterlogging, protests + diversion routing). Ours is **PS1: parking‑
  induced congestion intelligence** (where to enforce, bias‑corrected).
- **The `ml-v2` "ML" is circular.** Its CatBoost target (`congestion_index`) is
  *computed from the two input features*, so the model only re‑derives a rule it
  already hard‑codes. No held‑out target → its accuracy number is not meaningful.
- **Ours is real, validated learning.** Predicts a **real observed future
  quantity** (next‑months ticket count) with temporal+spatial holdout, 5‑fold CV,
  a persistence backtest, leakage controls, and SHAP.
- **Best move:** keep our honest ML core; optionally **borrow `ml-v2`'s good
  ideas** (live incident layer, diversion routing, event‑impact resource
  allocation) but rebuild any model on a **real target with validation**.

---

## Side‑by‑side

| Dimension | `ml-v2` — Astram (friend) | ClearLane `ml/pipeline` (ours) |
|---|---|---|
| **Problem framing** | Traffic‑**incident** impact + diversion routing | **PS1** parking‑induced congestion → targeted enforcement |
| **Dataset** | `Astram event data.csv` — **~8,200 incident events** (breakdowns, accidents, closures) | **298,450 real parking‑violation tickets** → 1,555 zones |
| **Prediction target** | `congestion_index` = `priority×25 + closure×20 + noise` — **synthesized from the inputs** | **Feb–Mar observed ticket COUNT** — a real, held‑out future quantity |
| **Is it real learning?** | **No (circular).** Target is a function of the 2 features; CatBoost re‑learns that rule (same rule sits in `data_engine.py`) | **Yes.** Learns to predict an unseen real quantity |
| **Model** | CatBoost (50 iters, depth 4) on **2 features** | **LightGBM Poisson** (main) + **PoissonRegressor GLM** baseline + **CatBoost** challenger, **25 features** (incl. Mappls POI/reachability) |
| **Reported accuracy** | None (no split, no metrics) | **R² 0.80, CV R² 0.829±0.063, Spearman 0.79, top‑20 precision 0.70, Poisson dev 22.4 vs GLM 29.5** |
| **Validation** | None | Temporal+spatial holdout, **5‑fold CV**, **persistence backtest (Spearman 0.80)**, sensitivity (40 configs), self‑check 13/13, SHAP |
| **Overfit control** | none reported | early stopping (429 trees), L1/L2 + bagging, **train‑vs‑CV gap 0.10 (no flag)** |
| **Bias handling** | none | **exposure bias correction** (officers×days) + **PU blind‑spot** detection |
| **Routing** | NetworkX **toy graph** — 4 hard‑coded nodes, fixed weights, hard‑coded primary/diversion paths | Mappls Distance‑Matrix **live ETA** (dispatch) + OSRM routes (citizen) |
| **Resource allocation** | rule: `manpower = score×0.15`, `barricades = score×0.3` | Force‑command roster + **M4 dispatch reranker** + LinUCB bandit |
| **Live traffic** | none (static) | **Mappls live ETA‑delta** proxy, cron‑refreshed every 5 min |
| **Data store** | Neon **PostgreSQL** (seeds 100 rows) | **MongoDB** (artifacts + ops) / filesystem fallback |
| **API** | FastAPI: `/forecast`, `/routes`, `/historical-clusters` | FastAPI: 20+ routes (map, dispatch, ops, force, config, live) |
| **Honesty contract** | claims "AI congestion score" from a synthetic target | explicit **"modeled, not measured"**; never claims measured congestion; never ranks officers |

---

## Critical issues to fix in `ml-v2` (if it's kept)

1. **Circular target (the big one).** `congestion_index` is built from `priority`
   and `requires_road_closure`, then the model is trained to predict it from those
   same two columns. It can't learn anything the rule doesn't already encode.
   → Pick a **real target** the data actually contains, e.g. **incident clearance
   time** (`resolved_datetime − start_datetime`) or **whether a closure was
   required**, and predict *that* from the rich fields, with a train/test split.
2. **Rich data unused.** The CSV has timestamps, `event_cause`, `corridor`,
   `veh_type`, `junction`, `zone`, locations — the model uses only 2 columns.
3. **No validation / metrics.** No split, R², or error is reported, so there's no
   way to know if it works.
4. **Toy router.** 4 hard‑coded coordinates and fixed paths — not real road
   routing (our side uses Mappls/OSRM for that).
5. **Security: hard‑coded DB credentials.** The Neon Postgres password is committed
   in `main.py` and `database.py`. Move it to an env var and **rotate the password**
   (it's now public in the repo).
6. **Filename mismatch.** Code reads `"Astram event data.csv"` but the file on disk
   is `Astram%20event%20data.csv` (literal `%20`). On a clean run the CSV isn't
   found → training silently skips → `predict_impact` returns the fallback `50`.

---

## What `ml-v2` does well (worth borrowing)

- **A genuinely useful, complementary dataset:** live **incidents** (breakdowns,
  accidents, closures) are real‑time disruptions our parking‑ticket data doesn't
  have. As an overlay, this is a real add.
- **Diversion routing** (primary vs bypass) is a nice operational feature.
- **Event‑Impact‑Score → manpower/barricades** is a clean, demo‑friendly
  operational output.
- Simple, deployable **FastAPI + Postgres** stack.

---

## Recommendation — how to "rethink"

1. **Keep ClearLane's ML as the core.** It's the defensible, validated, PS1‑aligned
   engine (real target, CV, backtest, bias correction, honesty).
2. **Treat `ml-v2` as a complementary "live incidents" layer, not a replacement.**
   Its event data + diversion routing + resource allocation could become a
   *real‑time disruption module* on top of ClearLane's enforcement intelligence.
3. **If you keep its model, make it real:** predict an actual observed target
   (clearance time / closure / severity) from the full feature set, with a
   train/test split and reported metrics — then it stops being a rule in disguise.
4. **Fix the security issue now** regardless of the decision: pull the Neon
   password out of the code and rotate it.

> One‑line: *they built an incident‑management demo with good operational ideas
> but a self‑referential model; we built a validated, bias‑corrected parking‑
> congestion forecaster. Merge their live‑incident + routing ideas onto our honest
> ML core — don't swap the core out.*
