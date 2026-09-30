"""Unit checks proving the explicit no-bomb mode rejects bomb input."""

import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))

from executor import ACTION_BOMB, ACTION_SHOT, ReflexExecutor  # noqa: E402
from agent import Agent, Macro, NO_BOMB_QUESTIONS, QUESTIONS  # noqa: E402
from macros import MacroTarget, GUARD_Y  # noqa: E402


class Macro:
    def __init__(self, bomb=False):
        self.macro_id = "guard"
        self.bomb = bomb
        self.focus = False
        self.source = "laya"
        self.issued_frame = 0
        self.target = MacroTarget(kind="hold")


def view(alive=True, death_timer=-1, bombs=3):
    player = SimpleNamespace(
        alive=alive, death_timer=death_timer, bombs=bombs, bomb_active=False,
        invulnerable=False, position=SimpleNamespace(x=240.0, y=470.0),
        velocity=SimpleNamespace(x=0.0, y=0.0), input_flags=0,
        lives=2, life_fragments=0, bomb_fragments=0, effective_power=300,
    )
    boss = SimpleNamespace(
        active=False, invulnerable=False, position=SimpleNamespace(x=240.0, y=100.0),
        velocity=SimpleNamespace(x=0.0, y=0.0),
        hp=1.0, max_hp=1.0, phase_type=0, spell_active=False,
        remaining_timeout_frames=0, recent_damage=0.0,
    )
    raw = SimpleNamespace(player=player, boss=boss, logical_frame=0,
                          stage_id=1, difficulty=2, score=1000, deaths=0)
    return SimpleNamespace(raw=raw, player=player, boss=boss,
                           projectiles=[], enemies=[], lasers=[],
                           laser_points=[], items=[])


class FakeLaya:
    """Canned Laya responses for _ask_laya wiring tests."""
    def __init__(self, answers):
        self.answers = answers

    def predict(self, text, questions):
        return {"answers": self.answers}


def main():
    ex = ReflexExecutor(allow_bombs=False, allow_edge_escape=True)

    # Laya's macro explicitly requests a bomb while alive.
    buttons = ex.execute(Macro(bomb=True), view())
    assert buttons & ACTION_SHOT
    assert not (buttons & ACTION_BOMB), "no-bomb mode emitted macro bomb"

    # A hit-time death-bomb opportunity must also be rejected.
    buttons = ex.execute(Macro(bomb=False), view(alive=False, death_timer=11))
    assert buttons == ACTION_SHOT, "no-bomb mode emitted death-bomb input"
    assert ex.last_costs is None

    # R4.5 (2026-09-26): threat-gated wall penalty. No positional penalty
    # (the edge row is a survival resource: in a full-screen rain the
    # bottom row is gap-trackable and the safe position); the +1000 step
    # fires only while pinned-in-danger: in the 40 px wall band AND a
    # hazard reaches the player within EDGE_GATE_TTH frames AND the
    # cheapest base heading is toward the wall. Pure lateral headings are
    # always free (the gap-track escape).
    tw = ex._toward_wall
    assert tw(240.0, 544.0, 0.0, 0.0) is True       # hold at the wall
    assert tw(240.0, 544.0, 0.0, 1.0) is True       # down into the wall
    assert tw(240.0, 544.0, -1.0, 0.0) is False     # pure lateral is free
    assert tw(240.0, 544.0, 0.0, -1.0) is False     # up is free
    assert tw(240.0, 544.0, -0.7071, 0.7071) is True
    assert tw(240.0, 544.0, -0.7071, -0.7071) is False
    assert tw(464.0, 280.0, 1.0, 0.0) is True       # right wall
    assert tw(16.0, 280.0, -1.0, 0.0) is True       # left wall
    assert tw(240.0, 16.0, 0.0, -1.0) is True       # top wall
    assert tw(240.0, 280.0, 1.0, 1.0) is False      # open field
    # tth window: approaching hazard within 12 frames -> threat
    hz_rising = [(240.0, 560.0, 0.0, -8.0, 4.0, 1.0)]     # tth = 1
    hz_slow = [(240.0, 576.0, 0.0, -1.0, 4.0, 1.0)]       # tth = 24
    hz_static_near = [(240.0, 549.0, 0.0, 0.0, 4.0, 1.0)]  # overlapping now
    hz_static_far = [(240.0, 560.0, 0.0, 0.0, 4.0, 1.0)]   # 16 px, never closes
    assert ex._escape_threat(240.0, 544.0, hz_rising, []) is True
    assert ex._escape_threat(240.0, 544.0, hz_slow, []) is False
    assert ex._escape_threat(240.0, 544.0, hz_static_near, []) is True
    assert ex._escape_threat(240.0, 544.0, hz_static_far, []) is False
    assert ex._escape_threat(240.0, 544.0, [], []) is False
    # a drawn beam overlapping the player is a threat
    beam = [(200.0, 544.0, 4.0, 280.0, 544.0, 4.0, 1.0)]
    assert ex._escape_threat(240.0, 544.0, [], beam) is True
    # the gate: band + threat + base-argmin-toward-wall
    base_hold = [1.0] * 9; base_hold[0] = 0.5      # hold is cheapest
    base_left = [1.0] * 9; base_left[3] = 0.5      # lateral is cheapest
    assert ex._pinned_gate(240.0, 544.0, hz_rising, [], base_hold) is True
    assert ex._pinned_gate(240.0, 544.0, hz_rising, [], base_left) is False
    assert ex._pinned_gate(240.0, 470.0, hz_rising, [], base_hold) is False
    assert ex._pinned_gate(240.0, 544.0, [], [], base_hold) is False
    # end-to-end: with the gate on, +1000 lands exactly on the strict
    # toward-wall headings (hold/down/DL/DR at the bottom); up, the pure
    # laterals, and UL/UR stay free.
    v2 = view()
    v2.raw.player.position.x = 240.0
    v2.raw.player.position.y = 544.0
    v2.projectiles = []
    ex_plain = ReflexExecutor(allow_bombs=False, allow_edge_escape=True)
    ex_plain.execute(Macro(), v2)
    ex_gated = ReflexExecutor(allow_bombs=False, allow_edge_escape=True)
    ex_gated._pinned_gate = lambda *a: True        # force the gate
    ex_gated.execute(Macro(), v2)
    d = [ex_gated.last_costs[i] - ex_plain.last_costs[i] for i in range(9)]
    # MOVES: 0 hold 1 up 2 down 3 left 4 right 5 UL 6 UR 7 DL 8 DR
    assert d[0] == 1000.0 and d[2] == 1000.0
    assert d[3] == 0.0 and d[4] == 0.0 and d[5] == 0.0 and d[6] == 0.0
    assert d[7] == 1000.0 and d[8] == 1000.0
    # bomb-enabled and default executors never pay the penalty
    ex_bombs = ReflexExecutor(allow_bombs=True, allow_edge_escape=True)
    ex_bombs._pinned_gate = lambda *a: True
    ex_bombs.execute(Macro(), v2)
    assert ex_bombs.last_costs[0] == ex_plain.last_costs[0]
    ex_def = ReflexExecutor()
    ex_def._pinned_gate = lambda *a: True
    ex_def.execute(Macro(), v2)
    assert ex_def.last_costs[0] == ex_plain.last_costs[0]

    # A bomb-requesting macro is not advertised as armed in no-bomb context.
    no_bomb_agent = Agent.__new__(Agent)
    no_bomb_agent.allow_bombs = False
    no_bomb_agent.allow_focus = True
    no_bomb_agent.allow_edge_escape = True
    no_bomb_agent.questions = NO_BOMB_QUESTIONS
    assert no_bomb_agent._macro_context(Macro(bomb=True)) == "guard"
    move_i = no_bomb_agent.questions["move"]["instructions"]
    assert "sidestep_left" in move_i
    # R2/R4 (2026-09-26): the no-bomb prompt must reference the
    # action-oriented dodge line (position / time-to-hit / pressure / edges).
    assert "how many frames until the nearest bullet hits you" in move_i
    assert "your exact position" in move_i
    assert "the bullet pressure in each direction" in move_i
    assert "lower pressure" in move_i
    assert "at least about 40 frames" in move_i
    # R4: the no-bomb move vocabulary drops the bomb/spell choices.
    move_c = no_bomb_agent.questions["move"]["criteria"]
    assert "bomb_setup" not in move_c and "clear_spell" not in move_c
    for mid in ("guard", "hold", "retreat", "sidestep_left",
                "sidestep_right", "item_sweep"):
        assert mid in move_c, mid
    assert "A separate question asks whether you must escape right now" in move_i
    # R4.1: the in-batch bomb_now question carries the numeric escape
    # criteria; the new-name evade questions are not part of the set.
    bn = no_bomb_agent.questions["bomb_now"]
    assert bn["type"] == "noul"
    assert "fewer than about 30 frames" in bn["instructions"]
    assert "40 px" in bn["instructions"]
    assert "8 or more" in bn["instructions"]
    assert "evade" not in no_bomb_agent.questions
    assert "evade_dir" not in no_bomb_agent.questions
    danger_i = no_bomb_agent.questions["danger"]["instructions"]
    assert "under about 20 frames" in danger_i
    assert "20 frames" in no_bomb_agent.questions["danger"]["criteria"][2]
    # the normal (bomb-allowed) prompt must stay untouched
    assert "useless and harmful" in QUESTIONS["move"]["instructions"]
    assert QUESTIONS["move"]["instructions"] != move_i

    # R4.1/R4.2 wiring: the repurposed bomb_now answer (model evade) OR the
    # harness edge exile overrides the move answer in no-bomb mode; the
    # target is resolved from the state (away from the pinned edge).
    from taisei_sim import PROJ_ENEMY  # noqa: E402

    def haz_bullet(x, y, vx=0.0, vy=0.0):
        return SimpleNamespace(
            category=PROJ_ENEMY, flags=16,
            position=SimpleNamespace(x=x, y=y),
            velocity=SimpleNamespace(x=vx, y=vy),
            collision_size=SimpleNamespace(x=4.0, y=4.0),
        )

    def ask(bomb_now_noul, move_choice, x=240.0, y=470.0, bullets=()):
        answers = {
            "move": {"choice": move_choice, "probabilities": {}},
            "focus": {"noul": 0.2},
            "bomb_now": {"noul": bomb_now_noul},
            "danger": {"score": 1.5},
        }
        a = Agent.__new__(Agent)
        a.allow_bombs = False
        a.allow_focus = True
        a.questions = NO_BOMB_QUESTIONS
        a.laya = FakeLaya(answers)
        v = view()
        v.raw.player.position.x = x
        v.raw.player.position.y = y
        v.projectiles = list(bullets)
        m, status, _resp = a._ask_laya(v, 0)
        assert status == "ok"
        return m

    # at the 0.55 threshold, mid-screen, no pressure: full tie -> left
    m = ask(0.55, "guard")
    assert m.macro_id == "sidestep_left" and m.evade_eff is True
    assert m.target.kind == "point"
    assert m.target.point == (120.0, 470.0)
    assert m.evade_raw == 0.55
    # left-side pressure -> sidestep right (120 px, keep height)
    m = ask(0.6, "guard", bullets=[haz_bullet(150.0, 470.0)])
    assert m.macro_id == "sidestep_right"
    assert m.target.point == (360.0, 470.0)
    # right-side pressure -> sidestep left
    m = ask(0.6, "guard", bullets=[haz_bullet(330.0, 470.0)])
    assert m.macro_id == "sidestep_left"
    assert m.target.point == (120.0, 470.0)
    # R4.4: near a wall the sidestep target is capped to stay >= 96 px from
    # it (the 120 px offset is relative to the current position and is
    # re-issued every decision; uncapped, a sidestep chain walked the
    # player to the 8 px clamp at the wall and into the corner — G2.75
    # m3cam-0926-144755 S2 deaths at (53,500)/(428,502)).
    m = ask(0.6, "guard", x=100.0, y=470.0)
    assert m.macro_id == "sidestep_left"
    assert m.target.point == (112.0, 470.0)   # PX_MIN + 96, not -20 clamped
    m = ask(0.6, "guard", x=380.0, y=470.0,
            bullets=[haz_bullet(310.0, 470.0)])
    assert m.macro_id == "sidestep_right"
    assert m.target.point == (368.0, 470.0)   # PX_MAX - 96, not 500
    # R4.2: pinned at the bottom edge -> return to the guard anchor
    # (re-centers + 74 px up; a 50 px-up point target that keeps the x was
    # worse — G2 m3cam-0926-121236, deaths in the player's own x column).
    m = ask(0.6, "guard", x=350.0, y=540.0,
            bullets=[haz_bullet(300.0, 540.0), haz_bullet(400.0, 540.0)])
    assert m.macro_id == "exile_bottom"
    assert m.target.kind == "below_boss"
    # top edge -> guard anchor too
    m = ask(0.6, "guard", x=240.0, y=20.0)
    assert m.macro_id == "exile_top"
    assert m.target.kind == "below_boss"
    # left edge -> right, keep height (R4.2 bug fix: no longer
    # "sidestep_left" into the wall just because left pressure is 0 past
    # the wall)
    m = ask(0.6, "guard", x=20.0, y=300.0,
            bullets=[haz_bullet(150.0, 300.0)])
    assert m.macro_id == "exile_left"
    assert m.target.point == (70.0, 300.0)
    # right edge -> left
    m = ask(0.6, "guard", x=460.0, y=300.0)
    assert m.macro_id == "exile_right"
    assert m.target.point == (410.0, 300.0)
    # corner -> away from BOTH edges (right + up to guard height)
    m = ask(0.6, "guard", x=20.0, y=540.0)
    assert m.macro_id == "exile_bottom_left"
    assert m.target.point == (70.0, GUARD_Y)
    # R4.2 trigger: low model answer, but edge + imminent hit -> exile fires
    m = ask(0.3, "guard", x=240.0, y=540.0,
            bullets=[haz_bullet(240.0, 440.0, vx=0.0, vy=10.0)])
    assert m.macro_id == "exile_bottom" and m.exile_eff is True
    assert m.evade_eff is False
    # no threat (stationary bullet far away) -> no exile, move answer stands
    m = ask(0.3, "guard", x=240.0, y=540.0,
            bullets=[haz_bullet(240.0, 440.0)])
    assert m.macro_id == "guard" and m.exile_eff is False
    # threat but mid-screen (not in the edge band) -> no exile
    m = ask(0.3, "guard", x=240.0, y=470.0,
            bullets=[haz_bullet(240.0, 370.0, vx=0.0, vy=10.0)])
    assert m.macro_id == "guard" and m.exile_eff is False
    # below the threshold, open field: the move answer stands
    m = ask(0.54, "guard")
    assert m.macro_id == "guard" and m.evade_eff is False
    assert m.evade_dir == ""

    # R4.7 (2026-09-26): adaptive gap horizon (opt-in). A dense wall of
    # 16 bullets crosses the player's hold position exactly at t=36 (the
    # snapshot is covered, cost >= GAP_HORIZON_SNAP_AT), while the window
    # t=8..48 contains clear snapshots: gap_horizon=True must see the
    # passing gap (cheaper hold cost). With a SPARSE wall (snapshot below
    # the threshold) the gap search must not fire — identical costs.
    # (Population-level check: tools/probe_evader.py, 2026-09-26 — VA4
    # kept G1.5 S1 at 0 deaths and cut G2 S2 from 3 -> 0.)
    v_gap = view()
    v_gap.raw.player.position.x = 240.0
    v_gap.raw.player.position.y = 300.0
    v_gap.projectiles = [haz_bullet(168.0, 300.0 + i, vx=2.0)
                         for i in range(16)]
    ex_def2 = ReflexExecutor(allow_bombs=False)
    ex_def2.execute(Macro(), v_gap)
    ex_gaph = ReflexExecutor(allow_bombs=False, gap_horizon=True)
    ex_gaph.execute(Macro(), v_gap)
    assert ex_gaph.last_costs[0] < ex_def2.last_costs[0] - 1.0, \
        "gap horizon missed the passing gap in a dense wall"
    v_sparse = view()
    v_sparse.raw.player.position.x = 240.0
    v_sparse.raw.player.position.y = 300.0
    v_sparse.projectiles = [haz_bullet(168.0, 300.0 + i, vx=1.0)
                            for i in range(2)]
    ex_def3 = ReflexExecutor(allow_bombs=False)
    ex_def3.execute(Macro(), v_sparse)
    ex_gaph2 = ReflexExecutor(allow_bombs=False, gap_horizon=True)
    ex_gaph2.execute(Macro(), v_sparse)
    assert ex_gaph2.last_costs[0] == ex_def3.last_costs[0], \
        "gap search must not fire below GAP_HORIZON_SNAP_AT"

    # R4.8 (2026-09-26): escape commit (opt-in). In severe danger (min
    # cost >= ESCAPE_COMMIT_AT) the choice is pinned to the cheapest
    # NON-STATIONARY heading for ESCAPE_COMMIT_FRAMES frames — a
    # straight-line escape that clears the ~16 px kill disk of a tracking
    # convergence storm (G2.91 S1 f12297: the per-frame argmin oscillated
    # hold/diagonal and stalled the player at the aim point). Fixed-cost
    # monkey-patch: intent (anchor 100 px up, beta 0.8) makes the plain
    # score-argmin UP (41.0 - 0.8 = 40.2), but the cheapest non-stationary
    # COST heading is RIGHT (40.5) -> the commit executor must pick right
    # and keep it through safe frames until the commit expires.
    from executor import MOVES
    move_idx = {(u[0], u[1]): i for i, (u, _b) in enumerate(MOVES)}

    def fixed_cost(values):
        # instance attribute (unbound): called with the 8 cost args only
        def _fc(px, py, dx, dy, speed, hazards, segs_now, segs_full):
            return values[move_idx[(dx, dy)]]
        return _fc

    esc_vals = [50.0, 41.0, 49.0, 48.0, 40.5, 47.0, 47.0, 46.0, 46.0]
    v_esc = view()
    v_esc.raw.player.position.x = 240.0
    v_esc.raw.player.position.y = 500.0
    m_point = SimpleNamespace(macro_id="guard", bomb=False, focus=False,
                              source="laya", issued_frame=0,
                              target=MacroTarget(kind="point",
                                                 point=(240.0, 400.0)))
    ex_plain = ReflexExecutor(allow_bombs=False)
    ex_plain._candidate_cost = fixed_cost(esc_vals)
    ex_commit = ReflexExecutor(allow_bombs=False, escape_commit=True)
    ex_commit._candidate_cost = fixed_cost(esc_vals)
    ex_plain.execute(m_point, v_esc)
    ex_commit.execute(m_point, v_esc)
    assert ex_plain.last_move_idx == 1, "plain argmin should be UP (intent)"
    assert ex_commit.last_move_idx == 4, \
        "commit must pin the cheapest non-stationary heading (RIGHT)"
    v_safe = view()
    v_safe.raw.player.position.x = 240.0
    v_safe.raw.player.position.y = 500.0
    safe_vals = [1.0] * len(MOVES)
    ex_plain._candidate_cost = fixed_cost(safe_vals)
    ex_commit._candidate_cost = fixed_cost(safe_vals)
    for n in range(3):  # frames 2-4: commit persists through safe states
        ex_plain.execute(m_point, v_safe)
        ex_commit.execute(m_point, v_safe)
        assert ex_plain.last_move_idx == 1
        assert ex_commit.last_move_idx == 4, "commit must persist (frame %d)" % (n + 2)
    ex_plain.execute(m_point, v_safe)
    ex_commit.execute(m_point, v_safe)
    assert ex_plain.last_move_idx == 1
    assert ex_commit.last_move_idx == 1, \
        "commit must expire after ESCAPE_COMMIT_FRAMES frames"
    # no-op in sparse states: min cost 5.0 < ESCAPE_COMMIT_AT -> plain choice
    v_sparse2 = view()
    v_sparse2.raw.player.position.x = 240.0
    v_sparse2.raw.player.position.y = 500.0
    ex_sparse = ReflexExecutor(allow_bombs=False, escape_commit=True)
    ex_sparse._candidate_cost = fixed_cost([5.0] * len(MOVES))
    ex_sparse.execute(m_point, v_sparse2)
    assert ex_sparse.last_move_idx == 1, \
        "commit must not fire below ESCAPE_COMMIT_AT"

    print("NO-BOMB MODE TEST PASSED")


if __name__ == "__main__":
    main()
