# Requirements & Decisions (user Q&A, 2026-09-24/25)

Every requirement below is a direct answer from the user (2026-09-24 question session), or a resolution I
made on the user's instruction. This file is the binding spec; if the plan or a milestone conflicts with it,
this file wins.

## 1. Completion definition (user: "Taisei Lunatic clear")
- **Target: clear all 6 stages of Taisei on Lunatic difficulty (difficulty=4)** with default initial
  resources (3 lives, 3 bombs), **no continues, no resource inflation, no sim cheats** ("clean run").
- Taisei (via taisei-sim) **is** the target game. Official PC-98 Touhou is out of scope for now.
- A "full game" = **6 chained stage episodes** (same character/difficulty; harness carries score/lives/bombs/
  power/power-item state between episodes), because taisei-sim episodes are per-stage (user accepted).

## 2. Human-likeness bar (user: "Minimal")
- The play just must **not look obviously scripted**. No requirement to pass an informed Touhou player,
  no requirement to die occasionally.
- Consequence: M4's "human-likeness pass" is a **sanity check** (replay playback: natural pace, sane bomb
  usage, no wall-skim spam), not a tuning objective.

## 3. Character & shot mode (user: "Pick one the most balanced character")
- **Decision: Marisa, shot mode A.** Rationale from Taisei source (`src/plrmodes/*`, master, fetched
  2026-09-24):
  - Speed (px/frame, normal / focus): **Marisa 6.25 / 2.75** > Youmu 6.0 / 2.125 > Reimu 5.625 / 2.5.
    Focus speed is the dodging tool in danmaku — Marisa is best in both modes.
  - A-mode damage: Marisa A main shot **60**/6f + Master Spark laser 13 (continuous, forgiving coverage) vs
    Reimu A 50/3f + homing slaves (aim forgiveness we don't need — the agent aims exactly) vs Youmu A
    60/6f + Myon sidekick 25/3f.
  - Shared across all: bomb 300f, collect radius 30/60 (focus), POC H/3.5, deathbomb window 12f.
  - Marisa A = best mobility + strong direct DPS + passive laser coverage → most balanced for a code-aimed
    agent on Lunatic. Runner-up: Reimu A. Revisit only if M2 data contradicts (cheap to switch; character
    is one field in the episode config).

## 4. Difficulty ladder (user: recommended option)
- **Easy → Normal → Hard → Lunatic**, incremental milestones with run data at each level.

## 5. Game speed (user: "does not matter as long laya can play")
- No 1× real-time requirement. Laya's decision cadence is expressed in **game time** (1 call per
  `DECIDE_EVERY` sim frames, default 12–60 = 0.2–1 s of game).
- **Synchronous harness (design finalized 2026-09-25):** the main loop steps the sim itself; while a Laya
  call is in flight the sim is **frozen**, so a response always applies to the exact snapshot frame it was
  computed from (staleness ≈ 0). Laya's wall latency affects only wall-clock throughput, never correctness.
  - **Worst case (user Q, 2026-09-25: "what if Laya slows to 5 s?"):** a 5 s call makes the game run at
    ~1/10× real time (fine — replays play back at 1×). The decision cycle adapts
    (`DECIDE_EVERY = max(min_frames, latency_in_frames)` → longer macro, fewer calls); frame-exact dodging
    is always the in-process 60 Hz executor's job (0 ms network). The design degrades to "slower + coarser
    macro", never to "wrong input". The staleness-stamp/discard of §10 remains as an async safety net.
- Replays always play back at 1×, so videos look natural regardless.

## 6. Viewing / deliverables (user: "Headless + replay video")
- Runs are **headless** (taisei-sim as designed). Final deliverable video = play the saved replay back
  and screen-record the game screen.
- **RELAXED (user decision, 2026-09-25: "if we replay not in stock 1.4.6 can? as long as I have the game
  screen to see. i do not want to overcomplicate it"):** the video does **NOT** need to run in the stock
  exe, and the sim no longer needs to be **bit-identical** to stock. The video is rendered by the
  **fork's own OpenGL 3.3 renderer** (`taisei.exe --renderer gl33 --replay <final.trsr>`), which shows the
  authentic Taisei **v1.4.6 game screen** (the game source is taisei v1.4.6 + this repo's sim-layer patch
   `third_party/simlayer-onto-v146.patch`, so content + gl33
  rendering match v1.4.6). Because the *same* engine that produced the replay renders it, there is **no
  desync**. This **removes** the "stock `--verify-replay` exit 0" M4 precondition and the **clang/LLVM
  MinGW rebuild** that existed solely to achieve bit-exactness. Only the window title/version string
  differs from stock (not a concern per the user).
  - The fork already builds both targets from one `libtaisei` core: `libtaisei_sim.dll` (headless sim C
    API; renderer hardcoded to `null`) for the campaign, and `taisei.exe` (renderers + replay) for the
    video. `gl33` needs only ~15 C files + the vendored `glad` loader (no shader-transpiler C++).
  - **REFINEMENT (decision, 2026-09-25 — does NOT supersede the relaxation above):** "no
    bit-exactness" means no *stock-toolchain* bit-exactness. The accuracy standard ("the video
    must be accurate on what Laya is actually playing") is kept and made machine-verifiable:
    the final campaign runs on the **same build** as the video renderer (`build-gl33`), and the
    acceptance proof is the fork exe's own desync check at freq=1 —
    `--renderer null --verify-replay final.trsr` with
    `TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY=1` → exit 0, **and** the gl33 recording itself runs
    with that env var (zero desync lines in the exe log). Provenance + full analysis:
    `doc/research-video-fidelity-source-of-truth.md` §10–12.
- ~~Stock Taisei version: v1.4.6 (user-specified 2026-09-25, release link) as the replay-playback host~~
  → superseded by the relaxation above. v1.4.6 remains the **content baseline** only (fork base). The
  stock asset `Taisei-1.4.6-windows-x86_64.zip` (213 MB) stays in the project as a reference / optional
  fallback but is **not** required for the video.

## 7. Control authority (user: "Laya is final")
- **The reflex layer never vetoes or overrides a Laya decision.** It is an *executor*: it converts Laya's
  macro (movement macro + bomb/focus flags) into 60 Hz button presses, and may choose the lowest-risk
  execution *within* the macro's intent (e.g. "retreat down" → retreat while dodging).
- If Laya picks a fatal macro, the player dies. No auto death-bomb, no auto dodge outside the macro's intent.
- Exception (harness-level, not a Laya override): when Laya is **unreachable** (tunnel down), the harness
  runs a degraded fallback policy (hold last macro + reflex dodging + shoot + conserve bombs) — see §10.

## 8. Laya deployment (user: "check if my PC is compatible, then tell me how fast" → measured)
- **Measured 2026-09-25** (`logs/run-2026-09-25-laya-cpu-bench.md`): local CPU **is compatible** but slow:
  **5.0 s per 3-question batch (0.20 decision cycles/s)** at 8 threads (best), 2.2 s single question.
  The remote GPU host = 3–5 cycles/s wall → local is ~10–25× slower. Physics-limited (421M fp32, 445 tokens ≈ 375 GFLOP on a
  4-core CPU).
- **Decision (user-confirmed 2026-09-25, paraphrased: "if laya on cpu is very slow then we must use the remote GPU host always"): the remote
  GPU server is the *only* runtime Laya backend.** The local venv + checkpoint (1.72 GB, `venv/` +
  `cache/hf/`) is an **offline dev sandbox only** (state/question design without tunnel risk or remote-host load) —
  it is *not* a runtime failover.
- Runtime client: single backend (remote-host HTTP `/predict`) + degraded fallback policy (see §10). The SDK shape
  difference (local 0.3.20 takes choice options under `criteria`, the remote host accepted `options`) only concerns the
  sandbox tooling.

## 9. Build & environment (user: recommended options)
- **Native Windows build first** (meson + MSVC or in-folder llvm-mingw). **WSL2 is pre-approved as
  fallback** (installing the WSL2 Windows feature needs user permission → granted "if needed").
- **Disk budget: ≤ 4 GB temporary, prune after** (C: had 8.7 GB free at Q&A; 5.7 GB free after the
  1.72 GB Laya sandbox landed).
- PowerShell 5.1, Windows 11 amd64 (per AGENTS.md §3).

## 10. Laya host outage behavior (user: "Explain the difference between reflex-only then resume vs pause and wait")
Explained in the 2026-09-25 reply; the key mechanics:
- The sim is **step-based** — the game only advances when the harness calls `step()`. There is no real-time
  clock inside the sim, so a pause costs no game time, only wall time.
- **Pause and wait:** on tunnel drop the harness stops stepping; the danmaku freezes mid-pattern. Zero
  gameplay risk (frozen bullets can't kill), but a 2-hour Laya-host outage stalls the run for 2 hours — bad for
  overnight campaigns.
- **Reflex-only, then resume:** the harness keeps stepping at normal cadence; Laya's strategist slot is
  filled by the deterministic fallback policy (§7 exception). The stage keeps progressing under real
  consequences — a weak phase in a dangerous moment can kill the run. Wall time is never wasted.
- **Staleness validation (answers "won't slow-tunnel inputs be dismissed or wrongly executed?"):** the sim is
  **frame-numbered**; every Laya request is stamped with the sim frame of its state snapshot. When a
  response arrives, if the game has advanced beyond the **stale limit** (default 30 frames = 0.5 s game
  time) since the snapshot, the response is **discarded** (logged) and the last Laya macro is held. A slow
  tunnel therefore produces *late* answers that get discarded — never *wrong* answers; nothing is ever
  applied to a state it was not computed from. Slow → down is one continuum in the same code path:
  longer macro holds, then the fallback policy.
- **Why split-second safety doesn't depend on the tunnel:** Laya's answers are *macros* (0.2–1 s intents:
  movement macro, bomb/focus flags). Split-second precision is the 60 Hz **in-process executor's** job —
  0 ms network latency, always reacting to the *current* frame. Even a 0.5-s-old macro is executed fresh,
  frame by frame.
- **Two run modes (final decision, 2026-09-25):**
  - *Exploration runs* (bulk of overnight time): **always continue** on tunnel drop (reflex-only degraded
    mode). Every frame logs Laya coverage; a run is **tainted** (excluded from final-clear eligibility) if
    Laya coverage < 99% of frames or any death occurs during an uncovered frame.
  - *Final-clear attempts*: **pause and wait** on tunnel drop (purity over wall time; the attempt can be
    rerun from the same seed — determinism makes reruns cheap).
- Both modes honor §7 ("Laya is final"): the fallback only acts when Laya is *absent*, never against its
  decisions.

## 11. Laya fine-tuning (user: "Not now")
- **Zero-shot + state/question design only** for now. Revisit fine-tuning only if decision quality becomes
  the bottleneck (would need remote-host changes or a local GPU path).

## 12. Runs & reporting (user: "Overnight" / "Per milestone")
- **Overnight unattended runs are OK**; the harness checkpoints per episode (seed, carried state, replay,
  per-frame Laya availability, decision log) so nothing is lost on crash.
- **Reporting: PLAN.md updated continuously + a short summary to the user after each milestone.**

## Open (2026-09-25 status)
1. ~~§8 remote-primary/local-failover~~ → **RESOLVED (user, 2026-09-25): the remote GPU host always at
   runtime; local Laya = offline dev sandbox only** (see §8).
2. ~~§10 drop behavior~~ → **DESIGN FINALIZED (2026-09-25)** after user's "will slow-tunnel inputs be
   dismissed or wrongly executed?" question: staleness-stamped requests + stale-discard + macro-hold means
   slow tunnels degrade gracefully (no wrong inputs); exploration runs = continue + taint, final-clear
   attempts = pause and wait (see §10). Awaiting user's final nod; this is the working default.
3. ~~§6 v1.4.6 pin for replay playback~~ → **RESOLVED / RELAXED (user, 2026-09-25):** the video is
   rendered by the fork's own gl33 renderer, not the stock exe; no bit-exactness / `--verify-replay`
   required. v1.4.6 is kept only as the content baseline (see §6). The clang/LLVM toolchain rebuild is
   superseded (no longer needed).
