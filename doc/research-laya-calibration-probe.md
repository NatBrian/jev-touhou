# Research: Laya answer calibration probes (2026-09-26)

Purpose: find which (checkpoint × question × state) combination gives a
discriminative "must escape now" signal, because G1 showed the 8-way `move`
choice's guard prior cannot be overridden by prose and the death forensics
showed the player dying pinned at the bottom edge with the dodge line already
saying "hit in ~4 frames".

Tools: `tools/probe_laya_calibration.py` (synthetic states),
`tools/probe_laya_states.py` (real full-state texts from a campaign replay),
`tools/dump_probe_states.py` (replays a recorded stage deterministically —
same seed/carry + exact macro/focus sequence from the trace — and writes
`compile_state(v)` at chosen frames; used to build the real states without
re-running Laya).

Probe states: `simdata/probe-states/m3cam-0926-104724-s2/` (9 frames of the
G1 Medium Stage 2: f500, f1500, f2500, f3657, f3715, f5000, f6500, f8196,
f8253 — the last three are the decision frames just before/at the two
bottom-edge deaths, plus one near the first).

Server: `http://127.0.0.1:8002` (L20X; english/typed-decisions/multilingual
all loaded). Client: `harness/laya_client.py` (supports `model=` forcing).

## Findings

### 1. Laya is deterministic — no sampling noise
Four identical calls on the same state returned bit-identical values
(0.363 stay/stay/stay/stay). Consequence: the per-frame guard_p variation in
G1 traces (0.38→0.71) is genuine STATE discrimination by the `move` question,
not noise. (Earlier audit wording "near-constant parsed guard" stays true for
the *parsing* — argmax is always guard — but the underlying probabilities do
track state.)

### 2. Question NAMES do not matter; instruction text does
In the same batch, `bomb_now` repurposed with the evade criteria and a NEW
question named `evade` with identical criteria returned IDENTICAL values in
every probe (e.g. 0.363/0.363, 0.62/0.62). The answer is a function of
(instructions × state × checkpoint), not of the question name. This means
out-of-distribution question names are not the problem — but new instruction
TEXT is a new task the checkpoint may not have calibration for.

### 3. Checkpoints behave very differently
- **english (auto-routed for these states)**: on SYNTHETIC ~300-char states
  the new evade criteria are weakly discriminative (0.31 safe → 0.41 danger);
  on REAL full 1.5KB states they are clearly discriminative:

  | frame | situation | bomb_now(evade criteria) |
  |---|---|---|
  | f500 | safe, pressure 4/0/0/2 | 0.486 |
  | f1500 | safe, 0/0/0/0 | 0.484 |
  | f2500 | tth 6f, pressure 2/4/1/8 | 0.322 |
  | f3657 | safe-ish, 4/3/4/2 | 0.419 |
  | f3715 | **tth 4f, bottom 34px** (death in 22) | **0.620** |
  | f5000 | safe, 4/6/4/4 | 0.171 |
  | f6500 | tth 37f, bottom 22px | 0.372 |
  | f8196 | tth 38f, 0/0/0/0 | **0.672** |
  | f8253 | **tth 8f, bottom 5px, press 25/0/10/11** (death in 16) | **0.597** |

  All death-adjacent frames ≥ 0.597; every non-danger frame ≤ 0.486. Clean
  gap → threshold 0.55 separates them. (Caveat: n=9 hand-picked frames from
  one stage; the margin is wide, and the campaign trace will show the full
  distribution. f8196's high score on a "safe" frame means the trigger will
  also fire on some non-lethal frames — acceptable: an escape pulse costs
  one macro period.)
- **typed-decisions**: flat 0.35–0.42 across all 9 real states (no signal).
- **multilingual**: flat 0.96–0.996 (always-YES; `move` answers
  retreat/hold/item_sweep with guard_p ≈ 0.03–0.25). Always-evade prior —
  the opposite failure mode; would never guard. Unusable as a trigger.

### 4. The direction question is not state-based
`evade_dir` / the 2-way stay-vs-evade choice: english picks
sidestep_right in 6/9 states regardless of content (one sidestep_left on the
safest frame). Stay/evade 2-way: stay ≈ 0.55 in all states. The model's
direction prior is uninformative → the escape DIRECTION must be resolved by
the harness from the same pressure numbers the dodge line shows Laya (this is
target resolution, consistent with `guard` → below-boss point).

### 5. Reference: original questions also discriminate on full states
Original bomb-allowed `bomb_now` on the same 9 frames: 0.387–0.561 on
non-danger, 0.655–0.799 on the three danger frames — consistent with G1's
149/295 calls ≥ 0.8. The `move` guard_p does NOT separate danger from safe
(0.53–0.66 both) — confirming the 8-way/6-way choice cannot be the trigger.

## Conclusion (drives R4.1)

- Keep auto routing (serves `english`).
- No-bomb mode: repurpose the in-batch `bomb_now` question with the numeric
  evade criteria (fewer than ~30 frames to hit; within 40px of an edge with
  pressure toward it; any-direction pressure ≥ 8). Threshold 0.55.
- Question set stays at 4 (move/focus/bomb_now/danger) — no added tokens or
  latency vs baseline; remove the new-name `evade`/`evade_dir` questions.
- On trigger, harness resolves direction: top/bottom edge (40px band) →
  `retreat` (pulls up/center); otherwise sidestep to the lower-pressure side
  (90px box, 180px tiebreak, left on full tie).
- Laya remains the decision maker: it answers the evade question; the
  harness only resolves the coarse intent into a target, exactly as it
  already does for `guard`.

## Post-run addendum (G1.5, 2026-09-26)

The G1.5 campaign (`m3cam-0926-113108`, R4.1) confirmed the threshold works
on Medium S1/S2 (evade 4.8%/13.6% of decisions; S1 0 deaths, S2 WON) but
surfaced two calibration limits that drove R4.2 (full forensics in
`logs/run-2026-09-26-g15-medium-r41.md`):

1. **Dense-stage compression.** In sustained-dense Stage 3, the `english`
   evade answer compresses to 0.25–0.45 even when the state line says
   "nearest bullet will hit you in about 0 frames … near the bottom 0 px
   edge" with pressure 29/11/22/22 (deaths f5323/f9682: last-decision
   answers 0.432/0.253, both < 0.55). The S2 calibration gap (0.60–0.67
   danger vs ≤ 0.49 safe) does NOT hold when "dense" is the stage baseline —
   the model normalizes urgency to the local density. A fixed threshold on
   the model answer alone cannot gate the escape in dense stages.
2. **Pressure-direction is a wall trap.** Picking the lower-pressure side
   when already pinned to a side wall sends the player into the wall (no
   bullets exist past the wall, so that side's pressure is structurally 0):
   S2 f13507 died at x=16 after an evade chose `sidestep_left` (pressure
   l=0/r=8). Escape direction must be "away from the pinned edge," not
   "toward the lower pressure," while edge-pinned.
3. **Edge pinning is a cost-landscape effect, not just a model effect.** The
   wall removes half the escape directions AND the executor's cost landscape
   pulls the player to the wall: off-screen space has zero bullet cost and
   the wall cost (WALL_K=0.5) is negligible vs bullet costs (200–660). So
   even a correct model answer can be undone frame-by-frame. This is why the
   harness exiles from the same state-compiler numbers (edge band 40 px +
   tth < 25 f) and why the existing opt-in `--edge-escape` wall penalty is
   the next lever (G2.5).

Consequently R4.2 makes the escape a bounded harness reflex: the model
answer still gates the *intelligent* escape (open field, calibrated), but a
pinned edge + imminent hit exiles regardless of the answer, and the target
is always resolved away from the edge.

Provenance: probe outputs were printed to the session console on 2026-09-26
(see `tools/probe_laya_calibration.py` and `tools/probe_laya_states.py` for
reproduction; state files preserved under `simdata/probe-states/`).
