# Research: evader gap-tracking and the adaptive gap horizon (R4.7, 2026-09-26)

Method: offline replay A/B. `tools/probe_evader.py` replays a recorded
campaign stage deterministically — the Laya macro sequence is fixed from the
trace (no Laya calls), seed/carry identical, executor variant swapped — and
counts deaths from `v.raw.deaths`. This isolates executor behavior from
Laya-call latency variance.

## The failure mode

The local evader (`ReflexExecutor._candidate_cost`) scores 9 headings:

```
cost = c_now + 0.5*c_hor + 0.2*c_2 + wall_cost [+disabled rollout/path terms]
c_hor = _risk_at(candidate, hazards, THREAT_HORIZON=36) + laser_full
```

`c_hor` is a SINGLE future snapshot: "is the candidate position covered 36
frames from now?" In a dense fast swarm (G2 S2: 339-397 bullets, speed
2.5-3.0, radius 10) every position is covered at t+36, so c_hor is a
near-constant across headings; the argmin is decided by the CURRENT field
(c_now). The safe place is the wall row (last row the descending swarm
covers), and within it a TEMPORAL gap — a gap passes column x at some
t in 8..48 frames. A single snapshot cannot see it: the evader
micro-optimizes the current field and is eaten when the coverage arrives
(3 deaths at y=544, G2 S2 f7515/f8021/f11071).

Slow dense rain (G1.5 S1: 104 bullets, speed 1.4-2.0) is different: gaps
are wide and persistent, the single snapshot discriminates, and the wall row
gap-tracks fine (0 S1 deaths). The fix must help the dense-fast case without
weakening the sparse/slow case.

## A/B results (replay, seed 12345, Medium, recorded macro sequences)

Variant = c_hor policy. Window W = {8,16,24,32,40,48}; c_snap = original
t=36 snapshot term; c_min = min over W.

| Variant | c_hor | G1.5 S1 (rain) | G2 S2 (swarm) | G1.5 S3 (hard) |
|---|---|---|---|---|
| V0 (current) | c_snap | 0 WON | **3 LOST** | 3 LOST |
| V1 | min(c_snap, c_min) | **2 WON** (broken) | 1 WON | 3 LOST |
| VA2 | snap < 2 ? c_snap : min | 0 WON | **3 LOST** | 3 LOST |
| **VA4 (R4.7)** | snap < 4 ? c_snap : min | **0 WON** | **0 WON** | 3 LOST |
| VA8 | snap < 8 ? c_snap : min | (0, untested here) | 1 WON | — |
| VA16 | snap < 16 ? c_snap : min | (—) | 1 WON | — |
| VA4w | VA4, window {4..60} | 1 WON (worse) | 0 WON | 3 LOST |
| VB | max(c_min, 0.5*c_snap) | — | **3 LOST** | — |
| VC | 0.5*c_snap + 0.5*c_min | — | 1 WON | — |

Key observations:

- **Always-min (V1) breaks the rain**: in sparse rain the gap-min is
  uniformly low at every column (a gap passes everywhere within 36 frames),
  so the horizon term stops discriminating and the argmin collapses to
  current-field micro-optimization (G1.5 S1: 0 -> 2 deaths).
- **Threshold 4.0 (VA4) is the sweet spot**: costs measure ~0.2-3 in safe
  states and 250+ in full walls; T=4 separates them. T=2 (VA2) fires the
  gap search too often (S2 regresses to 3, incl. a mid-band death);
  T>=8 still works on S2 but with less margin.
- **Window {8..48} beats {4..60} (VA4w)**: the wider window adds cost
  (42.8 s vs 32.3 s replay) and degrades the rain (0 -> 1 death) — the
  t=4/t=60 snapshots are noisier.
- Blend/max forms (VB/VC) are strictly worse on the swarm than the clean
  min.

## R4.7 (as implemented)

`executor.py`: `gap_horizon` flag (opt-in `--gap-horizon`), constants
`GAP_HORIZON_TTS = (8, 16, 24, 32, 40, 48)`, `GAP_HORIZON_SNAP_AT = 4.0`:

```
c_snap = risk_at(candidate, t=36) + laser_full
if gap_horizon:
    c_min  = min over t in GAP_HORIZON_TTS of (risk_at(t) + laser_full)
    c_hor  = c_snap if c_snap < GAP_HORIZON_SNAP_AT else min(c_snap, c_min)
else:
    c_hor  = c_snap
```

Behavior is bit-identical to the pre-R4.7 executor in sparse states
(c_snap < 4) and when the flag is off. Cost: 6 extra snapshot evaluations
per heading (hazards pre-filtered to R_SCAN=150 px) — replay speed ~1.7x
slower than V0, negligible against the Laya-call-bound campaign pace.

## S3 residuals (next target if live S3 fails)

G1.5 S3 replay deaths (VA4): f1920 wall (559-bullet normal-section swarm,
denser than G2 S2's 339-397), f4434 left-bottom corner (x=16, y=544),
f9784 left edge (x=16, y=411). The corner/edge deaths are a second trap
class: the cost landscape pushes the player into the corner (both walls
cheapest) and the corner closes in. Candidate follow-up: a corner-zone cost
(R4.7b, both-bands intersection only — must not touch the safe edge row).

## The tracking convergence storm class (G2.91 S1, 2026-09-26)

A third pattern class, found in the G2.91 run (`m3cam-0926-163143`, S1
f~11000-12300; state dump f12290): 96 bullets, speed 2.5, radius 12,
omnidirectional, boss spellcard HP 13%. The storm RE-AIMS at the player's
CURRENT position with a 14-40 frame lag (each wave's aim point ~= where the
player was ~1 s earlier).

- Kill disk: bullets pass through the aim point; the lethal zone is ~16 px
  radius (bullet 12 + player 4). One 6.25 px frame step cannot exit it;
  3-4 frames of continuous straight motion (18.75-25 px) can.
- Cost landscape at the death (dump f12280): c_now 41-271 (bullets ON the
  player) but c_snap/c_min ~= 0 — the storm passes through and clears ~15
  frames later, so neither the t=36 snapshot nor the R4.7 multi-horizon term
  can deter the player from holding/oscillating at the aim point.
- Measured VA4 replay (death f12297): hold, down, UL, 6 holds at the wall,
  2 diagonal steps, 3 holds, dead — the per-frame argmin oscillation (3
  holds in 6 frames) stalls the player exactly where the re-aimed wave
  converges.
- Schedule-variance dominated: on the 163143 macro sequence BOTH the V0 and
  VA4 replays die in the storm (f12327/f12297); on the 113108/121236
  sequences the same pattern class is survived (0 S1 deaths). The pattern
  sits close to the survival threshold; the outcome flips with the decision
  schedule (tunnel latency -> macro sequence -> trajectory).

## R4.8 escape commit A/B (2026-09-26) — why no positional lever works

R4.8 (`executor.py`, opt-in `--escape-commit`): while min cost >=
`ESCAPE_COMMIT_AT` (40), pin the cheapest FULL-DISPLACEMENT heading
(wall-clamped headings excluded) for `ESCAPE_COMMIT_FRAMES` (4) frames —
a straight-line escape long enough to clear the 16 px kill disk.

| Config | 113108 S1 (rain) | 163143 S1 (storm) | 121236 S2 (swarm) | 113108 S3 |
|---|---|---|---|---|
| VA4 baseline | **0** | **1** | **0** | **3** |
| commit (full policy) | 1 | 1 | 0 | 3 |
| commit (lateral_band) | 1 | 3 LOST | 3 LOST | 3 |
| lateral-edge cost K=20 (30 px) | 3 LOST | 1 | 2 | — |
| corner cost K=1..200 (R4.7b) | — | — | — | 3 (unchanged) |

Findings: (1) the full-policy commit cannot save the storm — the player is
in the bottom band, the "cheapest full-displacement heading" ends at a wall,
and the re-aimed storm converges there (163143 S1 1->1, earlier frame);
(2) the lateral_band policy (prefer pure left/right in the horizontal band)
is far worse — a forced straight line at 6.25 px/f overshoots the ~20-30 px
gaps and pins the player into the wall row (two LOST stages); (3) the
lateral-edge cost (K=20 within 30 px of the side walls) breaks the rain
stage (113108 S1 0->3) — the rain gap-track uses the lateral edges; (4)
corner costs below ~50 are negligible against full-wall costs (250+) and
higher values only move the death around. Conclusion: the evader's
micro-oscillation (VA4) is the best measured behavior; the remaining S1
storm death is schedule variance, not an executor defect. G2.92 therefore
runs R4.7 only (decision-schedule re-roll + first VA4 pass at S3-S6).

Sources: `tools/probe_evader.py` outputs (2026-09-26, this file's tables);
state geometry dumps `simdata/probe-states/g29-g15-s1-edge/` (G1.5 S1 wall
survival), `simdata/probe-states/g29-g2-s2-pin/` (G2 S2 swarm),
`simdata/probe-states/g29-g15-s3b/` (S3 death classes),
`simdata/probe-states/g291-s1/` + `g291-s2/` (G2.91 storm + S2 band death);
traces `simdata/laya-m3cam-0926-{113108,121236,155009,163143}.jsonl`.
