# Jev plays Touhou

A **local Jev-pattern decision engine** (a non-autoregressive classifier that answers probability questions: no text generation, no API keys, no cloud) plays **Touhou** like a human player. The game is [Taisei](https://taisei-project.org), the open-source Touhou engine and fan game, driven through a headless simulation layer we patched into it. The showcase videos below are **real gameplay**: Taisei's own OpenGL 3.3 renderer playing back a bit-exact replay of the run, window-captured live, composited side by side with the engine's decision dashboard.

## Showcase

Left panel: the actual game window, recorded with ffmpeg while the game plays the replay. Right panel: the decision dashboard, rendering the sim state and every question the engine was asked, with its answer and probabilities.

**Laya, Hard, stage 1** (WON: 2 deaths, score 2,924,004)



https://github.com/user-attachments/assets/3daebe75-b2d9-43f4-b09a-3bb58afaaab3



**Laya, Normal, stage 1**



https://github.com/user-attachments/assets/de58b3ef-cc85-44b3-ac5c-3b49884f43bd



**Mica, Normal, stage 1**



https://github.com/user-attachments/assets/6607328c-7a70-42a7-be4c-aeabfcb3ef4a



**Mica, Normal, stage 2** (WON: 2 deaths, score 3,099,334)



https://github.com/user-attachments/assets/85a4b37d-8531-44fe-9d5b-2e317b2ff0dc



All showcase runs: fresh 3 lives, no bombs, Marisa (shot mode A), fixed seed `12345+stage`, and the VA4 reflex executor (`--gap-horizon --laser-blind-fix --laser-ring`).

## Results

Best combos each engine could still **win** as a direct single-stage run, plus how dense the bullet field got (enemy bullets on screen, measured from the sim):

| Engine | Run | Result | Enemy bullets on screen |
|---|---|---|---|
| **Laya** | Hard, stage 1 | WON (2 deaths, score 2,924,004) | mean 113.4, p50 78, **peak 880** |
| **Mica** | Normal, stage 2 | WON (2 deaths, score 3,099,334) | **mean 148.3**, p50 155, peak 478 |

Laya hits higher instantaneous peaks; Mica sustains a denser average field. Both engines lose on everything harder (Hard stage 2+ and Normal stage 3+ are lost runs). That boundary is where the current ceiling sits.

## High-level architecture

Three pieces:

1. **Decision engine (remote, on your GPU)**: a Jev-pattern typed-decision model, either **Laya** (primary) or **Mica** (A/B), served over plain HTTP by you (see [Decision engines: host it yourself](#decision-engines-host-it-yourself)). It answers `choice`, `score`, and boolean `noul` questions with probabilities. It never generates text.
2. **Harness (Python, in this repo)**: freezes the sim each cycle, compiles the game state into a compact text snapshot, asks the engine a batch of questions in one POST, validates the answer against the frame it was asked on, and hands the result to the reflex layer. This is the **strategist**, running at about 3 Hz.
3. **Game backend (C, in this repo)**: Taisei v1.4.6 plus the sim layer in [`third_party/simlayer-onto-v146.patch`](third_party/simlayer-onto-v146.patch). A frame-exact, seeded 480x560 playfield exposed through a C API (`taisei_sim_*`), consumed from Python via ctypes (`harness/taisei_sim.py`). The same build also produces `taisei.exe` with the real gl33 renderer, used by the video pipeline.

Control is two-layer. The model answers at ~3 Hz and emits a 0.2 to 1 second movement **macro** plus bomb/focus flags. A 60 Hz **reflex executor** (pure Python, in-process, zero network latency) converts the macro into per-frame button presses: gap-horizon path planning, laser blind-window handling, converging-ring escape.

```
+------------------+   POST /predict (state text + N questions, one round trip)
| Laya or Mica     |   --> answers: macro + bomb/focus flags + probabilities
| (your GPU box)   |
+--------+---------+
         |
         v  stale-limit validation: a late answer is dropped, never applied
+--------+---------+  to the wrong frame
| harness (Python) |--- state compiler: 480x560 sim snapshot -> ~300 token text
+--------+---------+
         |
         v  ctypes
+--------+---------+
| taisei-sim C DLL |  frame-exact, seeded; also drives the gl33 renderer
+------------------+  for the video pipeline
```

## Harness pipeline (one cycle)

1. **Freeze** the sim at the current frame (fixed 60 fps timeline, fixed seed).
2. **Compile state**: all geometry (distances, relative directions, threat estimates over a 15 frame / 0.25 s window, the 6 nearest enemy bullets, lasers, items, player HP/bombs/lives/score, stage and phase) is computed in code and written as literal, self-contained sentences. The model never does arithmetic. The state budget is ~300 tokens (worst case ~2000, under the server's 2048-token input cap; a 4-question schema baseline costs ~550 tokens).
3. **Ask**: one HTTP POST carries the state plus the batched question set (`choice` for movement, `score` for ordinal rubrics, `noul` for boolean probabilities). Related questions share one forward pass.
4. **Validate**: the answer is stamped against the frame it was asked on. Anything that comes back too late is discarded.
5. **Execute**: the reflex layer converts the winning macro into per-frame inputs until the next cycle.

Measured engine latency on the reference server (NVIDIA L20X): ~18 ms server side per question, ~41 ms for a 3-question batch, ~220 to 300 ms wall time through an SSH tunnel. Budget: ~3 to 5 decisions per second, which is exactly the ~3 Hz strategist rate.

## What we built

- **Sim layer on Taisei v1.4.6**: the patch adds a C API (snapshot, step, input, replay) around the untouched game code, with a 480x560 logical playfield, frame-exact stepping, and fixed seeds. Bit-exactness against stock Taisei (desync checks) and the video source-of-truth proof are in `doc/research-sim-vs-stock-desync.md` and `doc/research-video-fidelity-source-of-truth.md`.
- **Two-layer control**: the strategist/reflex split above, with the executor's gap-horizon planner, laser blind-window fix, and converging-ring escape (`doc/design-m3-reflex-and-macros.md`).
- **State format calibration**: token budget, truncation, and prompt sizing tuned against the live server (`doc/research-laya-token-budget.md`).
- **Video pipeline**: runs are recorded as bit-exact `.trsr` replays; the gl33 `taisei.exe` plays the replay back, ffmpeg `gdigrab` records the real window, HUD-score anchors resample the variable capture pace onto the 60 fps sim timeline, and the dashboard is composited in (all scripts in `tools/`).
- **No in-repo training**: both engines are pretrained open weights. This repo is the prompt, the harness, and the executor around them.

Deeper per-topic research notes (one file per subject, sources cited) live in `doc/`.

## Project structure

```
harness/            the decision loop: state_compiler, agent, executor, macros,
                    laya_client (Laya + Mica HTTP clients), taisei_sim (ctypes)
tools/              build scripts (.bat), fetchers (mingw, gettext, wraps),
                    campaign runner, capture + composite pipeline, diagnostics
doc/                research notes (one file per topic, cited), design docs,
                    requirements, screenshots/
third_party/        simlayer-onto-v146.patch (the sim layer, tracked).
                    Everything else is fetched at setup time (gitignored).
simdata/            run data. Only the two sample runs below are tracked.
videos/             the four showcase videos above (tracked).
LICENSE             MIT
requirements.txt    Python deps (the harness itself is stdlib-only)
```

## Decision engines: host it yourself

Both engines are self-hosted open weights. There are no API keys and no cloud; you point `LayaClient(base_url=...)` at whatever host serves the protocol.

### Laya (primary)

- Model (3 checkpoints: `typed-decisions`, `multilingual`, `english`, auto-routed per request): [huggingface.co/convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya)
- Server: [`pip install laya`](https://pypi.org/project/laya/) (extras: `[serve]`, `[mcp]`, ...) or the [laya repo](https://github.com/NandhaKishorM/laya) (`examples/server.py`, FastAPI). No GPU handy? Try the [live demo space](https://huggingface.co/spaces/convaiinnovations/laya-demo).
- What the harness calls: `POST http://127.0.0.1:8002/predict` with `{"state": ..., "questions": {...}}`; `GET /health` returns `{"status":"ok","loaded":[...]}`. Every response carries `routing` (which checkpoint served it), `usage` (input tokens), and `_server_ms`; the harness logs all of them.

### Mica (A/B engine)

- Model: [huggingface.co/sky7350/Mica-v0.1-4B](https://huggingface.co/sky7350/Mica-v0.1-4B)
- Code/Docker scripts: [github.com/akivet/Mica-v0.1-4B](https://github.com/akivet/Mica-v0.1-4B). Serves the TypeSafe `/v1/systemone` wire protocol.
- What the harness calls: `POST http://127.0.0.1:8010/v1/systemone`.

Serve either engine on any GPU machine and reach it via an SSH tunnel or a direct URL. Laya's server is a superset: `/v1/systemone` also works on the stock `laya.serve` package, so one host can serve both engines.

## Requirements

- **Windows 10/11 x64, native** (no WSL, no system installs). Built and verified on Windows 11 Pro, i7-10610U, Intel UHD 620, 16 GB RAM; the game runs at 1280x720, medium/low. The build needs MinGW-w64, not MSVC, because Taisei's C uses GCC idioms (VLAs).
- **Python 3.11** (in-repo `venv/`); deps in [`requirements.txt`](requirements.txt).
- **ffmpeg** on `PATH` (screen capture + video compositing).
- A **Laya server** at `127.0.0.1:8002` (see above), optionally Mica at `:8010`.
- Disk: ~5 to 6 GB for toolchain + game source + builds (all in-repo, see `.gitignore`); the repo itself is ~85 MB (four videos + five screenshots).
- Time: ~15 to 30 minutes to build. A showcase-length stage takes a few minutes of wall time (the headless sim runs faster than realtime; engine round trips dominate).

## Setup (native Windows)

```bat
git clone https://github.com/NatBrian/jev-touhou
cd jev-touhou
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

1. **Game source + sim layer** (Taisei v1.4.6 + patch):

   ```bat
   git clone --depth 1 --branch v1.4.6 https://github.com/taisei-project/taisei third_party\taisei-sim
   git -C third_party\taisei-sim submodule update --init --recursive
   git -C third_party\taisei-sim apply ..\simlayer-onto-v146.patch
   ```

   > **Windows symlink note:** with `core.symlinks=false` (the default without Developer Mode), `subprojects\basis_universal` and `subprojects\koishi` check out as text files. Delete them and make NTFS junctions to the submodule dirs (no privilege needed):
   >
   > ```bat
   > del third_party\taisei-sim\subprojects\basis_universal
   > mklink /J third_party\taisei-sim\subprojects\basis_universal third_party\taisei-sim\external\basis_universal
   > del third_party\taisei-sim\subprojects\koishi
   > mklink /J third_party\taisei-sim\subprojects\koishi third_party\taisei-sim\external\koishi
   > ```
   >
   > (`tools\check_symlinks.py` verifies the state.)

2. **Toolchain** (in-folder MSYS2 MinGW-w64 GCC + gettext; no system installs):

   ```bat
   venv\Scripts\python tools\fetch_mingw.py
   venv\Scripts\python tools\fetch_gettext.py
   ```

3. **Subprojects** (the 17 meson wraps: SDL3, freetype, webp, and friends; the tarball fetcher resumes flaky downloads):

   ```bat
   venv\Scripts\python tools\fetch_wraps_tarball.py
   ```

4. **Build** (~15 to 30 minutes):

   ```bat
   tools\build_taisei.bat        rem headless sim -> third_party\taisei-sim\build\src\sim\libtaisei_sim.dll
   tools\build_taisei_gl33.bat   rem + taisei.exe with the gl33 renderer -> ...\build-gl33\src\taisei.exe
   ```

   The gl33 build's `libtaisei_sim.dll` is used for runs **and** video, so the sim that plays is the exact sim the renderer draws (bit-exact, seeded).

5. **Decision engine**: serve Laya on your GPU box and tunnel `127.0.0.1:8002` (`GET /health` returns `{"status":"ok",...}`). Optional: Mica at `127.0.0.1:8010`.

6. **Play** (the showcase config: Laya Hard stage 1):

   ```bat
   venv\Scripts\python tools\test_m3_campaign.py --engine laya --diff hard --no-bomb ^
       --start-stage 1 --end-stage 1 --build-dir build-gl33 ^
       --gap-horizon --laser-blind-fix --laser-ring
   ```

   (Mica Normal stage 2: `--engine mica --diff normal --start-stage 2 --end-stage 2`.)
   A run writes the decision trace (`simdata\laya-<tag>.jsonl`), per-stage checkpoints (`simdata\checkpoints\`), and a replay (`simdata\replays\<tag>-stage<N>-<diff>.trsr`).

7. **Showcase video (optional, real art + dashboard, 2560x720@60)**:

   ```bat
   venv\Scripts\python tools\render_jev_showcase.py <tag> <stage> laya hard
   venv\Scripts\python tools\record_perf_trsr.py <tag> <stage> simdata\replays\perf-<tag>-s<stage>.trsr
   powershell -NoProfile -File tools\capture_game_replay.ps1 -Replay simdata\replays\<tag>-stage1-hard.trsr -Out simdata\cache\game-capture.mp4 -Seconds 280
   venv\Scripts\python tools\resample_game_panel_v2.py simdata\cache\game-capture.mp4 --anchors <anchors.txt> --out simdata\cache\panel.mp4 --frames <N>
   venv\Scripts\python tools\composite_real_showcase.py simdata\cache\panel.mp4 <dashboard.mp4> --start 0 --frames <N> --out videos\final.mp4
   ```

   The capture launches the gl33 `taisei.exe` on the replay and records the real window with ffmpeg `gdigrab` (auto-detects the window title). The anchors file (`<time_s> <sim_frame>` per line) maps the variable real-time capture pace onto the 60 fps sim timeline; extract HUD-score timestamps from the capture (`tools\score_to_frame.py`, `tools\extract_hud_anchors.py`).

## Sample data

Two showcase runs are tracked so the pipeline works out of the box (with a built sim DLL; no live engine needed):

- `simdata/laya-m3cam-0927-162641.jsonl` + `checkpoints/m3cam-0927-162641-stage{1,2}.json` + `replays/m3cam-0927-162641-stage{1,2}-hard.trsr` + `replays/perf-m3cam-0927-162641-s1-hard.trsr` (Laya Hard S1, WON)
- `simdata/laya-micacam-0930-012401.jsonl` + `checkpoints/micacam-0930-012401-stage2.json` + `replays/micacam-0930-012401-stage2-normal.trsr` + `replays/perf-micacam-0930-012401-s2-normal.trsr` (Mica Normal S2, WON)

```bat
venv\Scripts\python tools\dump_replay_scores.py m3cam-0927-162641 1 500
venv\Scripts\python tools\measure_bullet_density.py m3cam-0927-162641 1
venv\Scripts\python tools\render_jev_showcase.py m3cam-0927-162641 1 laya hard
```

## Limitations

- **You must self-host an engine.** A live campaign needs a GPU box running Laya (or Mica) reachable at the endpoint. Without one you can still build the game, replay the sample runs, and render dashboard videos.
- **~3 to 5 decisions per second.** The model answers in real time only up to that rate (~220 to 300 ms per round trip through a tunnel). The strategist runs at ~3 Hz; going faster needs a lower-latency deployment.
- **The ceiling is documented.** Both engines win on specific stage/difficulty combos and lose on everything harder (Hard stage 2+, Normal stage 3+, and long multi-stage campaigns on a 3-life budget).
- **Human-like, not optimal.** No in-repo training: decisions come from pretrained weights plus a hand-built reflex layer. Showcase runs are no-bomb, 3 lives, Marisa A, fixed seed.
- **Windows-only setup path.** The documented build is native Windows (MinGW-w64). Linux/WSL is unverified (the sim builds as a shared library, and its static deps need `-fPIC` there).
- **Videos are replay-based.** The left panel is Taisei's real renderer playing a bit-exact replay of the recorded run (window-captured), not a capture of the live session. The sim state is provably identical (fixed seed + desync checks vs stock).

## Troubleshooting

- **`subprojects\basis_universal` is a text file**: `core.symlinks=false` on Windows. Enable Developer Mode, or delete + `mklink /J` (Setup step 1). `tools\check_symlinks.py` verifies the state.
- **MSVC build fails**: expected. Taisei uses GCC idioms; use the in-folder MinGW (Setup step 2).
- **Connection refused on `:8002`**: the tunnel is down or Laya is not up. Re-open the tunnel, then check `GET /health`.
- **Wraps fetch stalls**: re-run `tools\fetch_wraps_tarball.py`; it resumes where it left off.
- **Disk space**: keep ~6 GB free (toolchain + builds). `.gitignore` keeps all fetched/built artifacts out of the repo.

## License

MIT, see [LICENSE](LICENSE).
