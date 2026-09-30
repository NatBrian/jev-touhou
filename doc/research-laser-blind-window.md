# Research: laser time semantics, the evader blind window, and the S5 lasertrap

Date: 2026-09-26
Trigger: G2.93 re-roll (`m3cam-0926-183317`) + standalone S4/S5/S6 measures
(`m3cam-0926-184353` / `-185159` / `-185445`) all lost 4+ lives in S4-S6, while
the S4/S6 laser deaths showed **evader cost ≈ 0 with a beam 1-4 px from the
player** (`logs/run-2026-09-26-g293-measures.md`).

## 1. Engine laser model (sources)

- `third_party/taisei-sim/src/lasers/laser.c`
  - `laser_prepare_sampling_params` (laser.c:124-149): the **drawn** range of a
    laser at frame `f` (age `A = f - birthtime`):
    ```
    t = A*speed - timespan + timeshift
    c = timespan, clamped:  t + c <= deathtime + timeshift
    if t < 0: c += t; t = 0            -> drawn laser-time range [t, t+c]
    ```
    i.e. the trace covers exactly the currently-drawn (killable) beam. For a
    growing beam (speed 1, timeshift 0): `[0, min(A, death)]`; for a
    retraction-phase beam (A > death): `[A - span, death]` (the tip is pinned,
    the base recedes); for `laser_make_static` beams (speed 0, timeshift =
    timespan): the full curve `[0, timespan]` from birth.
  - `quantize_laser` (laser.c:171-303): samples the curve at 0.5 laser-time
    steps; **laser.c:270 stores `.time = { -t0, -t }` — NEGATED laser time**.
    Since the drawn laser-time range is ≥ 0, **every snapshot point has
    `time ≤ 0`** (base ≈ 0, tip most negative). The trace contains **no future
    growth** (no points with time > 0).
  - Kill condition (laser.c:495): `age > deathtime + timespan * speed`.
    So for a beam with speed 1, the beam stays alive (drawn + collidable) for
    `deathtime + timespan` frames after birth.
  - Collision (laser.c:526-604): per quantized segment, `ucapsule_dist_from_point`
    with endpoint radii `max(width*0.5 - 4, 2)` (laser.c:578-579) +
    motion-crossing kill (laser.c:571-574). Culling: segments are dropped when
    fully off-screen (laser.c:262-267) — off-screen beams are neither drawn
    nor collidable (verified: a beam fully outside the viewport has
    `point_count == 0` in the snapshot, `tools/diag_laser.py` f17095 output).
  - `laser_charge` (laser.c:731-746): charging beams ramp width 0 -> target;
    `collision_active = (width > 0.6 * target)` — beams are **visible but not
    killable** during the charge.
  - `create_laser` defaults (laser.c:36-64): `width = 10`, `speed = 1`,
    `collision_active = true`; `create_laserline_ab` (laser.c:70-80) uses
    `timespan = 200` + a `laser_charge` task.
- `third_party/taisei-sim/src/sim/sim.c`
  - Snapshot laser array (sim.c:498-534): **ALL** lasers are included (no
    `collision_active` filter), each with stable `spawn_id`, `age_frames`,
    `width`, `speed`, `timespan`, `death_time`, `time_shift`,
    `collision_active`, and its trace points.
  - `laser_trace` step = `laser_sample_step` (sim.c:965, default **8.0 px**
    arc-length) — denser than the evader's `LASER_BREAK_GAP = 14 px`, so
    segment building never fails on sampling density.
  - Measured in replay (`tools/diag_laser.py`, S4 measure f15980-17105):
    beam point times are `[-12.6, 0.0]`, `[-8.9, 0.0]`, `[-0.0, 0.0]` —
    always ≤ 0. Confirms the negation.

## 2. The evader blind window (bug)

`harness/executor.py::_collect_hazards` (pre-R5.1):

```python
if L.death_time > 0:
    t_max = min(THREAT_HORIZON, L.death_time + L.time_shift - L.age_frames)
else:
    t_max = THREAT_HORIZON
if t_max < 0:
    continue                       # <-- beam skipped entirely
...
if pt.time > t_max:                # never fires for drawn beams (times <= 0)
    last = None; continue
```

`segs_now` (both endpoints time ≤ 0) and `segs_full` (time ≤ t_max) were
designed under the wrong assumption that positive snapshot times are "future
growth". In reality (laser.c:270) all times are ≤ 0, so:

- For `t_max ≥ 0` (age ≤ death + shift): every point is kept — the full drawn
  beam is visible. Correct.
- For `t_max < 0` (**age > death + shift**, i.e. the retraction phase, while
  the engine keeps the beam alive until age > death + span·speed): the beam is
  **skipped entirely** — invisible to the evader although fully lethal.

The blind window is `(death + shift, death + span·speed]`:

| beam source (measured stage) | params (speed, span, death, shift) | blind window | frac of life |
|---|---|---|---|
| S4 `vampiric_vapour.c:79` / `blow_the_walls.c:55` (las_accel) | 1, 50, 100, 0 | age 101-150 | 1/3 |
| S4 `animate_wall.c:78` | 1, 50, 80, 0 | age 81-130 | 41% |
| S4 `vlads_army.c:125` | 1, 20, 200, 0 | age 201-220 | 10% |
| S5 `lasertrap` arcs (las_circle, static) | 0, 210, 210, 210 | none (shift=span) | 0 |
| S6 `broglie.c:163` (las_sine, width 20) | 1, 75, 100, 0 | age 101-175 | 75/175 ≈ 43% |
| S6 `maxwell.c:27` | 1, 200, 10000, 0 | age 10001-10200 | ~0 |

Measured deaths explained (all: state compiler reports the beam; evader cost
≈ 0; beam overlaps the player):

- S4 `m3cam-0926-184353` f15989 (341.6, 525.2): "beam 1px away (on top,
  width 10)", costs [1.0, 0.9, 1.1, 9.1, 0.7, 1.7, 0.7, 2.0, 0.8].
- S4 f17102 (246.7, 487.7): "beam 3px away (on top, width 10)", costs ~1-22.
- S6 `m3cam-0926-185445` f17600 (265.0, 543.2): "beam 1px away (on top,
  width 20)", costs 1.5-4.7.
- S6 f17956 (372.0, 486.5): "beam -2px away (on top, width 20); beam 4px
  away", costs **all 0.0** while a beam centerline is inside the player.

A segment 1 px from the player with r = max(10/2-4, 2) = 3 and r_p = 4 would
cost `1 - 10·(1-3-4) = 51` — so zero cost proves the beam was absent from
`segs_*`. Only the `t_max < 0` skip produces that (the keep() pre-filter
keeps segments < 210 px; the points are ≤ 0 ≤ t_max otherwise).

**R5.1 fix**: the trace IS the drawn beam — drop the time filter entirely
(keep all points of every collision-active beam). Bit-identical outside the
blind window; adds visibility of retraction-phase beams. Growth (tip
extension beyond the drawn body) is NOT in the trace and remains unmodeled
(R5.2b candidate).

## 3. The S5 lasertrap (all four S5 measure deaths are in the normal section)

S5 measure `m3cam-0926-185159` (carry lives 3, score 9.0M): LOST at f6187,
4 deaths at f1396 (bullet wall) + f5544 / f5846 / f6144 (300 f apart — the
`lasertraps` task, `num=3, interval=300`). All three late deaths: "No boss on
screen (normal-attack section)".

Pattern (`src/stages/stage5/timeline.c:718-787`, `laser_arc` at :674-683);
model C-verified against the sim 2026-09-27 (replay forensics +
`tools/diag_origins.py`, `tools/diag_ballspawn.py`, `tools/diag_ballfield.py`):

- `lasertraps`: fires `lasertrap` at `cwclamp(global.plr.pos, 0, vp)` —
  **centered on the player's current position** (verified: every arc's
  L.origin equals the player position at spawn exactly, sim.c:519),
  3 times, 300 f apart (S5 Normal: f5361 / f5661 / f5961).
- `lasertrap`: `traptime = 160`, `boomdelay = 30`, `boomtime = 190`
  (Normal); 5 arcs × 72° (`narcs=5`), `laser_make_static` (fully drawn at
  spawn), `laser_charge(target_width=18, charge_delay=traptime)`:
  - Arcs spawn at `preradius = 120 + 160·4 = 760`, shrink at 4 px/frame
    (`animate_arc`), reach r=120 at t=160.
  - **collision_active only from t = 161** (r=116, kill radius
    max(width/2-4, 2) = 2; full width 18 at t=170, kill radius 5), then the
    ring collapses 116 → 0 (r=0 at t=190), fades to inactive at t=199,
    lifetime ends t=210. **Lethal band** |d - r(t)| < kill radius: max
    OUTER EDGE = 118 (at t=161).
  - 5 × `pp_soul` (`lasertrap_arc_bullet`, :696): spawn at t=0 at the arc
    START angles, kill radius 36, `PFLAG_NOAUTOREMOVE`, track
    `l->prule(l, 0)` (radius r(t)) each frame, die at t=190. These are the
    "5 radius-36 bullets sitting 16-26 px away" in the death hit_states
    (r(t) ≈ 12-22 near the endgame) — NOT the balls.
  - **The balls spawn at t=190 (BOOMTIME), not t=0**: line 745
    `common_charge(boomtime, ...)` BLOCKS the lasertrap task body for 190
    frames (common_tasks.c:142: `for i < time: WAIT(1)`) before the ball
    loop runs. Normal: `cnt=28`, `ringcnt=4` → 8 rings × 28 `pp_ball`
    (kill radius 12.6) = 224 balls at t=190/197/204/211 (56 per wave; odd
    rings WAIT(7)). Each: `pos = center - aim·16`,
    `move_asymptotic(6·aim, -2·aim·⊥, 2^(-1/30))` — radial speed 6→0 px/f,
    tangential 0→2 px/f (alternating spin per ring): they spiral OUTWARD
    (measured: the cage band sweeps outward ~2 px/f, reaches d≈136 at
    t≈225, asymptotic radius ≈ 245). The old "cage settles at r≈16-26" was
    the souls, not the balls.
- Kill geometry: the ring is a sealed 360° circle. Crossing the lethal band
  kills. The only safe play: **be at d >= 121 by t=161 and stay outside the
  band while the beam is active (t=161-199)** — e.g. sprint outward from
  the center (from d≈25, r=136 is reached in ~18 f at 6.25 px/f, t≈153-161)
  and hold the circle. The souls (r=36 discs at the 5 arc-start angles)
  cross d=136 at t≈156 and block ±15.8° each — aim for the ~42° gaps.
  After t=199 the beam is gone; the ball cage (visible moving bullets) is
  handled by the normal cost model.
- Evader failure: during t=0-160 the arcs are `collision_active = 0` —
  invisible to the evader (`_collect_hazards` filters on the flag) and to the
  state compiler (`lasers_active` filter; the ring only enters the state text
  within 150 px at t ≈ 152). When the ring turns lethal at r ≈ 120 (t=161),
  the evader sees a sealed wall of beams collapsing at 4 px/f: the inward /
  hold headings cost ~0 (the beam is > 56 px away), the outward headings cross
  the lethal annulus — the player stays at the center and dies when the sweep
  passes r ≈ 10-40 (t ≈ 175-190), plus the ball cage.

Required behavior: detect the **converging drawn ring** (all beams, active or
charging; ≥ 2 same-origin shrinking beams near the player) and run to the
safe circle through the largest angular gap, avoiding the soul discs, and
HOLD it until the beam is inactive. **R5.2** implements this (opt-in
`--laser-ring`, iteration 3, 2026-09-27): the detector groups snapshot beams
by quantized circle origin (>= 2 beams within 350 px of the player, radii in
[40, 760] with per-beam spread <= 10%, shrinking >= 3 px/f — the trap shrinks
at exactly 4 px/f and the f3769 false positive at 2.1 px/f is rejected), and
the escape walks the nearest reachable point on the r=136 circle (wall +
large-hazard points skipped; nearest point >= 8 px away, re-aimed per frame)
until last detection + 24 f (~t=204 > t=199). A stationary player dies to
every trap; probe-verified: all three traps survived at d~135.6.

Note on detection limits: the snapshot contains ON-SCREEN points only
(quantize culls off-screen segments, laser.c:262-267), so the ring first
becomes visible at r ~ 454 with two arcs — full 360° coverage is never
observable; the detector needs same-origin shrinking beams, not coverage.

## 4. Consequences for the life budget (measured norms, R4.6 compiler)

VA4 + `--gap-horizon`, seed 12345, Normal:

| stage | run | deaths (of 4 carried) | class |
|---|---|---|---|
| S1 | G2.93 | 1 (WON, f7752 bottom wall) | wall/edge |
| S2 | G2.93 | 2 (LOST, f7500 wall, f8720) | wall/edge |
| S3 | G2.92 | 3 | wall gauntlet (3 swarm waves) |
| S4 | measure | 4 (LOST) | 2 wall (f10193, f14629, both y=544, exile_eff) + 2 laser blind window (f15989, f17102) |
| S5 | measure | 4 (LOST f6187) | 1 wall (f1396) + 3 lasertrap (f5544, f5846, f6144) |
| S6 | measure | 4 (LOST f17999) | 2 wall (f625, f1379, y=544) + 2 laser blind window (f17600, f17956) |

Corrected chain budget (base 3 + 5M + 10M [+ scythe] ≈ 6 total lives; no
re-grant — `doc/research-lives-score-extra-life.md` §2a/§6): a clear needs
d1+d2 small, d3 ≤ 3-4, d4 ≤ 1, d5 ≤ 1, d6 ≤ 1 (T_S6 = 3 - d4 - d5 after the
10M grant). Re-rolling cannot fix S4-S6 (norms 4 ≥ budget) — the executor
must improve:

- **R5.1** (blind window): removes S4×2 + S6×2 laser deaths → S4 norm 2,
  S6 norm 2.
- **R5.2** (laser-ring escape): removes S5×3 → S5 norm 1.
- Remaining: wall deaths S4×2, S5×1, S6×2 (all at/near the bottom edge,
  3 of 5 with exile_eff). R6 candidates: `--path-risk` (PATH_RISK_WEIGHT 0.35,
  12 f, already implemented but never A/B'd in campaigns), longer max-path
  rollout, exile-target safety.

Note (2026-09-27, re-verified in code): ITEM_LIFE grants +1 life directly
(`item.c:355-357` `player_add_lives`; the fragment path
`PLR_MAX_LIFE_FRAGMENTS=5`, `player.h:43`, is separate), and M items drop
at the 5M/10M/20M thresholds — so the campaign budget is 3 base + 0-3 M =
3-6 lives (total deaths <= 2-5), refining the "~6" estimate above
(`logs/run-2026-09-27-r5r6-matrix.md` §6).

## 5. Verification tooling

- `tools/diag_laser.py` (new): replays a measured stage (trace macros,
  `--lives N` override to survive past game-over) and prints per-frame, per
  beam: age/speed/span/death/shift, the evader's t_max, point time range,
  closest-point distance, and `_laser_risk` at the player + 9 candidates for
  segs_now/segs_full. Used to (a) confirm all snapshot times ≤ 0, (b) confirm
  the t_max<0 skip, (c) read the S4/S6 beam params.
- Probe A/B (`tools/probe_evader.py` with the new `--laser-blind-fix` /
  `--laser-ring` flags) on the 4 measurement traces + G2.93 S1/S2 + G2.92 S3
  is the promotion gate for R5.
