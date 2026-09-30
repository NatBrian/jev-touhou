# Research: Taisei .trsr replay file format (v14/zstd)

Date: 2026-09-25
Context: M4 video pipeline — the campaign's 6 single-stage `.trsr` replays must be
merged into one multi-stage replay that stock Taisei v1.4.6 can play
(`taisei.exe --replay file.trsr`).

Sources (all in `third_party/taisei-sim/`, fork base ≈ 2026-07-18):

- `src/replay/struct.h` — struct versions, field order ("All stored fields in
  the Replay* structures are in the order in which they appear in the file"),
  flags (`REPLAY_GFLAGS`/`REPLAY_SFLAGS`: bit 0 CONTINUES, 1 CHEATS, 2 CLEAR).
- `src/replay/write.c` — writer (header, two zstd streams, `fileoffset` patch).
- `src/replay/read.c` — reader (header parse, segment for meta, seek for events,
  useless byte; per-stage checksum validation).
- `src/replay/rw_common.c` — `replay_wrap_stream_compress` (zstd level 22 for
  v14+), stage metadata checksum.
- `src/version.c` / `src/version.h` — on-wire game version is **5 bytes**
  (u8 major, u8 minor, u8 patch, u16 LE tweak — `taisei_version_read/write`).
  NOTE: `TAISEI_VERSION_SIZE` macro says 5 while `sizeof(TaiseiVersion)` is 4 —
  the IO functions are the ground truth (they write each field separately).
- `src/replay/play.c` — `replay_do_play` auto-advances to the next stage in the
  replay → one multi-stage file plays the whole game continuously.
- `src/cli.c:71` — `--replay FILE` / `-r FILE`.
- `src/sim/sim.c` — `taisei_sim_reset` calls `replay_reset` on every episode →
  the sim's saved replay always contains exactly **one** stage (this is why the
  merge tool exists). `taisei_sim_save_replay` (line 1216) saves after episode end.

## File layout (version 14 = TS104000_REV1, compression bit set → version field 0x800E)

```
offset  bytes  field
0       10     magic  68 6f 6e 6f e2 9d a4 75 6d 69  ("hono♥umi", struct.h REPLAY_MAGIC_HEADER)
10      2      version u16 LE (0x800E)
12      5      game_version: u8 major, u8 minor, u8 patch, u16 LE tweak   (5 bytes on the wire!)
17      4      fileoffset u32 LE  = 21 + len(meta_zstd) + 4  (points at the events zstd frame)
21      ...    [zstd frame 1: metadata]
             + 4-byte gap (zeroes)
             [zstd frame 2: all events, stage order]
last    1      0x69 ("useless byte", premature-EOF check, write.c:206)
```

- `write.c` writes the meta stream, then patches `fileoffset = end_of_meta + 4`
  and seeks `end_of_meta + 4` before writing the events stream — hence the
  4-byte gap. `read.c` segments the meta as `[21, fileoffset)` (the gap bytes
  after the zstd frame are ignored by the decompressor) and seeks to
  `fileoffset` for the events.
- Metadata stream content (v14):
  `u8 playername_len + playername | u32 gflags | u16 numstages | ReplayStage × numstages`
- `ReplayStage` v14 = **76 bytes**, field order (write.c `replay_write_stage`):
  `u32 flags | u16 stage | u64 start_time | u64 rng_seed | u8 diff | u16 skip_frames
  | u64 plr_points | u8 plr_total_lives_used | u8 plr_total_bombs_used
  | u8 plr_total_continues_used | u8 plr_char | u8 plr_shot | u16 plr_pos_x
  | u16 plr_pos_y | u16 plr_power | u8 plr_lives | u16 plr_life_fragments
  | u8 plr_bombs | u16 plr_bomb_fragments | u8 plr_inputflags | u32 plr_graze
  | u32 plr_point_item_value | u64 plr_points_final
  | u8 plr_stage_lives_used_final | u8 plr_stage_bombs_used_final
  | u8 plr_stage_continues_used_final | u16 num_events | u32 checksum`
  - `checksum = 1 + ~replay_struct_stage_metadata_checksum(stg, 14)`
    (rw_common.c:17, uint32 wrap; read.c accepts iff
    `computed + stored == 0`). Verified quirks of the v14 sum:
    `plr_total_continues_used` is added **twice** (once in the v14 block,
    once in the v7+ block); `start_time`, `plr_total_bombs_used`, and the
    three `plr_stage_*_used_final` fields are **not** covered.
    `tools/merge_replays.py::stage_checksum` reimplements it and `parse()`
    verifies every stage struct (a mismatch raises).
- Events: 7 bytes each, `u32 frame | u8 type | u16 value` (struct.h
  `ReplayEvent`), concatenated for all stages in stage order; count per stage =
  that stage's `num_events`.
- `plr_lives` etc. in the stage struct = player resources **at stage start**
  (in a chained game this is the carried-over state — so merged per-stage
  replays are faithful to the campaign's carry-over).

## Merge algorithm (implemented in `tools/merge_replays.py`)

1. Parse each input .trsr (verify magic/version 0x800E), decompress both
   frames (`zstandard.decompressobj` — stop at first frame end; the meta
   segment includes the zero gap which `stream_reader` would reject).
2. New metadata: first file's playername (overridable, default "Laya"),
   `gflags` = CONTINUES/CHEATS **OR** over all stages, CLEAR **AND** over all
   stages; `numstages` = 6; stage structs **copied verbatim** (per-stage
   checksums therefore stay valid).
3. Events concatenated in file order; re-compress both streams (zstd level 22),
   write header with correct `fileoffset`, gap, events, `0x69`.
4. Round-trip verify: re-parse the merged file.

Verified (2026-09-25, per-stage metadata checksums pass) against the
campaign-5 replays `simdata/replays/m3cam-0925-064908-stage{1,2,3}-easy.trsr`
(sim build 1.5.0.0): name "thrl", stage id 1/2/3, diff=1 (Easy),
char=1 (Marisa; CHAR_MARISA=1), shot=0 (A), pos=(240,496), events
11740/11300/14171, carry-over scores 0 -> 1,763,075 -> 4,877,022 ->
5,579,291 (matches the campaign-5 jsonl exactly), seeds
12346/12347/12348, per-stage `stage_lives_used` 1/1/2 and
`stage_bombs_used` 3/3/2. Merged into
`simdata/replays/m3cam-0925-064908-merged.trsr` (3 stages, name "Laya",
gflags=0x0 because stage 3 was not cleared) and re-parsed with every
stage struct's checksum still valid. NOTE: an earlier pass mis-read this
file with wrong field offsets (reported "char=0", event-size mismatch);
the offsets above are the corrected, checksum-verified layout.

## Playback mechanism (verified against the stock codebase, 2026-09-25)

Verified by reading the stock v1.4.6 codebase (identical to taisei-sim
HEAD 6e6f8e3e for these files):

- **Per-stage start sync** (`src/stage.c:1255+` start block;
  `src/replay/stage.c:48-66` state restore): each stage of a multi-stage
  replay starts from ITS OWN stage-struct values — score (`plr_points`),
  lives, bombs, power, position, character/shot mode, `rng_seed`,
  `start_time`, `global.diff` (set in the `stage.c` start block). A merged
  file therefore plays back as one continuous game with exactly the
  carryover states the sim produced.
- **Stage end + auto-advance** (`src/stage.c:1363` records a trailing
  `EV_OVER` (type 2) at the stage's final frame; `src/replay/state.c:77`
  + `src/stage.c:609` — during play `EV_OVER` sets
  `global.gameover = GAMEOVER_DEFEAT`, stopping the stage loop; then
  `replay_do_post_play` → `replay_do_play` (`src/replay/play.c`) advances
  to the next stage and `stage_enter`s it — **no user input needed**; the
  final `EV_OVER` ends the replay and returns to the menu. The score
  screen of a WON stage is briefly visible (bonus at +60 frames,
  `GAMEOVER_SCORE_DELAY = 60`) before the trailing `EV_OVER` force-ends
  the stage as DEFEAT; the next stage's start sync overwrites all state,
  so this is invisible in the carried-over game.
- **Built-in desync verification** (`src/stage.c:965-988`
  `stage_replay_sync`): recorders write `EV_CHECK_DESYNC` (type 5) events
  at a fixed frequency carrying `(rng_u64() ^ plr.points) & 0xFFFF`;
  playback logs `replay desync detected!` on mismatch. So a stock
  playback that reaches the end **without desync warnings and without
  "Stageinfo is corrupt" errors** has reproduced the recorded game
  exactly (event stream + start states + seeds).

## Open risks

- **Stock v1.4.6 version support**: resolved 2026-09-25 — `taisei.exe
  --replay` accepted the 3-stage v14 merged file (no "Stageinfo is
  corrupt", no version error; log clean through `video_init`; see
  "Playback mechanism" above). The 1.5.0.0 game version in the header is
  informational (read.c only logs it). Full 3-stage desync-free playback
  is being confirmed by an unattended log run (run log 2026-09-25).
- If v1.4.6 rejects v14, fallback: transcode to v13 (TS104000_REV0: no
  skip_frames, no total/stage used-stat fields, 5-byte bug stat block of
  zeroes — write.c:80-84) — same merge structure, different stage size.
- The sim's `start_time` = rng_seed (not wall-clock) — irrelevant for
  determinism (REV2+ RNG uses rng_seed only) but means replay "date" shows
  garbage; cosmetic only.
