"""M4: merge per-stage .trsr replays into one multi-stage .trsr (v14/zstd).

The sim's taisei_sim_save_replay resets the recording on every episode, so a
6-stage campaign produces 6 single-stage replays. Stock Taisei plays a
multi-stage replay back-to-back automatically (replay/play.c replay_do_play),
so merging them yields one continuous video of the whole game.

File format (REPLAY_STRUCT_VERSION_TS104000_REV1 = 14, compression bit set,
version field 0x800E; layout from third_party/taisei-sim/src/replay/{struct.h,
write.c,read.c} — NOTE the on-wire game version is 5 bytes: u8 major, u8
minor, u8 patch, u16 tweak, per taisei_version_read/write):

    [10B magic "hono<3-heart>umi"][u16 version][5B game_version]
    [u32 fileoffset]
    [zstd frame: u8 name_len + name, u32 gflags, u16 numstages,
                 ReplayStage x numstages (76 B each, v14)]
    [4-byte gap]
    [zstd frame: all events concatenated, stage order; 7 B each:
                 u32 frame, u8 type, u16 value]
    [1B 0x69]

fileoffset = 21 + len(meta_zstd) + 4 (points at the events frame; read.c
segments [21, fileoffset) for the meta frame and seeks to fileoffset for
events — write.c leaves a 4-byte gap, replicated here for fidelity).

Per-stage metadata bytes (incl. the checksum `1 + ~checksum(stg)`) are copied
verbatim from the source files, so per-stage checksum validation still passes.
Global flags are recombined: CONTINUES/CHEATS = OR over stages, CLEAR = AND.

    venv\Scripts\python.exe tools\merge_replays.py out.trsr in1.trsr ... inN.trsr
    venv\Scripts\python.exe tools\merge_replays.py --parse file.trsr
"""
import io
import os
import struct
import sys

import zstandard as zstd

MAGIC = bytes([0x68, 0x6F, 0x6E, 0x6F, 0xE2, 0x9D, 0xA4, 0x75, 0x6D, 0x69])
VERSION = 0x800E          # 14 | compression bit
STAGE_SIZE = 76           # ReplayStage stored size at v14
EVENT_SIZE = 7

G_CONTINUES, G_CHEATS, G_CLEAR = 1 << 0, 1 << 1, 1 << 2
S_CONTINUES, S_CHEATS, S_CLEAR = 1 << 0, 1 << 1, 1 << 2

# ReplayStage v14 wire layout (verified against src/replay/write.c
# replay_write_stage + struct.h "stored fields", 76 bytes total):
F = {
    "flags": (0, "<I"), "stage": (4, "<H"), "start_time": (6, "<Q"),
    "rng_seed": (14, "<Q"), "diff": (22, "<B"), "skip_frames": (23, "<H"),
    "plr_points": (25, "<Q"), "total_lives_used": (33, "<B"),
    "total_bombs_used": (34, "<B"), "total_continues_used": (35, "<B"),
    "plr_char": (36, "<B"), "plr_shot": (37, "<B"),
    "plr_pos_x": (38, "<H"), "plr_pos_y": (40, "<H"),
    "plr_power": (42, "<H"), "plr_lives": (44, "<B"),
    "plr_life_frags": (45, "<H"), "plr_bombs": (47, "<B"),
    "plr_bomb_frags": (48, "<H"), "plr_inputflags": (50, "<B"),
    "plr_graze": (51, "<I"), "plr_piv": (55, "<I"),
    "plr_points_final": (59, "<Q"),
    "stage_lives_used": (67, "<B"), "stage_bombs_used": (68, "<B"),
    "stage_continues_used": (69, "<B"), "num_events": (70, "<H"),
    "checksum": (72, "<I"),
}


def stage_checksum(stg):
    """Metadata checksum for a v14 stage struct (rw_common.c), u32 wrap.

    Note the quirks: plr_total_continues_used is added TWICE (once in the
    v14 block, once in the v7+ block); start_time, plr_total_bombs_used,
    and the three *_final resource stats are NOT covered.
    """
    def g(fmt, off):
        return struct.unpack_from(fmt, stg, off)[0]
    cs = (
        g("<H", 4) + g("<Q", 14) + g("<B", 22) + g("<H", 23)
        + g("<Q", 25) + g("<B", 36) + g("<B", 37) + g("<H", 38)
        + g("<H", 40) + g("<H", 42) + g("<B", 44) + g("<H", 45)
        + g("<B", 47) + g("<H", 48) + g("<B", 50)
        + g("<H", 70)                    # num_events
        + g("<B", 33) + g("<B", 35)      # v14: total_lives_used, total_continues_used
        + g("<B", 35) + g("<I", 0)       # v7+: total_continues_used (again), flags
        + g("<I", 51) + g("<I", 55)      # v8+: graze, v9+: piv
        + g("<Q", 59)                    # v12+: points_final
    )
    return cs & 0xFFFFFFFF


def parse(path):
    data = open(path, "rb").read()
    if data[:10] != MAGIC:
        raise ValueError("%s: bad magic" % path)
    version, = struct.unpack_from("<H", data, 10)
    if version != VERSION:
        raise ValueError("%s: unsupported version 0x%04X (need 0x800E)" % (path, version))
    game_version = data[12:17]          # 5 bytes on the wire
    fileoffset, = struct.unpack_from("<I", data, 17)
    # decompressobj stops at the end of the first zstd frame (the meta frame);
    # stream_reader would choke on the 4-byte zero gap that follows it
    meta = zstd.ZstdDecompressor().decompressobj().decompress(data[21:fileoffset])
    off = 0
    nlen = meta[off]; off += 1
    name = meta[off:off + nlen]; off += nlen
    gflags, = struct.unpack_from("<I", meta, off); off += 4
    nstages, = struct.unpack_from("<H", meta, off); off += 2
    stages = []
    nevents = 0
    for idx in range(nstages):
        stg = meta[off:off + STAGE_SIZE]
        if len(stg) < STAGE_SIZE:
            raise ValueError("%s: truncated stage struct" % path)
        off += STAGE_SIZE
        nev, = struct.unpack_from("<H", stg, F["num_events"][0])
        nevents += nev
        stored, = struct.unpack_from("<I", stg, F["checksum"][0])
        cs = stage_checksum(stg)
        if (cs + stored) & 0xFFFFFFFF:
            raise ValueError("%s: stage %d checksum mismatch "
                             "(computed 0x%08X, stored 0x%08X)"
                             % (path, idx, cs, stored))
        stages.append(stg)
    events = zstd.ZstdDecompressor().decompressobj().decompress(data[fileoffset:-1])
    if len(events) != nevents * EVENT_SIZE:
        raise ValueError("%s: event size mismatch (%d bytes, want %d)"
                         % (path, len(events), nevents * EVENT_SIZE))
    return {
        "path": path, "gv": game_version, "name": name, "gflags": gflags,
        "stages": stages, "events": events,
    }


def merge(parts, out_path, playername=b"Laya"):
    gflags = 0
    any_cont = any(any(s[0:4] and struct.unpack("<I", s[0:4])[0] & S_CONTINUES
                       for s in p["stages"]) for p in parts)
    any_cheat = any(any(struct.unpack("<I", s[0:4])[0] & S_CHEATS
                        for s in p["stages"]) for p in parts)
    all_clear = all(struct.unpack("<I", s[0:4])[0] & S_CLEAR
                    for p in parts for s in p["stages"])
    if any_cont:
        gflags |= G_CONTINUES
    if any_cheat:
        gflags |= G_CHEATS
    if all_clear:
        gflags |= G_CLEAR

    name = playername if len(playername) < 255 else b"Laya"
    meta = bytes([len(name)]) + name + struct.pack("<IH", gflags, sum(len(p["stages"]) for p in parts))
    meta += b"".join(s for p in parts for s in p["stages"])
    events = b"".join(p["events"] for p in parts)

    cctx = zstd.ZstdCompressor(level=22)
    meta_z = cctx.compress(meta)
    events_z = cctx.compress(events)
    fileoffset = 21 + len(meta_z) + 4
    header = MAGIC + struct.pack("<H", VERSION) + parts[0]["gv"] + struct.pack("<I", fileoffset)
    with open(out_path, "wb") as f:
        f.write(header)
        f.write(meta_z)
        f.write(b"\x00" * 4)
        f.write(events_z)
        f.write(b"\x69")


def report(part):
    print("== %s ==" % part["path"])
    major, minor, patch, tweak = part["gv"][0], part["gv"][1], part["gv"][2], \
        struct.unpack("<H", part["gv"][3:5])[0]
    print("  game version: %d.%d.%d.%d  name=%r  gflags=0x%X"
          % (major, minor, patch, tweak, part["name"].decode("utf-8", "replace"), part["gflags"]))
    for i, stg in enumerate(part["stages"]):
        vals = {k: struct.unpack_from(fmt, stg, off)[0] for k, (off, fmt) in F.items()}
        fl = vals.pop("flags")
        sflags = []
        if fl & S_CONTINUES: sflags.append("CONT")
        if fl & S_CHEATS: sflags.append("CHEAT")
        if fl & S_CLEAR: sflags.append("CLEAR")
        print("  stage[%d]: id=%X diff=%d char=%d shot=%d lives=%d bombs=%d power=%d piv=%d "
              "pos=(%d,%d) events=%d flags={%s} score_final=%d stage_lives_used=%d stage_bombs_used=%d"
          % (i, vals["stage"], vals["diff"], vals["plr_char"], vals["plr_shot"],
             vals["plr_lives"], vals["plr_bombs"], vals["plr_power"], vals["plr_piv"],
             vals["plr_pos_x"], vals["plr_pos_y"], vals["num_events"],
             ",".join(sflags) or "-", vals["plr_points_final"],
             vals["stage_lives_used"], vals["stage_bombs_used"]))


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--parse":
        for p in sys.argv[2:]:
            report(parse(p))
        return
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    out, inputs = sys.argv[1], sys.argv[2:]
    parts = [parse(p) for p in inputs]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    merge(parts, out)
    merged = parse(out)
    print("merged %d stages from %d files -> %s (%d bytes, gflags=0x%X)"
          % (len(merged["stages"]), len(parts), out, os.path.getsize(out), merged["gflags"]))
    for i, stg in enumerate(merged["stages"]):
        vals = {k: struct.unpack_from(fmt, stg, off)[0] for k, (off, fmt) in F.items()}
        print("  stage[%d]: id=%X diff=%d seed=%d score=%d -> %d events=%d cs=OK"
              % (i, vals["stage"], vals["diff"], vals["rng_seed"],
                 vals["plr_points"], vals["plr_points_final"], vals["num_events"]))


if __name__ == "__main__":
    main()
