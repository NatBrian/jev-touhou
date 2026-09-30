# Research: prompt, harness, and Laya-input audit

Date: 2026-09-26  
Subject: why Laya fails in Medium Stage 2 despite zero transport failures.  
Baseline: `simdata/laya-m3cam-0926-081314.jsonl`,
`logs/campaign-medium-gl33-no-bomb-1.log`, and the default source path in
`harness/agent.py`, `harness/state_compiler.py`, and `harness/macros.py`.

## Executive conclusion

The failure is plausibly distributed across **prompt design, Laya input, and
harness observability/execution**, not caused by one transport problem.

The strongest confirmed issues are:

1. The normal move prompt explicitly tells Laya that dodging/repositioning is
   harmful. The no-bomb prompt reverses this, but still asks for a coarse macro
   while the local executor handles the actual frame-level dodge.
2. The state compiler does not provide candidate-path risk, time-to-collision,
   wall-trap status, or a direct safe-heading recommendation. It reports ten
   nearest bullets and a coarse occupancy hint instead.
3. The harness parses and logs the `danger` answer but does not use it to alter
   the executor's target, focus, or cadence.
4. The trace logs the parsed macro, not the raw Laya move answer. In no-bomb
   mode, `bomb_setup` is remapped to `guard`, so the current trace cannot prove
   that Laya literally chose `guard` on every request.
5. Laya calls are separated by about 49–50 game frames at the Medium Stage 2
   median, while the state compiler describes only a 15-frame projected danger
   window. A macro can remain active for nearly a second of game time while a
   new pattern develops.

These findings explain why lowering difficulty helps Stage 1 but does not make
the policy reliable in Stage 2. They do not yet prove which single change will
clear the campaign; a controlled instrumentation/correction phase is required.

## 1. Prompt audit

### Normal prompt contradicts proactive dodging

`harness/agent.py` `QUESTIONS["move"]` currently says:

> “a fast reflex layer handles ALL bullet dodging for you — you NEVER need to
> move in order to dodge or to 'get safe'; repositioning to escape bullets is
> useless and harmful.”

It then says to hold guard most of the time and deviate only for items or bomb
setup. This is a direct instruction not to request the proactive lateral setup
that the no-bomb diagnosis says is missing.

The no-bomb question variant replaces that text with a hard rule allowing
sidesteps/retreat near danger and edges. However, the Medium run used that
variant and still produced only parsed `guard`/`hold` outputs. The wording may
not be enough to overcome the macro's strong default prior, and the raw choice
is not currently visible in the trace.

### Independent danger question is not coupled to move

Laya answers four questions in one request: move, focus, bomb, and danger.
The danger answer is a score, but the move classifier is not explicitly given a
required mapping such as “if danger is severe, choose a sidestep.” The model can
therefore answer “severe” and “guard” independently. This is visible in the
Medium Stage 2 trace: danger scores were high while the parsed move remained
guard.

### Macro vocabulary is coarse

The available movement choices are `guard`, `hold`, `retreat`,
`sidestep_left`, `sidestep_right`, `item_sweep`, `clear_spell`, and
`bomb_setup`. These describe intent, not a timed route through a gap. That is
consistent with the architecture, but it means Laya must recognize the need
for an early setup before the executor's local candidate set collapses.

## 2. Laya input/state audit

`harness/state_compiler.py` gives Laya:

- current frame, stage, difficulty, lives, bombs, power, score, and deaths;
- boss position/phase/HP/timer;
- up to ten nearest active enemy bullets with distance, direction, radius,
  speed, and a coarse “closing in” label;
- a coarse 3×3 occupancy/gap hint;
- nearby laser descriptions and nearby items.

It does **not** give Laya:

- time-to-collision for each bullet;
- the predicted risk of each of the nine executor headings;
- a wall/edge-trap indicator;
- the safest lateral direction or a stable gap identity;
- a compact projected path through the next macro interval.

The compiler's `THREAT_HORIZON` is 15 frames, while the executor has a separate
36-frame local horizon. This mismatch means Laya receives a shorter predictive
view than the executor, and neither view is presented as a concrete action
recommendation to the move classifier.

The state is trimmed to 1600 characters. Medium Stage 2 logs show
`input_tokens` roughly 736–1991 (mean about 1739 for successful calls). This
does not prove server truncation, but it does show that the full state plus four
verbose question schemas is a substantial classifier input. A shorter,
action-oriented schema should be measured rather than assumed to be equivalent.

## 3. Harness/parser audit

### Raw move choice is not preserved in the trace

`Agent._ask_laya` stores the raw answers in `Macro.raw`, but `_log_call` writes
only `macro.macro_id`. In no-bomb mode, `bomb_setup` is converted to `guard`
after parsing. Therefore a trace count of 534 parsed `guard` choices cannot
distinguish literal guard answers from remapped bomb-setup answers.

This is an observability defect. Before changing prompts, the harness should
log at least `raw_move_choice`, `parsed_macro`, raw probabilities, and whether
the parser remapped the choice.

### Danger score is dead data for execution

`m.danger_score = float(a["danger"]["score"])` is assigned and logged, but the
executor never receives it. The executor uses its own cost field and the global
`DANGER_INTENT_FACTOR`; it does not use Laya's danger classification to force a
macro change, attenuate guard intent, or increase decision frequency.

This preserves the “Laya is high-level decision-maker” boundary, but it also
means one of the four Laya outputs has no effect beyond telemetry.

### Guard target is strong and persistent

`guard` and `hold` resolve to the same `below_boss` target. The target tracks the
boss x-position and uses `GUARD_Y=470`. The executor reevaluates movement every
frame, but a guard macro can remain active across many Laya calls and keeps
pulling toward this target unless local risk is sufficient to overcome intent.

At the Medium Stage 2 lethal records, the executor selected the lowest-cost or
tied-lowest candidate, so this is not proof of a parser error. It is evidence
that the target bias and local reactive policy are insufficient once the player
is already at a boundary or inside a dense pattern.

## 4. Cadence and trace audit

From `simdata/laya-m3cam-0926-081314.jsonl`, split at the Stage 1→2 frame
reset:

| Stage | Successful calls | Parsed moves | Focus ≥0.80 | Median call interval |
|---:|---:|---|---:|---:|
| 1 | 234 | 233 guard, 1 hold | 38 | 54 frames |
| 2 | 295 | 295 guard | 32 | 49 frames |

Stage 2 had zero Laya failures. Stage 1 had one unavailable call, but final
mode waited and still recorded 100% coverage; this is not the Stage 2 cause.

The effective focus count in Stage 2 is **32/295**, not 530. The trace's
`focus` field is the raw probability, not the emitted button. The earlier
documentation that described focus as active on nearly every decision was
incorrect and is corrected by this audit.

The three Medium Stage 2 death-hit frames were 7052, 14524, and 14765. The
executor selected move indices 5, 0, and 7 respectively; each was the minimum
or tied minimum raw candidate cost. The third hit had focus enabled, but the
first two did not, so focus is a possible contributor at the third hit but not
the dominant explanation for the stage failure.

## 5. Ranked root-cause hypotheses

1. **Prompt contradiction / weak macro instruction** — high confidence. The
   normal prompt explicitly suppresses proactive dodging; the no-bomb wording
   is newer but has not been validated at the raw-choice level.
2. **Insufficient Laya input representation** — high confidence. Laya does not
   see candidate risk, time-to-collision, wall traps, or a macro-interval path.
3. **Unused danger answer** — high confidence as a harness design gap. The
   output is collected but cannot influence behavior.
4. **Macro cadence/staleness** — medium confidence. Median 49–50 frame gaps are
   long for proactive setup, although the executor remains frame-exact.
5. **Focus threshold** — low-to-medium confidence for Medium Stage 2. Only 32
   decisions crossed the threshold; focus contributed to the third lethal event
   but not the first two.
6. **Transport/parser corruption** — low confidence. Protocol failures were
   zero in Stage 2, coverage was 100%, and the parser validates answer shapes.
   Raw-choice logging is still needed to rule out semantic remapping fully.

## Recommended next investigation

Before a gameplay correction, add audit-only telemetry for raw move choice,
parsed choice, raw probabilities, compiled state length/text hash, effective
focus, danger score, decision interval, and macro target kind. Then run one
short Medium Stage 2 comparison with no policy change. Only after that should
one prompt/input/harness correction be tested in isolation.
