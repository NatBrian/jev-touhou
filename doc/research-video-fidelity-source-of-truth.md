# Research: Video fidelity — what is the source of truth, and how do we PROVE the video shows what Laya played

Date: 2026-09-25
Context: user concern (M4) — "If we use 2 different games (taisei 1.4.6 stock and
taisei-sim), which is the source of truth where Laya is playing the Touhou game?
The video renderer must be accurate on what Laya is actually playing. If we are
merging 2 different games just for the sake of the video renderer that is
completely wrong, because game engine, video, Laya playing, all are different."
This doc records the file-level audit done in response, all claims verified
against repo files on 2026-09-25 (not from memory).

## 1. Verdict (TL;DR)

- The user's concern is **correct as a criterion**: the video is only accurate
  if the renderer re-derives the *same* game states the sim produced during the
  Laya run. A renderer built from a different toolchain/tree drifts
  (measured: f7457) and would show a different game.
- The pipeline is **not** "two games merged": there is exactly **one engine**
  (the fork: stock v1.4.6 game code + the touhourl sim layer, one build tree).
  Laya plays the fork via `libtaisei_sim.dll`; the video is rendered by the
  **same build** (`build-gl33` `taisei.exe`) playing the fork's own `.trsr`.
- The stock 1.4.6 exe is **disqualified as the video host by measurement**:
  `taisei.exe --verify-replay` on our replays DESYNCs (f5400 pre-rebase;
  exact f7457 post-rebase with per-frame checks passing through f7456).
  It stays in the repo only as reference/A-B baseline.
- Fidelity is **provable, not assumed**: the engine writes
  `EV_CHECK_DESYNC` digests (`(rng_u64() ^ score) & 0xFFFF`) into the replay;
  playback compares them every check and `--verify-replay` exits 1 on mismatch.
  Acceptance test for the final video: play the final `.trsr` in the fork's
  `taisei.exe` with `TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY=1` → exit 0 means
  score+RNG matched on **every frame** of the run the video renders.

## 2. Source-of-truth chain (verified)

1. **The run**: Laya (remote GPU host, 127.0.0.1:8002) → harness `agent.py` (macro every
   `decide_every` frames) → `ReflexExecutor` (60 Hz buttons) → sim step
   (`libtaisei_sim.dll` from a specific build dir). Deterministic: same
   (episode config + seed + per-frame inputs) ⇒ same state every frame.
2. **The record**: per stage the sim writes one `.trsr` (`taisei_sim_save_replay`,
   sim.c:1216; `replay_reset` per episode → one stage per file):
   - stage struct = **full start state**: `replay_stage_new` (replay/stage.c:14-41)
     captures points, total stats, char/shot, pos, lives, life_frags, bombs,
     bomb_frags, power, graze, PIV, inputflags + `rng_seed` + `diff`.
   - events = every input frame (7-byte `ReplayEvent`), plus `EV_CHECK_DESYNC`
     digests every `desync_check_freq` frames (default FPS*5 = 300, stage.c:1326,
     env `TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY`).
   - `tools/merge_replays.py` concatenates the 6 stage files into one 6-stage
     `.trsr` (stage structs copied verbatim → per-stage checksums stay valid;
     layout in `doc/research-trsr-replay-format.md`).
3. **The render**: any taisei build plays the `.trsr`: each stage starts from
   ITS OWN struct values — `replay_stage_sync_player_state` (replay/stage.c:47-62)
   restores score/lives/bombs/power/pos/char/shot; `replay_do_play`
   (replay/play.c:47-90) auto-advances stages. So the carry-over (chained
   stages) is preserved in playback, not lost.

   **⇒ Source of truth = the recorded run (start states + events + seed).**
   Any engine that passes the desync checks is reproducing it exactly.

## 3. Fork structure (git-verified 2026-09-25)

- `git -C third_party/taisei-sim describe` → `v1.4.6-1-gd9b12e75`,
  branch `sim-on-v146`; HEAD `d9b12e75` "sim-layer rebased onto v1.4.6"
  (parent = v1.4.6 release history `5bfc9b84`).
- `d9b12e75` touches, beyond `src/sim/` (new: runtime.c, sim.c, taisei_sim.h):
  `src/boss.c` (38), `src/stage.c` (84), `src/stage.h` (33),
  `src/eventloop/eventloop.{c,h}` (44), `src/global.{c,h}` (5),
  `src/stages/stage6/background_anim.c` (14), dialog files (text removed),
  meson/Makefile/.gitignore.
- **Every engine change is sim-mode gated** (read from the diff):
  - `global.is_simulation` guards: progress/unlock saves (boss.c),
    persistent-data commit (global.c), vfs_sync (eventloop.c), gameover
    spellstage-autorestart menu, fps counter, dynstage reload, hiscore, and
    score-screen auto-finish (stage.c).
  - `global.replay.input.replay == NULL` guards: `start_override` (carry-over
    applied at `stage_start`, stage.c) and the external input hook
    (`process_input`, stage.c:1148-1156 — same slot stock uses for
    `replay_input`; same `player_event` → `player_applymovement` sequence).
  - `global.is_simulation` is assigned in exactly ONE place:
    `src/sim/runtime.c:109` (the DLL runtime). **The exe never sets it** ⇒
    exe replay playback runs with it false ⇒ identical code path to stock.
- Gameplay code (bullet physics, boss attacks, stage content, RNG) = unmodified
  v1.4.6. The carry-over (score-threshold extra lives etc.) is applied via
  `stage_set_start_override` — engine-side, but only in sim mode, never during
  replay playback.
- Correction to an earlier claim: "engine C code is pure stock v1.4.6" is
  imprecise; the accurate statement is the gated-changes list above.

## 4. touhourl/taisei-sim provenance (git-verified)

- `origin` = https://github.com/touhourl/taisei-sim; `upstream` =
  https://github.com/taisei-project/taisei.
- Pre-rebase state preserved on branch `pre-rebase-150dev` (92eafb92);
  `git describe pre-rebase-150dev` → `v1.4-806-g92eafb92`; **v1.4.6 is NOT an
  ancestor** of it (`merge-base --is-ancestor` = false). Their sim work is
  ~12 commits (`ba2de594` "expose api version" … `6e6f8e3e` "stop any dialogs
  from appearing") on top of taisei upstream master **4e21fc39 (1.5.0-dev,
  2026-08-04)**. Tree diff vs v1.4.6 tag: 59 files, +1399/−774 (enemy_classes
  rewrite, laser.c + new `lasers/rules.c`, spells changed in all 6 stages) —
  `doc/research-sim-vs-stock-desync.md`, run log 287-292.
- Correction to an earlier claim: "807 commits ahead of v1.4.6" was a raw
  `git log v1.4.6..pre-rebase` count; the precise statement is above.
- We take from touhourl only the sim layer (`src/sim/` + eventloop hook +
  sim-mode gates); the game comes from stock v1.4.6.

## 5. Why the stock exe is NOT a faithful renderer (measured)

- Pre-rebase: stock `taisei.exe --verify-replay <merged 3-stage .trsr>` →
  DESYNC stage 1 f5400 (`0xf948 != 0xe502`, exit 1) — run log 287-292.
- Post-rebase (v1.4.6 engine, GCC -O0 sim): still DESYNC, **exact frame f7457**
  (`0x7912 != 0x8ce1`); freq=1 recording proves score AND RNG identical
  through f7456; divergence = differing RNG draw / score change at 7457→7458.
  Per-frame sim dump pinned the window (item pickups f7453-7454, flat score
  after; boss intro; input events verified equivalent in source) — run log
  314-332.
- Documented root-cause **candidate** (not 100% proven): official v1.4.6
  Windows exe is built with clang/LLVM MinGW + MSVC ucrt libm
  (`misc/ci/windows-llvm_mingw-x86_64-build-release.ini`), our sim with MSYS2
  GCC 16.2 + mingwex fdlibm → last-ulp sinf/cosf/sqrtf differences accumulate
  until a collision/branch flips. Run log 333-343;
  `doc/research-sim-vs-stock-desync.md`.
- Consequence: a stock-exe video of our replay would diverge from Laya's run
  after ~2 min (f7457 ≈ stage 1) — exactly the "merging two games" failure
  the user warned about. The M4 relaxation (render in the fork) exists to
  avoid this; the stock exe stays as reference/A-B only.

## 6. Fidelity requirements for the final video (binding)

1. **Same build for campaign and render.** The final Lunatic campaign MUST run
   on `--build-dir build-gl33` (the O2 `libtaisei_sim.dll`), because the video
   is rendered by that build's `taisei.exe`. The Easy campaign ran on the
   default `build/` (O0) — fine for tuning, NOT acceptable for the final
   video (inter-build FP drift must not exist anywhere in the chain).
2. **Freq=1 verification as the proof.** After recording the final replays:
   `build-gl33/src/taisei.exe --renderer null --verify-replay final.trsr` with
   `TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY=1` → must exit 0 (no
   "replay desync detected!"). This proves score+RNG equal on every frame
   between the campaign engine and the render exe. (Mechanism:
   `stage_replay_sync` stage.c:970-995; `replay_state_check_desync`
   replay/state.c:36-60; verify mode `exit(1)` at stage.c:982-988.)
3. **Record with the same exe** (`--renderer gl33 --replay final.trsr
   --width 1280 --height 720`, ffmpeg gdigrab, 60 fps). The renderer only
   reads gameplay state (draw), so gl33 playback = null-verify trajectory.
4. The M4 relaxation (user 2026-09-25) dropped the *stock* bit-exactness
   requirement; it did **not** drop the user's accuracy standard. Item 2 above
   is now the acceptance test for "the video shows what Laya actually played".

## 7. Engine ground truth verified for the executor v5 work (same audit)

- **Laser collision** (`src/lasers/laser.c:526-604`): gated by
  `laser_is_active` = `l->collision_active` (106-109); per quantized segment:
  (a) player motion segment intersecting the centerline ⇒ hit ("prevent
  phasing through laser beams", 571-574); (b) capsule
  radius `max(seg_width*0.5 - 4, 2)` at both ends,
  `ucapsule_dist_from_point < 0` ⇒ hit (576-586). The −4 is the player hitbox.
- **Snapshot laser points** sample the SAME quantized collision segments
  (`laser_trace` walks `l->_internal.segments`, laser.c:349+; `collect_laser_point`
  sim.c:331-359; step default 8.0 px, sim.c:965). `LaserPoint.flags` exposed
  to Python (DISCONTINUITY = bit 0, taisei_sim.h:101).
- **`pt.time` = NEGATED laser-time** (laser.c:270 `.time = {-t0, -t}`;
  sim.c:349 interpolation). Drawn beam ⇒ pt.time ≤ 0 (beam base at 0 in the
  growth phase; tip = most negative). The v4 filter `pt.time <= t_max`
  (t_max ≥ 0 for a live beam) therefore includes the entire drawn beam.
  (The v4 docstring's "tip is 0, growth positive" wording is wrong about which
  end is 0; the filter behavior — include whole drawn beam — was correct and
  validated.)
- **Death-bomb** (`src/player.c`, `src/plrmodes/marisa.c`): hit sets
  `deathtime = frames + 12` (player.c:1020; window = 12, marisa.c:45-47);
  hazards cleared each frame of the window (647-649); `frames == deathtime`
  ⇒ `player_realdeath` (645-646); bomb during window ⇒ `deathtime = -1`
  (unkilled) + **extra bomb consumed** (total cost 2 bombs; 685-692);
  BOMB_TIME = 300 frames (marisa.c:32-33); bomb disabled vs ExtraSpell
  (player.c:668-669). The current executor (executor.py:328-337) has NO
  hit-time bomb path — every hit while bombs remain costs a life.

## 8. Build/toolchain state at audit time

- `build/` = -O0 headless (12,970,548 B DLL) — campaign default
  (test_m3_campaign.py:21-27). `build-gl33/` = -O2 gl33+null
  (9,721,617 B DLL + 9,124 KB exe; exe still the pre-libc-allocator mimalloc
  build: 8 `mimalloc` byte hits vs 0 in stock 15,078 KB exe — re-scanned
  2026-09-25).
- Build blocker B — **root cause corrected 2026-09-25** (`tools/test_ar_mods.py`,
  `tools/test_ar_mods2.py`): the earlier "ar cannot parse D/T" theory was
  wrong — `csr`/`csrD`/`csrT`/`csrDT` all work with this ar (GNU binutils
  2.47.20260726; the failing variants `csD`/`csT`/`cDT` simply lacked the `r`
  command). The real failure: a **STALE** `build-gl33/src/libtaisei.a` left
  by an earlier empirical ar test — a thin archive (`!<thin>`; this MSYS2 ar
  stores member paths INSIDE thin archives) whose recorded paths were
  relative to the wrong cwd (`libtaisei.a.p/...` without the `src/` prefix,
  vs the correct `src/libtaisei.a.p/...`) → `ar r` cannot resolve the
  members → `ar: src/libtaisei.a: No such file or directory`; the stale thin
  archive also blocks a plain `csr` re-run ("Cannot convert existing thin
  library"). The successful `build/` used the IDENTICAL `csrDT` + `@rsp`
  (LINK_ARGS in both build.ninja files) → no meson change needed. Fix =
  delete the stale archive (build artifact; ninja regenerates) + re-run the
  build (`logs/build-gl33-4.log`). See also `doc/PLAN.md` M3.

- Build blocker C — **static-link correction in progress 2026-09-25**:
  `logs/build-gl33-4.log` completed, but the first `-Dc_link_args=-static`
  attempt did not affect the final executable because generated `build.ninja`
  uses the `cpp_LINKER` rule for `taisei.exe` (line 4516) and its `LINK_ARGS`
  had no `-static`. `objdump -p` still listed `libgcc_s_seh-1.dll`,
  `libwinpthread-1.dll`, `libstdc++-6.dll`, and `zlib1.dll`; consequently
  `tools/smoke_gl33.py` still returned `0xC0000135` (`STATUS_DLL_NOT_FOUND`).
  The build script now supplies both `c_link_args=-static` and
  `cpp_link_args=-static`; the next rebuild is `logs/build-gl33-6.log`.

- Build blocker C — **resolved 2026-09-25**: the corrected rebuild completed
  with `[build] OK` (`logs/build-gl33-6.log:1197`). The final `taisei.exe`
  is 9,611,708 bytes and `objdump -p` reports no imported DLLs. The updated
  `tools/smoke_gl33.py` functional check passed: the fork executable created
  the v1.4.6 window and remained alive after two seconds. On Windows, Taisei
  holds `simdata/gl33-smoke/log.txt` exclusively while running, so the smoke
  tool defers reading that file until after termination; this is a log-lock
  limitation, not a renderer failure. The fork gl33 host is ready for the
  same-build campaign.

- Same-build Easy campaign 1 result (2026-09-25):
  `logs/campaign-easy-gl33-1.log` reached all six chained stages with ABI/Laya-host
  healthy, 100% coverage, and no taint/Laya failures. Stages 1–5 won; stage 6
  lost after three real deaths. Results were s1 1d/4b, s2 0d/0b, s3 1d/2b,
  s4 1d/3b, s5 3d/5b, s6 3d/5b: 9 deaths, 19 bombs, 103.17M score, 32.5
  minutes wall. The stage replays/checkpoints are retained under
  `m3cam-0925-154734`; pre-hit diagnostics are in
  `simdata/laya-m3cam-0925-154734.jsonl`. This is a gameplay/resource gate
  failure, not a renderer or Laya transport failure; Stage 6 entered with a
  depleted life/bomb reserve and failed during late laser patterns.

- Stage 6 control result (2026-09-25): `tools/diag_guard_stage.py 6 12351
  easy 3 3` on the same `build-gl33` DLL WON at f29202 with 1 real death,
  4 death-bombs, and `bombs_used=4` (`logs/diag-guard-stage6-easy-12351.log`).
  Therefore the campaign loss is not an intrinsic Stage 6 impossibility; it is
  mainly the result of depleted carry-over resources. During the v5 audit,
  `_collect_hazards` was also found to discard a laser point flagged
   `DISCONTINUITY`; the flag marks the first point of a new valid stroke, so
   discarding it can hide beam origins and short segments. The executor now
   retains that point as the new polyline start.

- Post-fix Stage 6 control (2026-09-25): rerunning the deterministic control
  after the discontinuity fix again WON on `build-gl33` at f29885 with 1 real
  death, 4 death-bombs, and `bombs_used=4`
  (`logs/diag-guard-stage6-easy-12351-v6.log`). The laser-origin correction
  did not regress controlled survival.

- Same-build Easy campaign 2 result (2026-09-25): all six stages executed on
  `build-gl33` with 100% coverage and no taint; stages 1–5 WON and stage 6
  LOST. Results were s1 1d/4b, s2 0d/0b, s3 1d/2b, s4 1d/3b, s5 4d/7b,
  s6 3d/5b: 10 deaths, 21 bombs, 101.999M score, 72.4 minutes wall
  (`logs/campaign-easy-gl33-2.log`). The Laya-host interruption is represented by
  two retried calls in final mode, not fallback gameplay; the run remains
  untainted. Stage 6 again entered after Stage 5 with no lives and two bombs,
  so this is a gameplay/resource failure rather than a replay or renderer
  failure. Checkpoints/replays are under `m3cam-0925-164404`.

- Stage 5 horizon sweep (2026-09-25): controlled fresh-resource Stage 5 Easy
  seed 12350 on the same `build-gl33` DLL compared the reflex threat horizon.
  The baseline 24-frame control WON with 2 deaths/4 bombs; 36 frames WON at
  f20262 with **1 death/4 bombs**; 48 frames WON at f18729 with 2 deaths/5
  bombs; and 60 frames regressed to f17998 with 3 deaths/7 bombs. The
  parameter sweep is recorded in `logs/diag-guard-stage5-easy-12350.log` and
  `logs/diag-guard-stage5-h{36,48,60}.log`. The evidence selects 36 frames
  as the next executor default; the longer horizons are rejected as
  over-predictive/less stable.

- Horizon-36 regression controls (2026-09-25): after making 36 frames the
  executor default, fresh-resource Easy Stage 3 seed 12348 WON at f17095 with
  0 real deaths/2 death-bombs, and Stage 6 seed 12351 WON at f29484 with 2
  real deaths/6 death-bombs. Logs: `logs/diag-guard-stage3-h36.log` and
  `logs/diag-guard-stage6-h36.log`. Both controls used the same `build-gl33`
  DLL and passed before the next campaign rerun.

- Same-build Easy campaign 3 result (2026-09-25): using the horizon-36
  executor, stages 1–3 WON and stage 4 LOST: s1 1d/4b, s2 0d/1b, s3 2d/3b,
  s4 2d/3b. Totals were 5 deaths, 11 bombs, 29.471M score, and 16.2 minutes
  wall (`logs/campaign-easy-gl33-3.log`). Coverage was 100% and untainted with
  zero Laya failures on every completed stage. The complete run is retained
  under `m3cam-0925-181832`; this is a gameplay reliability failure before the
  Normal ramp, not a renderer or transport failure.

- Stage 4 isolated control (2026-09-25): Easy seed 12349 with fresh 3-life/
  3-bomb resources on `build-gl33` WON at f16667 with 1 real death and 2
  death-bombs (`logs/diag-guard-stage4-h36-baseline.log`). This separates the
  campaign 3 Stage 4 loss from intrinsic stage impossibility; the next test
  uses the low-resource carry state rather than fresh resources.

- Exact Stage 4 carry control (2026-09-25): reproducing campaign 3's complete
  Stage 3 carry (seed 12349; lives=0, bombs=2, PIV=20664, score=9648064,
  bomb fragments=100, power=600, graze=3255) still WON Stage 4 at f16483 with
  1 real death and 1 death-bomb (`logs/diag-guard-stage4-h36-exactcarry.log`).
  The campaign 3 Stage 4 loss is therefore stochastic, not an unavoidable
  low-resource failure.

- Same-build Easy campaign 4 result (2026-09-25): stages 1–4 WON and stage 5
  LOST at f1930: s1 1d/4b, s2 0d/1b, s3 1d/2b, s4 2d/3b, s5 1d/1b.
  Totals through the failure were 5 deaths, 11 bombs, 50.405M score, and
  17.3 minutes wall (`logs/campaign-easy-gl33-4.log`). Coverage was 100%,
  untainted, and there were no Laya failures. Stage 5 entered with zero lives
  and two bombs; the two recorded hits were f1443 and f1887. Complete
  artifacts are under `m3cam-0925-184446`; this is a stochastic gameplay
  resource failure, not a renderer or transport failure.

- Exact Stage 5 carry control (2026-09-25): reproducing campaign 4's complete
  Stage 4 carry on Stage 5 seed 12350 (lives=0, bombs=2, PIV=26354,
  score=16279993, bomb fragments=0, power=600, graze=4125) failed at f774.
  The player was hit at f313, consumed the available death-bomb reserve, was
  hit again at f732, and recorded 1 real death/1 bomb
  (`logs/diag-guard-stage5-h36-exactcarry.log`). This isolates a deterministic
  low-resource opening-survival gap in the executor.

- Exact Stage 5 carry horizon sweep (2026-09-25): the same carry lost at every
  tested horizon — h24 f1937, h36 f774, h48 f862, h60 f2816. Each run spent
  the two-bomb reserve on its first death-bomb and then lost on the next hit.
  Logs: `logs/diag-guard-stage5-exactcarry-h24.log`, `-h48.log`, and `-h60.log`
  (with h36 recorded separately). This rejects horizon length as a sufficient
  fix; the next diagnostic compares the campaign's focus state and then
  evaluates resource preservation before Stage 5.

- Swept-projectile validation (2026-09-25): adding the one-frame relative
  motion risk used by Taisei's projectile collision moved the exact-carry
  Stage 5 first hit from f313 to f737, but the player was at the right wall
  (`x=464`) and a second hit at f1416 still ended the zero-life run. The
  control remained LOST with 1 real death/1 bomb
  (`logs/diag-guard-stage5-h36-exactcarry-swept.log`). The correction is
  retained for engine fidelity; wall avoidance is the next measured target.

- Wall-penalty sweep (2026-09-25): exact campaign-4 Stage 5 carry remained
  LOST at WALL_K 0.5/f1458, 1.0/f5628, 2.0/f4519, and 4.0/f4532. K=1.0
  delayed the terminal hit most, but every run spent one death-bomb and lost
  on the next hit. Logs: `logs/diag-guard-stage5-wall{05,10,20,40}.log`.
  Wall cost alone is rejected as the fix; the next measured target is the
  150-pixel hazard prefilter versus fast projectiles and the 36-frame horizon.

- Hazard-scan sweep (2026-09-25): exact campaign-4 Stage 5 carry at R_SCAN
  150 LOST f1458, 250 LOST f2818, 400 LOST f7675 (2 deaths/3 bombs), and 600
  LOST f5628. R_SCAN 400 produced the longest progression but no radius
  cleared the zero-life carry, so scan radius alone is not accepted as the
  fix and the default remains unchanged. Logs:
  `logs/diag-guard-stage5-scan{150,250,400,600}.log`.

- Laya bomb-threshold sweep (2026-09-25): final-mode Laya-host tests on the exact
  Stage 5 carry at thresholds 0.60, 0.70, 0.80, and 0.90 all LOST with 100%
  coverage and zero Laya failures: f1821/2 bombs, f2363/1, f2288/1, and
  f2111/1. Summaries are in `logs/diag-laya-stage5-bomb{60,70,80,90}.out`;
  traces are the four `simdata/laya-diag-laya-s5-*` JSONL files. This rejects
  threshold mapping alone as a sufficient fix; the next target is the
  executor's armed-bomb cost gate.

- Focus-policy comparison (2026-09-25): independent final-mode exact-carry
  traces with focus thresholds 0.80, 0.90, and 0.99 all LOST with 100%
  coverage and zero Laya failures. Results were f3842, f4528, and f1458,
  respectively, each 1 real death/1 bomb. The independent traces are
  `simdata/laya-diag-laya-s5-b08-f08-0925192719.jsonl`,
  `...-f09-0925192919.jsonl`, and
  `...-f099-0925193159.jsonl`. Focus threshold is not accepted as the
  sufficient resource-preservation fix; the existing 0.80 default remains.

- Stage 4 resource-preservation scan sweep (2026-09-25): the exact campaign-4
  Stage 3 carry into Stage 4 (seed 12349; entry lives=1, bombs=0, score
  9480378, PIV=19335, bomb fragments=100, power=600, graze=2731) WON at all
  tested scan radii. R_SCAN=150 ended f15860 with 1 real death, 2
  death-bombs, lives=1, bombs=0, and 100 bomb fragments; 250 ended f15560,
  400 f16296, and 600 f16293, each with 1d/2 death-bombs, lives=1, bombs=0,
  and zero bomb fragments. Logs:
  `logs/diag-guard-stage4-carry-scan{150,250,400,600}.log`. Wider hazard
  scans did not improve the Stage 5 reserve, so no executor default changed.
  The diagnostic was extended to report terminal power/PIV/graze before an
  exact Stage 5 carry is reconstructed.

- Rich Stage 4 carry (2026-09-25): rerunning the R_SCAN=150 control with the
  extended terminal summary WON at f15860 with 1 real death and 2
  death-bombs. The exact Stage 5 entry state is lives=1, bombs=0, bomb
  fragments=100, score=16302305, PIV=25974, power=600, and graze=4086
  (`logs/diag-guard-stage4-carry-scan150-rich.log`). This state is used for
  the next exact Stage 5 reproduction.

- Exact Stage 5 rich-carry control (2026-09-25): Stage 5 seed 12350 with the
  complete R_SCAN=150 Stage 4 carry (lives=1, bombs=0, bomb fragments=100,
  score=16302305, PIV=25974, power=600, graze=4086) LOST at f15502 after 3
  real deaths and 4 bombs used (`logs/diag-guard-stage5-richcarry.log`). The
  first life was lost in the opening; fragments supplied bombs after respawn,
  but the stage still exhausted the reserve. Terminal state was lives=-1,
  bombs=3, power=416, PIV=32262, graze=7019. This isolates a Stage 5
  survival/resource bottleneck even after preserving one life into the stage.

- Stage 5 rich-carry scan sweep (2026-09-25): the same exact carry LOST at
  every scan radius: R_SCAN=150 f15502 with 3 deaths/4 bombs, 250 f5932 with
  2d/2b, 400 f6242 with 2d/2b, and 600 f6235 with 2d/2b. All exhausted the
  life reserve. Logs:
  `logs/diag-guard-stage5-richcarry-scan{150,250,400,600}.log`. Wider hazard
  visibility changes timing but does not clear this carry; the next control
  measures the minimum initial-life reserve.

- Stage 5 entry-life sweep (2026-09-25): with the exact rich Stage 4 carry,
  R_SCAN=150, and the same seed, entry lives=1 LOST at f15502 after 3 deaths;
  entry lives=2 WON at f19231 after 3 deaths/4 bombs, ending with lives=1,
  bombs=3, and 100 bomb fragments; entry lives=3 followed the identical
  trajectory and WON at f19231 ending with lives=2, bombs=3, and 100 bomb
  fragments. Logs: `logs/diag-guard-stage5-richcarry-lives2.log` and
  `-lives3.log`. This identifies 2 lives as the minimum deterministic Stage 5
  entry reserve for the current guard; final-mode Laya validation is next.

- Final-mode Laya two-life validation (2026-09-25): the Laya host was healthy and Stage
  5 seed 12350 ran with the exact rich carry plus entry lives=2, bomb threshold
  0.80, and focus threshold 0.80. It LOST at f7589 after 3 real deaths and 4
  bombs, with 100% coverage, `taint=False`, and zero Laya failures. Summary:
  `logs/diag-laya-stage5-rich-lives2-summary.log`; independent trace:
  `simdata/laya-diag-laya-s5-b08-f08-0925200146.jsonl`. This rejects the
  executor-only two-life result as sufficient for final Laya campaign play;
  the Laya trajectory requires a larger reserve or policy improvement.

- Final-mode Laya three-life validation (2026-09-25): the Laya host was healthy and the
  same exact Stage 5 rich carry ran with entry lives=3, bomb threshold 0.80,
  and focus threshold 0.80. It WON at f19180 after 4 real deaths and 8 bombs,
  with 100% coverage, `taint=False`, and zero Laya failures. Summary:
  `logs/diag-laya-stage5-rich-lives3-summary.log`; independent trace:
  `simdata/laya-diag-laya-s5-b08-f08-0925200640.jsonl`. Three entry lives are
  sufficient for this Laya Stage 5 carry; two are insufficient.

- Final-mode Laya Stage 4 carry validation (2026-09-25): the Laya host was healthy and
  the actual campaign-3 Stage 4 entry carry (seed 12349, lives=1, bombs=0,
  score=9480378, PIV=19335, bomb fragments=100, power=600, graze=2731) WON
  at f14693 with 2 deaths and 3 bombs, 100% coverage, `taint=False`, and zero
  Laya failures. Trace: `simdata/laya-diag-laya-s4-b08-f08-0925201422.jsonl`;
  summary: `logs/diag-laya-stage4-campaign3-carry-summary.log`. The trace
  ends with lives=0 and bombs=2, but the diagnostic summary lacked terminal
  PIV/fragments; an enhanced rerun is required before Stage 5 carry testing.

- Rich final-mode Laya Stage 4 carry (2026-09-25): the enhanced rerun WON at
  f14899 with 2 deaths and 3 bombs, 100% coverage, `taint=False`, and zero
  Laya failures. Its exact terminal Stage 5 carry is lives=0, bombs=2,
  bomb fragments=0, power=600, PIV=25954, score=16249387, and graze=4044.
  Summary: `logs/diag-laya-stage4-campaign3-carry-rich-summary.log`; trace:
  `simdata/laya-diag-laya-s4-b08-f08-0925202058.jsonl`. This is the faithful
  Laya-generated carry used by the next Stage 5 reproduction.

- Exact Laya-carry Stage 5 executor control (2026-09-25): with the actual
  Stage 4 Laya carry (lives=0, bombs=2, bomb fragments=0, power=600,
  PIV=25954, score=16249387, graze=4044), Stage 5 seed 12350 LOST at f1458
  after 1 real death and 1 death-bomb. Terminal state was lives=-1, bombs=3,
  power=420, PIV=26459, graze=4423
  (`logs/diag-guard-stage5-laya-carry.log`). The actual Laya handoff is
  therefore insufficient even for the executor-only Stage 5 path.

- Final-mode Laya exact-carry Stage 5 (2026-09-25): using the exact
  Laya-generated Stage 4 carry (lives=0, bombs=2, no bomb fragments,
  PIV=25954, score=16249387, power=600, graze=4044), Stage 5 seed 12350 LOST
  at f1178 after 1 death and 1 bomb. the Laya host was healthy; coverage was 100%,
  `taint=False`, and Laya failures were zero. Terminal state was lives=-1,
  bombs=3, power=420, PIV=26170, score=17297329, graze=4162. Summary:
  `logs/diag-laya-stage5-laya-carry-summary.log`; trace:
  `simdata/laya-diag-laya-s5-b08-f08-0925202754.jsonl`. This confirms the
  actual campaign handoff fails immediately in Stage 5.

- Final-mode Laya Stage 4 entry-life sweep (2026-09-25): entry lives=2 WON at
  f16166 after 2 deaths/3 bombs, ending with lives=1, bombs=2, bomb fragments=0,
  power=600, PIV=26502, score=16373611, graze=4281. Entry lives=3 WON at
  f16092 after 1 death/1 bomb, ending with lives=3, bombs=2, bomb fragments=0,
  power=600, PIV=26173, score=17790586, graze=4199. Both had 100% coverage,
  `taint=False`, and zero Laya failures. Traces:
  `simdata/laya-diag-laya-s4-b08-f08-0925202949.jsonl` and
  `simdata/laya-diag-laya-s4-b08-f08-0925202956.jsonl`; summaries:
  `logs/diag-laya-stage4-entry-lives{2,3}-summary.log`. These exact terminal
  states are the next Stage 5 carry inputs.

- Final-mode Laya Stage 5 from Stage 4 lives=2 carry (2026-09-25): the exact
  Stage 4 terminal carry entered Stage 5 with lives=1, bombs=2, PIV=26502,
  score=16373611, power=600, and graze=4281. Stage 5 seed 12350 LOST at
  f6229 after 2 deaths/4 bombs, with a healthy Laya host, 100% coverage, no taint, and
  zero Laya failures. Trace:
  `simdata/laya-diag-laya-s5-b08-f08-0925203627.jsonl`; summary:
  `logs/diag-laya-stage5-entry-lives2-summary.log`. Terminal state was
  lives=-1, bombs=3, power=399, PIV=29180, score=19377701, graze=5754.
  One life remaining after Stage 4 is insufficient for final Laya Stage 5.

- Final-mode Laya Stage 5 from Stage 4 lives=3 carry (2026-09-25): the exact
  Stage 4 terminal carry entered Stage 5 with lives=3, bombs=2, PIV=26173,
  score=17790586, power=600, and graze=4199. Stage 5 seed 12350 WON at f17896
  after 3 deaths and 7 bombs, ending with lives=1, bombs=0, and 100 bomb
  fragments. the Laya host was healthy; coverage was 100%, `taint=False`, and Laya
  failures were zero. Trace:
  `simdata/laya-diag-laya-s5-b08-f08-0925203635.jsonl`; summary:
  `logs/diag-laya-stage5-entry-lives3-summary.log`. Three lives entering
  Stage 4 are sufficient for this exact Stage 5 Laya handoff.

- Final-mode Laya Stage 3 upstream validation (2026-09-25): campaign 4's
  exact Stage 2 carry is lives=2, bombs=0, bomb fragments=100, score=5200021,
  PIV=13476, power=600, and graze=910. It is being reproduced on Stage 3
  seed 12348 with the current final-mode policy to identify the first upstream
  reserve bottleneck. Descriptor: `simdata/diagnostics/stage3-campaign4-carry.json`;
  terminal output: `logs/diag-laya-stage3-campaign4-carry-summary.log`.

- Final-mode Laya Stage 3 upstream validation result (2026-09-25): the exact
  campaign-4 Stage 2 carry entered Stage 3 with lives=2, bombs=0, bomb
  fragments=100, score=5200021, PIV=13476, power=600, and graze=910. Stage 3
  seed 12348 WON at f16757 after 1 death/2 bombs, ending with lives=1,
  bombs=0, bomb fragments=100, score=9566970, PIV=19825, power=600, and
  graze=2997. the Laya host was healthy; coverage was 100%, untainted, and Laya failures
  were zero. Trace: `simdata/laya-diag-laya-s3-b08-f08-0925205020.jsonl`;
  summary: `logs/diag-laya-stage3-campaign4-carry-summary.log`. This is the
  first measured upstream reserve bottleneck; the next control tests Stage 4
  and its 10M score-life crossing.

- Final-mode Laya Stage 4 from Stage 3 terminal carry (2026-09-25): the exact
  Stage 3 carry (lives=1, bombs=0, bomb fragments=100, score=9566970,
  PIV=19825, power=600, graze=2997) WON Stage 4 seed 12349 at f14685 after
  1 death/2 bombs, ending with lives=1, bombs=0, bomb fragments=0,
  score=16729782, PIV=26264, power=600, graze=4259. the Laya host was healthy; coverage
  was 100%, untainted, and Laya failures were zero. Trace:
  `simdata/laya-diag-laya-s4-b08-f08-0925205701.jsonl`; summary:
  `logs/diag-laya-stage4-laya-stage3-carry-summary.log`. The 10M score-life
  crossing did not yield the required three-life reserve.

- Final-mode Laya Stage 3 entry-life sweep (2026-09-25): with the exact
  campaign-4 Stage 2 carry, entry lives=3 WON at f18836 after 1 death/2 bombs,
  ending with lives=2, bombs=0, bomb fragments=100, score=9719035, PIV=20025,
  power=600, graze=3150. Entry lives=4 WON at f16890 after 1 death/2 bombs,
  ending with lives=3, bombs=0, bomb fragments=100, score=9742274, PIV=19690,
  power=600, graze=2773. Both had 100% coverage, no taint, and zero Laya
  failures. Traces:
  `simdata/laya-diag-laya-s3-b08-f08-0925210349.jsonl` and
  `simdata/laya-diag-laya-s3-b08-f08-0925210330.jsonl`; summaries:
  `logs/diag-laya-stage3-entry-lives{3,4}-summary.log`. Four lives entering
  Stage 3 are required to preserve three into Stage 4 for this trajectory.

- Final-mode Laya Stage 4 from Stage 3 entry-lives=4 carry (2026-09-25): the
  exact Stage 3 terminal carry (lives=3, bombs=0, bomb fragments=100,
  score=9742274, PIV=19690, power=600, graze=2773) WON Stage 4 seed 12349 at
  f15207 after 2 deaths/3 bombs, ending with lives=2, bombs=2, bomb fragments=0,
  score=16821914, PIV=26450, power=555, graze=4068. the Laya host was healthy; coverage
  was 100%, untainted, and Laya failures were zero. Trace:
  `simdata/laya-diag-laya-s4-b08-f08-0925211135.jsonl`; summary:
  `logs/diag-laya-stage4-stage3-lives4-summary.log`. The resulting carry is
  used by the next exact Stage 5 control.

- Final-mode Laya Stage 3 entry-lives=5 (2026-09-25): with the exact campaign-4
  Stage 2 carry, Stage 3 entry lives=5 WON at f16589 after 1 death/2 bombs,
  ending with lives=4, bombs=0, bomb fragments=100, score=9891930, PIV=20015,
  power=600, and graze=2756. the Laya host was healthy; coverage was 100%, untainted,
  and Laya failures were zero. Trace:
  `simdata/laya-diag-laya-s3-b08-f08-0925212118.jsonl`; summary:
  `logs/diag-laya-stage3-entry-lives5-summary.log`. This is the first tested
  upstream reserve that preserves four lives into Stage 4.

- Final-mode Laya Stage 5 from Stage 4 lives=4 carry (2026-09-25): the exact
  Stage 4 terminal carry (lives=2, bombs=2, PIV=26450, score=16821914,
  power=555, graze=4068) entered Stage 5 seed 12350. It WON at f19283 after
  3 deaths/7 bombs, ending with lives=0, bombs=1, and 100 bomb fragments.
  the Laya host was healthy; coverage was 100%, untainted, and Laya failures were zero.
  Trace: `simdata/laya-diag-laya-s5-b08-f08-0925212101.jsonl`; summary:
  `logs/diag-laya-stage5-stage4-lives4-summary.log`. Two lives plus two bombs
  entering Stage 5 are sufficient for this trajectory.

- Final-mode Laya Stage 4 from Stage 3 entry-lives=5 carry (2026-09-25): the
  exact Stage 3 terminal carry (lives=4, bombs=0, bomb fragments=100,
  score=9891930, PIV=20015, power=600, graze=2756) WON Stage 4 seed 12349 at
  f15063 after 3 deaths/5 bombs, ending with lives=3, bombs=2, bomb fragments=0,
  score=17271712, PIV=27370, power=555, graze=3871. the Laya host was healthy; coverage
  was 100%, untainted, and Laya failures were zero. Trace:
  `simdata/laya-diag-laya-s4-b08-f08-0925213027.jsonl`; summary:
  `logs/diag-laya-stage4-stage3-lives5-summary.log`. This is the exact
  three-life Stage 5 reserve path.

- Controlled Stage 3→4→5 Laya reserve chain (2026-09-25): the preserved
  reserve path was validated end-to-end. Stage 3 entry lives=5 ended with 4;
  Stage 4 ended with lives=3 and bombs=2; Stage 5 seed 12350 WON at f17838
  after 3 deaths/8 bombs, ending with lives=2 and bombs=0. the Laya host was healthy;
  Stage 5 had 100% coverage, `taint=False`, and zero Laya failures. Trace:
  `simdata/laya-diag-laya-s5-b08-f08-0925213833.jsonl`; summary:
  `logs/diag-laya-stage5-stage4-lives5-summary.log`. This is an isolated
  reserve-chain validation; the next test is the complete six-stage campaign.

- Easy campaign 5 Stage 6 bottleneck (2026-09-25): the complete campaign on
  `build-gl33`, seed 12345, cleared Stages 1–5 with 100% coverage, no taint,
  and zero Laya failures. Stage 6 entered with lives=2, bombs=2, bomb
  fragments=100, power=600, PIV=34894, score=26633710, and graze=7942, then
  LOST at f27378 after 3 deaths/5 bombs. Totals were 7 deaths/15 bombs.
  Evidence: `logs/campaign-easy-gl33-5.log`, checkpoint
  `simdata/checkpoints/m3cam-0925-214606-stage6.json`, and replay
  `simdata/replays/m3cam-0925-214606-stage6-easy.trsr`. The next control
  reproduces this exact Stage 6 carry before any policy change.

- Final-mode Laya Stage 6 exact campaign-5 carry (2026-09-25): the exact
  Stage 5 carry (lives=2, bombs=2, bomb fragments=100, power=600, PIV=34894,
  score=26633710, graze=7942) was replayed on Stage 6 seed 12351. It LOST at
  f26677 after 4 deaths/7 bombs, ending with lives=-1, bombs=3, power=402,
  PIV=46239, score=32101948, and graze=12907. Coverage was 100%, untainted,
  and Laya failures were zero. Trace:
  `simdata/laya-diag-laya-s6-b08-f08-0925222641.jsonl`; summary:
  `logs/diag-laya-stage6-campaign5-carry-summary.log`. Hits occurred at
  f575, f5923, f7223, f16920, f20437, f21383, f26150, and f26634; the last
  failures were in the survival-spell laser pattern. The next control is an
  entry-life sweep before changing policy.

- Final-mode Laya Stage 6 entry-lives=4 control (2026-09-25): the exact
  campaign-5 Stage 6 carry with entry lives=4, bombs=2, bomb fragments=100,
  power=600, PIV=34894, score=26633710, and graze=7942 WON seed 12351 at
  f27773 after 5 deaths/10 bombs. Terminal state was lives=1, bombs=2,
  power=498, PIV=47361, score=44136318, and graze=13565. Coverage was 100%,
  untainted, and Laya failures were zero. Trace:
  `simdata/laya-diag-laya-s6-b08-f08-0925223901.jsonl`; summary:
  `logs/diag-laya-stage6-carry-lives4-summary.log`. This is reserve-sensitivity
  evidence, not campaign acceptance: the resource cost is too high.

- Final-mode Laya Stage 6 entry-life sweep (2026-09-25): the exact campaign-5
  carry with entry lives=3 LOST at f27751 after 4 deaths/7 bombs, ending with
  lives=-1, bombs=3, power=420, PIV=47885, score=32349230, and graze=14100.
  Entry lives=4 WON at f27773 after 5 deaths/10 bombs, ending with lives=1,
  bombs=2, power=498, PIV=47361, score=44136318, and graze=13565. Both had
  100% coverage, no taint, and zero Laya failures. Traces:
  `simdata/laya-diag-laya-s6-b08-f08-0925223851.jsonl` and
  `simdata/laya-diag-laya-s6-b08-f08-0925223901.jsonl`; summaries:
  `logs/diag-laya-stage6-carry-lives{3,4}-summary.log`. Three lives are
  insufficient; four lives merely absorbs a 5-death/10-bomb cost. The next
  step is a bounded policy comparison, not a reserve increase.

- Stage 6 policy A/B controls deferred (2026-09-25): the planned bomb-0.60
  and focus-0.99 controls were not launched. They are superseded by direct
  Lunatic validation; no Easy Stage 6 policy or executor default changed.

- Direct Lunatic validation plan (2026-09-25): Laya is being tested directly
  on all six Lunatic stages with fresh Stage 1 state, Marisa A, final mode,
  seed 12345, and the same `build-gl33` DLL intended for replay verification
  and video. Runner: `tools/test_m3_campaign.py --build-dir build-gl33
  --seed 12345 --diff lunatic`; output: `logs/campaign-lunatic-gl33-1.log`.

- Direct Lunatic baseline result (2026-09-25): the run used fresh Stage 1
  state, Marisa A, final mode, seed 12345, and `build-gl33`. Stage 1 WON at
  f12443 after 2 deaths/7 bombs, with 100% coverage, no taint, and zero Laya
  failures. Its terminal state recorded lives=0, bombs=0, power=600,
  PIV=15887, score=2944706, and graze=1279. Stage 2 LOST at f3363 after
  1 death/0 bombs, also with 100% coverage, no taint, and zero Laya failures;
  the final lethal hit was at f3320 in a dense bullet pattern. Totals were
  3 deaths/7 bombs and score=6025140. Evidence: `logs/campaign-lunatic-gl33-1.log`,
  trace `simdata/laya-m3cam-0925-230434.jsonl`, checkpoints
  `simdata/checkpoints/m3cam-0925-230434-stage{1,2}.json`, and replays
  `simdata/replays/m3cam-0925-230434-stage{1,2}-lunatic.trsr`. Stages 3–6
  were not run; the direct Lunatic gate remains open.

- Fidelity tooling checkpoint (2026-09-25): `tools/verify_fork_replay.py` now
  runs the completed fork `build-gl33/src/taisei.exe` with
  `--renderer null --verify-replay` and
  `TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY=1`, preserving the output log.
  `tools/record_replay_video.py` sets the same environment variable while
  capturing the active gl33 playback, extending the per-frame check across
  the actual video render.
- Earlier allocator fix verified: `-Dallocator=libc` + declaration-aware
  `has_function` checks in `third_party/taisei-sim/meson.build` (mingw-w64
  exports `posix_memalign`/`aligned_alloc` symbols but never declares them →
  link-test false positive → `-Werror=implicit-function-declaration` failure).

## 9. Open items

- [~] Complete `build-gl33` (`taisei.exe` + DLL) — stale thin archive
      deleted, rebuild running 2026-09-25 (`logs/build-gl33-4.log`); no
      meson change needed (see §8); smoke-test after.
- [x] Executor v5 (laser centerline capsule + motion-crossing penalty,
      wall-proximity penalty, hit-time death-bomb + immediate macro bomb).
      Implemented 2026-09-25 in `harness/executor.py`; validated pure-guard
      stage 3 Easy seed 12348: WON f17406, 1 real death + 2 death-bombs
      (bombs 3→1→0) — incl. the fix that the death-bomb net must fire in the
      `!pl.alive` early-return branch (`pl.alive` is false during the death
      window; sim.c:410).
- [ ] Re-run Easy campaign on `build-gl33` (gate: 6 WON, cov ≥99%, untainted,
      deaths ≤9, bombs ≤9); then Normal → Hard → Lunatic on `build-gl33`.
- [ ] Merge 6 Lunatic replays; **freq=1 `--verify-replay` (fork exe) exit 0**;
      record gl33 video **with `TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY=1` active**
      (zero desync lines in the exe log = the check covers the video playback
      itself, §12); M4 human-likeness sanity check.
- [ ] Update this doc's §8 once the rebuild lands (ar fix + new exe byte scan).

## 10. Provenance — who built what (user Q&A, 2026-09-25)

```
Laya (remote GPU host, decision engine)          -> external service; no repo involved
     |
harness/ (agent.py, executor.py, taisei_sim.py) -> built against touhourl/taisei-sim's C API
     |  (ctypes: taisei_sim_reset / step(buttons) / get_state)
libtaisei_sim.dll (headless engine)             -> ONE compiled engine:
     |  taisei-project/taisei **v1.4.6 game code**
     |  + touhourl/taisei-sim's **sim layer** (src/sim/, fork commit d9b12e75)
taisei.exe (same build, gl33 renderer)          -> renders the video of the .trsr
```

- **Harness / integration: based on touhourl/taisei-sim — yes.** Stock taisei
  exposes no drive API (inputs come only from keyboard or replay file, no
  state API); the harness exists precisely because of touhourl's sim C API
  (`taisei_sim_reset/step/get_state`, `src/sim/taisei_sim.h`).
- **The game actually being played: taisei-project/taisei v1.4.6 code.** Fork
  branch `sim-on-v146` = v1.4.6 tag + 1 commit (git-verified:
  `describe -> v1.4.6-1-gd9b12e75`). All currently-valid results (post-rebase
  guard A/B, Easy campaign `logs/campaign-easy-1.log`, stage-3 death
  forensics) ran on this v1.4.6-based engine. The 1.5.0-dev engine existed
  only pre-rebase (2026-09-25 10:21); its results (campaigns 1-6) are
  historical tuning data.
- **Stock release binary (v1.4.6 zip): out of the pipeline**, kept as
  reference / A-B baseline (it desyncs at f7457 — §5).
- In one sentence: **Laya plays v1.4.6, driven through touhourl's sim API,
  compiled by us.** The two repos are not alternatives: touhourl provides the
  *how-to-drive*; taisei-project provides the *what-is-driven*.

## 11. Candidate solutions compared — decision: keep the current one (2026-09-25)

| Option | v1.4.6 content | Laya-driven | Video = exactly Laya's run | Complexity |
|---|---|---|---|---|
| **Current: fork (v1.4.6 + sim), same build renders its own replay** | yes | yes | yes, provable (freq=1 verify exit 0) | 1 build script + 1 linker flag |
| Stock exe renders our replay | yes | yes | no — desyncs at f7457 (measured): a different game after ~2 min | simplest |
| touhourl's original base (1.5.0-dev) | no — 59 files of different game code | yes | yes (if built) | still needs our own build — they ship no binary (0 releases) |
| Match stock's toolchain (clang/ucrt) so stock can render faithfully | yes | yes | maybe — last-ulp matching unproven, research-level flag chasing | most moving parts (new toolchain) |

Each "simpler" option breaks a locked requirement (accuracy or content). The
current option costs no extra code — the video exe is the upstream build with
the stock gl33 renderer enabled — and turns "trust me" into a test. Escape
hatches if simplicity is preferred: accept a drifting video (stock exe) or
accept 1.5.0-dev content (touhourl base). Neither was chosen (2026-09-25).

## 12. "100% accuracy / zero discrepancy" — what is claimed, what is proven

**Claim (user question, 2026-09-25):** for the final recorded run, zero
discrepancy between Laya, the game, and the video.

| Link in the chain | Fidelity | Guarantee / proof |
|---|---|---|
| Laya's decision -> executed buttons | 100% (for that run) | "Laya is final": executor never vetoes a macro (final mode pauses while Laya is unreachable); every decision + macro logged per frame in the Laya jsonl -> any on-screen moment traces to Laya's exact answer |
| Engine (what Laya played) -> `.trsr` | 100% (lossless) | Replay = complete game description: per-stage start states (score/lives/bombs/power/pos) + seed + every input event. Frame-based logic (no wall-clock in gameplay) -> same description => same game |
| `.trsr` -> video frames | 100% (machine-verified) | Campaign and video use the **same build** (`build-gl33`). Acceptance: `TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY=1` (engine's own `(rng_u64() ^ plr.points) & 0xFFFF` digest every frame, stage.c:1326; compare replay/state.c:36-60): (a) `--renderer null --verify-replay final.trsr` -> exit 0; (b) **stronger**: run the actual gl33 recording with the same env var -> zero desync lines in the exe log = the rendered frames are the checked states |

**Fine print (what is *not* literally 100% — none of it is a discrepancy
between components):**
1. The desync check is a 16-bit hash of (RNG state XOR score) per frame — the
   game's own definition of "in sync". Two engines of the same build matching
   it on every frame for 60k+ frames are the same game for all practical
   purposes.
2. **Laya is stochastic — that is the player, not an error.** Re-running the
   campaign yields different decisions and a different game. The video is
   *that* run; within it, everything is consistent.
3. Cosmetic: the video is **silent** (null-audio build; the spec asked for the
   game screen, not audio), window-captured at 1280x720, and capture
   smoothness depends on the Intel UHD holding 60 fps (frame drops = choppier,
   never wrong).

## Sources

- Git: `third_party/taisei-sim` (branches `sim-on-v146` d9b12e75,
  `pre-rebase-150dev` 92eafb92; remotes origin=touhourl/taisei-sim,
  upstream=taisei-project/taisei).
- Engine: `src/lasers/laser.c` (106-149, 260-303, 349-409, 479-535, 526-604),
  `src/sim/sim.c` (331-359, 498-534, 956-965, 1216), `src/sim/runtime.c` (79, 109),
  `src/sim/taisei_sim.h` (101, 323-344), `src/player.c` (630-709, 880-890,
  975-1026), `src/plrmodes/marisa.c` (30-50), `src/stage.c` (48, 54-84, 963-1042,
  1148-1156, 1326), `src/replay/stage.c` (14-62), `src/replay/state.c` (36-97),
  `src/replay/play.c` (44-90), `src/replay/struct.h` (106-123),
  `src/eventloop/eventloop.c`, `src/global.{c,h}`, `src/boss.c`.
- Harness: `harness/executor.py` (47-70, 104-166, 269-340),
  `harness/agent.py` (50-121, 443-540, 553-586), `harness/macros.py` (17-26),
  `harness/taisei_sim.py` (320-340), `tools/test_m3_campaign.py` (21-27).
- Logs: `logs/run-2026-09-25-m3-easy.md` (275-356, 455-478),
  `logs/build-gl33-3.log` (1498-1509), `logs/campaign-easy-1.log`.
- Docs: `doc/research-sim-vs-stock-desync.md`, `doc/research-trsr-replay-format.md`,
  `doc/research-lasers-snapshot.md`, `doc/requirements-decisions.md` §6,
  `doc/PLAN.md` (M4 + decision log).
