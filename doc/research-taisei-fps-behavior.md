# Taisei (fork) fps behavior — VFR renderer, real-time logic, capture notes

Research 2026-09-30 (S6 showcase pair, both winners). Sources: S6 run log
(`logs/run-2026-09-30-beststage.md` §6-§9), ffprobe/ffmpeg frame-level
measurements on the gdigrab captures (`simdata/cache/game-capture-*.mp4`),
and `%APPDATA%\taisei\log.txt` (per-replay log,
0 desyncs, self-exit timestamps).

## 1. The renderer presents VFR; the logic runs real-time ~60 Hz

- The GL33 renderer's PRESENT rate is variable (VFR) and thermally
  dependent, NOT a fixed 60: observed **19.2 fps** (hot — after ~1 h of
  sustained CPU/sim work), **44.8 fps** (after cooldown) in two Mica Normal
  S2 captures, and **~46-55 fps** in the Laya Hard S1 capture (run log §7).
- The game LOGIC is decoupled from the renderer and keeps real-time pace:
  - Mica S2: 17,138 logic frames over ~287 s of wall time = **59.6-59.9 fps
    average** in BOTH captures (19.2-fps and 44.8-fps render).
  - Death-to-death pace (Mica S2): (9022-1176) / (155.80-24.77) s =
    **59.99 fps**.
  - Laya S1: 14,540 f / ~243 s = 60.0 fps (run log §7).
  - Proof of lock: **0 desyncs** — the per-frame digest check
    (`EV_CHECK_DESYNC`, trsr event type 5) matched the replay on every
    frame in every S6 capture (e.g. 17,138 checks in the Mica trsr).
- The logic pace is NOT constant: it wanders locally (~50-75 fps) with
  catch-up bursts. The Mica S2 anchor set implies 49.8 fps over t=280-285
  and ~70 fps over the final ~1.9 s, where the engine bursts to land
  EV_OVER exactly at the stage-end fade (WON f17078 @ 291.4, EV_OVER
  f17138 @ ~292.3 = 60 frames in 0.89 s). The anchor-based pipeline
  (`tools/resample_game_panel_v2.py`) exists precisely to absorb this.
- The **in-game fps counter is unreliable** in this fork (it read ~17
  during the 19.2-fps capture — a renderer-side indicator at best; the
  logic was at 60 Hz the whole time). All earlier "55 fps logic" estimates
  were cascading score misreads from non-passthrough decodes (below).

## 2. Why the capture fps varies (thermal)

- Sustained CPU work (campaign sim runs, dashboard renders) heats the
  laptop (i7-10610U); the integrated GPU (Intel UHD, OpenGL 4.6) then
  presents much slower (19.2 fps). After a cooldown the same replay
  presents at 44.8 fps.
- Practical rules (S6 capture workflow):
  1. Do NOT run CPU-heavy sim work in parallel with a game capture.
  2. Give the machine a cooldown between heavy sim batches and captures.
  3. Verify capture health before trusting it: distinct-frame count vs pts
     count, brightness histogram (all-black = display off, §4), 0 desyncs
     in the replay log, clean self-exit timestamp.
  4. Keep a low-fps capture as a fallback — it is still a COMPLETE,
     gate-ready capture, because the logic pace is renderer-independent
     (only the renderer frames get sparser).

## 3. ffmpeg: VFR captures must be decoded with `-fps_mode passthrough`

- The gdigrab captures are VFR. `ffprobe -show_entries frame=pts_time`
  gives the true distinct-frame count (Mica S2: 13,100 pts over 292.625 s;
  Laya S1: 12,682 over 247.4 s).
- Decoding WITHOUT passthrough (default vsync=auto) pads to a CFR stream —
  observed 14,048 frames (≈48 fps) for the Mica capture. Decode index then
  does NOT equal pts index, so time-targeted frame extraction is wrong and
  the offset grows with time (~0.5 s at t=15 -> ~20 s at t=292). The first
  Mica anchor extraction hit exactly this and was redone with passthrough.
- All S6 tooling decodes with `-fps_mode passthrough` so decoded frame i
  has pts[i]; `resample_game_panel_v2.py` then pairs output frame j to the
  distinct capture frame nearest the anchor time.

## 4. Display-on requirement (gdigrab + GL window)

- Battery display timeout on this machine is 180 s (`powercfg /query`
  VIDEOIDLE, DC). With the display off, gdigrab of a GL window captures
  BLACK (window not composited) even though the game runs perfectly (clean
  shutdown, 0 desyncs) — this wasted the first Laya capture (run log §6).
- Fix: `tools/keep_awake.ps1` holds `ES_DISPLAY_REQUIRED` (0x2) — prevents
  the display from turning off — plus `tools/wake_display.py` (SendInput
  synthetic mouse move) to WAKE an already-off display immediately before
  each capture. Verified: GDI screenshot 4.9 KB (black) -> 968.5 KB
  (content).

## 5. Stage-end sequence (WON), observed Mica S2 (44.8 capture)

- Final spell-card bonus screen ("Spell Card captured!", +331,656 count-up)
  appears while the boss is still attacking (gameplay continues under the
  overlay); count-up completes at 985,996 (f17003 plateau) ~290.4.
- Boss death (WON) at f17078 = EV_OVER - 60 (`GAMEOVER_SCORE_DELAY = 60`,
  `doc/research-trsr-replay-format.md`) @ 291.396.
- Stage-end fade at EV_OVER (f17138, ~292.3); the **+2,000,000 clear bonus
  is applied at EV_OVER and is NOT displayed** (last displayed score
  1,099,334 = terminal 3,099,334 - 2,000,000). The sim/score screen shows
  the terminal in one step; the game never does.
- The game self-exits ~0.5-1.2 s later; gdigrab returns black frames after
  the window is destroyed (last distinct frame t=292.542, brightness ~0).
- Composite implication: pin the clear anchor to the LAST BRIGHT gameplay
  frame (292.292 for Mica), and `resample_game_panel_v2.py` holds that
  distinct frame for output frames >= stage_len, so the end card shows real
  gameplay instead of the black post-destroy frames.
