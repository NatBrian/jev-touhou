# Research: Jev AI (TypeSafe AI) and the "Jev pattern"

Date: 2026-09-24 · Researched via web (TypeSafe docs, systemonemodels.org, press, community repos)
Purpose: define the decision-engine pattern our harness implements locally with Laya.

## 1. What Jev is

- **Jev** is the first **"System One" model**, shipped **15 Sep 2026** by **TypeSafe AI** (a startup by a
  ChatGPT inventor; $40M funding, TechCrunch 18 Sep 2026).
- It is **not an LLM**: it reads a text *state* you supply and answers **typed questions** about it with
  **calibrated probabilities**. It never generates text — there is no output to parse and nothing to hallucinate.
- Trained (per the vendor, and the only public statement) **exclusively on synthetic data** with
  **"reinforcement learning for calibrated decisions" (RLCD)** so that reported probabilities match real outcome rates.
- Closed managed API. Current version **jev-1.13.0** (aliases `jev-latest`, `jev-preview`). No weights, no changelog,
  no paper published. Weights not released → no self-hosted Jev (that gap is what Laya fills, §research-laya).

Sources:
- https://systemonemodels.org/models/jev/ (independent hub page, updated 24 Sep 2026; primary aggregation source)
- https://docs.typesafe.ai (official docs: /primitives/choice, /primitives/score, /primitives/noul, /api, /models)
- https://techcrunch.com/2026-09-18/a-new-kind-of-ai-model-from-a-chatgpt-inventor-is-thrilling-developers/
- https://www.hpcwire.com/aiwire/2026-09-16/typesafe-ai-emerges-from-stealth-with-40m-in-funding-with-new-model-for-composable-ai/
- https://typesafe.ai/blog/introducing-system-one-models-and-jev (launch post)
- https://www.theregister.com/ai-and-ml/2026-09-16/typesafe-ai-debuts-model-for-machines-that-plays-doom/5296711

## 2. The API contract (Jev pattern)

One `POST https://api.typesafe.ai/v1/systemone` with `Authorization: Bearer $TYPESAFE_API_KEY`:

```json
{
  "state": "…text, or a JSON object/array of text…",
  "model": "jev-latest",
  "questions": {
    "question_id": { "type": "choice|score|noul", "instructions": "…", "criteria": … }
  }
}
```

Response: `{"model": …, "answers": {<id>: <typed answer>}, "usage": {"input_tokens": N, "output_tokens": 0}}`.
All questions in one request are evaluated **in parallel against the same state**; adding questions barely
changes latency. Question ids are for the caller; the model never sees them.

### The three question types ("the same three shapes Jev uses" — Laya's docs)

| Type | `criteria` | Answer | Use |
|---|---|---|---|
| **choice** | map `label → description-or-null` (≤ **255** options) | `choice` (top label), `probabilities` (sums to 1), `confidence` (0–1, from probability spread) | pick one of a fixed set |
| **score** | **ordered array** of 2–10 level descriptions | `score` = Σ level·P(level) (float, may fall between levels), `legend` (level→description), `probabilities`, `confidence` | position on an ordinal spectrum |
| **noul** | optional `{true: …, false: …}` | `noul` = P(yes) ∈ [0,1]; **no separate confidence field** (the probability IS the confidence) | yes/no with calibrated probability |

Details that matter for building with it (from official docs, fetched 2026-09-24):
- `instructions` and `criteria` values can be strings, objects, or arrays; start with strings, use structured
  objects with `what`/`not_for`/`examples` when options get confused.
- **Score**: describe *situations, not degrees* ("Moderately severe" is useless; the model can't see level numbers
  or neighbours). Split multi-dimension judgments into one Score per dimension, normalize by top level, combine in code.
- **Noul**: phrase so a high value = yes (never invert); one proposition per noul (two conditions → two nouls);
  threshold in your code (e.g. YES>0.8, NO<0.2, middle → fallback).
- **Confidence**: computed from how probability is spread; a flat shape = low confidence. Use it as a separate
  decision axis (act automatically when high, escalate when low).
- Specs: 64k total context, **32k state budget**, rate limits 250k tok/s & 1,200 req/min (dynamic),
  $0.042/M input tokens, output free, vendor-claimed latency 70–500 ms; third-party p50 236–276 ms
  (AbdelStark/jev-benchmarks, nibzard/decision-model-benchmark via Laya's BENCHMARKS.md).
- SDKs: `typesafe-sdk` (PyPI, Python ≥3.10), `@typesafe-ai/sdk` (npm, Node ≥20). Error codes 401/422/429/529.

## 3. Known weaknesses (TypeSafe's own "jaggedness" page for jev-1.13.0)

1. **Literal reading** — answers the question you wrote, not the one you meant.
2. **Math/numbers** — counting, numeric representations, arithmetic through a Score are weak. (Workaround: ask one noul per item.)
3. **Date/time comparison** — dates are read as text, not ordered quantities.
4. **Indirection** — double negatives / complex indirection degrade answers.
5. **Context rot** — accuracy falls as state grows with irrelevant detail.
6. **Adversarial content** — state is data; Jev doesn't treat it as hostile by default.
7. **Contradictory instructions & criteria** — answers degrade when they pull apart.
8. **Structural invariants don't hold** — e.g. an idea scored 0.22 as a noul but 0.99 as a choice; P(noul)+P(¬noul) can sum to 1.19. Code must enforce identities.
9. **No generation** — it cannot write values out for you.

Design rule from TypeSafe: **avoid System Two tasks** (multi-step indirection, planning, chaining facts).

## 4. The "Jev game demo" pattern (how people make Jev play games)

Source: https://systemonemodels.org/guides/jev-game-demos/ (updated 24 Sep 2026; ~40 demos catalogued)
plus referenced repos: `lukaske/jev-doom-agent`, `fhshaik/typesafe-mario`, `RomanSlack/jev-drone`,
`rmalde/minecraft-agent`, `vinnylarouge/jevlike`, `browser-use/jev-ultrafast`.

**The loop every demo shares:**
1. Code reads the game's **memory / entity list** (or runs CV first) and writes a **compact text state**:
   positions, health, what's ahead, which moves are legal.
2. Jev answers a **choice over a small move list**, often plus a **noul** ("should I stop?") and/or **score**
   ("danger level") — all in **one request**.
3. Code carries out the answer by pressing buttons.

**Key engineering findings from the demos (directly applicable to us):**
- **No demo calls the model every frame.** A 60 fps game has 16 ms/frame; Jev needs 70–500 ms. Demos call per
  junction / per obstacle / per turn / every few frames. Measured cloud cadence ≈ **3.2 decisions/sec**.
- **Code owns the rules, physics and button presses; the model only judges what the situation means.**
  Precompute anything measurable (distances, legal moves) before the call.
- **Reflex layer underneath:** `jev-drone` keeps a 50 Hz reflex layer that can **veto** the model and skips calls
  when nothing changed (~2.5 Hz decisions, 65-s flight ≈ 110 calls).
- **`typesafe-mario`:** emulator RAM → compact JSON (no screenshots); per request: 7-action choice + noul
  (jump start/hold) + score (danger); **emulator advances several frames between calls**.
- **`jev-doom-agent`:** structured state (health, armor, ammo, position, kills, visible monsters, pickups);
  Jev picks a **tactical macro**; a local motor controller converts it to movement/turning/fire/weapon inputs;
  low-confidence or failed calls show a scripted fallback.
- **No lookahead/memory:** "Jev sees one state and returns one answer. It doesn't search ahead or remember the
  last turn unless your code puts that in the state." (Snake demos trap themselves; Kyrandia agent loops;
  Minecraft completion needed GPT-6 Astra for planning + Jev for moves: 131 decisions + 35 plan calls.)
- **Extra questions are cheap** (one request, parallel evaluation, free output) → ask the move AND the safety
  checks together.
- **Jev vs Laya in games:** local Laya decides far faster (86.5 vs 3.2 dec/s over cloud in one Snake run;
  P50 9.2 ms vs 308.7 ms with wifi off), but Jev usually makes the *better* call (Tetris, Doom, arena survival);
  one Doom deathmatch went to Laya 5–1 purely by deciding twice as often. A 24-hour RL fine-tune of Laya on Doom
  still fell short of zero-shot Jev.

## 5. Implications for this project

- Our harness is exactly the Jev-game-demo pattern, with **Laya replacing the cloud API** (see research-laya)
  and **taisei-sim replacing CV/emulator RAM** (full ground-truth state; see research-taisei-sim).
- Budget: **~3–5 Laya decisions/sec** through the SSH tunnel → strategist cadence; **60 Hz execution in code**.
- State text must be short (context rot) and **pre-digested** (code does all arithmetic/comparison).
- Ask several questions per call (macro + bomb + focus + danger) in one forward pass.
- Keep a **scripted fallback** for low-confidence / slow / failed calls (confidence-gated actions).
- Because Laya/Jev have no memory, **carry recent history in the state** (last macro, deaths, spell progress)
  if it matters.
