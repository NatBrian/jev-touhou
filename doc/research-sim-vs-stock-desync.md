# Research: sim engine vs stock Taisei v1.4.6 — replay desync and the rebase decision

Date: 2026-09-25
Context: M4 requires the final video to be a replay played in **stock Taisei
v1.4.6** (`doc/requirements-decisions.md` §6). This doc records why the sim's
replays do NOT reproduce in stock v1.4.6 as-is, and the decision to rebase the
simulation layer onto the v1.4.6 source tree.

## 1. Empirical evidence — the desync

`taisei.exe --verify-replay <merged 3-stage .trsr>` (stock v1.4.6, headless
verification mode) fails:

```
W: replay/state>replay_state_check_desync: Frame 5400: replay desync detected! 0xf948 != 0xe502
EXIT: 1   (wall: 2s — full-CPU-speed headless run, first desync aborts)
```

- Stage 1 (seed 12346), frame 5400 — mid boss fight (boss active from ~f2700).
- Earlier checks passed (the sim records `EV_CHECK_DESYNC` events at
  `FPS * 5` = every 300 frames by default, `src/stage.c:1317`), so the engines
  matched through at least f4800 and diverged in (4800, 5400].
- The digest is `(rng_u64() ^ plr.points) & 0xFFFF`
  (`src/stage.c:965-988` `stage_replay_sync`) — any difference in RNG state or
  score fails the check. A mid-fight divergence means the game content itself
  (patterns/spawns/timing) differs between the two builds.

`--verify-replay` mechanics (verified in source, `src/main.c:354-356,
587-594`, `src/global.c:26-31`, `src/eventloop/executor_synchro.c:108-114`):
headless (dummy video+audio drivers), rendering skipped, FPS limiter disabled,
crash/exit-1 on desync, clean exit 0 when the whole replay verifies
(`main_cleanup` → `main_quit(ctx, 0)`). This is the acceptance test for the
rebase.

## 2. Why — the sim is built on a different taisei lineage

- The sim (fork `touhourl/taisei-sim`, HEAD `6e6f8e3e` 2026-08-24) is built on
  **upstream master `4e21fc39`** (2026-08-04, "ci: update to linux-toolkit",
  Andrei Alexeyev) — i.e. taisei **1.5.0-dev** (the sim reports game version
  1.5.0.0 in the replay header).
- Stock v1.4.6 is the **1.4 release line**: tag `v1.4.6` = `5bfc9b84`
  (2026-08-02 17:31, "xdg: update appdata for v1.4.6 release").
- Direct tree diff `v1.4.6 .. 4e21fc39` (game logic, `src/`): **59 files,
  +1399 / −774**, including:
  - `src/enemy_classes.c/h` (656/97 lines) — the fairy/enemy spawn API was
    rewritten (`espawn_*` → `ecls_spawn_*/ecls_*_summon`, see
    `src/stages/stage1/timeline.c` diff);
  - `src/lasers/laser.c/h` (420/39) + NEW `src/lasers/rules.c/h` (+186/+96) —
    laser system extended in 1.5.0-dev;
  - spell changes in **every stage** (stage2 `amulet_of_harm`, stage3
    `light_singularity`/`moonlight_rocket`/`moths_to_a_flame`, stage4
    `vlads_army`, stage5 `natural_cathode`, stage6 `maxwell`/`toe` …);
  - `src/boss.c`, `src/enemy.c`, `src/move.c`, `src/stage.c`, `src/main.c`,
    `src/global.h`, `src/rwops/*`.

Conclusion: the sim plays a different game than stock v1.4.6. Any replay
recorded on the sim will desync in stock, and the longer the stage the wider
the divergence (bullet-hell state is chaotic — small pattern offsets
amplify). A stock-played replay of the Lunatic run could end in a different
death/clear outcome than the run Laya actually made.

## 3. Decision (2026-09-25)

**Rebase the simulation layer onto the v1.4.6 source tree**, so the sim and
stock v1.4.6 share identical game logic; then every sim-recorded replay
reproduces bit-exactly in stock (verified by `--verify-replay` exit 0).

Rationale vs alternatives:
- *Keep 1.5.0-dev sim + record video on a matching dev build*: violates the
  user-locked "stock Taisei v1.4.6" spec; a random master commit is not
  verifiable/citable by a third party.
- *Accept the desynced playback*: the video would no longer show Laya's run.

Scope (measured):
- Sim layer = `4e21fc39..6e6f8e3e` + local uncommitted fixes: 19 files
  (+2115/−1603), mostly NEW (`src/sim/`, `Makefile`); core edits in
  `stage.c/h` (+84/+33), `boss.c` (38), `eventloop.c/h` (39+5), `global.c/h`
  (4+1), dialog trims, `stage6/background_anim.c`.
- Local uncommitted sim fixes carried along: `src/sim/sim.c` laser-sampling
  fix (`collect_laser_point` return NULL), BGM-init removal, meson build
  tweaks, new `src/sim/meson.build`.
- Expected conflicts vs the 1.4.6 delta: `stage.c`, `global.h`, `boss.c`,
  `src/meson.build` (all small hunks).
- Submodules: `external/{basis_universal,koishi,gamecontrollerdb}` (the fork
  builds via `subprojects/` symlinks to them; the fork's local submodule
  working trees are kept, so no submodule re-fetch is required).

Acceptance criteria:
1. `tools/build_taisei.bat` rebuilds the DLL on the v1.4.6-based tree.
2. Harness smoke test + guard A/B stages 1–3 (Easy, seeds 12346/47/48) all WON.
3. Stock `taisei.exe --verify-replay <sim-recorded replay>` exits 0 (no
   desync) — on at least one full stage and ideally the merged 3-stage file.
4. Re-run the Easy campaign (G3) on the new engine (old-engine results are
   reference-only).

Notes:
- All M3 tuning (guard strategy, death classes, laser timings) was measured on
  1.5.0-dev content; expect small shifts (the stage timelines/spells differ),
  so re-validate the guard A/B before the campaign.
- The stock binary is presumed to match the v1.4.6 tag; the verify-replay test
  is the empirical check.

Sources:
- `third_party/taisei-sim` git: `git log` (fork commits by touhourl over
  upstream commits by Andrei Alexeyev et al.), tag `v1.4.6` fetched from
  `https://github.com/taisei-project/taisei` (2026-09-25).
- Desync log: stock run 2026-09-25 (AppData\Roaming\taisei\log.txt +
  console capture, excerpt above).
- `src/stage.c:965-988` (`stage_replay_sync`), `src/stage.c:1317`
  (`desync_check_freq = env TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY, FPS*5`),
  `src/main.c:354-356` (CLI_VerifyReplay → headless), `src/global.c:26-31`,
  `src/eventloop/executor_synchro.c:108-114` (skip render + FPS limiter in
  verification), `src/replay/state.c:36-60` (desync check + warning).
- `doc/research-trsr-replay-format.md` (playback mechanism section).
