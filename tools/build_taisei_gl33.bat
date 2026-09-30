@echo off
rem Build taisei-sim with MinGW-w64 GCC (MSYS2 packages in third_party\mingw) via meson,
rem WITH the OpenGL 3.3 renderer (r_gl33) enabled, for the M4 video.
rem
rem Produces BOTH targets from one libtaisei core:
rem   - libtaisei_sim.dll : headless sim C API (renderer hardcoded null) -> drives the campaign
rem   - taisei.exe        : renderers + replay -> records the video (taisei.exe --renderer gl33)
rem
rem Buildtype = debugoptimized (-O2) so replay playback runs a smooth 60 fps (the -O0 debug
rem build is too slow for a real-time video on the i7-10610U / Intel UHD). gl33 needs only
rem ~15 C files + the vendored glad loader -- it does NOT require the shader transpiler
rem (only gles30/sdlgpu do), so glslang/SPIRV-Cross/shaderc stay disabled (lighter build).
rem
rem Builds into a NEW dir (build-gl33) so the existing -O0 headless build (build/) is left
rem intact for reference / the earlier tuning campaigns.
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "SRC=%ROOT%\third_party\taisei-sim"
set "BUILDDIR=%SRC%\build-gl33"

rem 1) MinGW GCC (mingw64) + gettext tools (xgettext/msgfmt) + venv tools (meson, ninja)
set "PATH=%ROOT%\third_party\mingw\mingw64\bin;%ROOT%\third_party\gettext\mingw64\bin;%ROOT%\venv\Scripts;%PATH%"
rem Make meson (and the CMake SDL3 subproject) pick MinGW GCC
set "CC=gcc"
set "CXX=g++"

rem 2) Configure.
rem    - allocator=libc : use the system allocator, NOT mimalloc. The meson default
rem      'auto' resolves to mimalloc on Windows, which overrides the global
rem      malloc/free and crashed the exe with an access violation at window creation
rem      (0xC0000005). The stock 1.4.6 release build does NOT embed mimalloc
rem      (verified: 0 mimalloc symbols in the stock exe), so match it. See
rem      doc/research-gl33-build.md.
rem    - c_link_args=-static : statically link the MinGW runtime (libgcc_s_seh,
rem      libwinpthread, libstdc++, zlib) into the exe/DLL. Without it the exe
rem      exits 0xC0000135 (STATUS_DLL_NOT_FOUND) when launched without
rem      mingw64\bin on PATH (measured 2026-09-25: objdump -p on the dynamic
rem      build). The official v1.4.6 Windows CI build also uses -static
rem      (misc/ci/windows-llvm_mingw-x86_64-build-release.ini).
rem      The final taisei executable uses Meson's cpp_LINKER rule, so both
rem      language-specific link-args options are required.
rem    - Fresh dir -> 'meson setup'; existing dir -> 'meson setup --reconfigure'
rem      so option changes (like this allocator fix) are applied on re-run.
if exist "%BUILDDIR%\meson-private\coredata.dat" (
    set SETUP_OPT=--reconfigure
) else (
    set SETUP_OPT=
)
echo [build] meson setup %SETUP_OPT% ...
rem use_libpng=enabled makes dep_png REQUIRED so meson takes the subprojects/libpng
rem fallback; a soft/auto dep is not searched. native-win.ini forces plain ar/ranlib
rem (gcc-ar wrapper breaks relative paths under ninja).
meson setup %SETUP_OPT% "%BUILDDIR%" "%SRC%" --native-file "%ROOT%\tools\native-win.ini" ^
    -Dbuildtype=debugoptimized ^
    -Duse_libpng=enabled ^
    -Dallocator=libc ^
    -Dc_link_args=-static ^
    -Dcpp_link_args=-static ^
    -Dr_default=null -Dr_null=enabled -Dr_gl33=enabled -Dr_gles30=disabled -Dr_sdlgpu=disabled ^
    -Da_default=null -Da_null=enabled -Da_sdl=disabled ^
    -Dshader_transpiler=disabled -Dvalidate_glsl=disabled ^
    -Dtests=disabled -Ddocs=disabled ^
    -Ddeveloper=false
if errorlevel 1 goto :err

rem 3) Compile
echo [build] meson compile ...
meson compile -C "%BUILDDIR%" -j4
if errorlevel 1 goto :err

echo [build] OK
exit /b 0

:err
echo [build] FAILED
exit /b 1
