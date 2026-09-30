"""ctypes binding for the taisei-sim C API (taisei_sim_*).

Loads the built ``libtaisei_sim.dll`` (real DLL, exports the C API; see
third_party/taisei-sim/src/sim/meson.build) and wraps the lifecycle.

Must be the DLL, not taisei.exe: an EXE loaded via LoadLibrary never runs
its CRT entry point, so every CRT call inside it (snprintf/fopen/malloc)
access-violates. Call register_runtime_dirs(mingw_bin) before constructing
TaiseiSim so the DLL's mingw dependencies resolve (see that function).

    sim = TaiseiSim(exe_path, resource_path=..., storage_path=..., cache_path=...)
    sim.global_init()
    sim.create()
    sim.reset(EpisodeConfig(stage_id=1, difficulty=4, player_character=MARISA, shot_mode=A))
    for _ in range(60):
        sim.step(buttons=ACTION_SHOT)
    st = sim.get_state()

The C API is self-contained (see src/sim/taisei_sim.h). Coordinates use
Taisei's 480x560 playfield, (0,0) top-left, +x right, +y down.

Struct layout is declared here in C field order; at load time every size is
cross-checked against the library's taisei_sim_sizeof_*() so a header/ctypes
drift fails loudly instead of silently misreading memory.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import (
    c_uint8, c_uint16, c_uint32, c_uint64,
    c_int32, c_float, c_double, c_size_t, c_char_p,
    POINTER, byref, sizeof,
)
from dataclasses import dataclass, field

_REGISTERED_DLL_DIRS: set = set()


def register_runtime_dirs(d: str):
    """Make the mingw runtime DLLs (libgcc_s_seh-1, libwinpthread, libstdc++,
    zlib1) findable by ctypes on Windows.

    ctypes on Windows (Python 3.8+) searches DLL dependencies using a list
    registered via os.add_dll_directory(), snapshotted from PATH at
    ``import ctypes`` time — updating os.environ["PATH"] afterwards does NOT
    affect CDLL() dependency resolution. Register the directory explicitly.
    Idempotent. (Also prepends to env PATH for other loaders / child procs.)
    """
    d = os.path.abspath(d)
    if os.name != "nt" or not os.path.isdir(d):
        return
    if d not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    if d in _REGISTERED_DLL_DIRS:
        return
    try:
        os.add_dll_directory(d)
    except OSError:
        pass
    _REGISTERED_DLL_DIRS.add(d)

# --- constants (mirror taisei_sim.h) -----------------------------------------

API_VERSION = 1
USE_DEFAULT_I32 = -(2 ** 31) + 1          # INT32_C(-2147483647)
USE_DEFAULT_U64 = 2 ** 64 - 1             # UINT64_MAX

VIEWPORT_WIDTH = 480.0
VIEWPORT_HEIGHT = 560.0

# action / input button bits
ACTION_UP = 1 << 0
ACTION_DOWN = 1 << 1
ACTION_LEFT = 1 << 2
ACTION_RIGHT = 1 << 3
ACTION_FOCUS = 1 << 4
ACTION_SHOT = 1 << 5
ACTION_BOMB = 1 << 6
ACTION_SPECIAL = 1 << 7
ACTION_ALL = 0xFF

# difficulty
DIFFICULTY_DEFAULT = 0
DIFFICULTY_EASY = 1
DIFFICULTY_NORMAL = 2
DIFFICULTY_HARD = 3
DIFFICULTY_LUNATIC = 4

# player characters (plrmodes.h CharacterID)
CHAR_REIMU = 0
CHAR_MARISA = 1
CHAR_YOUMU = 2

# shot modes (plrmodes.h)
SHOT_A = 0
SHOT_B = 1

# projectile category
PROJ_INVALID = 0
PROJ_ENEMY = 1
PROJ_CLEARING = 2
PROJ_PLAYER = 3

# episode status
STATUS_INVALID = 0
STATUS_RUNNING = 1
STATUS_WON = 2
STATUS_LOST = 3
STATUS_ABORTED = 4
STATUS_ERROR = 5

# boss phase type
PHASE_NONE = 0
PHASE_NONSPELL = 1
PHASE_MOVE = 2
PHASE_SPELL = 3
PHASE_SURVIVAL = 4
PHASE_EXTRA = 5

# result codes
SIM_OK = 0
SIM_BUFFER_TOO_SMALL = -11
RESULT_NAMES = {
    0: "OK",
    -1: "INVALID_ARGUMENT",
    -2: "INVALID_HANDLE",
    -3: "NOT_INITIALIZED",
    -4: "ALREADY_INITIALIZED",
    -5: "SIMULATION_ACTIVE",
    -6: "NO_ACTIVE_EPISODE",
    -7: "EPISODE_RUNNING",
    -8: "EPISODE_TERMINAL",
    -9: "STAGE_NOT_FOUND",
    -10: "PLAYER_MODE_NOT_FOUND",
    -11: "BUFFER_TOO_SMALL",
    -12: "IO",
    -13: "ABI_MISMATCH",
    -14: "INTERNAL",
}


class TaiseiSimError(RuntimeError):
    def __init__(self, code, message):
        name = RESULT_NAMES.get(code, f"code={code}")
        super().__init__(f"taisei_sim {name}: {message}")
        self.code = code
        self.name = name


# --- ctypes struct declarations (C field order) ------------------------------

class Vec2(ctypes.Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


class GlobalConfig(ctypes.Structure):
    _fields_ = [
        ("struct_size", c_uint32),
        ("api_version", c_uint32),
        ("resource_path", c_char_p),
        ("storage_path", c_char_p),
        ("cache_path", c_char_p),
        ("flags", c_uint32),
        ("reserved", c_uint32),
    ]


class Config(ctypes.Structure):
    _fields_ = [
        ("struct_size", c_uint32),
        ("flags", c_uint32),
        ("laser_sample_step", c_double),
        ("reserved", c_uint32),
    ]


class EpisodeConfigC(ctypes.Structure):
    _fields_ = [
        ("struct_size", c_uint32),
        ("stage_id", c_uint16),
        ("difficulty", c_uint8),
        ("player_character", c_uint8),
        ("shot_mode", c_uint8),
        ("practice_mode", c_uint8),
        ("reserved0", c_uint16),
        ("rng_seed", c_uint64),
        ("start_time", c_uint64),
        ("initial_lives", c_int32),
        ("initial_bombs", c_int32),
        ("initial_life_fragments", c_int32),
        ("initial_bomb_fragments", c_int32),
        ("initial_power", c_int32),
        ("initial_point_item_value", c_int32),
        ("initial_score", c_uint64),
        ("initial_graze", c_uint32),
        ("reserved1", c_uint32),
    ]


class Action(ctypes.Structure):
    _fields_ = [
        ("struct_size", c_uint32),
        ("buttons", c_uint32),
    ]


class PlayerState(ctypes.Structure):
    _fields_ = [
        ("position", Vec2),
        ("previous_position", Vec2),
        ("velocity", Vec2),
        ("input_flags", c_uint32),
        ("focused", c_uint32),
        ("shooting", c_uint32),
        ("lives", c_int32),
        ("bombs", c_int32),
        ("life_fragments", c_int32),
        ("bomb_fragments", c_int32),
        ("stored_power", c_int32),
        ("effective_power", c_int32),
        ("point_item_value", c_uint32),
        ("score", c_uint64),
        ("graze", c_uint32),
        ("voltage", c_uint32),
        ("invulnerable", c_uint32),
        ("recovering", c_uint32),
        ("alive", c_uint32),
        ("death_timer", c_int32),
        ("respawn_timer", c_int32),
        ("recovery_timer", c_int32),
        ("bomb_active", c_uint32),
        ("bomb_progress", c_double),
        ("bomb_trigger_frame", c_int32),
        ("bomb_end_frame", c_int32),
        ("power_surge_active", c_uint32),
        ("power_surge_positive", c_float),
        ("power_surge_negative", c_float),
        ("player_character", c_uint8),
        ("shot_mode", c_uint8),
        ("reserved", c_uint16),
    ]


class BossState(ctypes.Structure):
    _fields_ = [
        ("active", c_uint32),
        ("position", Vec2),
        ("velocity", Vec2),
        ("hp", c_float),
        ("max_hp", c_float),
        ("invulnerable", c_uint32),
        ("phase_index", c_int32),
        ("phase_type", c_uint32),
        ("attack_id", c_uint16),
        ("spell_id", c_uint16),
        ("spell_active", c_uint32),
        ("phase_start_frame", c_int32),
        ("phase_end_frame", c_int32),
        ("phase_timeout_frames", c_int32),
        ("remaining_timeout_frames", c_int32),
        ("spell_failed_frame", c_int32),
        ("spell_failed", c_uint32),
        ("spell_captured", c_uint32),
        ("recent_damage", c_float),
    ]


class ProjectileState(ctypes.Structure):
    _fields_ = [
        ("spawn_id", c_uint32),
        ("category", c_uint32),
        ("position", Vec2),
        ("previous_position", Vec2),
        ("velocity", Vec2),
        ("collision_size", Vec2),
        ("damage", c_float),
        ("angle", c_float),
        ("age_frames", c_int32),
        ("flags", c_uint32),
        ("damage_type", c_uint32),
        ("clear_flags", c_uint32),
    ]


class EnemyState(ctypes.Structure):
    _fields_ = [
        ("spawn_id", c_uint32),
        ("position", Vec2),
        ("velocity", Vec2),
        ("hp", c_float),
        ("max_hp", c_float),
        ("hit_radius", c_float),
        ("hurt_radius", c_float),
        ("age_frames", c_int32),
        ("flags", c_uint32),
        ("damageable", c_uint32),
        ("harmful", c_uint32),
    ]


class ItemState(ctypes.Structure):
    _fields_ = [
        ("spawn_id", c_uint32),
        ("position", Vec2),
        ("velocity", Vec2),
        ("item_type", c_uint32),
        ("age_frames", c_int32),
        ("collect_frame", c_int32),
        ("attracted", c_uint32),
        ("pickup_value", c_float),
    ]


class LaserState(ctypes.Structure):
    _fields_ = [
        ("spawn_id", c_uint32),
        ("origin", Vec2),
        ("age_frames", c_int32),
        ("width", c_float),
        ("speed", c_float),
        ("timespan", c_float),
        ("death_time", c_float),
        ("time_shift", c_float),
        ("collision_active", c_uint32),
        ("unclearable", c_uint32),
        ("clear_flags", c_uint32),
        ("first_point", c_uint32),
        ("point_count", c_uint32),
    ]


class LaserPoint(ctypes.Structure):
    _fields_ = [
        ("position", Vec2),
        ("half_width", c_float),
        ("time", c_float),
        ("flags", c_uint32),
    ]


class State(ctypes.Structure):
    _fields_ = [
        ("struct_size", c_uint32),
        ("api_version", c_uint32),
        ("stage_id", c_uint16),
        ("stage_type", c_uint16),
        ("difficulty", c_uint8),
        ("player_character", c_uint8),
        ("shot_mode", c_uint8),
        ("practice_mode", c_uint8),
        ("logical_frame", c_uint64),
        ("initial_rng_seed", c_uint64),
        ("start_time", c_uint64),
        ("episode_status", c_uint32),
        ("stage_clear", c_uint32),
        ("game_over", c_uint32),
        ("reserved0", c_uint32),
        ("score", c_uint64),
        ("graze", c_uint32),
        ("voltage", c_uint32),
        ("deaths", c_uint32),
        ("bombs_used", c_uint32),
        ("continues_used", c_uint32),
        ("gameover_frame", c_int32),
        ("reserved2", c_int32),
        ("player", PlayerState),
        ("boss", BossState),
        ("projectile_count", c_uint32),
        ("enemy_count", c_uint32),
        ("item_count", c_uint32),
        ("laser_count", c_uint32),
        ("laser_point_count", c_uint32),
        ("reserved1", c_uint32),
        ("gameplay_digest", c_uint64),
    ]


class StateBuffers(ctypes.Structure):
    _fields_ = [
        ("struct_size", c_uint32),
        ("reserved", c_uint32),
        ("projectiles", POINTER(ProjectileState)),
        ("projectile_capacity", c_uint32),
        ("enemies", POINTER(EnemyState)),
        ("enemy_capacity", c_uint32),
        ("items", POINTER(ItemState)),
        ("item_capacity", c_uint32),
        ("lasers", POINTER(LaserState)),
        ("laser_capacity", c_uint32),
        ("laser_points", POINTER(LaserPoint)),
        ("laser_point_capacity", c_uint32),
    ]


# --- size cross-check table: (ctypes struct, sizeof function name) -----------
_SIZE_CHECKS = [
    (Vec2, "taisei_sim_sizeof_vec2"),
    (GlobalConfig, "taisei_sim_sizeof_global_config"),
    (Config, "taisei_sim_sizeof_config"),
    (EpisodeConfigC, "taisei_sim_sizeof_episode_config"),
    (Action, "taisei_sim_sizeof_action"),
    (PlayerState, "taisei_sim_sizeof_player_state"),
    (BossState, "taisei_sim_sizeof_boss_state"),
    (ProjectileState, "taisei_sim_sizeof_projectile_state"),
    (EnemyState, "taisei_sim_sizeof_enemy_state"),
    (ItemState, "taisei_sim_sizeof_item_state"),
    (LaserState, "taisei_sim_sizeof_laser_state"),
    (LaserPoint, "taisei_sim_sizeof_laser_point"),
    (State, "taisei_sim_sizeof_state"),
    (StateBuffers, "taisei_sim_sizeof_state_buffers"),
]


# --- Python-facing config/state wrappers -------------------------------------

@dataclass
class EpisodeConfig:
    stage_id: int = 1                 # 1..6 story, 7 extra
    difficulty: int = DIFFICULTY_EASY
    player_character: int = CHAR_REIMU
    shot_mode: int = SHOT_A
    practice_mode: int = 0
    rng_seed: int = USE_DEFAULT_U64   # deterministic if set to a fixed value
    start_time: int = USE_DEFAULT_U64
    initial_lives: int = USE_DEFAULT_I32
    initial_bombs: int = USE_DEFAULT_I32
    initial_life_fragments: int = USE_DEFAULT_I32
    initial_bomb_fragments: int = USE_DEFAULT_I32
    initial_power: int = USE_DEFAULT_I32
    initial_point_item_value: int = USE_DEFAULT_I32
    initial_score: int = USE_DEFAULT_U64
    initial_graze: int = 0

    def to_c(self) -> EpisodeConfigC:
        return EpisodeConfigC(
            struct_size=sizeof(EpisodeConfigC),
            stage_id=self.stage_id,
            difficulty=self.difficulty,
            player_character=self.player_character,
            shot_mode=self.shot_mode,
            practice_mode=self.practice_mode,
            reserved0=0,
            rng_seed=self.rng_seed,
            start_time=self.start_time,
            initial_lives=self.initial_lives,
            initial_bombs=self.initial_bombs,
            initial_life_fragments=self.initial_life_fragments,
            initial_bomb_fragments=self.initial_bomb_fragments,
            initial_power=self.initial_power,
            initial_point_item_value=self.initial_point_item_value,
            initial_score=self.initial_score,
            initial_graze=self.initial_graze,
            reserved1=0,
        )


@dataclass
class StateView:
    """Parsed snapshot. Entity arrays are lists of the ctypes structs (read-only)."""
    raw: State
    projectiles: list = field(default_factory=list)
    enemies: list = field(default_factory=list)
    items: list = field(default_factory=list)
    lasers: list = field(default_factory=list)
    laser_points: list = field(default_factory=list)

    @property
    def frame(self) -> int:
        return int(self.raw.logical_frame)

    @property
    def status(self) -> int:
        return int(self.raw.episode_status)

    @property
    def player(self) -> PlayerState:
        return self.raw.player

    @property
    def boss(self) -> BossState:
        return self.raw.boss


# --- the binding --------------------------------------------------------------

class TaiseiSim:
    def __init__(self, lib_path: str):
        self.lib_path = str(lib_path)
        self._lib = ctypes.CDLL(self.lib_path)
        self._configure_prototypes()
        self._check_abi()

        self._sim = ctypes.c_void_p(None)
        self._global_inited = False
        # persistent state buffers (grown on demand; stage 3+ Easy patterns
        # exceed 4096 live bullets, so start at 8192)
        self._cap = {
            "projectiles": 8192, "enemies": 1024, "items": 1024,
            "lasers": 512, "laser_points": 16384,
        }
        self._buf = {
            "projectiles": (ProjectileState * self._cap["projectiles"])(),
            "enemies": (EnemyState * self._cap["enemies"])(),
            "items": (ItemState * self._cap["items"])(),
            "lasers": (LaserState * self._cap["lasers"])(),
            "laser_points": (LaserPoint * self._cap["laser_points"])(),
        }

    # -- setup helpers ---------------------------------------------------------
    def _configure_prototypes(self):
        L = self._lib
        L.taisei_sim_api_version.restype = c_uint32
        L.taisei_sim_abi_fingerprint.restype = c_uint64
        L.taisei_sim_last_error.restype = c_char_p
        L.taisei_sim_last_error.argtypes = [ctypes.c_void_p]
        for _, name in _SIZE_CHECKS:
            getattr(L, name).restype = c_size_t
        L.taisei_sim_global_init.argtypes = [POINTER(GlobalConfig)]
        L.taisei_sim_global_init.restype = c_int32
        L.taisei_sim_global_shutdown.restype = c_int32
        L.taisei_sim_create.argtypes = [POINTER(Config), POINTER(ctypes.c_void_p)]
        L.taisei_sim_create.restype = c_int32
        L.taisei_sim_reset.argtypes = [ctypes.c_void_p, POINTER(EpisodeConfigC)]
        L.taisei_sim_reset.restype = c_int32
        L.taisei_sim_step.argtypes = [ctypes.c_void_p, POINTER(Action), c_uint32]
        L.taisei_sim_step.restype = c_int32
        L.taisei_sim_abort.argtypes = [ctypes.c_void_p]
        L.taisei_sim_abort.restype = c_int32
        L.taisei_sim_get_state.argtypes = [
            ctypes.c_void_p, POINTER(State), POINTER(StateBuffers)]
        L.taisei_sim_get_state.restype = c_int32
        L.taisei_sim_save_replay.argtypes = [ctypes.c_void_p, c_char_p]
        L.taisei_sim_save_replay.restype = c_int32
        L.taisei_sim_destroy.argtypes = [ctypes.c_void_p]
        L.taisei_sim_destroy.restype = c_int32

    def _check_abi(self):
        ver = self._lib.taisei_sim_api_version()
        if ver != API_VERSION:
            raise TaiseiSimError(
                -13, f"API version {ver} != expected {API_VERSION}")
        for struct, fn in _SIZE_CHECKS:
            c_size = getattr(self._lib, fn)()
            py_size = sizeof(struct)
            if c_size != py_size:
                raise TaiseiSimError(
                    -13, f"ABI mismatch for {struct.__name__}: "
                         f"C={c_size} ctypes={py_size}")

    def _err(self, code) -> str:
        raw = self._lib.taisei_sim_last_error(self._sim)
        return raw.decode("utf-8", "replace") if raw else ""

    def _require(self, code, what):
        if code != SIM_OK:
            raise TaiseiSimError(code, f"{what}: {self._err(code) or RESULT_NAMES.get(code)}")

    # -- lifecycle -------------------------------------------------------------
    @staticmethod
    def _to_bytes(p):
        if p is None:
            return b""
        return p.encode("utf-8") if isinstance(p, str) else p

    def global_init(self, resource_path=None, storage_path=None, cache_path=None):
        # keep the encoded bytes alive for the whole process: the C side may
        # retain these pointers (env values) far beyond this call
        self._path_bytes = (
            self._to_bytes(resource_path),
            self._to_bytes(storage_path),
            self._to_bytes(cache_path),
        )
        cfg = GlobalConfig(
            struct_size=sizeof(GlobalConfig),
            api_version=API_VERSION,
            resource_path=self._path_bytes[0],
            storage_path=self._path_bytes[1],
            cache_path=self._path_bytes[2],
            flags=0,
            reserved=0,
        )
        code = self._lib.taisei_sim_global_init(byref(cfg))
        self._require(code, "global_init")
        self._global_inited = True

    def global_shutdown(self):
        if not self._global_inited:
            return
        code = self._lib.taisei_sim_global_shutdown()
        self._require(code, "global_shutdown")
        self._global_inited = False

    def create(self, laser_sample_step: float = 0.0):
        cfg = Config(
            struct_size=sizeof(Config),
            flags=0,
            laser_sample_step=laser_sample_step,
            reserved=0,
        )
        out = ctypes.c_void_p(None)
        code = self._lib.taisei_sim_create(byref(cfg), byref(out))
        self._require(code, "create")
        self._sim = out

    def destroy(self):
        if not self._sim:
            return
        code = self._lib.taisei_sim_destroy(self._sim)
        self._require(code, "destroy")
        self._sim = ctypes.c_void_p(None)

    # -- episode ---------------------------------------------------------------
    def reset(self, episode: EpisodeConfig):
        ecfg = episode.to_c()
        code = self._lib.taisei_sim_reset(self._sim, byref(ecfg))
        self._require(code, "reset")

    def step(self, buttons: int = 0, frame_count: int = 1):
        act = Action(struct_size=sizeof(Action), buttons=buttons & 0xFFFFFFFF)
        code = self._lib.taisei_sim_step(self._sim, byref(act), frame_count)
        self._require(code, "step")

    def abort(self):
        code = self._lib.taisei_sim_abort(self._sim)
        self._require(code, "abort")

    def save_replay(self, path: str):
        p = path.encode("utf-8")
        self._replay_path_keep = p
        code = self._lib.taisei_sim_save_replay(self._sim, p)
        self._require(code, "save_replay")

    # -- state -----------------------------------------------------------------
    def _grow(self, key, needed):
        if needed <= self._cap[key]:
            return
        cap = max(needed * 2, 256)
        t = {"projectiles": ProjectileState, "enemies": EnemyState,
             "items": ItemState, "lasers": LaserState,
             "laser_points": LaserPoint}[key]
        self._buf[key] = (t * cap)()
        self._cap[key] = cap

    def get_state(self) -> StateView:
        st = State(struct_size=sizeof(State), api_version=API_VERSION)
        for _attempt in range(4):
            bufs = StateBuffers(
                struct_size=sizeof(StateBuffers), reserved=0,
                projectiles=ctypes.cast(self._buf["projectiles"], POINTER(ProjectileState)),
                projectile_capacity=self._cap["projectiles"],
                enemies=ctypes.cast(self._buf["enemies"], POINTER(EnemyState)),
                enemy_capacity=self._cap["enemies"],
                items=ctypes.cast(self._buf["items"], POINTER(ItemState)),
                item_capacity=self._cap["items"],
                lasers=ctypes.cast(self._buf["lasers"], POINTER(LaserState)),
                laser_capacity=self._cap["lasers"],
                laser_points=ctypes.cast(self._buf["laser_points"], POINTER(LaserPoint)),
                laser_point_capacity=self._cap["laser_points"],
            )
            code = self._lib.taisei_sim_get_state(self._sim, byref(st), byref(bufs))
            if code == SIM_BUFFER_TOO_SMALL:
                # soft signal: the C side always fills *out_state (incl. the
                # counts) before returning this (sim.c:1170); grow + retry
                for k, n in {
                    "projectiles": st.projectile_count,
                    "enemies": st.enemy_count,
                    "items": st.item_count,
                    "lasers": st.laser_count,
                    "laser_points": st.laser_point_count,
                }.items():
                    self._grow(k, n)
                continue
            self._require(code, "get_state")
            break
        return StateView(
            raw=st,
            projectiles=list(self._buf["projectiles"][:st.projectile_count]),
            enemies=list(self._buf["enemies"][:st.enemy_count]),
            items=list(self._buf["items"][:st.item_count]),
            lasers=list(self._buf["lasers"][:st.laser_count]),
            laser_points=list(self._buf["laser_points"][:st.laser_point_count]),
        )

    def status(self) -> int:
        """Lightweight episode_status read (no per-frame Python object build).

        Passes buffers=NULL: the C side still fills the TaiseiSimState and
        then returns BUFFER_TOO_SMALL (-11) whenever entities exist — that is
        expected and not an error here. (build_snapshot() still runs C-side,
        so probe at low frequency, not per measured frame.)
        """
        st = State(struct_size=sizeof(State), api_version=API_VERSION)
        code = self._lib.taisei_sim_get_state(self._sim, byref(st), None)
        if code != 0 and code != -11:
            self._require(code, "status")
        return int(st.episode_status)
