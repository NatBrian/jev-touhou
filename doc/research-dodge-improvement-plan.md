# Plan: minimal dodge-first improvement for Laya Lunatic play

Date: 2026-09-25
Status: **experimental rollout disabled by default; investigation documented**.
Scope: improve the local harness reflex dodge layer before another direct
Lunatic campaign. Do not change the game engine, replay format, Laya model, or
bomb thresholds in this phase.

## 1. Evidence and problem statement

The first direct Lunatic campaign used final-mode Laya on the same
`build-gl33` DLL intended for replay/video:

- Stage 1 WON at frame 12443 after 2 deaths and 7 bombs.
- The Stage 1 carry had raw `lives=0` and `bombs=0`.
- Stage 2 LOST at frame 3363 after one death; the lethal hit was at frame 3320
  in a dense bullet pattern.
- Both stages had 100% coverage, `taint=False`, and zero Laya failures.

Evidence: `logs/campaign-lunatic-gl33-1.log`,
`simdata/laya-m3cam-0925-230434.jsonl`, and
`simdata/checkpoints/m3cam-0925-230434-stage{1,2}.json`.

The current system is not failing because Laya is unavailable. The combined
Laya-plus-harness policy spends the Stage 1 reserve before Stage 2. The
executor is the first correction target because it currently evaluates only a
one-frame movement choice while a coarse `guard` intent continues to pull the
player back under the boss during dense patterns.

Relevant local sources:

- `harness/executor.py`: current v5 risk field, one-frame candidates,
  36-frame hazard projection, laser capsules, wall cost, and bomb handling.
- `harness/agent.py`: Laya macro/focus/bomb parsing and the 60 Hz executor loop.
- `harness/state_compiler.py`: compact state supplied to Laya.
- `doc/design-m3-reflex-and-macros.md` §4: executor contract.
- `doc/requirements-decisions.md` §7: Laya remains the high-level decision
  maker; the reflex layer operates within the selected macro.
- `doc/research-lasers-snapshot.md`: engine-faithful laser snapshot and
  collision evidence.

## 2. Small design to implement

Implement one focused executor improvement: **fixed-heading short rollout**.

For each existing nine movement candidates (hold, four cardinal, four
diagonal):

1. Compute the candidate's first-frame position exactly as today.
2. Continue that same heading for a fixed 8 game frames at the candidate's
   current speed, clamped to the playfield.
3. At each projected point, evaluate the existing projectile risk, laser
   capsule risk, and wall cost.
4. Add the mean future risk to the existing candidate score with a modest
   weight.
5. Keep the existing macro intent, hysteresis, shot, focus, and bomb handling.

Initial constants:

```python
DODGE_ROLLOUT_FRAMES = 8
DODGE_ROLLOUT_WEIGHT = 0.35
```

The first implementation must not add a pattern classifier, a behavior tree,
an item-assist bias, stage-specific coordinates, or a separate path-search
system. Earlier experiments showed that even a small item-assist bias can
destabilize dense trajectories (`doc/PLAN.md` item-assist evidence).

### Exact scoring rule

Refactor the existing candidate risk calculation into a reusable helper. Keep
the current first-frame terms unchanged:

```text
current_cost = risk_now(q1)
             + 0.5 * risk_horizon(q1)
             + 0.2 * risk_now(q2)
             + wall_cost(q1)
             + laser_crossing(prev, q1)
```

For rollout steps `t=2..8`, project the same candidate heading and calculate:

```text
future_cost(t) = projectile_risk(q_t, projectile_time=t)
               + laser_risk(q_t, current_threat_segments)
               + wall_cost(q_t)
```

Use:

```text
score = current_cost
      + DODGE_ROLLOUT_WEIGHT * mean(future_cost(2..8))
      - beta * intent(candidate)
```

The first projected point is already represented by `current_cost`, so the
rollout mean starts at step 2. Preserve the current laser crossing check for
the actual first-frame movement. Do not invent a second laser geometry model.

### Limited danger override

After rollout costs are available, if the lowest-cost candidate still has a
severe score (`>= BOMB_NOW_COST`), attenuate the target-intent beta for this
frame only:

```text
effective_beta = beta * 0.25
```

Otherwise use the current beta unchanged. This does not override Laya's macro:
it lets the safest candidate inside that macro win when every immediate option
is dangerous. If this rule changes too many ordinary frames, remove it and
retain the rollout alone.

## 3. Explicit non-goals

- No lower bomb threshold.
- No automatic pre-hit bomb decision.
- No change to hit-time death-bomb safety.
- No focus-threshold change in the first iteration.
- No Laya prompt/model change in the first iteration.
- No taisei-sim C or build change.
- No stage-specific scripted responses.
- No cross-macro override: Laya's selected macro remains the legal intent.
- No extra network calls; the 60 Hz executor remains local.

## 4. Concrete implementation sequence

### Phase 0 — baseline freeze

- Keep commit `67d9f22` as the direct Lunatic baseline.
- Use the same `build-gl33` DLL, seeds, Marisa A, and final-mode Laya path.
- Do not launch another six-stage campaign until the controls below pass.
- Preserve unrelated existing untracked diagnostics; do not delete them.

### Phase 1 — executor-only implementation — **DONE 2026-09-25**

Modify only `harness/executor.py`:

1. Add the two rollout constants beside the existing executor constants.
2. Add a small position-clamp helper.
3. Add a helper for the existing one-frame risk terms.
4. Add the fixed-heading rollout loop.
5. Apply severe-danger beta attenuation only during candidate ranking.
6. Leave bomb code, shot input, laser collection, and logging untouched.
7. Add an implementation comment referring to this document.

Do not modify `harness/agent.py`, `harness/state_compiler.py`, or Laya
questions in this phase. Implemented in `harness/executor.py`; no files in
those components changed.

### Phase 2 — deterministic tests — **DONE 2026-09-25**

Add `tools/test_executor_rollout.py`, with synthetic hazards and no Laya host needed:

1. A bullet outside the player now but entering a held path makes the rollout
   prefer a lateral candidate.
2. A lateral candidate crossing a laser remains rejected by the existing laser
   crossing term.
3. A clear field preserves the existing guard-directed candidate and does not
   jitter.
4. A wall-adjacent future path loses to a clear central path when immediate
   risk is otherwise equal.

The test must print PASS/FAIL and return nonzero on failure. It must call the
executor's helpers rather than implement a second risk model.

Result: `tools/test_executor_rollout.py` passed all four checks. The existing
`tools/test_executor_only.py` regression also passed: 14,400 frames, status
running at the test cap, 0 deaths, steering checks passed, and bomb macro used
2 bombs. Run evidence: `logs/run-2026-09-25-dodge-rollout-implementation.md`.

### Phase 3 — executor-only game controls — **DONE 2026-09-25**

Run current and improved executor under identical conditions:

1. Easy Stage 3, seed 12348.
2. Easy Stage 6, seed 12351.
3. Lunatic Stage 1, seed 12346.
4. Lunatic Stage 2, seed 12347 with the exact Stage 1 carry when testing
   carry-over behavior.

Use `tools/test_guard_strategy.py` where its guard-only interface is enough and
`tools/diag_guard_stage.py` for explicit resources/carry. Give every run a
unique log and retain replays where supported.

Results with the new executor, Marisa A, the repository's `build-gl33` sim,
and the planned seeds:

- Easy Stage 3, seed `12348`: **WON**, frame `19292`, 0 deaths, 2 bombs;
  terminal lives=3, bombs=0.
- Easy Stage 6, seed `12351`: **WON**, frame `35244`, 2 deaths, 6 bombs;
  terminal lives=3, bombs=0. It is survivable but resource-heavy, so this is
  not treated as a clean resource-regression pass.
- Lunatic Stage 1, seed `12346`: **WON**, frame `15134`, 2 deaths, 4 bombs;
  terminal lives=1, bombs=3.
- Lunatic Stage 2, seed `12347`, entered with the exact Stage 1 carry
  (lives=1, bombs=3, score=2404415, PIV=16473, power=476, graze=1619):
  **WON**, frame `18346`, 1 death, 4 bombs; terminal lives=1, bombs=0.

Evidence is preserved in `logs/run-2026-09-25-dodge-control-*.log`. These are
executor-only controls, not Laya-driven campaign evidence. The Lunatic
Stage 1→2 carry result is sufficient to proceed to the planned Laya A/B.

### Phase 4 — Laya-driven Lunatic A/B — **NOT ACCEPTED 2026-09-26**

Run the existing final-mode campaign runner with the improved executor:

```text
venv\Scripts\python.exe tools\test_m3_campaign.py \
  --build-dir build-gl33 --seed 12345 --diff lunatic
```

Compare directly with commit `67d9f22`:

- Stage 1 must still clear.
- Stage 1 must improve on the baseline carry (`lives=0`, `bombs=0`) or at
  least reduce deaths/bombs without worsening the carry.
- Stage 2 must run from the real Stage 1 carry and improve on the baseline
  loss.
- Every completed stage must retain ≥99% coverage, no taint, and zero Laya
  failures.
- Record deaths, bombs, score, carry, and wall time.

Do not claim Lunatic campaign success unless all six stages actually clear.

First final-mode trial with the rollout (`seed=12345`, `build-gl33`) stopped at
Stage 1: **LOST**, frame `10846`, 3 deaths, 7 bombs, score `1607249`. Coverage
was 100%, `taint=False`, Laya failures were 0, and Laya host health was OK. The
baseline committed campaign reached Stage 1 WON at frame `12443` with 2
deaths and 7 bombs. Therefore this first mixed-policy A/B did not meet the
acceptance gate.

The result cannot yet be attributed to the executor alone. The new trace
selected `guard` on all 98 recorded decisions and had 92 focused decisions;
the baseline trace selected `guard` 112 times plus 4 `item_sweep` decisions
and had 108 focused decisions. The first death landmark was essentially the
same (`f3249` vs baseline `f3250`), but the new run then died at `f7222` on the
left wall and `f9258` in a dense boss pattern; the baseline's later deaths
were at `f10815` and `f11191`. Evidence:
`logs/campaign-lunatic-gl33-dodge-rollout.log`,
`simdata/laya-m3cam-0925-235804.jsonl`,
`simdata/checkpoints/m3cam-0925-235804-stage1.json`, and
`simdata/replays/m3cam-0925-235804-stage1-lunatic.trsr`.

Next action is a bounded repeat/diagnostic comparison with the same code and
build, followed by either acceptance or rejection of the rollout. No Laya
prompt, focus threshold, bomb threshold, or macro vocabulary change is
authorized by this result alone.

The unchanged repeat also failed Stage 1: **LOST**, frame `12065`, 3 deaths,
8 bombs, score `1622333`, with 100% coverage, `taint=False`, and zero Laya
failures. Its Laya trace sampled `guard` throughout and included a different
sequence of focus values and macro timing, so the repeat confirms the rollout
campaign is not presently reliable but still does not make the Laya service a
fixed-policy oracle. Evidence:
`logs/campaign-lunatic-gl33-dodge-rollout-repeat.log`,
`simdata/laya-m3cam-0926-000637.jsonl`,
`simdata/checkpoints/m3cam-0926-000637-stage1.json`, and
`simdata/replays/m3cam-0926-000637-stage1-lunatic.trsr`.

Before accepting or rejecting the implementation, run one temporary
baseline-mode diagnostic through the same final-mode runner with rollout
weight `0` and `DANGER_INTENT_FACTOR=1.0` (the committed default remains
`0.25`). This changes no normal committed behavior and is solely to isolate
the executor term. The reproducible launcher is
`tools/run_dodge_baseline_diagnostic.py`.

That baseline-mode diagnostic also lost Stage 1: **LOST**, frame `11010`, 3
deaths, 6 bombs, score `1438469`, with 100% coverage, untainted, and zero Laya
failures. First lethal event was at `f1238` at the right boundary before the
boss phase; further hits were at `f3221`, `f8263`, `f9848`, `f10330` (laser),
and `f10967`. This confirms that Laya-policy and run variance are material;
the available trials do not isolate a causal executor effect.

Decision: rollout and severe-danger attenuation are **disabled by default**
(`DODGE_ROLLOUT_WEIGHT=0.0`, `DANGER_INTENT_FACTOR=1.0`). The experimental
implementation and synthetic tests remain available for an isolated follow-up,
but the change is not accepted as a production default. Do not continue a full
Lunatic campaign on the experimental version.

## 5. Acceptance and rejection gates

Accept the rollout as the new default only if:

- synthetic tests pass;
- Easy Stage 3 and Stage 6 do not materially regress;
- Lunatic Stage 1 uses no more deaths or bombs than the baseline and produces
  a better carry;
- Laya-driven Lunatic Stage 2 improves over the baseline;
- coverage, taint, Laya host health, replay, and build behavior remain clean.

Keep the change diagnostic-only or reject it if it merely survives by spending
substantially more resources, breaks Easy controls, requires bomb-threshold
changes, or produces unstable/jittery movement.

If executor-only controls improve but Laya-driven controls do not, stop and
run a separate Laya prompt/state experiment. Do not mix that result with the
executor claim.

## 6. Required evidence and commit checkpoints

At each checkpoint update `doc/PLAN.md` and preserve:

- run summaries under `logs/`;
- Laya JSONL traces;
- checkpoints and replays;
- exact build, difficulty, seed, and thresholds;
- test exit status and resource totals.

Planned commits:

1. planning checkpoint: this document plus `doc/PLAN.md`;
2. executor implementation plus synthetic tests;
3. executor-only controls;
4. Laya Lunatic A/B result;
5. only if accepted, another direct Lunatic campaign attempt.

## 7. Current status

- Direct Lunatic six-stage gate: **not met**; baseline stopped at Stage 2.
- Easy Stage 6 policy A/B: **deferred**, not launched.
- Rollout implementation: **experimental and disabled by default**; executor-
  only controls passed, but both rollout Laya trials and the baseline-mode
  diagnostic failed at Stage 1, so no causal attribution or acceptance is
  claimed.
- Laya prompt change: **not started**.
- Final replay/video/human-likeness acceptance: **blocked** until a complete
  Lunatic campaign exists.
