# Design: M3 — Reflex executor, macro list v1, progression policy

Date: 2026-09-25. Status: **draft → implementing**.
Scope: everything needed to make a Laya-driven Marisa A **clear Taisei Easy (6 stages)**
without sim cheats and with natural-looking play, then ramp Normal → Hard → Lunatic.

Binding spec: `doc/requirements-decisions.md` (wins on conflict).
Inputs: M2 data (`logs/m2-2026-09-25-loop2.log`, `simdata/laya-m2-*.jsonl`), M1 smoke
(`logs/smoke-2026-09-25-m1-final.log`), gameplay research (`doc/research-touhou-gameplay.md`).

---

## 1. What M2 proved (data)

| Fact | Value | Source |
|---|---|---|
| Loop end-to-end (Laya → macro → buttons → step) | works, 0 failures / 0 protocol errors | `logs/m2-2026-09-25-loop2.log` |
| Laya wall per 4-question batch | med **1166 ms** (min 916, max 1257) | `simdata/laya-m2-0925-0407.jsonl` |
| Resulting `decide_every` | ≈ 70 game frames (≈1.17 s of game time per call) | `agent._adapt_decide_every` (60 fps game clock, §5) |
| Episode outcome (macro-only executor) | LOST @ 1743 f (29 s), 3 deaths, **3/3 bombs spent**, score 347 970 | loop2 log |
| Move distribution (v0 9-dir drift) | up 18/28, down 4, up_left 3, left 2, hold 1 | jsonl summary |
| `bomb_now` ≥ 0.5 | **27/28 calls** (probabilities 0.83→0.99) | jsonl summary |
| `focus` ≥ 0.5 | 2/28 | jsonl summary |
| `danger` score (0–2) | min 0.57, med 1.50, max 1.72 | jsonl summary |
| Degraded mode (dead port) | runs to terminal, 100% uncovered, taint=True, no crash | loop2 log |
| Headless step throughput | ~12 400–13 900 logic fps (M1) | M1 smoke |

**Diagnosis.** The control loop is correct; the *play* is not. Three gaps:

1. **No evader.** The executor v0 applies the macro literally (drift + always-shoot).
   Drifting into stage-1 danmaku = death in ~30 s. Laya's "up" bias is reasonable
   (advance/engage), but a 1.17 s macro with no intra-macro dodging is not survivable.
2. **Bomb over-trigger (prompt bug).** 27/28 calls say "bomb now" — the model reads
   "bullets closing in" → "bomb". All 3 bombs burned in the first stage-1 attempt.
   Needs a scarcity-framed question + a higher threshold.
3. **Macro vocabulary too coarse.** 9 compass drifts give Laya no way to say
   "hold", "hug the corner", "orbit the boss", "sweep the item line".

## 2. Layering (unchanged, per §7 "Laya is final")

```
Laya (remote GPU host, ~1 call / 70 game frames, sim FROZEN during call)
  └─ macro: move intent + focus flag + bomb flag (+ danger read, logged)
Reflex executor (60 Hz, in-process, 0 ms)
  └─ frame-exact buttons: movement (8-dir) + focus + bomb + shot aim
Sim (taisei-sim, deterministic, frame-stepped)
```

- The executor **never vetoes** a Laya macro: it picks the lowest-risk execution
  *within* the macro's intent (§7). A fatal macro → death; that is the design.
- Harness-level exception only when Laya is **absent** (degraded policy, §10) —
  already built and verified in M2.
- **Shot aim (verified empirically 2026-09-25, `tools/diag_shot_dir.py`): Marisa A
  fires fixed UPWARD regardless of movement direction** (player bullets measured
  (0, −20) for SHOT|RIGHT / SHOT|DOWN / SHOT-only). **Correction (2026-09-25):** the
  bullet travels straight up *from the player's x-position*, so to hit a centered
  boss the player must stay roughly in the boss's x-column — DPS is NOT
  position-independent. The optimal spot is **lower center, below the boss**.
- **`guard` strategy (validated 2026-09-25, `tools/test_guard_strategy.py`):** stay
  in the lower center (y≈470), track the boss's x, always shoot, let the evader
  dodge → **WON stage 1 Easy with 0 deaths / 0 bombs** (boss killed f8610, ~98 s
  boss fight). This is the natural Marisa A play and the recommended default macro.
  The big Master Spark laser is the *bomb* laser (marisa_a.c `marisa_laser_bomb_
  masterspark`), so a bomb is both a bullet-clear and a boss DPS burst.
- Playfield bounds (measured): player clamps to x∈[16, 464], y∈[16, 544].

## 3. Macro list (Laya's choice space)

One `choice` question. **v3 (2026-09-25): 8 options.** v2 had 13 (added
`guard`); v3 removed the five options that pull the player into the boss's
dense-bullet zone or off the shot column — `hug_left` / `hug_right` (edges:
shot misses boss), `advance` (top: densest bullets, no DPS gain), `orbit_left`
/ `orbit_right` (close to boss). `resolve_macro_target` still handles those ids
(robustness), but Laya no longer sees them. Rationale: with the v1/v2 sets,
Laya picked the risky options in "danger" moments (advance 59–63%, hug_left up
to 19%), costing lives; the safe subset keeps the player in the guard zone.

| id | description (in prompt) | executor target behaviour |
|---|---|---|
| `guard` **(default)** | Stay low, centered under the boss, and shoot | `below_boss`: (clamp(boss.x,60,420), 470), re-anchored per frame |
| `hold` | Stay in the lower safe zone and shoot | **same as `guard`** (`below_boss`) — robust to Laya's guard/hold confusion |
| `retreat` | Back away toward the bottom of the screen | point-seek (240, 510) |
| `sidestep_left` | Shift a bit left, keep your height | point-seek (x−120, y) |
| `sidestep_right` | Shift a bit right, keep your height | point-seek (x+120, y) |
| `item_sweep` | Collect a nearby item drop (prioritize LIFE/BOMB) | point-seek best item (value-weighted), only if within 250 px |
| `clear_spell` | Stay low and wait out the spell | hold lower third (y ≥ 380), let timer run out |
| `bomb_setup` | Get to a clean spot to use a bomb | hold in place; executor presses bomb on an early/safe frame of the macro |

Plus two `noul` flags and one `score` read (reworded):

- `focus` — **v2 (2026-09-25, G3 fix):** the v1 wording ("use focus while dodging
  dense patterns") was *fatal*: focus halves Marisa's speed (6.25 → 2.75 px/f),
  and the evader can barely dodge at half speed. Controlled test (executor-only,
  stage 2 Easy, seed 12347, `tools/test_guard_strategy.py`): no-focus → **WON, 1
  death**; forced 100% focus → **LOST, 3 deaths**. Campaign 3 stage 2 had focus
  on 56% of macros (noul median 0.579) → 3 deaths. New instructions: focus is
  ONLY for threading extremely narrow gaps; in dense patterns the answer is NO.
  Threshold **0.80** (was 0.5).
- `bomb_now` — reworded (see §5, + Master-Spark DPS framing). Threshold **0.80**
  (0.5 → 0.70 → 0.80).
- `danger` — unchanged (safe/moderate/severe → 0/1/2 float). Logged for tuning.

Macro → executor contract: each macro resolves to one of five **target kinds**
computed at macro-issuance (cheap, once per macro) and refreshed if the anchor
moves: `hold`, `point(x,y)`, `band_x(x0,x1,y0,y1)`, `orbit(center, r, sign)`,
`item(spawn_id)`. The per-frame work is only: risk field + candidate scoring.

## 4. Reflex evader (60 Hz, in-process)

New file `harness/executor.py` — pure code, no Laya.

### 4.1 Hazard set (per frame)

- **Bullets**: `projectiles` with `category == PROJ_ENEMY` and
  `flags & (1<<4)` (ACTIVE_HAZARD, `taisei_sim.h`). Player bullets (cat 3) and
  clearing shots (cat 2) are ignored for risk.
- **Enemy bodies**: `enemies` with `harmful` set (contact damage), radius `hit_radius`.
- **Boss body**: `boss.active && !boss.invulnerable`, radius ≈ 32 (tunable).
- **Lasers**: for each laser with `collision_active`, its sampled points
  (`laser_points[first_point .. +point_count]`); each point is a hazard with
  radius `half_width` *at its `time`*. **v3:** count points with
  `time_shift ≤ time ≤ min(tip + speed·H, death + time_shift)` — the beam is
  predicted to grow over the threat horizon, so a sweeping beam is visible
  before it reaches the player (was: already-drawn points only).
- Pre-filter: keep hazards within `R_scan = 150 px` of the player (v2; was a
  speed-scaled 130 px). Typical count after filter: 100–600.

### 4.2 Risk model

For candidate position `q` (where the player would be after moving one frame
in direction `d` at speed `s`, or staying):

```
risk(q) = Σ_h  w_h · g(dist(q, proj_h) − r_h − r_p)
g(u) = 1 + 10·|u|          if u < 0                      (overlap: steep penalty)
g(u) = exp(−u / 6)         if 0 ≤ u < 56                 (near; G_RANGE v2, was 48)
g(u) = 0                   otherwise
w_h = 1.0 bullets / 1.5 enemy bodies & boss body
```

- `r_p` = player radius ≈ 4 (taisei default; locked POC H/3.5 keeps collision
  lenient — the margin is forgiving).
- For *forward projection*, evaluate `risk` thrice and sum:
  `cost = risk_now(q1) + 0.5 · risk_horizon(q1, H=24 f) + 0.2 · risk_now(q2)`
  (**v3**: H 18→24 f; `q2` = 2-frame-ahead position along the same direction —
  catches threats arriving in the direction of travel; weight 0.20 keeps the
  1-step term dominant). Horizon projection is per-hazard `p + v·t` (linear);
  homing bullets are short-horizon anyway (re-evaluated every frame).
- Overlap term dominates: any candidate inside a hazard → cost ≥ 1.0.
- **v3 results (2026-09-25, `tools/test_guard_strategy.py`, Easy, campaign
  seeds):** executor-only guard — stage 1 WON 1 death, stage 2 WON 1 death,
  stage 3 WON 1 death (stage 3 was LOST 3 deaths on v2; the pre-boss death was
  eliminated by laser prediction + 2-frame lookahead).
- **Trajectory sensitivity (v3 finding):** the stage-3 boss patterns are at
  the evader's margin — a tiny behavioral change flips the outcome. An
  executor-level item-assist bias (curve toward nearby LIFE/BOMB items)
  measurably destabilized the dodge: even β=0.15 within 60 px flipped stage 3
  from WON/1 death to LOST/3 deaths (A/B tested). Item pickup is therefore
  owned by Laya's `item_sweep` (fixed weights incl. life fragments) + passive
  collection, not by the executor.

### 4.3 Candidate set and scoring

Candidates (9): the 8 movement directions + hold, each at the macro's speed
(full 6.25 px/f, or focus 2.75 px/f when the macro's focus flag is set),
evaluated at the resulting next-frame position (clamped to the playfield). Score:

```
score(c) = cost(c) − β · intent(c)
```

- `intent(c)` = alignment with the macro target:
  - `hold` → 1 if c == hold else 0.25
  - `point` / `item` / `below_boss` → cosine alignment of c with the target
    vector (1.0 when within 24 px of the target; 0.2 for hold)
  - `band_x` → 1 inside the band (8 px tolerance), falloff over 120 px
  - `orbit` → tangent alignment + radial correction (stay on the ring)
- `β` per target kind (implemented): hold 0.25 / point·below_boss·band_x 0.8 /
  orbit·item 0.6 (evasion first, intent second; §7: lowest-risk execution
  *within* the macro).
- **Hysteresis**: if `cost(current direction) ≤ ε = 0.05`, a 0.02 tie-break
  nudge keeps it (no twitching when it is safe) → smoother, more human traces.
- Output buttons: 8-dir movement + `ACTION_FOCUS` if the macro focus flag is
  set, + `ACTION_SHOT` always held (Marisa A fires fixed upward —
  `tools/diag_shot_dir.py`).

### 4.4 Bomb handling (executor side)

- `macro.bomb` set → press `ACTION_BOMB` this frame (Laya's decision, §7; no
  auto death-bomb against Laya).
- Bomb button is held 1 frame; `bomb_active` suppresses repeats (already in v0).
- **Degraded mode only** (Laya absent): the fallback policy adds the locked
  death-bomb rule — bomb if death is predicted within **12 f** and a bomb is
  available (requirements §3 shared params). This never fires while Laya is
  present and answering.
- **UPDATE 2026-09-25 (executor v5, in progress — `doc/PLAN.md` M3):** the v1.4.6
  Easy campaign (s3 LOST 2d; bombs_left=3 unused at each death; Laya `bomb_now`
  0.77–0.90 nearby) shows the pre-hit "safe/early" gate + no hit-time net is not
  enough. v5: (1) **hit-time death-bomb** — fire when `pl.death_timer >= 0`
  (engine death window = 12 f, player.c:1020; a bomb during the window cancels
  the death, total cost 2 bombs, player.c:685-692); (2) **immediate macro
  bomb** — on a `macro.bomb` frame fire when age ≤ 10 f or the best candidate's
  cost ≥ ~1.0 (Laya's `bomb_now` is a NOW decision, not a "safe/early" one);
  at most one bomb per macro. §7's "no auto death-bomb against Laya" stands for
  PRE-HIT steering; the net only fires after a hit already occurred (so it can
  never change what Laya chose to do, only the outcome of the hit). Laser model
  also upgraded to the verified capsule + motion-crossing kill with
  wall-proximity penalty (`doc/research-video-fidelity-source-of-truth.md` §7).

### 4.5 Human-likeness knobs (minimal bar, §2)

- Speed choice: focus when macro says so or when best candidate is focus-speed;
  otherwise full speed.
- Hysteresis (§4.3) prevents robot-jitter.
- No diagonal spam: direction changes only when strictly better.
- Bomb usage: only per Laya (threshold 0.80; v5: immediate fire on the macro +
  hit-time safety net, §4.4) → sparse, natural.
- Replay video is the final sanity check (M4).

### 4.6 Performance budget

Per frame (Python): hazard pre-filter (few thousand distance checks) + risk eval
(≈ 21 candidates × ≤ 600 hazards × 2) ≈ 25 k ops ≈ 5–15 ms.
Plus `get_state` list build (M2 measured loop ≈ 54 effective fps).
Worst case ~40–60 fps wall per game frame → an Easy stage (≈ 10–15 k frames)
steps in 3–6 min wall + Laya calls (≈ 150–250 × 1.2 s ≈ 3–5 min) →
**~6–11 min wall per stage; a full 6-stage Easy run ≈ 0.7–1.2 h.**
Overnight runs allowed (§12); no optimization needed until it hurts.

## 5. Prompt v1 (fix the bomb over-trigger)

State text (v1 adds, in `state_compiler.py`):

```
Frame 4123 of stage 2 (Normal), Marisa A. Lives 3, Bombs 2, Power 12, Score 1234567.
Deaths this run: 0.
Boss: [active, 214px below player, phase: spell "..." 42s left | not on screen].
Bullets: 341 active; nearest: 12px above (closing, 3px/f), 28px below-left...
Items: 3 power 40px right; 1 life 60px left; ...
Your last macro: advance. Its result so far: [fine | drifting off-target].
```

`bomb_now` question (v1):

> You have only **3 bombs for the entire stage** and each clears bullets for
> about 5 seconds. **Default is NO.** Answer YES only if (a) the player will be
> hit within the next half-second and no safe move exists, or (b) using a bomb
> right now clearly wins a spell phase or a bad pattern. Otherwise NO.

Threshold 0.5 → **0.70** (`BOMB_NOUL_THRESHOLD` in `agent.py`). Expected effect:
bomb calls drop from ~96% to a few per stage (verify in M3 data; if still > 1 per
stage on Easy, raise to 0.8).

## 6. Episode chaining (one "game" = 6 stages)

- `Agent.carry_over(v)` (exists) → next `EpisodeConfig` `initial_*` fields:
  lives, bombs, stored power, point-item value, score (verify exact C field names
  in `taisei_sim.h` while wiring; `USE_DEFAULT_I32/U64` sentinels for anything
  not carried).
- Per-episode checkpoint (§12): `{seed, carried state, replay file, coverage
  jsonl, stage, outcome}` written to `simdata/checkpoints/ep-<n>.json` after each
  episode → crash-safe overnight runs; final-clear reruns use the same seed.
- Stage 1–6 on the chosen difficulty, `rng_seed` fixed per campaign (one seed for
  the whole 6-stage run; carried state is the only cross-stage mutation).

## 7. Validation gates (M3 exit criteria)

`tools/test_m3_survive.py`:

1. **G1** — stage 1 Easy WON, Marisa A, seed 12345, Laya coverage ≥ 99%
   (untainted), bombs used ≤ 3, deaths ≤ 2, bombs used ≤ 1 (Easy, natural play).
2. **G2** — stage 2 Easy WON (chained from a real stage-1 carry).
3. **G3** — full Easy campaign (6 chained stages) WON, untainted,
   total deaths ≤ 3, total bombs ≤ 3, no sim-cheat fields touched.
4. Replay files for all 6 stages saved (M4 playback input).

Tuning loop: run G1 → inspect `laya-*.jsonl` (macro distribution, bomb/focus
rates, danger drift) + final-state dumps → adjust prompt/β/ε → repeat.
Then G2/G3, then Normal (M4 start).

## 8. Implementation order (this milestone)

| # | Item | File | Status |
|---|---|---|---|
| 1 | `ReflexExecutor` v1 (risk field, candidates, hysteresis, aim) | `harness/executor.py` (new) | [x] 2026-09-25 — executor-only test green (217 s survival vs 14.6 s stand-still; advance/retreat/hug steering verified; `tools/test_executor_only.py`) |
| 2 | Macro table v1 (12 macros + target kinds) | `harness/macros.py` (new) | [x] 2026-09-25 |
| 3 | `agent.py`: QUESTIONS v1, threshold 0.70, executor wiring | `harness/agent.py` | [x] 2026-09-25 (shot aim dropped — Marisa A fires fixed upward, verified) |
| 4 | `state_compiler.py` v1 (difficulty names, held-macro context) | `harness/state_compiler.py` | [x] 2026-09-25 |
| 5 | Carry-over chaining + per-episode checkpoints | `harness/agent.py` (`run_game`, `carry_over`) / `tools/test_m3_campaign.py` | [x] 2026-09-25 (field names verified vs C struct) |
| 6 | `tools/test_m3_survive.py` (G1) + `tools/test_m3_campaign.py` (G2/G3) | new | [x] 2026-09-25 |
| 7 | Run G1 → tune → G3; run log `logs/run-2026-09-25-m3-*.md` | — | [~] G1 running |

Out of scope for M3 (deferred to M4 polish): spell-capture targeting, item
economy optimization (point item value tuning), voltage, human-likeness styling
beyond §4.5, video capture.
