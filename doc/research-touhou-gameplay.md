# Research: Touhou/Taisei gameplay — what "play like a human" requires

Date: 2026-09-24 · Sources: Taisei game manual (fetched: https://github.com/taisei-project/taisei/blob/master/doc/GAME.rst),
Touhou Wiki gameplay pages, Wikipedia "Touhou Project", r/touhou threads, taisei-sim C API (see research-taisei-sim).

Goal: define (a) the rules of the game we must win, (b) the behaviors of a *normal human player*, so the Laya
strategist + code reflex layer can be tuned to look and play like one.

## 1. The rules (Taisei)

### Win / lose conditions
- **Win**: clear **Stage 6** ("Roof of the World") at the chosen difficulty → ending (sim: `episode_status = WON`).
  Extra stage (7) is bonus content. Each stage ends in a boss fight; stages also have midbosses.
- **Lose**: all lives spent → Game Over (sim: `LOST`). Continues exist (scoreless); the sim counts
  `continues_used` — **avoid continues for a "clean" human-like clear**.
- Difficulty ladder: Easy → Normal → Hard → **Lunatic**. Completion target = **Lunatic, stages 1–6, no
  continues, minimal cheats** (sim episode config `difficulty=4`).

### Player resources & mechanics
- **Lives** (default 3) and **bombs** (default 3; +1 bomb per 500 bomb fragments). Getting hit costs a life
  (respawn with brief invulnerability). **Death bombing**: press bomb at the moment of impact to skip the death.
- **Hitbox**: very small (a few px) vs the large sprite; visible as a white circle only in **focus** mode.
  Focus = slower movement + tighter/stronger shot — the core of precise dodging.
- **Power**: shot strength 0→4 (max normal), can overcollect to 6. Power gates damage output → needed to
  capture spellcards in reasonable time.
- **Power Surge** (Taisei-specific, C key): needs 2.00 power; collects all items on screen, +20% damage,
  graze spawns lightning charge items; maintain balanced positive/negative charges to extend; **discharge**
  cancels bullets in a radius (no spell fail!), damages enemies, spawns **voltage** (huge PIV boost).
  Auto-activates at 6.00 power. Voltage unlocks per-stage **Voltage Overdrive** spells (invincible but bombless).
- **Graze**: passing close to bullets (grazeable projectiles) raises the graze counter → score bonus, and at
  high power graze spawns power/PIV items.
- **Items** (dropped by enemies/bombs/graze): blue **points**, red **power** (P, mini/full), green star **bomb**
  (full / 500-fragment outline), pink heart **life**, yellow ghost **PIV**, surge lightning, **voltage**.
- **PIV (Point Item Value)**: value multiplier for point items; grown by PIV ghosts, high-power grazing, and
  surges. **Score → bonus lives** (extra lives at score thresholds) — good scoring keeps you alive.
- **Autocollection**: moving near the **top of the screen**, bomb, or surge collects all visible items
  (counted at top value).
- **Boss attacks** (types visible in sim as `boss.phase_type`): **Normal** (signature breakers), **Spell Card**
  (timer-bounded; background changes), **Survival Spell** (boss invincible; survive the timer), **Voltage
  Overdrive** (secret). **Spell capture** = reduce spell HP to 0 within the timer **without getting hit and
  without bombing** → 100 bomb fragments + big bonus; bombing or dying during it forfeits the bonus.
- Scoring: stage-clear + spell-capture bonuses dominate; PIV scales them. For *clearing* the game, score mainly
  matters as a life insurance valve.

### Stage flow
Story stage: ~1–2 min of enemy waves + midboss → boss fight (several normal + spellcard phases, ~1–3 min) →
stage clear → next. Full game ≈ 20–30 min of play at 1× speed.

## 2. How humans play (behavior model for the agent)

Synthesized from Touhou wiki gameplay pages (EoSD/Gameplay, Subterranean Animism/Gameplay, Legacy of Lunatic
Kingdom/Gameplay), Wikipedia (Touhou Project), r/touhou discussions, and standard danmaku technique knowledge:

1. **Movement is continuous and purposeful** — 8-directional at 60 fps; humans don't teleport, they *drift*.
   Typical pattern: hold a safe position, make small corrective moves, occasionally a deliberate repositioning
   sprint. Never stand still for long, never pace the full screen without reason.
2. **Read the pattern, not the bullets** — skilled play is pattern recognition + memory: the player knows which
   bullets will arrive where in ~0.3–1 s and routes the tiny hitbox through **safe space** (gaps, thin lanes,
   behind other bullets, screen edges). Bullets have predictable velocities → **forward projection** is how both
   humans and our reflex layer avoid hits.
3. **Keep options open** — don't corner yourself; keep the center/edges reachable; back off when a pattern
   converges; use focus for the tight part of a dodge, then release it.
4. **Distance management vs bullets** — most danmaku kills come from walls/rings converging on you; humans keep
   their distance from emitters (boss face) and let walls pass, diving in only to collect or shoot.
5. **Bombs are an escape valve, not a crutch** — used when actually overwhelmed or to death-bomb; a human
   conserves bombs and doesn't spam them. (Sim exposes `bombs` and `bomb_active` — policy: bomb when
   threat > survivability AND (spell isn't worth failing OR death is imminent).)
6. **Focus + power for offense** — hold focus while shooting boss/spell HP for capture; switch to unfocused
   movement for dodges. Capture requires enough power to beat the spell timer.
7. **Item economy** — humans weave routes to pick up power (damage), PIV (score), and bombs/lives; use
   top-of-screen autocollection deliberately. Power is the binding constraint for Lunatic spell capture.
8. **Risk tolerance & imperfection** — humans occasionally take a hit, graze-heavy at the margins, make
   suboptimal reads on new patterns (first encounter of each spellcard is hardest). A "normal human" agent
   should *mostly* play clean but allow occasional deaths, especially in early stages, rather than being
   robotically perfect from frame 1. (We can dial this via the Laya strategist's risk appetite; sim
   `deaths` counter is the metric.)
9. **Cognitive rate**: humans make *tactical* decisions at ~1–4 Hz (which side to thread, when to bomb, when to
   focus, which item lane) while motor control runs continuously. → Exactly the 3 Hz strategist + 60 Hz reflex
   split in PLAN.md.
10. **Memory**: humans remember what they've seen (spell patterns repeat across retries). Our agent gets this
    for free by keeping a per-spell history in the state text (attempt count, previous death cause) — cheap and
    human-like.

## 3. What the state text should convey (bridge to Laya questions)

From the sim state (research-taisei-sim §2), the code layer compiles a ≤ ~300-token digest, e.g.:
- `stage 3/6, frame 4210, boss fight, spell "…" phase: 42% hp, 18s left, spell_fail_risk high`
- `player: pos (240,300) v(0,-2), lives 2, bombs 3, power 3.2, graze 145, invuln no`
- `threats: 210 enemy bullets; dense wall ahead 120px, gap: upper-left 40x50px @ (150,180), ring closing 0.4s;`
  `nearest bullets: b1 (Δx=-12,Δy=-40,vx=0.3,vy=1.8,r=4) …` (top N by predicted proximity)
- `items: 1x power @(300,220), 1x bomb @(120,400), attracted none`
- `history: attempt 2; last death: stage 3 spell 2 (hit, 0 bombs left in spell)`
- `last_macro: drift_to_gap(upper-left), 1.2s ago`

All geometry (distances, gaps, predicted collisions) **precomputed in code** — Laya never does arithmetic
(Jev-pattern math weakness; Laya inherits the same RLCD profile).

## 4. Candidate macro action space (Laya `choice`)

Small, human-meaningful, code-executable (reflex layer turns each into 60 Hz inputs):
- `hold_safe` — maintain current safe position, keep shooting
- `drift_to_gap` (direction variants, or a single option with the gap embedded in state)
- `retreat_bottom` / `retreat_edge`
- `orbit_boss` — circle at mid range (safe offense)
- `rush_boss` — close in for max DPS (risky)
- `item_sweep` — detour to item lane / top autocollect
- `focus_bomb_setup` — focus + hold for spell capture
- `wait` — pause for pattern shift (rare)

Plus per-cycle companions: `noul bomb_now`, `noul focus_now` (or a 3-way choice
`unfocused/focus/full-focus`), `score danger` (safe/moderate/severe), `noul collect_items_priority`.
All in **one /predict call** (one forward pass, ~40 ms server-side).

## 5. Success metrics (per run log)

- Stage reached, `episode_status`, `deaths`, `bombs_used`, `continues_used`, score, graze, spellcards captured.
- Laya stats: calls, mean/median wall latency, `routing.model`, `usage.input_tokens`, `_server_ms`,
  confidence distribution per question, fallback-trigger count.
- Human-likeness: replay playback review (no wall-skim spam, natural macro durations, occasional imperfection).

## 6. Sources
- Taisei Game Manual: https://github.com/taisei-project/taisei/blob/master/doc/GAME.rst (fetched 2026-09-24 —
  mechanics, HUD, controls, items, bosses, scoring, power surge)
- Taisei site: https://taisei-project.org/ (+ /news — 1.4.x rewrite history)
- Taisei stage data: `src/stageinfo.c`, `src/plrmodes.c` (fetched 2026-09-24)
- Touhou Wiki gameplay pages (via hound search 2026-09-24):
  - https://en.touhouwiki.net/wiki/Subterranean_Animism/Gameplay (graze mechanics)
  - https://en.touhouwiki.net/wiki/Legacy_of_Lunatic_Kingdom/Gameplay (graze items)
  - https://touhou.fandom.com/wiki/Embodiment_of_Scarlet_Devil/Gameplay (grazing, power, spellcards)
  - https://touhou.fandom.com/wiki/Subterranean_Animism:_Strategy (strategy: bomb + lock focus tactics)
- https://en.wikipedia.org/wiki/Touhou_Project (power scaling, extra lives, general series mechanics)
- https://www.reddit.com/r/touhou/comments/1d4v6eo/ (hitbox/focus explanation for newcomers)
