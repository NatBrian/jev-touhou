"""Jev showcase renderer (2026-09-29).

Replays a recorded campaign stage BIT-EXACTLY (trace macro sequence + the
same executor as the live run: VA4 gap-horizon + laser-blind-fix +
laser-ring, no-bomb) and renders a 1920x720 @ 60fps showcase video:

  LEFT  (640 px)  = field view: enemy bullets (colored by radius), lasers,
                    items, enemies, player, boss + HP bar, death/clear FX
  RIGHT (1280 px) = JEV DASHBOARD: engine header, live HUD (frame/score/
                    lives/deaths/bullets), the exact INPUT state text sent
                    to the model (reconstructed via compile_state and
                    VERIFIED against the trace's state_sha1), the OUTPUT
                    (6-way move probabilities, escape noul w/ 0.55
                    threshold, focus noul w/ 0.80, danger low/mid/high
                    gauge), and the HARNESS row (final macro, override
                    reason, target) + latency/token footer.

No model calls: everything comes from the recorded trace + the sim.

    venv\Scripts\python.exe tools\render_jev_showcase.py <tag> <stage> <engine> [diff] [--out PATH]

  engine: laya | mica   diff: easy|normal|hard|lunatic (default normal)
  out:    default videos/dashboard-<engine>-s<stage>-<diff>.mp4
          (dashboard = sim wireframe render on the left + decision
          dashboard on the right; the real-art finals are
          videos/jev-showcase-real-*.mp4 from the S5/S6 pipeline)

Exits non-zero if any reconstructed state text fails its state_sha1 check
or the replay death count differs from the trace.
"""
import hashlib
import json
import os
import subprocess
import sys
import textwrap
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_NORMAL, STATUS_RUNNING,
    PROJ_ENEMY, PROJ_PLAYER, PROJ_CLEARING,
)
from macros import resolve_macro_target  # noqa: E402
from executor import ReflexExecutor  # noqa: E402
from state_compiler import compile_state  # noqa: E402
from agent import Agent  # noqa: E402
from dump_probe_states import TraceMacro  # noqa: E402

DIFFS = {"easy": 1, "normal": DIFFICULTY_NORMAL, "hard": 3, "lunatic": 4}
DIFF_NAMES = {1: "Easy", 2: "Normal", 3: "Hard", 4: "Lunatic"}
LIB = os.path.join(SIM_ROOT, "build-gl33", "src", "sim", "libtaisei_sim.dll")

W, H = 1920, 720
FIELD_W = 640
# playfield 480x560 -> scale 1.25 = 600x700, centered in the field panel
S = 1.25
OX, OY = 20, 10
FPS = 60

ENGINE_INFO = {
    "laya": {
        "name": "LAYA",
        "model": "laya-rl-agent (convaiinnovations/laya)",
        "endpoint": "POST http://127.0.0.1:8002/predict",
    },
    "mica": {
        "name": "MICA",
        "model": "mica-v0.1-4b (sky7350/Mica-v0.1-4B)",
        "endpoint": "POST http://127.0.0.1:8010/v1/systemone",
    },
}

# colors
BG = (8, 10, 16)
FIELD_BORDER = (70, 80, 100)
PLAYABLE = (46, 52, 68)
BULLET_COLORS = ((245, 245, 250), (255, 120, 175), (255, 220, 110))  # small/mid/big
LASER_C = (235, 90, 225)
PLAYER_C = (120, 255, 150)
DEATH_C = (255, 70, 70)
BOSS_C = (150, 150, 170)
BOSS_HP = (255, 90, 90)
ITEM_C = (255, 190, 80)
LIFE_C = (90, 255, 120)
BOMB_C = (255, 90, 90)
PPLAYER_C = (130, 160, 240)
ENEMY_C = (140, 140, 150)

DASH_BG = (12, 14, 20)
PANEL = (20, 24, 34)
ACCENT = (0, 190, 230)
TEXT_C = (225, 232, 245)
DIM = (130, 140, 160)
GREEN = (110, 235, 150)
RED = (255, 90, 90)
YELLOW = (255, 215, 90)
CYAN = (0, 220, 255)
BAR_DIM = (90, 110, 140)


def load_fonts():
    d = r"C:\Windows\Fonts"
    def f(name, size):
        try:
            return ImageFont.truetype(os.path.join(d, name), size)
        except OSError:
            return ImageFont.load_default()
    return {
        "title": f("consolab.ttf", 20),
        "h2": f("consolab.ttf", 15),
        "mono": f("consola.ttf", 13),
        "mono_s": f("consola.ttf", 12),
        "mono_b": f("consolab.ttf", 13),
        "val": f("consolab.ttf", 16),
        "big": f("consolab.ttf", 28),
    }


def fx(p):
    return (OX + p[0] * S, OY + p[1] * S)


def bullet_color(r):
    if r < 5.5:
        return BULLET_COLORS[0]
    if r < 9.0:
        return BULLET_COLORS[1]
    return BULLET_COLORS[2]


class Renderer:
    def __init__(self, engine, stage, diff_name, fonts):
        self.engine = engine
        self.stage = stage
        self.diff_name = diff_name
        self.fonts = fonts
        self.info = ENGINE_INFO[engine]
        self.X0 = 656  # dashboard left margin
        self.X1 = 1904
        self.decision_flash_until = -1

    # ---- field (left) --------------------------------------------------------
    def render_field(self, v, lf, death_frames, prev_pos, out):
        d = ImageDraw.Draw(out)
        d.rectangle([0, 0, FIELD_W, H], fill=BG)
        # playfield + playable bounds
        x0, y0 = fx((0, 0))
        x1, y1 = fx((480, 560))
        d.rectangle([x0, y0, x1, y1], outline=FIELD_BORDER)
        px0, py0 = fx((16, 16))
        px1, py1 = fx((464, 544))
        d.rectangle([px0, py0, px1, py1], outline=PLAYABLE)

        # boss HP bar
        b = v.boss
        if b.active:
            frac = (b.hp / b.max_hp) if b.max_hp > 0 else 0.0
            d.rectangle([x0, y0, x0 + (x1 - x0) * frac, y0 + 6], fill=BOSS_HP)
            d.text((x1 - 130, y0 + 10), "BOSS", font=self.fonts["mono_s"], fill=BOSS_C)
            bx, by = fx((b.position.x, b.position.y))
            d.ellipse([bx - 24, by - 24, bx + 24, by + 24], fill=(60, 60, 75),
                      outline=BOSS_C, width=2)

        # enemies
        for e in v.enemies:
            ex, ey = fx((float(e.position.x), float(e.position.y)))
            d.rectangle([ex - 6, ey - 6, ex + 6, ey + 6], fill=ENEMY_C)

        # items
        for it in v.items:
            ix, iy = fx((float(it.position.x), float(it.position.y)))
            c = ITEM_C
            if it.item_type == 10:
                c = LIFE_C
            elif it.item_type == 9:
                c = BOMB_C
            d.rectangle([ix - 3, iy - 3, ix + 3, iy + 3], fill=c)

        # bullets
        for p in v.projectiles:
            if p.category == PROJ_ENEMY:
                r = max(float(p.collision_size.x), float(p.collision_size.y)) * S
                r = max(r, 2.6)
                bx, by = fx((float(p.position.x), float(p.position.y)))
                d.ellipse([bx - r, by - r, bx + r, by + r],
                          fill=bullet_color(r / S))
            elif p.category == PROJ_PLAYER:
                bx, by = fx((float(p.position.x), float(p.position.y)))
                d.ellipse([bx - 1.5, by - 1.5, bx + 1.5, by + 1.5], fill=PPLAYER_C)
            elif p.category == PROJ_CLEARING:
                bx, by = fx((float(p.position.x), float(p.position.y)))
                d.ellipse([bx - 2, by - 2, bx + 2, by + 2], fill=(110, 240, 140))

        # lasers (points with time <= 0 are drawn: tip == 0, body < 0)
        lps = v.laser_points
        for L in v.lasers:
            if not L.collision_active:
                continue
            i0, n = int(L.first_point), int(L.point_count)
            pts = []
            for i in range(i0, min(i0 + n, len(lps))):
                pt = lps[i]
                if pt.time <= 0:
                    pts.append(fx((float(pt.position.x), float(pt.position.y))))
            if len(pts) >= 2:
                w = max(2.0, float(L.width) * S)
                for a, bb in zip(pts, pts[1:]):
                    d.line([a, bb], fill=LASER_C, width=int(w))
            elif len(pts) == 1:
                d.ellipse([pts[0][0] - 3, pts[0][1] - 3,
                           pts[0][0] + 3, pts[0][1] + 3], fill=LASER_C)

        # player
        pl = v.raw.player
        px, py = float(pl.position.x), float(pl.position.y)
        if pl.alive:
            sx, sy = fx((px, py))
            if pl.invulnerable and (lf // 3) % 2 == 0:
                d.ellipse([sx - 11, sy - 11, sx + 11, sy + 11], outline=PLAYER_C)
            d.ellipse([sx - 7, sy - 7, sx + 7, sy + 7], fill=PLAYER_C,
                      outline=(240, 255, 245), width=1)
            if pl.focused:
                d.ellipse([sx - 10, sy - 10, sx + 10, sy + 10], outline=YELLOW)
        else:
            sx, sy = fx(prev_pos)
            d.line([sx - 12, sy - 12, sx + 12, sy + 12], fill=DEATH_C, width=4)
            d.line([sx - 12, sy + 12, sx + 12, sy - 12], fill=DEATH_C, width=4)

        # death flash
        for i, df in enumerate(death_frames):
            if df <= lf < df + 90:
                d.rectangle([x0, y0, x1, y1], outline=DEATH_C, width=4)
                msg = "DEATH %d" % (i + 1)
                tw = d.textlength(msg, font=self.fonts["big"])
                d.text(((FIELD_W - tw) / 2, 320), msg, font=self.fonts["big"],
                       fill=DEATH_C)

    # ---- dashboard (right) ---------------------------------------------------
    def build_panel(self, idx, row, text, sha_ok):
        f = self.fonts
        panel = Image.new("RGB", (W - FIELD_W, H), DASH_BG)
        d = ImageDraw.Draw(panel)
        X0, X1 = self.X0 - FIELD_W, self.X1 - FIELD_W

        # header
        d.text((X0, 10), "JEV DECISION DASHBOARD", font=f["title"], fill=TEXT_C)
        routing = row.get("routing") or "-"
        hdr = "%s  ·  %s  ·  %s%s" % (
            self.info["name"], self.info["model"], self.info["endpoint"],
            ("  ·  routed: " + routing) if self.engine == "laya" else "")
        d.text((X1 - d.textlength(hdr, font=f["mono_s"]), 16), hdr,
               font=f["mono_s"], fill=ACCENT)

        # HUD row placeholder (re-drawn live per frame)
        d.rectangle([X0 - 8, 42, X1 + 8, 70], fill=PANEL)

        # input
        tok = row.get("input_tokens")
        sha8 = (row.get("state_sha1") or "")[:8]
        mark = ("OK" if sha_ok else "MISMATCH")
        col = GREEN if sha_ok else RED
        d.text((X0, 84), "INPUT — exact state text sent to the model   "
               "(%s chars · %s tokens · sha1 %s %s)"
               % (row.get("state_chars"), tok, sha8, mark),
               font=f["mono"], fill=TEXT_C)
        lines = textwrap.wrap(text, 158) or [""]
        if len(lines) > 11:
            lines = lines[:11]
            lines[-1] = lines[-1][:-2] + " …"
        for i, ln in enumerate(lines):
            d.text((X0, 104 + i * 17), ln, font=f["mono"], fill=(190, 225, 235))

        # output title
        d.text((X0, 300), "OUTPUT — model answers at decision frame %d" % row["frame"],
               font=f["h2"], fill=YELLOW)

        # move bars
        probs = row.get("move_probs") or {}
        labels = ["guard", "hold", "sidestep_left", "sidestep_right",
                  "retreat", "item_sweep"]
        pick = row.get("raw_move")
        for i, lab in enumerate(labels):
            y = 328 + i * 30
            p = float(probs.get(lab, 0.0))
            d.text((X0 + 150, y + 4), lab, font=f["mono"], fill=TEXT_C,
                   anchor="rs")
            bw = int(900 * min(p, 1.0))
            chosen = lab == pick
            d.rectangle([X0 + 160, y, X0 + 160 + max(bw, 2), y + 20],
                        fill=CYAN if chosen else BAR_DIM)
            d.text((X0 + 168 + max(bw, 2), y + 3), "%.2f" % p,
                   font=f["mono_s"], fill=TEXT_C if chosen else DIM)
            if chosen:
                d.text((X1, y + 4), "◀ PICK (model)", font=f["mono_b"],
                       fill=CYAN, anchor="rs")

        # three metric columns
        cols = [
            ("ESCAPE (bomb_now repurposed · thr 0.55)",
             float(row.get("bomb_now") or 0.0), 0.55, row.get("evade_eff"),
             ("EVADE → " + str(row.get("evade_dir") or "")) if row.get("evade_eff") else ""),
            ("FOCUS (noul · thr 0.80)",
             float(row.get("focus") or 0.0), 0.80, row.get("focus_eff"),
             "FOCUS ON (half speed)" if row.get("focus_eff") else ""),
            ("DANGER (score 0-2)", None, None, None, ""),
        ]
        for ci, (title, val, thr, eff, badge) in enumerate(cols):
            cx = X0 + ci * 400
            d.text((cx, 520), title, font=f["mono_b"], fill=TEXT_C)
            if val is not None:
                d.text((cx, 540), "noul = %.3f" % val, font=f["val"],
                       fill=GREEN if (eff and thr == 0.55 and val >= thr) else TEXT_C)
                d.rectangle([cx, 566, cx + 360, 578], fill=PANEL)
                d.rectangle([cx, 566, cx + 360 * min(val, 1.0), 578], fill=CYAN)
                tx = cx + 360 * thr
                d.line([tx, 560, tx, 584], fill=YELLOW, width=2)
                d.text((tx, 586), "%.2f" % thr, font=f["mono_s"], fill=YELLOW,
                       anchor="ma")
                if badge:
                    d.rectangle([cx, 602, cx + 340, 620], fill=(30, 70, 45)
                                if thr == 0.55 else (80, 70, 30))
                    d.text((cx + 8, 604), badge, font=f["mono_b"], fill=GREEN)
            else:
                # danger gauge
                score = float(row.get("danger") or 0.0)
                d.text((cx, 540), "score = %.3f" % score, font=f["val"], fill=TEXT_C)
                full = min(2, int(score))
                frac = min(1.0, score - full)
                for k, lab in enumerate(("LOW", "MID", "HIGH")):
                    bx = cx + k * 120
                    d.rectangle([bx, 566, bx + 116, 590], outline=BAR_DIM)
                    if k < full:
                        d.rectangle([bx + 2, 568, bx + 114, 588], fill=CYAN)
                    elif k == full and frac > 0:
                        d.rectangle([bx + 2, 568, bx + 2 + 112 * frac, 588],
                                    fill=CYAN)
                    d.text((bx + 58, 569), lab, font=f["mono_s"],
                           fill=DASH_BG if (k < full or (k == full and frac > 0.5)) else TEXT_C)

        # harness row
        raw = row.get("raw_move")
        macro = row.get("macro")
        override = "  ·  HARNESS OVERRIDE" if (raw and raw != macro) else ""
        flags = []
        if row.get("evade_eff"):
            flags.append("evade_eff")
        if row.get("exile_eff"):
            flags.append("exile_eff(edge)")
        if row.get("focus_eff"):
            flags.append("focus")
        d.text((X0, 634),
               "HARNESS → macro: %s   ·   model raw: %s%s   ·   target: %s%s"
               % (macro, raw, " (remapped)" if row.get("move_remapped") else "",
                  row.get("target_kind") or "-",
                  ("   ·   " + " + ".join(flags)) if flags else ""),
               font=f["mono"], fill=(200, 210, 230))

        # footer
        d.text((X0, 664),
               "decision #%d   ·   server %s ms   ·   wall %0.1f ms   ·   in-tok %s   ·   "
               "adaptive cadence 30-300f (this: %sf — longer when safe)"
               % (idx, row.get("server_ms"), float(row.get("wall_ms") or 0.0),
                  row.get("input_tokens"), row.get("decide_every")),
               font=f["mono_s"], fill=DIM)
        d.text((X0, 684),
               "%s — %s — Jev-pattern typed decisions (no text generation)"
               % (self.info["name"], self.info["model"]),
               font=f["mono_s"], fill=DIM)
        legend = ("field: ● white r<6  ● pink r6-9  ● yellow r≥9  "
                  "■ laser  ● player  ○ boss")
        d.text((X1 - d.textlength(legend, font=f["mono_s"]), 684), legend,
               font=f["mono_s"], fill=DIM)
        return panel

    # ---- per-frame HUD strip ---------------------------------------------------
    def draw_hud(self, img, lf, v, bullets):
        d = ImageDraw.Draw(img)
        d.rectangle([self.X0 - 8, 42, self.X1 + 8, 70], fill=PANEL)
        pl = v.raw.player
        txt = ("stage %d %s · Marisa A · no-bomb     frame %d     score %s     "
               "lives %d     deaths %d     enemy bullets %d"
               % (self.stage, self.diff_name, lf,
                  "{:,}".format(int(v.raw.score)),
                  int(pl.lives) + 1, int(v.raw.deaths), bullets))
        d.text((self.X0, 48), txt, font=self.fonts["mono_b"], fill=TEXT_C)


def start_carry(tag, cp):
    """Reconstruct the START-of-stage carry from the checkpoint.

    The checkpoint's "carry" field holds the END-of-stage carry (for the
    NEXT stage); the start-of-stage state comes from "carried_from":
      None   -> fresh episode (no carry)
      int    -> previous stage number (load that checkpoint's "carry")
      string -> explicit --carry file path
    (S6 2026-09-30: the old `stage == 1` check replayed a fresh S2 with
    the end-of-S2 carry = wrong state.)
    """
    cf = cp.get("carried_from")
    if cf is None:
        return {}
    if isinstance(cf, int):
        prev = json.load(open(os.path.join(DATA, "checkpoints",
                                           "%s-stage%d.json" % (tag, cf)),
                              encoding="utf-8"))
        return dict(prev.get("carry") or {})
    with open(cf, encoding="utf-8") as f:
        d = json.load(f)
    return dict(d.get("carry") or (d if "initial_score" in d else {}))


def load_stage(tag, stage):
    """Trace rows (segment for `stage`), death-hit frames, checkpoint."""
    path = os.path.join(DATA, "laya-%s.jsonl" % tag)
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    segs, cur, prev = [], [], None
    for r in rows:
        f_ = r.get("frame")
        if prev is not None and isinstance(f_, int) and f_ < prev:
            segs.append(cur)
            cur = []
        cur.append(r)
        prev = f_
    if cur:
        segs.append(cur)
    seg = segs[0] if len(segs) == 1 else segs[stage - 1]
    decisions = [r for r in seg if r.get("status") == "ok"
                 and r.get("state_sha1")]
    decisions.sort(key=lambda r: r["frame"])
    death_hits = sorted(r["frame"] for r in seg
                        if r.get("status") == "death_hit")
    cp = json.load(open(os.path.join(DATA, "checkpoints",
                                     "%s-stage%d.json" % (tag, stage)),
                        encoding="utf-8"))
    return seg, decisions, death_hits, cp


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    tag, stage, engine = sys.argv[1], int(sys.argv[2]), sys.argv[3].lower()
    diff_name = "normal"
    args = sys.argv[4:]
    out_path = None
    i = 0
    while i < len(args):
        if args[i] == "--out":
            out_path = args[i + 1]
            i += 2
        else:
            diff_name = args[i]
            i += 1
    if engine not in ENGINE_INFO:
        sys.exit("engine must be laya|mica")
    diff = DIFFS.get(diff_name, DIFFICULTY_NORMAL)
    if out_path is None:
        out_path = os.path.join(HERE, "videos",
                                "dashboard-%s-s%d-%s.mp4"
                                % (engine, stage, diff_name))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    seg, decisions, death_hits, cp = load_stage(tag, stage)
    total_frames_cp = int(cp.get("frames") or 0)
    carry = start_carry(tag, cp)
    if cp.get("no_bomb"):
        carry.update(initial_bombs=0, initial_bomb_fragments=0)

    print("tag=%s stage=%d engine=%s diff=%s" % (tag, stage, engine, diff_name))
    print("  decisions=%d death_hits=%s cp_frames=%d carry=%s"
          % (len(decisions), death_hits, total_frames_cp, carry))

    fonts = load_fonts()
    rend = Renderer(engine, stage, DIFF_NAMES.get(diff, diff_name), fonts)

    register_runtime_dirs(
        os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
    for d in ("storage", "cache"):
        os.makedirs(os.path.join(DATA, d), exist_ok=True)
    sim = TaiseiSim(LIB)
    sim.global_init(
        resource_path=os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir"),
        storage_path=os.path.join(DATA, "storage"),
        cache_path=os.path.join(DATA, "cache"),
    )
    sim.create()
    sim.reset(EpisodeConfig(
        stage_id=stage, difficulty=diff, player_character=CHAR_MARISA,
        shot_mode=SHOT_A, rng_seed=12345 + stage, **carry,
    ))
    # EXACT live-campaign executor config for the showcase runs:
    # --no-bomb --gap-horizon --laser-blind-fix --laser-ring (build-gl33)
    ex = ReflexExecutor(allow_bombs=False, allow_edge_escape=False,
                        gap_horizon=True, laser_blind_fix=True,
                        laser_ring=True)
    ex.reset()

    cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
           "-pix_fmt", "yuv420p", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)

    t0 = time.time()
    rendered = 0
    di = 0
    cur_macro = None
    prev_macro_id, prev_focus = None, False
    sha_ok = 0
    sha_bad = []
    replay_deaths = 0
    prev_pos = (240.0, 590.0)
    prev_deaths = 0
    canvas = Image.new("RGB", (W, H), BG)
    panel_img = None
    end_status = None

    while rendered < 60000:
        v = sim.get_state()
        st = int(v.raw.episode_status)
        lf = int(v.raw.logical_frame)
        px, py = float(v.raw.player.position.x), float(v.raw.player.position.y)
        pl_alive = bool(v.raw.player.alive)
        dcount = int(v.raw.deaths)
        if dcount > prev_deaths:
            replay_deaths = dcount
            prev_deaths = dcount

        terminal = st != STATUS_RUNNING
        if not terminal:
            # advance decisions whose frame has arrived
            while di < len(decisions) and lf >= decisions[di]["frame"]:
                row = decisions[di]
                # agent._macro_context (agent.py:437): compile_state adds the
                # "Currently held macro: " prefix itself; the VALUE is the bare
                # macro_id (+ ", focus on"), or the degraded string when the
                # held macro is not Laya-sourced (the loop starts with a
                # fallback "hold" macro, so decision #1 gets that string).
                ctx = "none (degraded mode, no Laya macro)"
                if prev_macro_id is not None:
                    ctx = prev_macro_id
                    if prev_focus:
                        ctx += ", focus on"
                text = compile_state(v, macro_context=ctx)
                h = hashlib.sha1(text.encode("utf-8")).hexdigest()
                ok = h == row.get("state_sha1")
                sha_ok += ok
                if not ok:
                    sha_bad.append((row["frame"], h[:8],
                                    (row.get("state_sha1") or "")[:8]))
                prev_macro_id = row.get("macro")
                prev_focus = bool(row.get("focus_eff"))
                mid, foc = row.get("macro", "guard"), bool(row.get("focus_eff"))
                xeff = bool(row.get("exile_eff"))
                eeff = bool(row.get("evade_eff"))
                if xeff or eeff:
                    tgt = Agent._evade_target(None, v)[0]
                else:
                    tgt = resolve_macro_target(mid, v)
                cur_macro = TraceMacro(mid, foc, row["frame"], tgt)
                panel_img = rend.build_panel(di + 1, row, text, ok)
                rend.decision_flash_until = lf + 6
                di += 1
            if cur_macro is None:
                cur_macro = TraceMacro("guard", False, lf,
                                       resolve_macro_target("guard", v))

        # ---- render frame ----
        canvas = Image.new("RGB", (W, H), BG)
        rend.render_field(v, lf, death_hits, prev_pos, canvas)
        if panel_img is None:
            # pre-first-decision placeholder
            d0 = ImageDraw.Draw(canvas)
            d0.rectangle([FIELD_W, 0, W, H], fill=DASH_BG)
            d0.text((rend.X0, 300), "waiting for first decision…",
                    font=fonts["h2"], fill=DIM)
        else:
            canvas.paste(panel_img, (FIELD_W, 0))
        bullets = sum(1 for p in v.projectiles if p.category == PROJ_ENEMY)
        rend.draw_hud(canvas, lf, v, bullets)
        dd = ImageDraw.Draw(canvas)
        if lf <= rend.decision_flash_until and panel_img is not None:
            dd.rectangle([FIELD_W + 2, 2, W - 3, H - 3], outline=ACCENT, width=2)
        if terminal:
            if st == 2:  # STATUS_WON
                msg = "STAGE %d CLEAR   ·   score %s   ·   deaths %d" % (
                    stage, "{:,}".format(int(v.raw.score)), dcount)
                col = GREEN
            else:
                msg = "GAME OVER   ·   score %s   ·   deaths %d" % (
                    "{:,}".format(int(v.raw.score)), dcount)
                col = RED
            tw = dd.textlength(msg, font=fonts["big"])
            dd.rectangle([(W - tw - 40) // 2, 330, (W + tw + 40) // 2, 380],
                         fill=(0, 0, 0))
            dd.text(((W - tw) / 2, 338), msg, font=fonts["big"], fill=col)
        proc.stdin.write(canvas.tobytes())
        rendered += 1
        print("\r  frame %d / cp %d   (%.0f%%)   %.0f s" %
              (rendered, total_frames_cp,
               100.0 * rendered / max(total_frames_cp, 1),
               time.time() - t0), end="", flush=True)

        if terminal:
            end_status = st
            for _ in range(FPS * 2 - 1):  # hold the end card for 2 s
                proc.stdin.write(canvas.tobytes())
                rendered += 1
            break

        if pl_alive:
            prev_pos = (px, py)
        ex._view = v
        sim.step(buttons=ex.execute(cur_macro, v))

    print()
    proc.stdin.close()
    proc.wait()
    sim.destroy()
    sim.global_shutdown()

    size_mb = os.path.getsize(out_path) / 1e6
    trace_deaths = len(death_hits)
    print("== showcase render ==")
    print("  frames written: %d (checkpoint: %d, end=%s)"
          % (rendered, total_frames_cp,
             {2: "WON", 3: "LOST"}.get(end_status, end_status)))
    print("  state_sha1: %d/%d OK%s" % (
        sha_ok, len(decisions),
        "" if not sha_bad else "  BAD: %s" % sha_bad[:5]))
    print("  deaths: trace=%s replay=%d" % (death_hits, replay_deaths))
    print("  wall=%.1fs  out=%s (%.1f MB)" % (time.time() - t0, out_path, size_mb))
    # fidelity = every reconstructed state text matches its recorded sha1,
    # and the replay death count matches the trace
    ok = (not sha_bad) and (replay_deaths == trace_deaths)
    if not ok:
        print("  ** FIDELITY MISMATCH **")
        return 1
    print("  FIDELITY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
