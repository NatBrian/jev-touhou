# Research: Lives, Death Budget, and the Score Extra-Life (taisei-sim)

Date: 2026-09-25. Resolves the "where did the campaign-5 stage-3 life come from?" mystery
and establishes the complete life budget model for the 6-stage campaign.

## Question

Campaign 5 stage 3 (Laya run) gained a life mid-stage (lives 0→1 at f4467, no death, no life
fragments), then died twice and LOST. Source greps found no life-item spawn in stage 3. What
are ALL life sources, and what is the total death budget for a full campaign?

## 1. Lives semantics

- `PLR_START_LIVES = 2` (`src/player.h:46`) — `plr.lives` = reserve lives ("3 lives" in-game =
  lives field 2). Display = `lives + 1` (state compiler already does this).
- Game over: `player.c:604-607` — when `respawntime - PLR_RESPAWN_TIME/2 == frames &&
  plr.lives < 0` → `stage_gameover()`. In sim mode `stage_gameover()` immediately does
  `stage_finish(GAMEOVER_DEFEAT)` (`src/stage.c:375-378`) — **no continue menu in sim**.
  `PLR_RESPAWN_TIME = 60` (`player.h:57`) → game over fires 30 frames after the death that
  made lives < 0.
- **3 total deaths = defeat** (2 reserves + current life). Survivable deaths = 2 without
  gaining lives.
- Death handler `player_realdeath` (`player.c:882-907`): clears all hazards (killer bullet
  erased same frame), teleports player to (240, 590), `bombs = PLR_START_BOMBS (3)`,
  `bomb_fragments = 0`, `voltage *= 0.9`, `power *= 0.7`, `lives--`, `stats.lives_used++`
  (this is `state.deaths` in the sim, `sim.c:380`).
- **Extra-spell death is FREE** (`player.c:898-902`): if the stage is not a spell stage and
  the boss's current attack is `AT_ExtraSpell`, the death returns early — no life lost, no
  bomb reset, no power drop, no death counted. Only hazard clear + teleport. Dying inside an
  extra spell (e.g. Wriggle's "Light Singularity", stage 3) is a free respawn.
- Caps: `PLR_MAX_LIVES = 8`, `PLR_MAX_BOMBS = 8` (`player.h:34-35`);
  `PLR_MAX_LIFE_FRAGMENTS = 5` (5 frags = 1 life — NOT 8 as previously assumed);
  `PLR_MAX_BOMBS_FRAGMENTS = 500` (`player.h:43-44`).

## 2. All life sources (exhaustive)

Writes to `plr->lives` anywhere in `src/`: `player.c:43` (init=2), `player.c:610`
(continue=2), `player.c:906` (death--), `player.c:1472` (fragment system via
`player_add_fragments(&plr->lives,…)`), `replay/stage.c:54` (replay restore), `stage.c:197/200/212`
(practice/override). Fragment system is fed only by item pickup (`item.c:355-363`).

### (a) SCORE EXTRA LIFE — the big one

`player_add_points` (`src/player.c:1590-1599`):

```c
void player_add_points(Player *plr, uint points, cmplx location) {
    plr->points += points;
    while(plr->points >= plr->extralife_threshold) {
        plr->extralife_threshold = player_next_extralife_threshold(++plr->extralives_given);
        player_add_lives(plr, 1);
    }
    ...
}
```

Thresholds (`src/player.c:1692-1695`): `5,000,000 * (n²+n+2)/2` with n =
`extralives_given` (0 at init, pre-incremented on each grant) →
**5M, 10M, 20M, 35M, 55M, 80M, 110M, 145M, 185M, …** — gaps grow by 5M per step
(5, 10, 15, 20, 25, …). NOTE: this is NOT the classic 5/10/20/40/80 doubling table;
it grows slower past 20M.

**Sim-carryover behavior — CORRECTED 2026-09-26 (no re-grant):** in sim mode each
stage is a fresh episode. The actual sequence (verified in source + G2.92):

1. `player_init` (`sim.c:~1033`) is a FULL struct reset (designated initializer,
   `player.c:38-52`): `points=0`, `extralives_given=0` (both zeroed as unspecified
   fields), `lives=PLR_START_LIVES`, …
2. The carry override is applied afterwards (`sim.c:~1035-1075` builds
   `StageStartOverride`; `stage.c:218` `global.plr.points = start_override.score`) —
   a DIRECT assignment, not via `player_add_points`, so no grant at stage start.
3. `player_stage_post_init` (`player.c:~74-106`) ends with the catch-up:

   ```c
   plr->extralife_threshold = player_next_extralife_threshold(plr->extralives_given);
   while(plr->points >= plr->extralife_threshold) {
       plr->extralife_threshold = player_next_extralife_threshold(++plr->extralives_given);
   }
   ```

   This **fast-forwards the threshold past the carried score WITHOUT granting any
   life** (no `player_add_lives` in this loop — grants happen only in
   `player_add_points`). A carried score of 5.47M enters the stage with
   threshold = 10M, extralives_given = 1, and **no re-grant**: each threshold is
   granted at most ONCE, in the stage where the live score crosses it.

Empirical confirmation (2026-09-26, G2.92 `m3cam-0926-172908`): S3 carried
5,470,010 (5M crossed in S2) and started with 3 total lives; at S3 f5300
(score 5,932,862, deaths=0) the state shows "You have 3 life(s)" and the
extra-life hint "crosses 10,000,000 (4,067,138 points to go)" — exactly the
no-re-grant behavior. (The original version of this section claimed a
per-stage re-grant: a misread — the catch-up loop lives at the end of
`player_stage_post_init`, not `player_init`, and it never calls
`player_add_lives`.)

### (b) Full LIFE item — exactly one in the whole game

`src/stages/stage4/timeline.c:724` (stage-4 "elly scythe" mid-boss enemy):
`if(ARGS.fleetime >= 300) spawn_items(s->pos, ITEM_LIFE, 1);` — the scythe drops a full LIFE
at its own position if it survives ≥300 frames (5 s) of flight, then despawns.
`player_add_lives(1)` = +5 life frags = +1 life (`player.c:1499-1501`).
To get it: don't kill the scythe within 5 s (keep the player's x out of its column — Marisa A
fires straight up), then chase the item (items fly upward at 12–18 px/f and despawn off-screen).

### (c) Life fragments — dead code

`ITEM_LIFE_FRAGMENT` has a full pickup path (`item.c:361-362`) but **no spawn site anywhere**:
no `ITEMS(.life_fragment=…)` table, no `spawn_item(…, ITEM_LIFE_FRAGMENT)`. Never drops.

### (d) Continue — never in sim

`player.c:609-620` (`lives = PLR_START_LIVES` etc.) requires `EV_CONTINUE`, which only the
game-over menu sends (`stage.c:339-341`); sim skips the menu. Empirically confirmed: the
+1-life event in stage 3 had `continues_used = 0` in the final state.

## 3. Score sources (what to farm)

| Source | Where | Amount |
|---|---|---|
| PIV item | enemy kills / drops | point_item_value (scales with PIV level) |
| POINTS item | spell/boss end (×12) | point_item_value × pickup_value |
| POWER / POWER_MINI | drops, spell/boss end (×14) | 25 / 5 pts; **at max power POWER_MINI→PIV** (`item.c:269-279`) |
| SURGE | `player.c:1676` (powersurge), drops | 25 pts |
| VOLTAGE | bomb kills (`enemy.c:261`, hp/100) | 10 pts + voltage |
| Enemy kill | `enemy.c:155-162` | PIV per cleared bullet near corpse; per-enemy `ITEMS()` table via `enemy_drop_items` (`enemy_classes.c:43-51`, **only when killed by the player**) |
| Spell captured | `boss_give_spell_bonus` (`boss.c:968-996`, called at `boss.c:1057`) | clear + time + survival + endurance, × diff multiplier (0.6+0.2·diff) |
| Spell/boss end | `boss.c:1077-1081` | POWER×14 + POINTS×12 + BOMB_FRAGMENT×(captured?1:0) — **per spell end, not just boss death** |
| Stage clear | `stage_give_clear_bonus` (`stage.c:936-968`) | base = stage_id×1,000,000 + voltage bonus + lives×PIV×5 + graze + (all-clear bonus on last story stage) |

Measured campaign-5 scores (checkpoints `simdata/checkpoints/m3cam-0925-064908-*`):
stage 1 end **1,763,075** → stage 2 end **4,877,022** → stage 3 (LOST) **5,579,291**.
≈3M per stage → a full campaign ends around 15–18M.

## 4. Item mechanics (for the state compiler / Laya)

- Types (sim header `taisei_sim.h:104-114`): 1 PIV, 2 POINTS, 3 POWER_MINI, 4 POWER,
  5 SURGE, 6 VOLTAGE, 7 BOMB_FRAGMENT, 8 LIFE_FRAGMENT, 9 BOMB, 10 LIFE.
- Pickup: `process_items` (`item.c:259-370`). Grab radius `ITEM_GRAB_RADIUS`; soft-attract
  within `COLLECT_RADIUS` with value scaled `1 - playerY/VIEWPORT_H`; **items are auto
  collected at full value when the player is above the POC line OR when the stage is cleared**
  (`item.c:293-295`); items younger than 20 frames can't be collected (`item.c:285-287`);
  items fly upward (v ≈ −10..−20 px/f) and despawn off the top.
- Stage 4 note: `ITEMS(.bomb=1)` on the splasher fairy (`stage4/timeline.c:43`) drops a full
  BOMB item when player-killed.

## 5. Empirical verification (this work)

| Run | Seed | Lives trace | Score at end | Extra life? |
|---|---|---|---|---|
| Stage 3 standalone (pure guard) | 12348 | 2 → 1 (death f7212) → **2** (f17921) | 5,211,801 | **yes** (crossed 5M at stage-clear bonus; `continues_used=0`) |
| Stage 1 standalone (pure guard) | 12345 | 2 → 1 (death f11916) → 1 | 1,657,179 | no (<5M) |
| Campaign 5 stage 3 (Laya) | 12348 | 0 → **1** (f4467, "Deadly Dance" spell-capture bonus crossed 5M) → 0 (f7379) → −1 (LOST) | 5,579,291 | **yes** (mid-stage) |

Logs: `logs/diag-s3-items-v3.log`, `logs/diag-s1-items-v3.log`,
`simdata/laya-m3cam-0925-064908.jsonl`. Diagnostic tool: `tools/diag_item_spawns.py`.

The stage-1 vs stage-3 comparison was the clincher: identical clear-sequence behavior, only
the score differed — 5.21M triggers the extra life, 1.66M does not.

## 6. Campaign life budget (model) — CORRECTED 2026-09-26 (no re-grant, §2a)

- Base: **3 lives** (2 reserves).
- Score extra lives: +1 per threshold crossing, **granted exactly once, in the
  stage where the live score crosses the threshold** (no per-stage re-grant).
- Stage-4 scythe LIFE: **+1** if collected.
- No life fragments; no continues.

Projected for a full campaign at ~2.2–3M/stage (campaign-5 / G2.92 rate;
correct thresholds 5/10/20/35/55 M):

| Stage | start score | crossing during stage | extra lives in stage |
|---|---|---|---|
| 1 | 0 | — | 0 |
| 2 | ~2.2M | (5M — S2 end 4.9–5.5M; crossed in S2 or early S3) | 0–1 |
| 3 | ~4.9–5.5M | 5M (if not already) | 0–1 |
| 4 | ~8.5–9M | — (10M not reached) | 0 |
| 5 | ~11–12M | 10M | 1 |
| 6 | ~14M | — (20M not reached) | 0 |

Score extra lives total = **2** (5M + 10M); with scythe +1 → **≈6 total death
budget**, vs agent rate ≈1 death/stage (6 total) — TIGHT, not comfortable.
With the measured per-stage norms (S1 {0,1,2}, S2 {0,1,3}, S3 3 — G2.x runs),
the binding constraints are: (1) S1+S2 must not stack >1 death before the 5M
crossing lands (base budget is only 3); (2) a stage with a 3-death norm needs
4 total lives at its start — for S3 that means d1=0 AND d2=0 (T3 = 3−0−0+1 = 4);
(3) after a 3-death stage the next stage starts on 1 life (d must be 0 unless
the scythe LIFE was collected in S4); (4) the 10M crossing (S5) is the only
late-stage cushion.

## 7. Strategy implications

1. **Score = lives.** State compiler should report score + next extra-life threshold +
   distance-to-it; prompt should teach Laya: crossing 5M (then 10M, 20M…) grants an extra
   life; PIV/points collection is survival insurance.
2. **Extra-spell deaths are free** — safe zone for risky play (Wriggle stage 3, Kurumi stage 4, …).
3. **Stage 4 scythe**: let it survive 5 s (offset x), then sweep for the LIFE.
4. Bomb economy: death resets bombs to 3 (inflation-free); bomb fragments cap 500 → full BOMB.
5. Death context logging (prev_v) remains the right tool for cutting the ~1 death/stage rate.

## Sources

- `third_party/taisei-sim` HEAD 6e6f8e3e (built 2026-09-25, only local mods = meson + BGM
  init removal for headless; verified via `git status --porcelain` / `git diff`):
  `src/player.c:43,55-63,100-104,604-620,882-907,1440-1505,1590-1610,1692-1695`,
  `src/player.h:34-57`, `src/stage.c:197-218,339-341,375-378,936-968,1055-1091`,
  `src/boss.c:968-996,1045-1091`, `src/item.c:259-370`, `src/item.h:17-53`,
  `src/enemy.c:155-162,255-265`, `src/enemy_classes.c:43-51`, `src/common_tasks.c:17-25`,
  `src/stages/stage4/timeline.c:43,700-724`, `src/stages/stage3/timeline.c:557-596,801,837`,
  `src/sim/sim.c:380,392,1031,1035-1069,1084,730-746`, `src/replay/stage.c:9-55`.
- Empirical: `logs/diag-s3-items-v3.log`, `logs/diag-s1-items-v3.log`,
  `simdata/laya-m3cam-0925-064908.jsonl` (campaign 5),
  `simdata/checkpoints/m3cam-0925-064908-stage{1,2,3}.json`.
