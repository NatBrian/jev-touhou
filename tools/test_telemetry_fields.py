"""R0 telemetry checks (2026-09-26): the trace must carry the RAW Laya
answers and the exact compiled state text, without any behavior change.

    venv\Scripts\python.exe tools\test_telemetry_fields.py
"""
import json
import os
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))

from agent import Agent  # noqa: E402
from macros import MacroTarget  # noqa: E402


def _view():
    """Minimal stub covering every field _log_call/_log_death_hit/
    compile_state read (same pattern as tools/test_no_bomb_mode.py)."""
    player = SimpleNamespace(
        alive=True, death_timer=-1, bombs=3, bomb_active=False,
        invulnerable=False, position=SimpleNamespace(x=240.0, y=470.0),
        velocity=SimpleNamespace(x=0.0, y=0.0), input_flags=0,
        lives=2, life_fragments=0, bomb_fragments=0, effective_power=300,
    )
    boss = SimpleNamespace(
        active=False, invulnerable=False,
        position=SimpleNamespace(x=240.0, y=100.0),
        velocity=SimpleNamespace(x=0.0, y=0.0),
        hp=1.0, max_hp=1.0, phase_type=0, spell_active=False,
        remaining_timeout_frames=0, recent_damage=0.0,
    )
    raw = SimpleNamespace(
        player=player, boss=boss, logical_frame=123, stage_id=1,
        difficulty=2, score=1000, deaths=0,
    )
    return SimpleNamespace(raw=raw, player=player, boss=boss,
                           projectiles=[], enemies=[], lasers=[],
                           laser_points=[], items=[])


def _macro(remap_from=None):
    choice = "guard"
    raw_move = remap_from if remap_from is not None else choice
    m = SimpleNamespace(
        macro_id=choice,
        target=MacroTarget(kind="below_boss"),
        focus=True, bomb=False, danger_score=1.42,
        source="laya", issued_frame=120,
        state_text="Frame 123 of stage 1 (Normal). You are at (240, 470).",
        raw={
            "move": {"type": "choice", "choice": raw_move,
                     "probabilities": {"guard": 0.9, "hold": 0.1},
                     "confidence": 0.9, "action": {"act_probability": 0.9}},
            "focus": {"type": "noul", "noul": 0.9, "confidence": 0.9},
            "bomb_now": {"type": "noul", "noul": 0.2, "confidence": 0.8},
            "danger": {"type": "score", "score": 1.42, "legend": {
                "0": "safe", "1": "moderate", "2": "severe"}},
        },
    )
    return m


def _agent(log_dir):
    a = Agent.__new__(Agent)
    a.log_dir = log_dir
    a.episode_tag = "tele-test"
    a.decide_every = 52
    a.allow_bombs = False
    a.allow_focus = True
    a.allow_edge_escape = False
    a.executor = SimpleNamespace(last_move_idx=0, last_cost=0.31,
                                 last_costs=[0.31] * 9, last_buttons=1)
    return a


def main():
    tmp = tempfile.mkdtemp(prefix="tele-test-")

    # --- _log_call: raw answer + state provenance fields -------------------
    a = _agent(tmp)
    a._log_call(frame=123, status="ok",
                resp={"_wall_ms": 850.0, "_server_ms": 25.0,
                      "routing": {"model": "english"},
                      "usage": {"input_tokens": 1700}},
                macro=_macro(), v=_view())
    a._log_call(frame=180, status="ok",
                resp={"_wall_ms": 850.0, "_server_ms": 25.0,
                      "routing": {"model": "english"},
                      "usage": {"input_tokens": 1700}},
                macro=_macro(remap_from="bomb_setup"), v=_view())
    path = os.path.join(tmp, "laya-tele-test.jsonl")
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    assert len(rows) == 2
    r0, r1 = rows
    for key in ("raw_move", "move_probs", "move_remapped", "focus_eff",
                "target_kind", "state_chars", "state_sha1", "decide_every"):
        assert key in r0, "missing telemetry field %s" % key
    assert r0["raw_move"] == "guard"
    assert r0["move_probs"] == {"guard": 0.9, "hold": 0.1}
    assert r0["move_remapped"] is False
    assert r0["focus_eff"] is True
    assert r0["target_kind"] == "below_boss"
    assert r0["state_chars"] == len(_macro().state_text)
    assert isinstance(r0["state_sha1"], str) and len(r0["state_sha1"]) == 40
    assert r0["decide_every"] == 52
    # no-bomb remap must be visible: raw said bomb_setup, parsed is guard
    assert r1["raw_move"] == "bomb_setup"
    assert r1["macro"] == "guard"
    assert r1["move_remapped"] is True

    # --- _log_death_hit: raw fields + the state Laya would have seen --------
    v = _view()
    a._log_death_hit(v, _macro(remap_from="bomb_setup"), v_now=v)
    rows = [json.loads(x) for x in open(path, encoding="utf-8")
            if x.strip()]
    hit = [r for r in rows if r.get("status") == "death_hit"]
    assert len(hit) == 1, "death_hit record missing"
    h = hit[0]
    assert h["raw_move"] == "bomb_setup"
    assert h["move_remapped"] is True
    assert h["focus_eff"] is True
    assert h["target_kind"] == "below_boss"
    assert isinstance(h["hit_state_text"], str) and len(h["hit_state_text"]) > 0
    assert h["hit_state_chars"] == len(h["hit_state_text"])
    assert h["hit_state_text"].startswith("Frame 123 of stage 1")

    print("TELEMETRY FIELDS TEST PASSED")


if __name__ == "__main__":
    main()
