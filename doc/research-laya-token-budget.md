# Research: Laya token budget and state truncation (2026-09-26)

Found during G2.8 (`m3cam-0926-150704`) forensics: `usage.input_tokens` hits a
hard **2048** cap at p50 in every no-bomb campaign since G1.5. The model has
been making roughly half of all decisions from a truncated state.

## Method

`tools/probe_token_budget.py` sends controlled states to `POST /predict`
with the no-bomb 4-question schema (`agent.NO_BOMB_QUESTIONS`) and reads
`usage.input_tokens` back:

1. baseline (trivial state) — cost of system prompt + question schema;
2. scaling (padded states of known length) — chars->tokens ratio;
3. marker test (head/mid/tail markers in an over-long state + a choice
   question asking which markers are visible) — what the cap truncates;
4. re-send of REAL campaign death states from the trace
   (`hit_state_text` in the `death_hit` records) — exact measurement.

## Findings

| Item | Measured |
|---|---|
| Baseline (system + no-bomb 4-question schema) | **550 tokens** |
| Server input cap | **2048 tokens** |
| State token budget to stay under the cap | ~1498 tokens |
| Campaign content efficiency | **~1.0 token/char** (digits/parens-heavy) |
| Simple-text efficiency (probe padding) | ~0.67 token/char |
| Max state length under cap (campaign content) | **~1350 chars** (1350 -> 2008; 1436 -> 2048; 1567 -> 2048) |
| Campaign state size (G2.8) | p50 1468, max 1575 chars -> **at cap at p50** |

At-cap ok-calls per run: G1.5 462/661 · G2 301/445 · G2.5 224/369 ·
G2.75 312/459 · G2.8 169/276.

### What gets truncated

The server truncates the **state tail**; the questions survive (the marker
probe: the model answers the marker question coherently on the truncated
state; the tail marker is reported invisible). State section order
(`state_compiler.compile_state`):

scene -> macro context -> boss -> 10-bullet list (~800 chars) -> gap hint ->
**dodge line** (~170 chars, ends ~char 1300) -> lasers -> items -> player.

So the lost tail at the cap = **lasers + items** (+ part of the player line);
the dodge line (position / time-to-hit / pressure / edges) survives.

### Impact assessment

- Dense states (long bullet lists) are exactly the states that truncate —
  the states where laser proximity matters most (a laser sweep is an instant
  kill). The model answers with missing laser awareness on ~half of calls.
- Does NOT explain the G2.5/G2.75/G2.8 band deaths: the dodge line is intact,
  so the compressed evade answers in dense states (0.25-0.45) are genuine
  model compression, not truncation (consistent with
  `doc/research-laya-calibration-probe.md`).
- Wall time is dominated by tunnel transport (G2.8: wall_ms p50 945 vs
  server_ms p50 48), so shrinking the state does not shorten the decision
  interval; it only prevents truncation.

## Fix plan (R4.6, isolated run G2.95)

Get the state under the cap so no call truncates:

- `NEAREST_BULLETS` 10 -> 6 (~260 chars saved in dense states; each bullet
  desc is ~65 chars: "bullet closing in on you at 123px away (SE, radius 4,
  speed 2.9)"). Dense states were 1468-1575 chars -> ~1210-1315.
- Fix `_trim`'s hard budget 1600 -> 1280 chars (see verification below for
  why 1280, not 1340): the old value assumed ~4 chars/token; campaign
  content is ~1.0 token/char, so even a fully trimmed 1600-char state
  (1600 + 550 baseline = 2150) still exceeds the 2048 cap. In G2.8 the
  trim never fired (max state 1575 < 1600).
- Verify with the probe: worst-case dense state reports input_tokens < 2048;
  then re-run the campaign and confirm at-cap calls drop to 0.
- (Optional, only if still over) move the dodge line BEFORE the bullet list,
  so any residual truncation hits the bullet list (detail) before the
  laser/item sections.

## R4.6 verification (2026-09-26, `tools/check_state_tokens.py`)

New tool: replays a recorded stage (recorded macros, VA4 executor), compiles
the NEW state on selected frames, and measures `usage.input_tokens` live on
the Laya server (no-bomb 4-question schema).

Measured fixed overhead (system + questions, state-independent): **700-733
tokens** (median ~722) — larger than the 550 "baseline" row above (that
probe's question set differed); state content ~1.0 token/char. Densest frame
found (S3 f9750, 383 hazards + active spellcard + 21 beams + 3 items):
**1315 chars -> 2033 tokens** (15 below the cap — the reason the trim budget
is 1280, not 1340: 1340 chars would measure ~2060).

| Frame (stage) | hazards | new state chars | input_tokens |
|---|---|---|---|
| 163143 S2 f7000 | 9 | 1093 | 1822 |
| 163143 S2 f7150 (swarm) | 389 | 1211 | 1939 |
| 113108 S3 f1920 (559-bullet swarm) | 12 | 1186 | 1885 |
| 113108 S3 f4400 | 408 | 1197 | 1930 |
| 113108 S3 f9750 (worst case) | 383 | 1315 | 2033 |

With `_trim` budget 1280 the worst-case output is ~2000 tokens (margin
~50). G2.95 gate: campaign `input_tokens` max < 2048 (at-cap calls -> 0).

Sources: `tools/probe_token_budget.py` output (2026-09-26, L20X,
checkpoints typed-decisions/multilingual/english); G2.8 trace
`simdata/laya-m3cam-0926-150704.jsonl` (`input_tokens`, `state_chars`,
`wall_ms`, `server_ms` fields); state composition from
`harness/state_compiler.py`.
