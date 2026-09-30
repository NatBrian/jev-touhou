# Research: why Laya still fails on Medium no-bomb play

Date: 2026-09-26  
Question: why does the no-bomb Laya policy fail even at Medium difficulty?  
Scope: explain the Hard→Medium campaign results without claiming a six-stage
clear.

## Evidence

### Medium campaign

Source: `logs/campaign-medium-gl33-no-bomb-1.log` and the preserved artifacts
listed in `logs/run-2026-09-26-medium-no-bomb-campaign.md`.

- Stage 1: **WON**, frame `12337`, 0 deaths, 0 bombs.
- Stage 2: **LOST**, frame `14808`, 3 deaths, 0 bombs.
- Coverage: 100%; taint: false; Laya failures: 0.
- Stage 1 carry into Stage 2: `initial_lives=2`, `initial_bombs=0`,
  `initial_power=600`, score `2196675`.

The result is important: Laya can clear the full Medium Stage 1 without
dying. The failure begins in Stage 2, not at campaign startup or because the
Laya service is unavailable.

### Medium Stage 2 lethal records

Source: `simdata/laya-m3cam-0926-081314.jsonl`, records with
`status=death_hit`.

| Frame | Position | Context | Selected move | Candidate result |
|---:|---|---|---:|---|
| 7052 | `(296.8,544.0)` | 245 bullets, dense downward wave | 5 (up-left) | minimum cost `247.24` |
| 14524 | `(464.0,16.0)` | 286 bullets, player at upper-right corner | 0 (hold) | minimum cost `208.44` (tie) |
| 14765 | `(204.5,509.4)` | 138 bullets, focus speed 2.75 | 7 (down-left) | minimum cost `311.88` |

At all three records the executor selected the lowest-cost or tied-lowest
candidate. This means the failure is not simply Laya ignoring a clearly safe
executor heading. By the lethal frame, the local candidate set is already
unsafe or the player is trapped at a boundary.

### Laya behavior

The Medium Stage 2 trace contains 295 successful decisions, all parsed as
`guard`. The trace's `focus` field is the raw Laya probability, not the emitted
focus button: only 32 of the 295 decisions crossed the 0.80 threshold. The
trace does not preserve the raw move choice before no-bomb remapping, so the
295 parsed guard values cannot prove that Laya literally answered guard every
time.
The no-bomb prompt keeps guard as the default, and the executor target for
guard/hold tracks the lower boss position. This is stable behavior, but it
creates a recurring failure mode: Laya does not proactively request a broad
lateral escape before a dense pattern closes.

The trace also reports `bomb_now` probabilities above the normal threshold at
some lethal frames. Those requests are intentionally ignored because the
binding goal forbids all bomb input. This is not hidden bomb use or a harness
failure; it is the expected consequence of the zero-bomb constraint.

### Hard comparison

Source: `logs/campaign-hard-gl33-no-bomb-1.log` and
`simdata/laya-m3cam-0926-080606.jsonl`.

- Hard Stage 1: WON, frame `14444`, 2 deaths, 0 bombs.
- Hard Stage 2: LOST, frame `1869`, 1 death, 0 bombs.

Both difficulties fail at Stage 2 with the default no-bomb policy. Hard is
more severe and fails almost immediately; Medium lasts much longer but still
eventually spends its three available lives in Stage 2. Lower difficulty
reduces bullet density/timing pressure; it does not remove the policy's
dependence on bombs for patterns where the local reflex layer cannot recover.

## Diagnosis

## What `guard` means

`guard` is a tactical macro, not a command to stop moving and not a replacement
for the executor. In `harness/macros.py`, `guard` resolves to a target below the
boss, normally in the lower playfield. In `harness/executor.py`, the reflex
layer still evaluates the nine movement headings every frame and emits the
lowest-scoring safe movement together with Marisa A's shot.

The control hierarchy is therefore:

1. Laya chooses a coarse macro such as `guard`, `item_sweep`, or
   `sidestep_left`.
2. The executor converts that macro into a target bias.
3. Every frame, the executor scores hazards, lasers, walls, and movement
   candidates, then emits the actual directional input.

Laya does receive danger, nearby-hazard, boss, focus, and bomb-decision
questions. It can recognize danger; the traces also show high `bomb_now`
probabilities at some lethal moments. However, its move answer is a compact
classification choice, not a continuous dodge trajectory. In the Medium Stage
2 trace it selected `guard` on 534 decisions, so it did not proactively request
a broad lateral setup before the local executor candidates became unsafe.

Thus the accurate conclusion is: **Laya understands some danger signals, but
it does not currently produce a reliable proactive dodge plan.** The executor
does reactive frame-level dodging, but it cannot always recover a player who is
already trapped or facing a dense pattern. The no-bomb rule makes that weakness
fatal because bombs cannot convert those moments into survivable hits.

The dominant cause is the interaction of four constraints:

1. **No bombs are permitted.** Bomb requests and death-bomb opportunities are
   correctly suppressed, removing the game's intended emergency recovery.
2. **Laya is mostly selecting guard.** Guard is a valid DPS default in open
   space, but it is too passive when a pattern requires early lateral setup.
3. **The executor is reactive and local.** It chooses among nine one-frame
   headings and selects the safest available candidate; it does not invent a
   new macro-level escape route when all local candidates are already bad.
4. **Stage carry preserves the finite life budget.** Medium Stage 1 ends with
   two reserve lives and zero bombs. Stage 2 consumes all three lives because
   no bomb can convert lethal hits into survivable damage.

 Therefore, “Medium” is not equivalent to “safe without bombs.” It only makes
 the same failure mode less immediate.

## What this does not indicate

- It does not indicate Laya transport failure: coverage is 100% and protocol
  failures are zero in Stage 2.
- It does not indicate a difficulty-parser bug: checkpoints report
  `difficulty: normal`, and the state compiler maps difficulty 2 to Normal.
- It does not indicate hidden bomb use: every checkpoint reports
  `allow_bombs: false` and `bombs_used: 0`.
- It does not justify claiming campaign completion: both Hard and Medium stop
  at Stage 2.

## Consequence for next work

The next useful experiment should target early macro-level lateral setup while
retaining the no-bomb constraint, not simply lower difficulty again or widen
the local hazard scan. It must be separately planned, tested, and committed;
no rejected diagnostic should be enabled by default.
