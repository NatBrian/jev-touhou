# Research: Laya (open-source Jev-pattern decision engine)

Date: 2026-09-24 · Sources: Hugging Face model card, GitHub README (fetched today), PyPI, systemonemodels.org,
plus **live measurements against our Laya server** (see `logs/run-2026-09-24-laya-smoke.md`).

Laya is the open-weight, self-hosted implementation of the **Jev pattern** (choice / score / noul typed questions
over a text state). It is our decision engine: local, no API key, no rate limits, no cloud dependency.

## 1. What Laya is

- **Laya** = open-source, **non-autoregressive System 1 decision model family** by **Convai Innovations**.
  Give it a state (text, email, ticket, or JSON document) and typed questions; it returns typed answers with
  **mathematically calibrated probabilities** in a **single forward pass (~33 ms)**. It never generates text.
- Trained with **RLCD** (Reinforcement Learning for Calibrated Decisions): the policy reports a distribution,
  exploration adds zero-mean Gaussian noise to logits, reward is a **strictly proper scoring rule**
  (log + spherical, plus ranked probability score for ordinal questions) → expected reward is maximized **only by
  honest probabilities**. Updates: REINFORCE with group-mean baseline + soft cross-entropy against teacher
  distributions.
- **Apache 2.0**, open weights + code.
- Links:
  - HF hub repo: https://huggingface.co/convaiinnovations/laya (all 3 checkpoints)
  - GitHub: https://github.com/NandhaKishorM/laya (code, router, benchmark harnesses)
  - PyPI: https://pypi.org/project/laya/ (`pip install laya`; extras: `[serve]`, `[mcp]`, `[langchain]`, `[onnx]`, `[fast]`)
  - Docs: https://nandhakishorm.github.io/laya/
  - Demo Space: https://huggingface.co/spaces/convaiinnovations/laya-demo
  - systemonemodels.org profile: https://systemonemodels.org/models/laya/
  - Dev.to write-up by the author (Nandakishor M)

### Architecture (per model card)
- **Backbone**: ModernBERT-large (395M, bidirectional, fully fine-tuned) + **decision head trained from scratch**
  (2 transformer layers, an option-marker scorer, and an act/escalate head) → **421M total** (English checkpoint).
  Option markers: every option is scored at its own `[MASK]` token, softmaxed over that question's options.
  The answer space is defined **at request time** — new schemas need no retraining.
- **Multilingual checkpoint**: mmBERT-base (22 layers, 256k vocab), 322M total.

### The three checkpoints (one repo, `subfolder` select; only requested weights download)

| Checkpoint | Encoder | Params | Context | Best at |
|---|---|---|---|---|
| `convaiinnovations/laya` | ModernBERT-large | 421M | 512 (head_max_len 192 → **~320 tokens state**) | English text, guardrails, email triage |
| `convaiinnovations/laya-multilingual` | mmBERT-base | 322M | 1024 (up to 8192 with `max_len`) (head 256 → ~768 state) | 100+ languages, ~2.2× faster |
| `convaiinnovations/laya-typed-decisions` | ModernBERT-large | 421M | 1024 | the four typed-decisions workflows (0.766 acc) |

### Router
- `Router()` detects script/language in <0.5 ms (pure Python) and routes: Latin+English → english checkpoint,
  non-English → multilingual. `model=` forces a checkpoint (`english` / `multilingual` / `typed-decisions`).
- English checkpoint **collapses on non-Latin scripts** (Khmer: 0.000 accuracy at 0.952 confidence — confident while
  wrong), which is why routing happens before the forward pass. Our state is English → routes to `english`.
- `Router(preload=True)` keeps checkpoints resident (no reload churn). `predict_batch` groups requests by
  checkpoint+schema to share forward passes.

## 2. Our local deployment (Laya server, per AGENTS.md §2 + live test 2026-09-24)

- Served over an SSH tunnel: local `127.0.0.1:8002` → the Laya host's `127.0.0.1:8002` (any host
  serving the same contract works; `LayaClient(base_url=...)` is configurable).
- **Health (measured 2026-09-24):**
  `GET /health` → `{"status":"ok","device":"cuda","loaded":["multilingual","typed-decisions","english"],"startup_secs":23.9,"gpu":"NVIDIA L20X","cuda_visible":"5"}`
- Endpoints (measured contract, AGENTS.md §2):
  - `POST /predict` with `{"state": {…}, "questions": {name: {type, instructions, criteria}}}`; optional
    `"model"` and `"lang"` to force routing.
  - `GET /presets/{preset}` / `POST /predict/{preset}` — presets: `router`, `guard`, `moderation`, `triage`
    (mirrors `laya.router_questions()` / `guard_questions()` / `moderation_questions()` / `triage_questions()`).
  - `POST /v1/systemone` also exists in the stock `laya.serve` package (Jev-compatible wire protocol) — our
    the Laya server additionally exposes `/predict` + `/presets/*` (matches `examples/server.py` in the laya repo).
- Every response carries `routing` (which checkpoint served + why), `usage` (input tokens), `_server_ms` — **we log all of them**.
- **The model is `convaiinnovations/laya` ("laya-rl-agent")** — the HF repo ships `rl_agent_api.py` whose docstring
  is literally: *"Jev-compatible inference for a saved RL Agent model: system_one(state, questions) -> typed
  answers."* Response model id is `laya-rl-agent`.

### Measured latency (Laya server, L20X)
| Workload | Server-side | Wall through SSH tunnel |
|---|---|---|
| Single question | ~18 ms | ~220–300 ms (2026-09-23) |
| 3-question batch (1 forward pass) | ~41 ms (AGENTS.md) / **38.7 ms (2026-09-24 test)** | **574.8 ms (2026-09-24 test — variance exists)** |

Budget: **~3–5 decisions/sec wall**. A full Laya run of one Touhou stage (≈ 6 stages × ~2–4 min = ~20 min game
time) at 1× speed with 1 decision per 0.5 s ≈ 2,400 Laya calls.

### Measured 3-question danmaku test (2026-09-24, recorded in logs/run-2026-09-24-laya-smoke.md)
State: 4-field JSON (~60 tokens: scene, player, nearest bullets, boss) + 3 questions (4-option choice, 3-level
score, 1 noul) → `usage.input_tokens = 390`, wall 574.8 ms. Answers were **semantically coherent** with the state:
choice `drift_upleft` (p=0.53) matching the described gap, score 1.46/2 (leaning "severe"), noul bomb_now 0.951.
**Token math:** 390 tokens for a small state + 3 questions → with the 512-token English budget, keep state+options
per question well under ~450 tokens; prefer the `multilingual`/`typed-decisions` checkpoints (1024 ctx) if states grow.

## 3. SDK / HTTP shapes (identical to Jev's)

Python SDK:
```python
from laya import Router
router = Router(preload=True)
result = router.predict(state, questions)
result["answers"]["department"]["choice"]      # choice
result["answers"]["churn_risk"]["noul"]        # P(true)
result["routing"]["model"]                     # english | multilingual | typed-decisions
```
- `noul` scores two semantic slots `[false, true]` and **returns P(true)** (rl_agent_api.py: `p[1]`).
- `score` returns `score` = Σ i·p_i as a float + `legend` (index→label) + `probabilities` — **no label in the
  response; map float → label via legend in code** (AGENTS.md §2, confirmed in rl_agent_api.py).
- `choice` → `{"choice", "probabilities", "confidence", "action.act_probability"}`.
- `laya.serve` = FastAPI server, `POST /v1/systemone` wire-identical to TypeSafe Jev (an existing Jev client can
  just repoint `baseUrl`). Env: `LAYA_HOST/PORT/DEVICE/PRELOAD/MODELS/THREADS/AUTO_TASK/API_KEY`.
- Extras: `decide(state, schema=…)` (JSON-schema/pydantic → typed values), prediction hooks, MCP server,
  LangChain/LangGraph integrations, ONNX runtime, TileLang GPU fast path.

## 4. Benchmarks & honest limits (from Laya's BENCHMARKS.md / README; read 2026-09-24)

Speed (Tesla T4): 1 question 39.5 ms (english) / 32.8 ms (multilingual); 10 questions batched 158.6 / 72.3 ms
(**7.2 ms/question**); throughput 103–332 questions/sec. Jev p50 independently measured 236–276 ms → Laya is
**6–8× faster per question**.

Accuracy vs Jev 1.13.0 (published numbers):
| Benchmark | Jev | Laya (routed) |
|---|---|---|
| typed-decisions (2,000 decisions) | 0.727 | **0.766** (fine-tuned checkpoint) |
| AG News (4 labels) | 0.910 | **0.950** |
| DAIR Emotion (6 labels) | 0.480 | **0.595** |
| Banking77 (72–77 labels) | **0.870** | 0.425 (token-budget constraint) |
| ECE (post-temperature) | 0.246 | **0.081** |

**Pitfalls we must design around:**
1. **Base checkpoints are near chance on typed-decisions zero-shot** (0.362/0.352 vs 0.461 majority-class).
   The 0.766 number comes from the fine-tuned checkpoint. For a novel domain (game tactics) expect base-model
   quality — mitigate with **well-described options** and **state digests**, or fine-tune later (Kaggle 2×T4, ~4 h).
2. **Option token budget**: options share `head_max_len` (192 English / 256 other). 77 options → ~3–4 tokens/label
   → accuracy collapses. **Keep choice options ≤ ~20** (AGENTS.md), short labels + one-line descriptions.
   (Raise `head_max_len` at runtime if we run our own server; or `predict_shortlist`.)
3. **Avoid boolean-word labels in choice** (`true/false/yes/no`) — checkpoints can follow the label instead of the
   descriptions. Use semantic or opaque labels (A/B) and validate.
4. **Noul label bias (#156)**: on the English checkpoint, noul can answer the *label pair* instead of the state
   (confident "no" on clearly positive input). Mitigations: `labels` override (`{"true":"A","false":"B"}`),
   explicit `criteria` text, or use a **2-option choice with neutral keys**. Validate on our data.
5. **Score is the weakest primitive** (SST-5 0.372); `laya-multilingual` has a **position bias** on score
   (#131, rarely picks the first level). Route English score questions to `model="english"`.
6. **`action.act_probability` has no usable signal** (#185; AUROC 0.30 vs correctness) — **gate on `confidence`**
   (AUROC 0.77).
7. **Calibration**: overconfident as shipped; ECE 0.466 → 0.081 after temperature fitting (english). Don't treat
   raw probabilities as calibrated truth without our own validation.
8. **Context rot & indirection** apply (same RLCD/jaggedness family as Jev): keep states short, questions literal.

## 5. Community signal: Laya in games

From https://systemonemodels.org/guides/jev-game-demos/ ("Jev against Laya" section):
- Local Laya vs cloud Jev on Snake: **46 vs 1** (86.5 vs 3.2 dec/s — network round trip decides); with wifi off,
  Laya P50 9.2 ms vs Jev 308.7 ms.
- But in Tetris Bench and a Doom deathmatch, **Jev's calls were sharper**; in one arena survival test Jev was
  "more accurate out of the box" while Laya ran ~21 ms/decision on a laptop.
- "24 hours of RL training Laya on Doom" → still well short of zero-shot Jev.
- Practical read for us: **Laya's decision rate (3–5/s here) is enough for a 3 Hz strategist layer**, and its
  semantic quality on well-posed tactical questions is adequate (validated by our danmaku smoke test). Where it
  will lose to a human is *lookahead* — which we supply with the code reflex layer (PLAN.md §1).
