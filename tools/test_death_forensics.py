"""R0.1 gate (2026-09-26): death forensics must use the immutable
pre-step entity snapshot, because StateView entity lists reference
persistent C buffers that step() rewrites in place.

    venv\Scripts\python.exe tools\test_death_forensics.py
"""
import json
import os
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))

from taisei_sim import PROJ_ENEMY  # noqa: E402
from agent import Agent  # noqa: E402
from macros import MacroTarget  # noqa: E402


def bullet(x, y, vx=0.0, vy=0.0, r=4.0, flags=16):
    return SimpleNamespace(
        category=PROJ_ENEMY, flags=flags,
        position=SimpleNamespace(x=x, y=y),
        velocity=SimpleNamespace(x=vx, y=vy),
        collision_size=SimpleNamespace(x=r, y=r),
    )


def fake_view(px=240.0, py=470.0, bullets=()):
    player = SimpleNamespace(
        alive=True, death_timer=0, bombs=0, bomb_active=False,
        invulnerable=False, position=SimpleNamespace(x=px, y=py),
        velocity=SimpleNamespace(x=0.0, y=0.0), input_flags=0,
        lives=1, life_fragments=0, bomb_fragments=0, effective_power=300,
    )
    boss = SimpleNamespace(
        active=False, invulnerable=False,
        position=SimpleNamespace(x=240.0, y=100.0),
        velocity=SimpleNamespace(x=0.0, y=0.0),
        hp=1.0, max_hp=1.0, phase_type=0, spell_active=False,
        remaining_timeout_frames=0, recent_damage=0.0,
    )
    raw = SimpleNamespace(player=player, boss=boss, logical_frame=100,
                          stage_id=1, difficulty=2, score=1000, deaths=1)
    return SimpleNamespace(raw=raw, player=player, boss=boss,
                           projectiles=list(bullets), enemies=[],
                           lasers=[], laser_points=[], items=[])


def fake_macro():
    return SimpleNamespace(
        macro_id="guard", target=MacroTarget(kind="below_boss"),
        focus=False, bomb=False, danger_score=1.5, source="laya",
        issued_frame=90, state_text="",
        raw={"move": {"choice": "guard", "probabilities": {"guard": 0.6}},
             "focus": {"noul": 0.2}, "bomb_now": {"noul": 0.1},
             "danger": {"score": 1.5}},
    )


def main():
    # 1. The snapshot must survive in-place buffer mutation.
    b = bullet(300.0, 470.0, vx=-5.0)
    view = fake_view(bullets=[b])
    snap = Agent._snapshot_hazards(view)
    assert snap["bullets"] == [(300.0, 470.0, -5.0, 0.0, 4.0, 16)]
    # simulate step() rewriting the persistent buffer (kill + respawn)
    b.position.x = 10.0
    b.position.y = 10.0
    b.velocity.x = 0.0
    b.flags = 0
    assert Agent._snapshot_hazards(view)["bullets"][0][:2] == (10.0, 10.0)
    assert snap["bullets"][0][:2] == (300.0, 470.0), "snapshot mutated!"

    # 2. The death record must show the PRE-HIT entities even though the
    #    live view is now the cleared world.
    tmp = tempfile.mkdtemp(prefix="forensics-")
    a = Agent.__new__(Agent)
    a.log_dir = tmp
    a.episode_tag = "fore-test"
    a.decide_every = 30
    a.allow_bombs = False
    a.allow_focus = True
    a.executor = SimpleNamespace(last_move_idx=0, last_cost=50.0,
                                 last_costs=[50.0] * 9, last_buttons=1)
    a._log_death_hit(view, fake_macro(), snap=snap)
    rows = [json.loads(x) for x in
            open(os.path.join(tmp, "laya-fore-test.jsonl"), encoding="utf-8")
            if x.strip()]
    hit = [r for r in rows if r.get("status") == "death_hit"]
    assert len(hit) == 1
    h = hit[0]
    assert h["bullets"] == 1, "record must count the pre-hit bullet"
    assert h["nearest_hazards"], "killer bullet missing from forensics"
    assert abs(h["nearest_hazards"][0]["d"] - 60.0) < 0.1
    assert h["nearest_hazards"][0]["vx"] == -5.0
    # 3. hit_state_text must be compiled from the snapshot, not the cleared
    #    live view: the 300->240 bullet closing at 5 px/f hits in ~10 frames.
    hs = h["hit_state_text"]
    assert "You are at (240, 470)" in hs
    assert "will hit you in about 10 frames" in hs, hs
    assert "No bullet will hit you within" not in hs

    print("DEATH FORENSICS TEST PASSED")


if __name__ == "__main__":
    main()
