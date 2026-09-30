"""Vectored-exception crash hook for the taisei-sim ctypes smoke tests.

Installs a top-level Windows exception handler that, on any exception, records:
  - exception code, faulting instruction address, info[0..1]
  - every loaded module (name, base, size) and the one containing the address
  - if the fault is inside taisei.exe: nearest COFF symbol + offset, plus
    nearby symbols for context

The exception is NOT swallowed (handler returns EXCEPTION_CONTINUE_SEARCH),
so the normal OSError propagation in ctypes still happens.

Usage:
    from crash_hook import install
    install(exe_path, r"C:\...\crash.txt")
"""
import ctypes
import struct
import sys

EXCEPTION_CONTINUE_SEARCH = 0


def _parse_coff_symbols(exe_path):
    """Return list of (rva, name) sorted by rva from the exe's COFF table."""
    data = open(exe_path, "rb").read()
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    coff = pe_off + 4
    (_machine, _num_sec, _ts, sym_ptr, nsym, _opt, _ch) = struct.unpack_from(
        "<HHIIIHH", data, coff)
    if sym_ptr == 0 or nsym == 0:
        return []
    base = sym_ptr
    names_off = base + nsym * 18
    out = []
    for i in range(nsym):
        off, _sec, value, _len, stored = struct.unpack_from("<IBIIH", data, base + i * 18)
        if value == 0:
            continue
        name = None
        try:
            if off:
                end = data.find(b"\x00", names_off + off)
                name = data[names_off + off:end].decode("utf-8", "replace")
            elif stored:
                l, n = struct.unpack_from("<IB", data, names_off + off)
                name = data[names_off + off + 1:names_off + off + 1 + n].decode("utf-8", "replace")
        except Exception:
            continue
        if name:
            out.append((value, name))
    out.sort()
    return out


class _MODULEINFO(ctypes.Structure):
    _fields_ = [("lpBaseOfDll", ctypes.c_void_p),
                ("SizeOfImage", ctypes.c_uint32),
                ("EntryPoint", ctypes.c_void_p)]


class CrashHook:
    def __init__(self, exe_path, log_path, module_name=None):
        import os
        self.exe_path = exe_path
        self.log_path = log_path
        self.module_name = module_name or os.path.basename(exe_path)
        self.symbols = _parse_coff_symbols(exe_path)
        self.k32 = ctypes.windll.kernel32
        self.psapi = ctypes.windll.psapi
        self.k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        self.k32.GetModuleHandleW.restype = ctypes.c_void_p
        self.k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        self.k32.OpenProcess.restype = ctypes.c_void_p
        self.psapi.EnumProcessModules.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        self.psapi.EnumProcessModules.restype = ctypes.c_bool
        self.psapi.GetModuleInformation.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_MODULEINFO), ctypes.c_uint32]
        self.psapi.GetModuleInformation.restype = ctypes.c_bool
        self.psapi.GetModuleBaseNameW.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
        self.psapi.GetModuleBaseNameW.restype = ctypes.c_uint32
        self.k32.GetCurrentProcess.restype = ctypes.c_void_p
        self.k32.AddVectoredExceptionHandler.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        self._cbtype = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
        self._handler = self._cbtype(self._on_exception)
        self.k32.AddVectoredExceptionHandler(0, self._handler)
        self._log("crash hook installed; symbols=%d" % len(self.symbols))

    def _log(self, msg):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def _modules(self):
        """Return list of (base, size, name) for all loaded modules."""
        out = []
        hproc = self.k32.OpenProcess(0x1000 | 0x0400, False,
                                     self.k32.GetCurrentProcess())
        if not hproc:
            return out
        buf = (ctypes.c_void_p * 4096)()
        cb = ctypes.c_uint32(len(buf) * 8)
        if self.psapi.EnumProcessModules(hproc, buf, ctypes.byref(cb), None):
            n = cb.value // 8
            for i in range(n):
                h = buf[i]
                mi = _MODULEINFO()
                if self.psapi.GetModuleInformation(hproc, h, ctypes.byref(mi),
                                                   ctypes.sizeof(_MODULEINFO)):
                    namebuf = ctypes.create_unicode_buffer(256)
                    self.psapi.GetModuleBaseNameW(hproc, h, namebuf, 256)
                    out.append((mi.lpBaseOfDll, mi.SizeOfImage, namebuf.value))
        self.k32.CloseHandle(hproc)
        return out

    def _resolve(self, rva):
        import bisect
        rv = [r for r, _ in self.symbols]
        i = bisect.bisect_right(rv, rva) - 1
        if i < 0:
            return None
        best = (self.symbols[i][0], self.symbols[i][1])
        near = [n for r, n in self.symbols[max(0, i - 3):i + 4] if r != best[0]]
        return best, near

    def _on_exception(self, ptr):
        if not ptr:
            return EXCEPTION_CONTINUE_SEARCH
        rec = ctypes.c_uint64.from_address(ptr).value   # PEXCEPTION_RECORD
        code = ctypes.c_uint32.from_address(rec).value
        addr = ctypes.c_uint64.from_address(rec + 16).value
        nparams = ctypes.c_uint32.from_address(rec + 24).value
        info = []
        for k in range(min(nparams, 4)):
            info.append(ctypes.c_uint64.from_address(rec + 32 + 8 * k).value)
        lines = ["EXCEPTION code=%08X addr=%012X params=%d info=%s"
                 % (code, addr, nparams, ["%016X" % x for x in info])]
        for mbase, msize, mname in self._modules():
            if mbase and mbase <= addr < mbase + msize:
                delta = addr - mbase
                lines.append("  module: %s base=%012X size=%X delta=%08X"
                             % (mname, mbase, msize, delta))
                if mname.lower() == self.module_name.lower() and self.symbols:
                    res = self._resolve(delta)
                    if res:
                        r, nm = res[0], res[1]
                        lines.append("  symbol: %s (+0x%X)" % (nm, delta - r))
                        lines.append("  nearby: %s" % ", ".join(res[1][:8]))
                break
        else:
            lines.append("  (no module contains the fault address)")
        self._log("\n".join(lines))
        return EXCEPTION_CONTINUE_SEARCH

    def close(self):
        self.k32.RemoveVectoredExceptionHandler(self._handler)


def install(exe_path, log_path, module_name=None):
    return CrashHook(exe_path, log_path, module_name)
