# Research: Lunatic no-bomb trajectory failure analysis

Date: 2026-09-26  
Scope: explain the repeated Stage 1 no-bomb deaths before implementing the
Phase 11 bounded trajectory diagnostic.  
Build: `third_party/taisei-sim/build-gl33`; Marisa A; Lunatic.

## Sources and evidence

All evidence is local and preserved in the repository:

- `simdata/laya-m3cam-0926-012129.jsonl` — instrumented Laya no-bomb/no-focus
  trace with executor candidate costs;
- `logs/run-2026-09-26-no-bomb-wide-scan-lunatic-stage1.log` — executor-only
  `R_SCAN=300` control;
- `logs/run-2026-09-26-no-bomb-horizon60-lunatic-stage1.log` and
  `logs/run-2026-09-26-no-bomb-horizon90-lunatic-stage1.log` — longer-horizon
  controls;
- `harness/executor.py` — current candidate scoring and hazard pre-filter.

## Findings

### 1. The local selector is not ignoring a safer immediate heading

The instrumented trace records the selected index and all nine candidate costs:

| Death-hit frame | Position | Selected index | Selected cost | Minimum cost | Result |
|---:|---|---:|---:|---:|---|
| 3250 | `(262.7, 544.0)` | 3 | 751.7392 | 751.7392 | selected minimum |
| 3836 | `(269.4, 544.0)` | 8 | 418.9686 | 418.9686 | selected minimum |
| 10258 | `(235.3, 544.0)` | 0 | 306.0802 | 306.0802 | selected minimum |

Source: `simdata/laya-m3cam-0926-012129.jsonl`, records with
`status=death_hit`.  The first two records contain eight nearby hazards and
the player is at the lower playfield boundary. The selector is therefore not
making a simple tie-breaking mistake at the recorded lethal frame; the safe
space has already collapsed by then.

### 2. Existing horizon scoring is an endpoint test, not a path test

`ReflexExecutor._candidate_cost` evaluates `c_hor` at one projected endpoint
(`THREAT_HORIZON`) and the optional short rollout only when
`DODGE_ROLLOUT_WEIGHT` is nonzero. The default rollout weight is `0.0` because
the earlier mixed-policy trials regressed. A bullet can cross the candidate's
fixed-heading path at an intermediate frame without being represented by the
single endpoint sample.

This is a bounded, code-level limitation rather than evidence that Laya should
be replaced. The proposed correction keeps the same nine headings and adds an
opt-in intermediate path-risk diagnostic; it does not add a pattern classifier,
stage script, or independent player.

### 3. Simple radius and horizon expansion did not solve the failure

Executor-only no-bomb controls produced:

| Variant | Result | Terminal frame | Deaths | First two hit landmarks |
|---|---|---:|---:|---|
| Normal (`R_SCAN=150`, horizon 36) | LOST | 11814 | 4 | 3251 / 3837 |
| Horizon 60 | LOST | 12145 | 4 | 3223 / 3839 |
| Horizon 90 | LOST | 11470 | 4 | 3224 / 3838 |
| Wide scan (`R_SCAN=300`) | LOST | 11775 | 4 | 3251 / 3837 |

Sources: the three horizon/wide-scan logs listed above and
`logs/run-2026-09-26-no-bomb-executor-controls.md`.  These results reject blind
increases to the horizon or local scan radius as the next correction.

## Phase 11 experiment boundary

The next diagnostic will add only a fixed-heading intermediate path-risk term:

- sample the existing candidate trajectory at bounded intervals before the
  existing horizon endpoint;
- project the already collected hazards with their existing velocities;
- reuse `_risk_at`, laser risk, and the current nine `MOVES` candidates;
- keep the term disabled by default and expose it only through an explicit
  executor-only diagnostic flag;
- keep `allow_bombs=False`, the normal threat horizon, and all Laya prompts
  unchanged;
- reject the experiment if it does not improve the first lethal landmark and
  terminal survival.

This is a trajectory-aware reflex diagnostic, not a second autonomous player:
Laya still selects the macro and the executor only chooses among its existing
frame-level headings.
