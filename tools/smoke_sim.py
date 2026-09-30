"""M1 smoke test: load the built taisei-sim, run scripted episodes, verify.

Checks (per doc/PLAN.md M1):
  1. Library loads, API version == 1, all struct sizes match (ABI check).
  2. Headless episode runs: stage 1 Easy, Marisa A, fixed seed.
  3. "Stand still" -> player dies -> episode LOST.
  4. Determinism: same seed + same inputs => identical gameplay_digest.
  5. save_replay produces a file.
  6. Headless logic frames/sec on this PC.

Usage:
    venv\\Scripts\\python.exe tools\\smoke_sim.py [path-to-taisei_sim.dll]

Note: the harness must load the real shared module (taisei_sim.dll), not the
executable: an EXE loaded via LoadLibrary never runs its CRT entry point, so
every CRT call inside it (snprintf/fopen/malloc) access-violates.
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # project root
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
REPO_PKGDIR = os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir")
DATA = os.path.join(HERE, "simdata")

sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, TaiseiSimError,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY,
    STATUS_RUNNING, STATUS_WON, STATUS_LOST, STATUS_ABORTED, STATUS_ERROR,
    ACTION_SHOT,
)

LIB_CANDIDATES = [
    os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll"),  # meson's name
    os.path.join(SIM_ROOT, "build", "src", "taisei_sim.dll"),
    os.path.join(SIM_ROOT, "build", "src", "taisei.exe"),       # broken: EXE-as-DLL never runs CRT init
    os.path.join(SIM_ROOT, "build", "taisei.exe"),
]


def find_lib():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for p in LIB_CANDIDATES:
        if os.path.isfile(p):
            return p
    sys.exit("taisei_sim.dll not found; pass its path as argv[1]. Looked in: " +
             " | ".join(LIB_CANDIDATES))


def ensure_runtime_path():
    """The MinGW-built DLL needs libgcc/libwinpthread/libstdc++/zlib DLLs.
    ctypes (3.8+) resolves deps via os.add_dll_directory dirs registered at
    ``import ctypes`` time, so env-PATH alone is not enough — register both."""
    from taisei_sim import register_runtime_dirs
    register_runtime_dirs(os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))


def status_name(s):
    return {1: "RUNNING", 2: "WON", 3: "LOST", 4: "ABORTED", 5: "ERROR"}.get(s, str(s))


def run_episode(sim, episode, buttons_fn, max_frames, fps_check_frames=0):
    """Step an episode until terminal or max_frames. Returns (view, frames, t_s)."""
    sim.reset(episode)
    frame = 0
    t0 = time.perf_counter()
    while frame < max_frames:
        sim.step(buttons=buttons_fn(frame))
        frame += 1
        v = sim.get_state()
        if v.status != STATUS_RUNNING:
            break
        if fps_check_frames and frame >= fps_check_frames:
            break
    t1 = time.perf_counter()
    return v, frame, t1 - t0


def main():
    lib = find_lib()
    print(f"lib: {lib}")
    ensure_runtime_path()
    os.makedirs(os.path.join(DATA, "storage"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "cache"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "replays"), exist_ok=True)

    sim = TaiseiSim(lib)                      # ABI check happens here
    print("ABI check OK (api_version=1, all struct sizes match)")

    import crash_hook                          # noqa: E402  (tools/ on sys.path)
    crash_hook.install(lib, os.path.join(HERE, "logs", "crash-2026-09-25-m1.txt"),
                       module_name=os.path.basename(lib))

    sim.global_init(
        resource_path=REPO_PKGDIR,
        storage_path=os.path.join(DATA, "storage"),
        cache_path=os.path.join(DATA, "cache"),
    )
    print("global_init OK (headless bootstrap: dummy video/audio, null renderer)")
    sim.create()
    print("create OK")

    ep = EpisodeConfig(
        stage_id=1,
        difficulty=DIFFICULTY_EASY,
        player_character=CHAR_MARISA,
        shot_mode=SHOT_A,
        rng_seed=12345,
    )

    # 1) stand still, no input -> should die -> LOST
    v, frames, dt = run_episode(sim, ep, lambda f: 0, max_frames=60 * 180)
    print(f"stand-still: status={status_name(v.status)} after {frames} frames "
          f"({frames / 60:.1f} s game time); deaths={v.raw.deaths} score={v.raw.score}")
    assert v.status == STATUS_LOST, f"expected LOST, got {status_name(v.status)}"

    # 2) determinism: two identical runs -> same gameplay_digest
    def script(frame):
        # simple deterministic input: shoot, wiggle horizontally
        buttons = ACTION_SHOT
        if (frame // 30) % 4 < 2:
            buttons |= 1 << 3  # right
        else:
            buttons |= 1 << 2  # left
        return buttons

    v1, f1, dt1 = run_episode(sim, ep, script, max_frames=60 * 60)
    d1 = v1.raw.gameplay_digest
    v2, f2, dt2 = run_episode(sim, ep, script, max_frames=60 * 60)
    d2 = v2.raw.gameplay_digest
    print(f"determinism: run1 digest={d1:#x} ({f1} frames) "
          f"run2 digest={d2:#x} ({f2} frames)")
    assert d1 == d2, "gameplay_digest mismatch -> non-deterministic!"
    print("determinism OK")

    # 3) save replay of a fresh run (10 s, or until the episode terminates)
    sim.reset(ep)
    for f in range(60 * 10):
        try:
            sim.step(buttons=script(f))
        except TaiseiSimError:
            break
    if sim.get_state().status == STATUS_RUNNING:
        sim.abort()
    replay_path = os.path.join(DATA, "replays", "smoke-stage1-easy.trsr")
    sim.save_replay(replay_path)
    size = os.path.getsize(replay_path)
    print(f"save_replay OK: {replay_path} ({size} bytes)")
    assert size > 100, "replay file suspiciously small"

    # 4) headless logic FPS: steady-state stepping (mid-stage, bullets on screen).
    #    The scripted player eventually dies (3 lives), so measure 1-second
    #    buckets and stop at the terminal state; report overall + median bucket.
    sim.reset(ep)
    f = 0
    for _ in range(60 * 5):  # 5 s warmup so bullets/enemies are in steady state
        sim.step(buttons=script(f))
        f += 1
        if sim.status() != STATUS_RUNNING:
            break
    buckets = []
    total_frames, total_t = 0, 0.0
    while len(buckets) < 30:
        t0 = time.perf_counter()
        n = 0
        while n < 60:
            try:
                sim.step(buttons=script(f))
                f += 1
                n += 1
            except TaiseiSimError:
                break
        dt = time.perf_counter() - t0
        if n == 0:
            break
        buckets.append((n, dt))
        total_frames += n
        total_t += dt
        if sim.status() != STATUS_RUNNING:
            break
    fps_all = total_frames / total_t if total_t else 0.0
    steady = sorted(n / dt for n, dt in buckets[1:]) or [fps_all]
    fps_med = steady[len(steady) // 2]
    v = sim.get_state()
    print(f"headless logic: {total_frames} frames in {total_t:.2f}s "
          f"-> {fps_all:.0f} fps overall, {fps_med:.0f} fps median bucket "
          f"({len(buckets)} buckets)")
    print(f"final state: bullets={v.raw.projectile_count}, enemies={v.raw.enemy_count}, "
          f"lasers={v.raw.laser_count}; player=({v.player.position.x:.1f}, "
          f"{v.player.position.y:.1f}) alive={bool(v.player.alive)} "
          f"lives={v.player.lives} bombs={v.player.bombs} "
          f"boss_active={bool(v.boss.active)} status={status_name(v.status)}")

    sim.destroy()
    sim.global_shutdown()
    print("\nALL M1 SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
