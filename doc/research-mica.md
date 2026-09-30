# Research: Mica v0.1 4B as the decision engine (2026-09-27)

Why: user direction (2026-09-27) — swap the decision engine from Laya
(`127.0.0.1:8002`) to **Mica** (`127.0.0.1:8010`, same SSH host) and test
whether Mica plays Medium/Hard/Lunatic no-bomb better than Laya, using the
finished harness + promoted executor fixes (VA4 gap-horizon + R5.1 blind +
R5.2 ring iter 5).

## 1. What Mica is

**Mica v0.1 4B** (`sky7350/Mica-v0.1-4B`, Apache-2.0) — a small Jev-pattern
decision model: "You give it a state, a question and the allowed answers, and
it returns a probability for each answer: yes/no, a choice among 2-255
options, or a score with 2-10 levels. It reads the input once and generates
no text, so a decision costs one prefill."

- Base: `Qwen/Qwen3.5-4B` (rev `851bf6e`) + merged rank-16 LoRA (32 layers,
  Gated DeltaNet + full attention). Trained on English + Korean.
- Serves the **TypeSafe `/v1/systemone`** format: "clients written for Jev
  work unchanged."
- Inputs > **8,192 tokens** are rejected with HTTP 400 (not truncated).
- JevBench public (RTX 3090, BF16): easy **100.0**, original **100.0**,
  hard **69.5** (64.9 via server) vs **Laya: 97.9 / 65.0 / 10.5**; ECE 5.4%.
- Latency (RTX 3090): p50 **54 ms** BF16 / 47 ms Q4_K_M vs Laya ~30 ms.
- Tetris demo (same seed/pieces/options): Mica 223 lines vs Kev 55 vs **Laya
  17**.
- Known limits: knowledge-heavy sets (MMLU-Pro 53.0 vs JEV 82.3); long
  English policy documents (hard tier) weakest; planted instructions in the
  state still move answers (a note pointing at the right option lifts it to
  88.7%).

Sources:
- HF model card: https://huggingface.co/sky7350/Mica-v0.1-4B
- Code/Docker/scripts: https://github.com/akivet/Mica-v0.1-4B
- Reddit (author): "Mica 4B vs Laya on Tetris: same seed, same prompt" —
  https://www.reddit.com/r/LocalLLM/comments/1wpvkf7/

## 2. Measured contract on our server (2026-09-27, via tunnel)

`GET /health` -> `{"status": "ok", "model": "mica-v0.1-4b"}` (same `status`
key as Laya -> `LayaClient.is_available()` works unchanged).

Decision endpoint: **`POST /v1/systemone`** (canonical; `POST /v1/decide` is
an alias — both return identical results). Other routes 404
(`/v1/chat/completions`, `/predict`, `/presets`, ...).

Request: identical shape to Laya:
`{"state": str, "questions": {name: {type, instructions, criteria}}}`
(`choice` criteria = {id: text}, >= 2 options; `score` criteria = [label];
`noul` has no criteria).

Response (measured, 4-question batch, realistic 1280-char state):
```json
{
  "model": "mica-v0.1-4b",
  "answers": {
    "move":     {"type": "choice", "probabilities": {"guard": 0.15, "...": ...},
                 "answer": "retreat", "confidence": 0.41, "choice": "retreat"},
    "focus":    {"type": "noul", "noul": 0.30, "answer": false, "confidence": 0.70},
    "bomb_now": {"type": "noul", "noul": 0.52, "answer": true, "confidence": 0.52},
    "danger":   {"type": "score", "probabilities": {"0": 0.21, "1": 0.35, "2": 0.45},
                 "answer": 2, "confidence": 0.45, "score": 2}
  },
  "usage": {"input_tokens": 1633, "output_tokens": 0},
  "latency_ms": 189.2
}
```

Delta vs Laya contract:
- path `/v1/systemone` (Laya: `/predict`)
- `latency_ms` instead of `_server_ms`; no `routing` (single model)
- `score` may be an **int** (e.g. `2`) — `float()`-compatible
- choice carries BOTH `answer` and `choice` (label) — harness reads
  `a["move"]["choice"]` -> works
- **no `legend`** in score answers — harness never used `legend` (only
  `float(a["danger"]["score"])`, executor.py:1458 danger valve) -> works
- validation in `laya_client._validate_answer` passes all three types
  as-is.

## 3. Measured performance (L20X, via SSH tunnel, 2026-09-27)

- Cold start (first call after idle): one 3-question batch took ~7.0 s
  server-side. Steady state after that: **p50 ~70 ms (3q) / ~190 ms
  (4-question realistic batch)**, wall ~0.6-1.2 s through the tunnel.
  Comparable to Laya (~41 ms server / 220-300 ms wall for 3q).
- Input scaling (4-question batch, bullet-list padding):
  1280 chars = 1633 in_tok, 198 ms; 4000 chars = 3996 in_tok, 407 ms;
  8000 chars = 7444 in_tok, 729 ms (OK); **16000 chars (~14.9k tok) ->
  HTTP 400 `{"error": "Input exceeds max_length; evidence was not
  truncated"}`** (confirms the 8,192-token cap).
- Campaign impact: realistic batch = 1633 in_tok << 8,192 cap -> the R4.6
  compaction (<= 2048 tokens) needs no change. At decide_every=30 (0.5 s
  game time) with ~1 s wall per call, a 6-stage campaign (~100k+ frames)
  takes roughly 40-70 min wall (Laya: 15-20 min).

## 4. A/B design (bounded, opt-in, everything else identical)

- Client: `MicaClient(LayaClient)` — same validation, path
  `/v1/systemone`, base `http://127.0.0.1:8010`, `latency_ms` normalized to
  `_server_ms` for trace logging.
- Runner: `tools/test_m3_campaign.py --engine {laya,mica}` (default `laya`;
  Laya stays the default engine per project constraints).
- Executor for BOTH engines: the promoted combo —
  `--no-bomb --gap-horizon --laser-blind-fix --laser-ring`, `--build-dir
  build-gl33`, Marisa A, seed 12345+stage.
- Thresholds (EVADE_NOUL_THRESHOLD 0.55, FOCUS_NOUL_THRESHOLD 0.80,
  BOMB_NOUL_THRESHOLD 0.80) are Laya-calibrated; kept IDENTICAL for the
  first A/B pass (one variable at a time). Re-calibrate only if Mica proves
  promising.
- Ladder: (1) Mica Medium S1 smoke -> (2) Mica Medium full chain ->
  (3) Laya Medium full chain with the SAME current executor (control,
  G2.93 predates the blind/ring fixes) -> (4) head-to-head; if Mica >= Laya,
  repeat on Hard (Laya baseline: S1 WON 2 / S2 LOST 1) then Lunatic
  (binding goal).
- Provenance: `engine` + model recorded in every checkpoint; traces
  (`laya-<tag>.jsonl`) already log `model`, `input_tokens`, `server_ms`.

## 5. A/B results (2026-09-27, full ladder) — see `logs/run-2026-09-27-mica-ab.md`

All runs: no-bomb, promoted combo (gap-horizon + blind + ring), build-gl33,
Marisa A, seed 12345+stage.

| diff | Laya | Mica |
|---|---|---|
| Medium | LOST S3 (4 deaths, 13.58M) | LOST S2 (3, 3.59M) |
| Hard | LOST S2 (3, 6.02M) | LOST S1 (3, 1.01M) |
| Lunatic | LOST S1 (3, f6383, 432K) | LOST S1 (3, f8486, 578K) |

Verdict: Mica does NOT beat Laya with the current harness. Laya is strictly
better on Medium and Hard (dies a full stage later); on Lunatic both die at
S1 with 3 deaths and Mica survives ~2.1k frames longer (its only, marginal
edge). Every death in all six runs is the bottom-edge class (y=544), so the
executor — not the decision engine — is what blocks the Lunatic clear.
Mica's behavior is qualitatively more "human" (guard 36% vs 99%, model
evade 24-28% vs 0.2%, clean bimodal escape noul) but that active movement
feeds the executor's bottom-edge blind spot. Mica stays available as an
opt-in `--engine mica`; Laya remains the default engine.
