# Research: Taisei Project, taisei-sim, and thrl

Date: 2026-09-24 · Sources: GitHub repos (taisei-sim source fetched file-by-file; API trees/commits via GitHub API),
taisei-project.org, codeberg.org/thrl. This is the game we will play — **headless, fully inspectable state, no CV**.

## 1. Taisei Project (the game)

- **Open-source Touhou fangame**, MIT-licensed, C11 + SDL3 + OpenGL (also Vulkan/Metal backends), official
  releases for Windows/Linux/macOS + WebGL. Not a clone of any specific Touhou title; original story/art/music
  in the Touhou world. https://github.com/taisei-project/taisei (≈1.6k stars) · https://taisei-project.org
- Current stable: **v1.4.6 (2026-08-02)**; v1.4.5 (2026-07-03) added localization; v1.4.x line is the
  ground-up engine rewrite (2024-10 news).
- Structure: **6 story stages + Extra stage**, 4 difficulties (Easy / Normal / Hard / Lunatic), **3 playable
  characters × 2 shotmodes each**: Reimu A/B, Marisa A/B, Youmu A/B (confirmed from `src/plrmodes.c`).
- Stages (from `src/stageinfo.c`, ids used by the sim's episode config):

  | id | Title |
  |---|---|
  | 1 | Misty Lake Encounter |
  | 2 | Riverside Hina-Nagashi |
  | 3 | Crawly Mountain Ascent |
  | 4 | Forgotten Mansion |
  | 5 | Climbing the Tower of Babel |
  | 6 | Roof of the World |
  | 7 | Extra: Descent into Madness (bonus, D_Extra) |

  Plus **spell practice stages** (one per spellcard per difficulty) and dev-only DPS test stages.
- Gameplay mechanics — see `doc/research-touhou-gameplay.md` (hitbox/focus, bombs, power + power surge, items,
  PIV/scoring, spell cards, lives/continues).
- **Replays**: full input recording; stored in `%APPDATA%\taisei` (override with `TAISEI_STORAGE_PATH`).
  → We can **save our runs as replays and watch them play back in real Taisei** (human-likeness check + video).
- Storage/cache env vars: `TAISEI_RES_PATH`, `TAISEI_STORAGE_PATH`, `TAISEI_CACHE_PATH` (the sim's global config
  sets exactly these).
- Build (upstream): `meson setup build/ && meson compile -C build/`; deps: meson ≥1.8.0, SDL3 ≥3.2.0, cglm ≥0.7.8,
  freetype2, libwebp ≥0.5, libzstd ≥1.4, zlib, libunibreak, libpng (optional); subprojects: koishi, glad,
  basis_universal, openlibm. Windows is a first-class target (NSIS installer, ANGLE fallback for Intel iGPU).

## 2. taisei-sim (the headless simulator we use)

- Repo: https://github.com/touhourl/taisei-sim — "**Headless Taisei Project Simulation of thrl**" by **touhourl**
  (author of the thrl Touhou RL framework; 1 star, actively developed).
- **What it is**: a fork of taisei-project/taisei with a **self-contained C API** for driving the whole game
  headlessly. Fork base ≈ taisei master around **2026-07-18** (fork history contains upstream commits through that
  date; first sim commit 2026-08-06, last 2026-08-24; no releases published; README is still upstream's).
  The tree diff vs current upstream master is only the sim additions + 4 newer upstream bullet sprites/shader —
  i.e. gameplay is v1.4.6-era.
- Additions vs upstream (verified by diffing GitHub API trees):
  - `Makefile` (Linux: python venv + `pip install backports.zstd` + `git submodule update --init --recursive` +
    `meson setup/compile/install`)
  - `src/sim/taisei_sim.h` (the C API), `src/sim/sim.c` (implementation), `src/sim/runtime.c`/`runtime.h` (headless bootstrap)
  - commit "fix: stop any dialogs from appearing" (all dialog files emptied; render/music kept)
- **Headless bootstrap** (`runtime.c`): forces `SDL_VIDEODRIVER=dummy`, `SDL_AUDIODRIVER=dummy`,
  `TAISEI_RENDERER=null`, `TAISEI_AUDIO_BACKEND=null`, `TAISEI_FRAMELIMITER_LOGIC_ONLY=1`,
  `global.is_headless = true`, `global.is_simulation = true`, `global.frameskip = 1`, then runs the normal
  init (config, VFS, resources, audio stub, renderer null). **No GPU, no display, no audio needed** — pure logic.

### The C API (`taisei_sim.h`, API version 1)

Coordinates: **480×560 playfield, (0,0) top-left, +x right, +y down**.

```c
taisei_sim_global_init(TaiseiSimGlobalConfig*)   // resource_path, storage_path, cache_path
taisei_sim_create(TaiseiSimConfig*, TaiseiSim**) // laser_sample_step; ONE sim per process (use subprocess for multi)
taisei_sim_reset(sim, TaiseiSimEpisodeConfig*)   // start/restart an episode
taisei_sim_step(sim, TaiseiSimAction*, uint32_t frame_count)  // frame_count may be 0; N logic frames per call
taisei_sim_abort(sim)
taisei_sim_get_state(sim, TaiseiSimState*, const TaiseiSimStateBuffers*)  // full snapshot
taisei_sim_save_replay(sim, const char *path)   // once, after episode terminates
taisei_sim_destroy(sim)
taisei_sim_last_error(sim)                       // error strings
// + taisei_sim_api_version(), taisei_sim_abi_fingerprint(), taisei_sim_sizeof_*() for ABI-safe struct sizing
```

**Episode config** (per stage run): `stage_id`, `difficulty` (1=Easy … 4=Lunatic), `player_character`,
`shot_mode`, `practice_mode`, `rng_seed` (deterministic; also drives start_time), and optional initial
`lives/bombs/life_fragments/bomb_fragments/power/point_item_value/score/graze` (use `TAISEI_SIM_USE_DEFAULT_*`
sentinels for game defaults).

**Action**: single `buttons` bitmask: `UP, DOWN, LEFT, RIGHT, FOCUS, SHOT, BOMB, SPECIAL` (0x01–0x80).
Held buttons persist across `step` calls (the sim injects press/release events + reconciled input flags each
frame — multi-combination supported).

**State snapshot** (everything we need to play blind — no CV):
- Meta: `stage_id`, `stage_type` (story/extra/spell/special), `difficulty`, `logical_frame`, `episode_status`
  (RUNNING/WON/LOST/ABORTED/ERROR), `stage_clear`, `game_over`, `score`, `graze`, `voltage`, `deaths`,
  `bombs_used`, `continues_used`, `gameplay_digest` (FNV-style hash of the whole snapshot, for determinism checks).
- **Player**: position, previous_position, velocity, input flags, focused/shooting, lives, bombs,
  life/bomb fragments, stored/effective power, point_item_value, score, graze, voltage, invulnerable,
  recovering, alive, death/respawn/recovery timers, bomb_active + bomb_progress + bomb frames,
  power-surge active + positive/negative charges, character + shotmode.
- **Boss**: active, position, velocity, hp, max_hp, invulnerable, phase_index, `phase_type`
  (NONSPELL/MOVE/SPELL/SURVIVAL/EXTRA), attack_id, `spell_id`, spell_active, phase start/end/timeout frames,
  `remaining_timeout_frames`, spell_failed_frame, spell_failed, spell_captured, `recent_damage` (dmg we dealt
  this step — perfect for DPS feedback).
- **Projectiles** (array, sorted by spawn_id): spawn_id, category (ENEMY/CLEARING/PLAYER), position,
  previous_position, velocity, collision_size, damage, angle, age_frames, flags (GRAZEABLE, CLEARABLE,
  COLLISION_ENABLED, INDESTRUCTIBLE, **ACTIVE_HAZARD**), damage_type, clear_flags.
- **Enemies**: position, velocity, hp, max_hp, hit/hurt radius, age, flags (KILLED, TARGETABLE, DAMAGEABLE,
  HARMFUL, INVULNERABLE, IMPENETRABLE, NO_AUTOKILL), damageable, harmful.
- **Items**: position, velocity, item_type (PIV, POINTS, POWER_MINI, POWER, SURGE, VOLTAGE, BOMB_FRAGMENT,
  LIFE_FRAGMENT, BOMB, LIFE), age, collect_frame, attracted, pickup_value.
- **Lasers**: origin, age, width, speed, timespan, death_time, time_shift, collision_active, unclearable,
  clear_flags, plus **sampled polyline points** (`first_point`/`point_count` into a shared `laser_points` array:
  position, half_width, time, discontinuity flag) at a configurable `laser_sample_step` (default 8) —
  lasers are given as geometry, so we can compute their swept path in code.
- Error model: `TAISEI_SIM_ERROR_*` codes incl. `BUFFER_TOO_SMALL` (grow buffers and re-read) and
  `ABI_MISMATCH`; `taisei_sim_last_error()` gives the message.

### Semantics notes (from sim.c)
- `reset()` aborts any running episode, re-inits resources, applies a `StageStartOverride` (seed, start_time,
  graze, optional initial resources), starts the stage via the normal `stage_enter()` + event loop, and runs the
  init frame. `step()` runs `eventloop_step_logic()` N times (the exact logic step the game uses) and tracks
  boss HP delta per step.
- Episode ends map to `status`: `GAMEOVER_WIN/SCORESCREEN` → **WON**, `GAMEOVER_DEFEAT` → **LOST**, abort → ABORTED.
- Replay is recorded for the whole episode (player name "thrl"); `save_replay` writes a standard Taisei replay
  file **after** the episode terminates.
- `taisei_sim_create` note in code: "Only one simulation is supported per process. Use `multiprocessing` or
  `std::process::Command`" → for parallel rollouts, use subprocesses.
- ABI: stable sizing functions + fingerprint; struct fields are versioned (`struct_size` first member) —
  we can safely add our own consumers (ctypes) without recompiling.

## 3. thrl (context: who built taisei-sim and why)

- **thrl** = "Touhou Reinforcement Learning Framework" — https://codeberg.org/thrl/thrl (also
  github.com/touhourl/thrl). Rust + Python (maturin), MOPPO-style multi-objective PPO, paper:
  Liu, T. "A High-Fidelity Reinforcement Learning Environment and Baseline for Multi-Objective Bullet Hell
  Games" (2026), doi:10.5281/zenodo.21788472.
- Two game backends: (a) **PC-98 Touhou games** (TH05 Mystic Square, TH06 Lotus Land Story, …) via a
  from-source **dosbox-x** build + `th98patch` (memory-patching of the game executables; ReC98-style reverse
  engineering), and (b) **Taisei via taisei-sim** (the "Taisei Headless Simulation" link in thrl's README).
- Requirements: **GNU/Linux only** (WSL2 "won't promise it works"), GPU ≥6 GB VRAM for its RL workers,
  `make defconfig`/`make switch`, `uv sync` + `maturin develop`.
- Author's reported results: a PPO agent reached stage 2–3 (fighting bosses) after ~20 days of training on TH04;
  "cannot fully beat stage 3 (idx 2) in game with 3 lives and 3 bombs … only a time issue."
- **Why we use taisei-sim but not thrl**: we need a *decision engine* (Laya) on top of the game, not RL training.
  thrl's stack is Linux-only and RL-shaped (workers, rollouts, reward vectors). taisei-sim's C API alone is all
  the game side needs; we consume it with Python `ctypes` from Windows.

## 4. Build plan on this PC (for M1)

- Clone `https://github.com/touhourl/taisei-sim` (with submodules) into `third_party/taisei-sim/`.
- Build with **meson on Windows** (taisei officially supports Windows; taisei-sim's own Makefile is just a
  Linux convenience). Toolchain options inside the folder (no system installs):
  1. MSVC (Visual Studio Build Tools) + meson (meson supports VS generator on Windows), or
  2. **llvm-mingw** (mstorsjo) — taisei's own BUILD doc recommends it for Windows cross/native builds;
  3. Fallback: WSL2 (Ubuntu + system meson deps) — but thrl is Linux-only, so this path also insulates us from
     Windows toolchain quirks; note: WSL2 install must be scoped to this folder (WSL itself is a system feature —
     ask user before installing if needed).
- Deps via meson wrap system (SDL3, cglm, freetype, libwebp, libzstd, zlib, libunibreak, openlibm, koishi, glad,
  basis_universal) — downloads into the build tree; keep an eye on **C: free space (8 GB)** and prune after build.
- Output: `taisei` exe (or DLL) exporting `taisei_sim_*` symbols (TAISEI_SIM_API = `__declspec(dllexport)` under
  `TAISEI_SIM_BUILD`; on Windows the exe itself is the DLL — loadable via `ctypes.WinDLL`).
- Validate: `taisei_sim_api_version() == 1`, `taisei_sim_sizeof_state()` matches our ctypes struct, run a
  fixed-seed Easy stage-1 episode, assert determinism via `gameplay_digest`, save a replay.

### Build-phase findings (2026-09-25, M1)
- **Fork bug — missing `src/sim/meson.build`:** the fork's build commit (`b64fe671` "build: simulation lib
  and build system") adds `subdir('sim')` to `src/meson.build` but **never committed `src/sim/meson.build`**,
  so a plain `meson setup` fails ("Directory does not contain a meson.build file") on every platform.
  Reconstructed in-tree: append `sim.c` + `runtime.c` to `taisei_main_src` (the exe's extra sources) and
  `add_project_arguments('-DTAISEI_SIM_BUILD', language: 'c')` so `TAISEI_SIM_API` becomes
  `__declspec(dllexport)` → the built `taisei.exe` carries the export table and is loadable via
  `ctypes.CDLL` (the exe is the "DLL" for the API).
- **Toolchain (confirmed on this PC):** VS 2022 BuildTools with MSVC toolset 14.44.35207 present → MSVC path
  chosen (no llvm-mingw download needed). `vcvars64.bat` at
  `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\`. meson 1.12.1 +
  ninja 1.13.2 installed into the project `venv/` (pip, no system installs).
- **gettext is a hard build dependency:** `po/meson.build` does `find_program('xgettext'|'msgfmt',
  required: true)` unconditionally (i18n catalogs). No modern Windows binaries on ftp.gnu.org (source only;
  the only prebuilt zip is woe32 from 2004) → pulled MSYS2 packages
  `mingw-w64-x86_64-gettext-tools-1.0-1` + `gettext-runtime-1.0-1` from
  `https://repo.msys2.org/mingw/mingw64/` (note: **the repo layout is `mingw/mingw64/`, not `mingw/w64/`**)
  into `third_party/gettext/` (`.pkg.tar.zst` = zstd tarball, extracted with the `zstandard` wheel). Binaries
  at `third_party/gettext/mingw64/bin/` — prepended to PATH for the build.
- **Build flags used** (`tools/build_taisei.bat`): only the **null renderer + null audio** backends
  (`-Dr_null=enabled -Dr_gl33=disabled -Dr_gles30=disabled -Dr_sdlgpu=disabled -Da_null=enabled
  -Da_sdl=disabled -Dshader_transpiler=disabled -Dvalidate_glsl=disabled -Dtests=disabled -Ddocs=disabled`).
  The sim forces `TAISEI_RENDERER=null`/`TAISEI_AUDIO_BACKEND=null` anyway (runtime.c), and skipping the GL
  backends avoids building glslang/shaderc/SPIRV-Cross/SPIRV-Tools (huge C++ deps).
- **Resource layout:** asset tree is `resources/00-taisei.pkgdir/` (bgm, demos, fonts, gfx, models, sfx,
  shader) — no `stage/` dir because **stages 1–6 are compiled in** (`src/stages/stageN/`). So the sim can run
  straight from the build tree with `TAISEI_RES_PATH=resources/00-taisei.pkgdir` (set via
  `TaiseiSimGlobalConfig.resource_path`).
- **v1.4.6 (2026-08-02) is the latest release** and contemporary with the fork base (2026-07-18) — used for
  replay playback / final video: `Taisei-1.4.6-windows-x86_64.zip` (213 MB, portable).
- **Windows symlink checkout breaks `subprojects/basis_universal` + `subprojects/koishi`:** these are git
  **symlink entries** (mode 120000) pointing at `../external/basis_universal` / `../external/koishi` (the
  real submodules live under `external/`). On this PC `core.symlinks=false` (no Developer Mode privilege,
  WinError 1314), so git checks them out as **plain text files** containing the target path → meson:
  "Subproject basis_universal is buildable: NO". Workaround applied: deleted the text files and created
  **NTFS directory junctions** (`mklink /J subprojects\basis_universal <abs>\external\basis_universal`) —
  junctions need no privilege and are transparent to meson/Python. (On Linux this never occurs.)
- **Flaky GitHub git protocol on this connection:** meson's full-clone wrap downloads repeatedly failed
  (`fatal: fetch-pack: invalid index-pack output`, `curl 56 schannel: server closed abruptly`). Workaround:
  `tools/fetch_wraps_tarball.py` downloads the pinned revisions as **codeload tarballs**
  (`https://codeload.github.com/<owner>/<repo>/tar.gz/<ref>`, retried) into `subprojects/<dir>`; meson's
  `_resolve()` accepts a pre-existing subproject dir as soon as it contains a build file (`meson.build` /
  `CMakeLists.txt`), so no further git is needed. All 17 wraps fetched this way (one libpng retry).
- **koishi (coroutine lib) fcontext backend needs a gas assembler MSVC lacks:** on `x86_64 + Windows`,
  koishi's auto-pick selects the `fcontext` backend, whose meson hardcodes `fcontext_asm_flavor = 'gas'`
  (`src/fcontext/meson.build`) → it emits `.S` files (`jump_x86_64_ms_pe_gas.S`) that meson cannot compile
  under MSVC ("No host machine compiler for ...gas.S"; meson has no MASM/`.asm` support). Fix applied in the
  root `meson.build`: when `cc.get_id() == 'msvc'`, pass `subproject('koishi', default_options:
  ['impl=win32fiber'])` → uses koishi's native Win32-Fiber backend (pure C, `src/win32fiber/win32fiber.c`),
  a first-class drop-in replacement. (Linux keeps fcontext.)
- **MSVC is a dead end for taisei's C — switched to MinGW-w64 GCC:** after the koishi fix, `meson setup`
  then hit `assert(have_vla and have_complex, ...)` (meson.build:273) because MSVC defines
  `__STDC_NO_VLA__`/`__STDC_NO_COMPLEX__`. Taisei's C genuinely uses **VLAs** in several core modules
  (e.g. `src/coroutine/coevent.c` `BoxedTask subs_snapshot[evt->subscribers.num_elements]`,
  `src/coroutine/cotask.c` VLA *parameter* arrays, `src/log.c`, `src/cli.c`, `src/boss.c`, `src/video.c`,
  `src/dynstage.c`, `src/taskmanager.c`, `src/plrmodes.c`), plus GCC idioms. Patching all VLA sites is
  invasive and fragile, and official Taisei Windows releases are **MinGW-built** → picked MinGW-w64 GCC
  (MSYS2) instead. `tools/build_taisei.bat` now sets `CC=gcc CXX=g++` and prepends
  `third_party\mingw\mingw64\bin` to PATH; the MSVC `vcvars64` step was dropped.
- **MinGW toolchain fetched via `tools/fetch_mingw.py`:** pulls a minimal 25-package closure (~500 MB) into
  `third_party/mingw/`. Notes on the **2026 MSYS2 layout**: (1) the repo index `mingw64.db` is now a
  **zstd-compressed TAR** of per-package `desc` files (not the old SQLite `PACKAGE` table); (2) package
  **names are arch-qualified** (`mingw-w64-x86_64-gcc`); (3) the short **`%BASE%` is NOT unique**
  (e.g. `lto-dump`'s base is also `mingw-w64-gcc`) so the index must be keyed by full `%NAME%`, not base;
  (4) `DEPENDS` entries carry version constraints (`=16.2.0-4`) that must be stripped; (5) GCC **16.x**
  merged the C++ front end into the `gcc` package (no separate `g++` pkg), and renamed
  `libstdc++-v3`→`libstdc++`, `gcc-libs`→`cc-libs`. Fetched set: gcc, g++ (in gcc), binutils, crt, headers,
  cc-libs, libgcc, libstdc++, libgomp, libwinpthread (+gmp/isl/mpfr/mpc/iconv/zlib/zstd/tzdata etc.),
  gettext-tools+runtime. `gcc.exe g++.exe ld.exe ar.exe xgettext.exe msgfmt.exe` all present.

## 5. Risks / open items

- **Windows build of a fork**: RESOLVED by GitHub read-through 2026-09-25 (see §6). Fork has no releases,
  Linux-only author support, and a broken `subdir('sim')` reference — but the inherited taisei CI proves the
  llvm-mingw cross-build path, and our MSYS2-native MinGW build already passed `meson setup`.
  Mitigation: pin the exact fork commit (master @ 2026-08-24, sha 6e6f8e3e…), fall back to WSL2.
- **Fork staleness**: fork base ≈ 2026-07-18 → no v1.4.6 bugfixes (e.g. Stage 4 stack-use-after-free fix #378
  landed 2026-07-03 so it IS included; post-fork fixes are not). Acceptable for a sim.
- **Single sim per process**: parallel rollouts need one process each (fine — we run one game).
- **No precompiled sim binaries**: we must build (disk budget noted above).
- Stage/boss *names* (spell titles etc.) live in C `AttackInfo` tables (`src/stages/stageN/stageN.h`); the sim
  exposes numeric `spell_id`/`attack_id` — map them to names by reading those headers at implementation time
  (useful for human-readable state text like "boss: spell 3 '…'").

## 6. GitHub read-through of touhourl/taisei-sim + CI (2026-09-25)

Per user instruction ("read the github completely to find solutions"), full read of the fork repo, its CI,
and the parent thrl project. Sources:

- Fork: <https://github.com/touhourl/taisei-sim> (created 2026-08-06, last push 2026-08-24; C; 4 stars; 0 open issues; **releases: none** — `GET /releases` → `[]`)
- Fork workflows: <https://github.com/touhourl/taisei-sim/tree/master/.github/workflows> — `main.yml` (test builds), `release.yml`, `build-ci-container.yml`, `emscripten-experimental.yml` (all inherited from upstream taisei)
- Parent: <https://codeberg.org/thrl/thrl> — "Touhou Reinforcement Learning Framework" (Rust + PyTorch), 18 commits, paper: Liu 2026, DOI 10.5281/zenodo.21788472

### Findings

1. **No off-the-shelf Windows solution exists.** Fork has zero releases (no prebuilt sim binaries), zero issues,
   and its README (`README.rst`) is stock upstream taisei text with no sim build instructions. The parent thrl
   README states: *"Currently, only GNU/Linux is supported. I do not have the enough time to do for Windows.
   You can try WSL2, but I won't promise that works."* → building ourselves was the right call.

2. **The fork's master branch is unbuildable as published.** Commit `b64fe671de` ("build: simulation lib and
   build system", 2026-08-18) adds `subdir('sim')` to `src/meson.build:479`, but the repo's `src/sim/` contains
   only `runtime.c`, `runtime.h`, `sim.c`, `taisei_sim.h` — **`src/sim/meson.build` was never committed**
   (verified via GitHub API file listing on master). Meson hard-fails on a `subdir()` without a `meson.build`.
   Our local reconstruction (`src/sim/meson.build`: append `sim.c`/`runtime.c` to `taisei_main_src`,
   `taisei_sim_c_args = ['-DTAISEI_SIM_BUILD']` applied to the exe target at `src/meson.build:484`) is the only
   fix. Validated: `TAISEI_SIM_BUILD` is used only in `taisei_sim.h:14` (`__declspec(dllexport)` export
   decorator) and only `sim.c` + `runtime.h` include that header, so scoping the define to the exe target is
   exactly right. The dllexport is *required* for `ctypes` to resolve `taisei_sim_*` symbols from the PE exe
   on Windows (export table), confirming the fork's intended design.

3. **Official Windows toolchain is llvm-mingw (clang-based MinGW), not MSYS2 GCC.** Both the test-build CI
   (`main.yml` → `windows-test-build`) and release CI (`release.yml` → `windows-release-build-x64`) run inside
   the Docker image `taiseiproject/linux-toolkit:20260804` and cross-compile from Linux using
   `misc/ci/windows-llvm_mingw-x86_64-build-release.ini`:
   - toolchain `/opt/llvm-mingw`, cc=`x86_64-w64-mingw32-clang`, cxx=`…clang++`, lld, `ldflags = ['-static']`
   - `march = x86-64-v2`, `mtune = znver2`, `werror = false`
   - `[project options]`: `install_angle=false`, `r_gles30=disabled`, `r_sdlgpu=enabled`, `r_default=sdlgpu`,
     `shader_transpiler=enabled` (CI builds the *full GUI* game; our sim build uses null renderer instead —
     a valid subset, meson options are independent)
   - `misc/ci/forcefallback.ini`: `wrap_mode = 'forcefallback'` (all deps vendored, no system packages)
   - CI never compiles the sim (fork added no CI job for it), but it proves the meson config resolves and the
     Windows target links with this exact toolchain family.
   - **Implication / fallback path**: if our MSYS2 GCC 16.2.0 build hits compile errors, switch to the
     CI-proven path: download `sailfish/llvm-mingw` (GitHub release, MSYS2-style tree, single HTTP GET —
     fits our reliable-download constraint) into `third_party/llvm-mingw/`, write a cross-file mirroring the
     CI ini (toolchain dir + `x86_64-w64-mingw32` prefix + lld + `-static`), re-run `meson setup` fresh.
     No WSL2 needed even then.

4. **Fork diff vs upstream** (commit history, 2026-08-05 → 2026-08-24, on top of upstream base ≈2026-07-18):
   - `0b19711` headless simulation C API; `926807e` headless runtime init; `27f4d39` prepare headless runtime
   - snapshot/observation series: `56b7ed6`→`7e6c6ae` (player/boss/projectile/enemy/item/laser snapshots,
     entity counts, ordering/metadata helpers)
   - `ed5c03b` external actions → player input; `cf94504` `env.step` frame advance; `45f46d7` sim handling
   - `a6a19a6` save replays + cleanup; `03c7723` episode end + state observations
   - `af9783f` simulation errors; `b64fe67` build system (the broken `subdir('sim')`); `6e6f8e3` **fix: stop
     any dialogs from appearing** (the headless-safety commit that makes unattended runs possible)
   - `78e1a4c` keep stage 6 boss rotation outside (story-mode continuity, relevant to 6-episode chaining)
   No Windows-specific fixes, no sim CI, no docs beyond code.

5. **thrl context** (parent project, Codeberg `thrl/thrl`): Rust RL framework (MOPPO) driving taisei-sim +
   dosbox-x (for PC-98 games via th98patch). Their agent "cannot fully beat stage 3 with 3 lives and 3 bombs"
   after 20 days of training (README, 2026-08) — consistent with our plan that a zero-shot Laya + reflex
   executor needs a real difficulty ladder; their baseline is an RL-trained policy, not a generalist.
   Nothing to reuse directly (Linux-only, GPU-required PyTorch stack, RL-shaped), but useful as a sanity
   anchor for what "hard" means in this codebase.

## 7. First full compile on GCC 16.2.0 — findings & fixes (2026-09-25)

First `meson compile` reached **807/809** and failed with three distinct errors — two of them are further
evidence that **the fork was never actually compiled** (alongside the missing `src/sim/meson.build`):

### 7.1 Fork bug: `src/sim/runtime.c` calls functions that don't exist

`runtime.c:125/149` call `bgm_init()` / `bgm_shutdown()`. The base code has **no such functions** —
`src/resource/bgm.h` only declares `bgm_get_title/artist/comment/duration/loop_start` + the
`bgm_res_handler` resource handler (registered in `src/resource/resource.c:43`; BGM needs no separate
init/shutdown — it's handled by `res_init`/`res_shutdown`, which `runtime.c` already calls).
→ **Fix (local patch):** deleted the two calls. Compile flags include
`-Werror=implicit-function-declaration` (root `meson.build`), so the error is hard, not a warning.

### 7.2 libpng: `dep_png` probe is pkg-config+cmake only; upstream ships a meson-ized fork

`meson.build:195`: `dep_png = dependency('libpng', 'libpng16', version : '>=1.5', required : get_option('use_libpng'))`
— meson only probes pkg-config and cmake (no compiler/`find_library` method), so a bare MinGW toolchain
without libpng fails the probe. `src/main.c:49` includes `<png.h>` unconditionally and calls
`png_get_libpng_ver()` (line 195), so libpng **must** be found and linked.

The repo already ships the intended solution: `subprojects/libpng.wrap` →
`https://github.com/taisei-project/libpng.git` **branch `meson-1.6.58`**, `[provide] libpng=png_dep`.
taisei-project maintains meson-ized forks of its C deps (same pattern: `zlib.wrap` →
`taisei-project/zlib @ meson-1.3.2`, `libwebp.wrap` → `taisei-project/libwebp @ meson-1.6.0`, …).
Vanilla libpng 1.6.58 has no meson build (autotools + CMake only).

→ **Fix:** vendored the taisei fork branch into `subprojects/libpng/` (codeload tarball of branch
`meson-1.6.58`, sha256 `6f207c05af94bd5a…`; its `meson.build` does
`project('libpng','c',version:'1.6.58')`, `zlib_dep = dependency('zlib', fallback:['zlib','zlib_dep'])`,
exposes `png_dep`; `libpng:default_library=static` comes from the root project's `default_options`).
Implicit subproject fallback verified with a scratch meson project:
`Dependency libpng ... from subproject subprojects/libpng found: YES 1.6.58`.

Also installed `mingw-w64-x86_64-libpng` into `third_party/mingw/` (via `tools/fetch_mingw.py` seed list) —
kept as a system-level fallback; the vendored static libpng is what the build uses.

**Gotcha (found in compile attempt 2):** the subproject fallback is only searched when the
dependency is **required**. taisei declares it as `required : get_option('use_libpng')` — a *soft*
(`auto`) feature — so meson logged `libpng found: NO` and silently skipped the fallback (sdl3 got its
fallback only because it passes an explicit `fallback :` keyword). With `-Duse_libpng=enabled`
(required=true) the fallback is searched and found — verified empirically (scratch project
`required: true` → fallback used; real build `auto` → not). **All build scripts now pass
`-Duse_libpng=enabled`.**

### 7.3 `scripts/pack.py` needs a Python zstd module

The resource-packaging custom target (`resources/00-taisei.zip`) runs
`scripts/pack.py`, which imports stdlib `compression.zstd` (Python 3.14+) **or**
`backports.zstd`. Our venv is Python 3.11 → neither existed.
→ **Fix:** `pip install backports.zstd` into `venv/`.

### 7.4 Meson bug: CMake trace parser crashes on dev-level CMake warnings

`meson setup --reconfigure` crashed with `JSONDecodeError` → `ERROR: Unhandled python exception`
(meson bug) while re-analysing the sdl3 CMake subproject: CMake 4.x dev warnings
(`CMake Warning (dev) ... Policy CMP0200 ...` / `Configuration selection for imported target
"Git::Git" ...`) land as non-JSON lines in the CMake stderr stream that meson's
`cmake/traceparser.py:_lex_trace_json` feeds to `json.loads`.
→ **Fix (build scripts):** `set "CMAKE_ARGS=-DCMAKE_POLICY_WARNING_DEV=NO"` before meson
(`CMAKE_ARGS` is picked up by every CMake invocation, incl. `sdl3-cmake-wrapper`).

### 7.5 Meson caches dependency probes in coredata

Adding `subprojects/libpng/` after the original setup did **not** change the cached
`Run-time dependency libpng found: NO` result on `--reconfigure` (no fresh probe logged in
`build/meson-logs/meson-log.txt`). Meson keys dependency lookups by arguments and caches the outcome;
filesystem changes don't invalidate it.
→ **Fix:** `meson setup --wipe` (fresh probe + full rebuild). Lesson for future dep additions:
wipe, or change the probe's arguments.

### 7.6 Build-environment notes

- C: drive free space changed from **8 GB → 255 GB** during this session — the AGENTS.md §3
  hard-disk constraint no longer binds (prune discipline kept anyway).
- Harmless: `git describe` fails on the in-folder clone (no tags) → version falls back to `v1.5-dev`.
- `rwops_zstd.c:984` emits `-Wformat` warnings under GCC 16 (`%zi` size_t format) — warning only
  (`werror=false` for that flag), no action.
- Build scripts now: `tools/build_taisei.bat` (setup-if-needed + compile),
  `tools/reconfigure.bat` (in-place reconfigure), `tools/wipe_setup_compile.bat` (wipe + setup +
  compile; sets `CMAKE_ARGS=-DCMAKE_POLICY_WARNING_DEV=NO`).
- **Windows batch gotcha**: `rem` comments inside a parenthesised `if (...) (...)` block must not
  contain `(` or `)` — cmd closes the block early and fails with `. was unexpected at this time.`
  (hit this in `build_taisei.bat`; keep comments parenthesis-free inside blocks).

### 7.7 The MSYS2 `gcc-ar` wrapper breaks under ninja (compile attempt 4)

After the libpng fix, the build failed at `Linking static target src/libtaisei.a`:

    "gcc-ar" "csrDT" src/libtaisei.a @src/libtaisei.a.rsp
    ar.exe: src/libtaisei.a: No such file or directory

Investigation (test bats `tools/ar_test*.bat`, since deleted):
- Plain binutils `ar` handles the **exact same invocation** fine — thin (`T`) and regular
  archives, all 292 members, output in `src/`, cwd-relative rsp paths (rsp files must use
  **forward slashes**: binutils ar treats `\` in rsp files as an escape and strips it).
- Meson picks `gcc-ar` as the archiver for GCC ("use gcc-ar if available; needed for LTO",
  `mesonbuild/compilers/detect.py`). The MSYS2 `gcc-ar.exe` is only a 75 KB driver shim
  (vs 3.3 MB `gcc.exe`): it resolves the real binutils from a prefix list
  (`GCC_EXEC_PREFIX`, defaults `/mingw64/bin/`, `/mingw64/lib/gcc/…`) and re-execs them.
  Under ninja the re-exec runs with relative args (`src/libtaisei.a`) resolved against the
  wrong cwd → ENOENT. It also fails silently (exit 53, no output) with the full system PATH,
  but works with `PATH=<mingw bin> only` — i.e. the shim's prefix resolution is fragile.
- **Fix:** `tools/native-win.ini` with `[binaries] ar='ar' ranlib='ranlib'` passed as
  `--native-file` in all build bats. Native-file binary entries take precedence over
  meson's compiler-default archiver (`detect.py: env.lookup_binary_entry(machine, 'ar')`),
  so plain binutils `ar` is used. LTO is unaffected (objects are archived as-is; the final
  `g++ -flto` link does the codegen).
- **Second caching gotcha:** archiver detection (`detect_static_linker`) is *also* cached in
  coredata — attempt 4's reconfigure (with the native file) kept the old `gcc-ar` rule and
  failed identically. Verified in a scratch project that a **fresh setup** with the native
  file produces `command = "ar" $LINK_ARGS ...` (no `gcc-ar`) → `meson setup --wipe` required
  (attempt 5).

### 7.8 Runtime: an EXE loaded via LoadLibrary never runs its CRT → the harness must load a real DLL (2026-09-25)

Build attempt 5 linked `taisei.exe` (13.3 MB) fine. Loading it via `ctypes.CDLL` and
calling `taisei_sim_global_init` then crashed:

    OSError: exception: access violation writing 0x0000000000A4B2F0

**Diagnosis (tools/crash_hook.py + TEMP debug probes, since removed):**
- Added `sim_dbg()` file-log markers through the whole `taisei_sim_runtime_init` sequence and
  two exported CRT probes (`taisei_sim_debug_crt` = pure `snprintf`, `taisei_sim_debug_fopen`
  = `fopen`+`fprintf`). The **pure-snprintf probe access-violated** (write near NULL, address
  drifted between runs: 0xA4B062 / 0xA4B1E8 / 0xA4B2F0 — a corrupted-heap signature), and the
  fopen marker file was never created.
- Root cause: Windows loads an EXE image via `LoadLibrary` **without running its entry
  point as a DllMain**, so the mingw CRT is never initialised in the loaded module. Every
  CRT call inside it (snprintf/fopen/malloc/…) touches uninitialised CRT globals and writes
  to the broken heap near NULL. The ABI size-check functions had run fine because they are
  pure C with no CRT state. (CPython even loads the EXE *without resolving its imported
  DLLs* — after a successful `CDLL(taisei.exe)`, `GetModuleHandle("libgcc_s_seh-1.dll")`
  returns NULL — which is why the ABI check passed and the crash was deferred to the first
  CRT use.)
- **Fix: build a real shared module.** Added to the reconstructed
  `src/sim/meson.build`:

      taisei_sim = shared_module('taisei_sim',
          files('sim.c', 'runtime.c'),
          c_args : taisei_sim_c_args,        # -DTAISEI_SIM_BUILD
          dependencies : libtaisei_dep,
          install : false,
      )

  meson names the artifact `build/src/sim/libtaisei_sim.dll` (13.0 MB, fully self-contained:
  SDL3, zlib, libpng, webp, basis, mimalloc all static; only mingw runtime DLLs are
  imported). A real DLL **does** run its DllMain → `_CRT_INIT` on load, so stdio/locale/
  heap work. The exe target is kept as-is (harmless).
- **Second gotcha (Python side): ctypes (3.8+) does not use the live env PATH for DLL
  dependency resolution.** It registers search dirs via `os.add_dll_directory()` snapshotted
  from PATH at `import ctypes` time; updating `os.environ["PATH"]` afterwards has no effect
  (verified: `CDLL(dll)` fails after an env-PATH prepend, succeeds after
  `os.add_dll_directory(mingw_bin)`). `harness/taisei_sim.register_runtime_dirs(dir)` now
  does both (env PATH + `add_dll_directory`, idempotent) and is called before `TaiseiSim()`.
- **Result (M1 smoke, `logs/smoke-2026-09-25-m1-final.log`):** ABI check OK (14 struct
  sizes), full headless bootstrap OK, stand-still stage-1 Easy Marisa A → **LOST after 874
  frames** (3 deaths), determinism digest identical across two runs
  (0x18d203be39a5247e), `save_replay` writes a .trsr, and headless logic runs at
  **~12,400–13,900 frames/s** (24 one-second buckets, debug build) — three orders of
  magnitude above the 60 fps the game needs, so the synchronous Laya pattern has huge
  headroom.
