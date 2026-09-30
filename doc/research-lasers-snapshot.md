# Research: Laser beam model in taisei-sim — snapshot bug, point-time model, death timing

Date: 2026-09-25
Context: M3 — stage 3 Easy deaths on laser beams the executor "couldn't see";
required to make the reflex executor (v4) and Laya's state description correct
before campaign 6 / the Lunatic clear.

Sources (all in `third_party/taisei-sim/`, fork base ≈ 2026-07-18, HEAD 6e6f8e3e;
local mods: meson build, BGM-init removal, and the sim.c fix documented below):

- `src/player.c:882-907` — `player_realdeath` (teleport, lives--, power ×0.7,
  voltage ×0.9, bombs=3, bomb_frags=0).
- `src/player.c:1020` — `deathtime = global.frames + floor(PLR_PROP_DEATHBOMB_WINDOW)`.
- `src/plrmodes/marisa.c:45` — Marisa `PLR_PROP_DEATHBOMB_WINDOW = 12`.
- `src/player.c` (`player_update`) — on `global.frames == deathtime` →
  `player_realdeath`; on `deathtime > global.frames` →
  `stage_clear_hazards(CLEAR_HAZARDS_ALL | CLEAR_HAZARDS_NOW)` **every frame**
  (the screen is wiped the instant of a lethal hit).
- `src/player.c` (bomb) — bombing while `deathtime >= global.frames` sets
  `deathtime = -1` ("death bomb — unkill the player").
- `src/lasers/laser.c` `laser_collision` — the REAL collision: for each beam
  segment, (a) player-motion-segment vs beam-segment intersection ("Prevent
  phasing through laser beams") and (b) uneven-capsule distance from the player
  point with radius `width/2 - 4` (player radius already subtracted). Beams are
  CONTINUOUS capsules, not sampled points.
- `src/lasers/laser.c:480` — `laser_trace(l, step, func, ctx)`: walks the
  beam's segments, dispatching one sample every `step` px (default step 8.0).
  **Trace stops if the callback returns non-NULL** (`laser_trace_dispatch` /
  `laser_trace_advance`, laser.c:450-478).
- `src/sim/sim.c:331-354` — `collect_laser_point` (snapshot builder) and
  `sim.c:405` — `death_timer = deathtime - frames` (−1 when not dying).
- `src/sim/sim.c:960` — default `laser_sample_step = 8.0`.
- Empirical runs: `logs/guard-v4-s1/s2/s3.log`, `tools/diag_death_hit.py`
  (jsonl `simdata/laya-diag-death-hit.jsonl`), `tools/diag_laser_dump.py`,
  `tools/diag_guard_s3_v4.py` outputs below.

## 1. Death timing model (why the old death log was blind)

Sequence of a lethal hit on frame F (Marisa A):

1. **F**: hazard overlap detected during the frame step → `player_death` sets
   `deathtime = F + 12` and, in the same frame's `player_update`,
   `stage_clear_hazards(ALL | NOW)` wipes **all bullets and lasers**.
2. **F+1 … F+12**: player is invulnerable and frozen at the death position
   (movement input cleared); the field stays empty. A bomb cast in this
   window cancels the death (`deathtime = -1`).
3. **F+12**: `player_realdeath` — teleport to `(240, 590)`
   (`VIEWPORT_W/2 + (VIEWPORT_H+30)·I`), `lives--`, power ×0.7,
   `stats.lives_used++` (this is what `sim.state.deaths` counts).

Consequences for forensics:

- The `deaths` counter only increments at F+12, and every state from F+1 on
  has the field already cleared → a log keyed on the deaths counter sees a
  cleared screen (the "bullets=0" death records of v5/v6 runs).
- The killer exists only in the state **before** frame F. Detect the hit via
  `player.death_timer` (sim.c:405): it flips −1 → ≥0 at F+1; the pre-hit state
  is `prev_v` at that moment. `harness/agent.py` now implements exactly this:
  `_log_death_hit` (pre-hit forensics) + `_log_death_real` (slim record at
  F+12, or absent if the death was bombed away).
- Measured (pure guard, stage 3, seed 12348): `death_timer` 11 → 0 over
  frames 7199 → 7210, hit during frame 7198 (7210 − 12 = 7198 ✓).

## 2. The snapshot sampling bug (fixed)

`collect_laser_point` (sim.c:353) ended with `return userdata;` — non-NULL.
Per the `laser_trace` contract, a non-NULL callback result **stops the trace**,
so each beam contributed exactly ONE sample point (the first segment's start —
the tip for these beams). Measured at stage 3 f7197 (48 collision-active
beams): `laser_points = 44` total (≤1/beam). The beam BODIES were missing from
the snapshot entirely, so any hazard model built on `laser_points` (executor
v3, forensics) treated 200-px beams as a single small dot at the tip.

Fix (local, 2026-09-25): `return NULL;` with an explanatory comment
(sim.c:353-359). Rebuilt with `tools/build_taisei.bat`. Verification:

- Same frame f7197: `laser_points` 44 → **252**; samples at exactly 8.0 px
  spacing along each beam (measured: 8.0, 8.0, 8.0, 7.9, 8.0, 8.0).
- Behavior-neutral with respect to game logic: the DeadLaya fallback stage-3
  run before and after the rebuild produced identical results
  (`status=2 frames=12500 deaths=2 bombs=9 score=4000540`) — sampling only
  feeds `build_snapshot`, never the simulation.

## 3. Laser point `time` is relative to NOW (verified)

`LaserPoint.time` = `segment->time.a + (time.b − time.a)·t` (sim.c:349), which
for these beams is **beam-local time relative to the current frame** (in
frames): the tip point is at `time = 0`, the drawn body is at **negative**
times, and future growth is at positive times (a point appears after
`time` frames). Verified on fully-grown beams (age 42 / 176, timespan 20,
speed 1.0): point times `0.0, −4.0, −7.9, −11.9, −15.9, −19.9` (8 px apart).

The executor v3 filter (`pt.time < L.time_shift or pt.time > t_max`, built on
an absolute-time assumption) discarded the entire drawn body — a second,
independent reason the beams were invisible. Executor v4 (2026-09-25) uses:

```
t_max = min(THREAT_HORIZON, death_time + time_shift − age)   # if death_time > 0
include point iff pt.time <= t_max
```

(drawn body has `pt.time ≤ 0` → always in; growth is predicted up to the
horizon, capped at the beam's death; beams that start later are naturally
excluded because their tip time is still positive).

## 4. The stage-3 kill, captured

Pure guard, stage 3 Easy, seed 12348, hit frame 7198 (pre-hit state):

- Player `(264.1, 491.9)`, moving up-left 6.25 px/f (input UP+LEFT+SHOT).
- Lethal beam: laser[4], origin `(88.9, 186.1)`, drawn tip `(266.1, 483.5)`,
  width 10, age 176, death t=300. Closest beam body point **8.6 px** from the
  player (after subtracting half-width) — the beam passed over the player;
  the real collision (capsule + motion-segment intersection, §1 sources)
  registered the hit.
- With the OLD snapshot (tip point only) the same beam read as 37.9–41.8 px
  away — well inside the evader's "safe" band, so the evader walked into it.
- The pattern: post-midboss "laserball" swarm (stage 3 timeline.c:
  `laserball_fairy` invocations at T+1600 / T+2240 after the midboss death),
  48 diagonal beams sweeping across the lower-center of the screen.

After the fix + executor v4, the same pure-guard run **WON at f19569**
(1 death, 0 bombs, score 4,609,348 — the stage is ~2.5k frames longer than
v3 because the evader now threads the beam bodies instead of walking through
them). `tools/test_guard_strategy.py` frame cap raised 18000 → 36000 to match.

## 5. Laya was also blind to beams (fixed)

`harness/state_compiler.py` had **no laser section at all** — Laya's move
question never mentioned beams. Added (2026-09-25): a laser line reporting the
count of collision-active beams plus the 1–2 nearest beam bodies
(distance from player via the same relative-time point filter, compass-8
direction, width, and "still growing" when `age·speed < timespan`).
Rendered examples (pure guard, seed 12348):

- f6500: `36 laser beam(s) on screen, all far from you.` (1353 chars total)
- f7198: `48 laser beam(s) on screen; nearest: beam 33px away (right, width 10); beam 75px away (right, width 10).` (1414 chars total, within the 1600-char trim budget)

## 6. Status / follow-ups

- Sim fix + executor v4 + state laser line + death forensics implemented and
  smoke-tested 2026-09-25. A/B pending: Laya runs on stages 1–3 (campaign
  seeds), then campaign 6 in final mode.
- Open risk: Lunatic beam density will stress the per-frame cost of dense
  point lists (mitigated by the 150 px scan radius pre-filter); re-check step
  fps during the Lunatic campaign.
- If stock Taisei v1.4.6 rejects anything about the merged replay, note the
  sim's on-wire game version (1.5.0.0) is informational only — see
  `doc/research-trsr-replay-format.md`.

## 7. v1.4.6 re-validation (2026-09-25, post-rebase)

After the engine rebase onto stock v1.4.6 (branch `sim-on-v146` @ d9b12e75), the
laser model was re-validated on v1.4.6 content (`tools/diag_laser_guard_s3.py`,
stage 3 Easy, seed 12348, -O0 build):

- **The sim's `collect_laser_point` is compatible with the v1.4.6 `LaserSegment`**
  (laser.h:85-98 has `pos`, `width.a/b`, `time.a/b`, `discontinuous`); the local
  `return NULL` fix is preserved. The v1.4.6 `quantize_laser` sets each segment's
  `.time = { -t0, -t }` (laser.c:270) — the drawn beam body still carries
  **negative beam-local times**, so executor v4's filter (`pt.time <= t_max`)
  still includes the whole body. No sim/executor laser-model change was needed.
- **The executor SEES v1.4.6 beams.** At the stage-3 laser death (pre-hit state
  frame ~9905): **84** laser points on screen, nearest beam body **8.3 px** from
  the player, 13 points within 30 px — the beam was fully visible in the
  snapshot. The player still died (a sweeping beam the guard's static model
  didn't escape) → a *strategy* gap, not a *blindness* gap.
- The other two stage-3 deaths (pre-hit frames ~14331 / ~17163) had **0 laser
  points** (525 / 293 bullets) → dense-bullet deaths, not laser deaths.
- **Conclusion:** the laser model carries over to v1.4.6 unchanged. The guard
  baseline LOST (stage 3, 3 deaths = 1 laser + 2 bullet) is expected for a
  simple "stay below the boss" macro; the Laya-driven campaign (smarter move
  decisions) — not a laser-model fix — is the path to a clear.
