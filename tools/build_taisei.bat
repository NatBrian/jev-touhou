@echo off
rem Build taisei-sim with MinGW-w64 GCC (MSYS2 packages in third_party\mingw)
rem via meson. MinGW because taisei's C code uses VLAs / GCC idioms that MSVC
rem rejects, and official Taisei Windows releases are MinGW-built.
rem
rem Headless sim build: only the null renderer + null audio are enabled,
rem which avoids the heavy glslang / SPIRV-Cross / shaderc C++ dependencies.
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "SRC=%ROOT%\third_party\taisei-sim"
set "BUILDDIR=%SRC%\build"

rem 1) MinGW GCC (mingw64) + gettext tools (xgettext/msgfmt) + venv tools (meson, ninja)
set "PATH=%ROOT%\third_party\mingw\mingw64\bin;%ROOT%\third_party\gettext\mingw64\bin;%ROOT%\venv\Scripts;%PATH%"
rem Make meson (and the CMake SDL3 subproject) pick MinGW GCC
set "CC=gcc"
set "CXX=g++"

rem 2) Configure (skip if already configured; modern meson keeps coredata.dat in meson-private)
if not exist "%BUILDDIR%\meson-private\coredata.dat" (
    echo [build] meson setup ...
    rem use_libpng=enabled makes dep_png REQUIRED so meson takes the
    subprojects/libpng fallback; a soft/auto dep is not searched.
    rem native-win.ini forces plain ar/ranlib (gcc-ar wrapper breaks under ninja).
    meson setup "%BUILDDIR%" "%SRC%" --native-file tools\native-win.ini ^
        -Dbuildtype=debug ^
        -Duse_libpng=enabled ^
        -Dr_default=null -Dr_null=enabled -Dr_gl33=disabled -Dr_gles30=disabled -Dr_sdlgpu=disabled ^
        -Da_default=null -Da_null=enabled -Da_sdl=disabled ^
        -Dshader_transpiler=disabled -Dvalidate_glsl=disabled ^
        -Dtests=disabled -Ddocs=disabled ^
        -Ddeveloper=false
    if errorlevel 1 goto :err
)

rem 3) Compile
echo [build] meson compile ...
meson compile -C "%BUILDDIR%" -j4
if errorlevel 1 goto :err

echo [build] OK
exit /b 0

:err
echo [build] FAILED
exit /b 1
