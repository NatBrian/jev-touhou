@echo off
rem Wipe + fresh meson setup with the standard flag set, then compile.
setlocal
set "ROOT=%~dp0.."
set "SRC=%ROOT%\third_party\taisei-sim"
set "BUILDDIR=%SRC%\build"
set "PATH=%ROOT%\third_party\mingw\mingw64\bin;%ROOT%\third_party\gettext\mingw64\bin;%ROOT%\venv\Scripts;%PATH%"
set "CC=gcc"
set "CXX=g++"
rem Suppress CMake dev-level policy warnings (CMP0200 etc.): their text lines
crash meson's CMake trace parser (JSONDecodeError) when a cmake subproject
is analysed.
set "CMAKE_ARGS=-DCMAKE_POLICY_WARNING_DEV=NO"
cd /d "%ROOT%"
meson setup --wipe "%BUILDDIR%" "%SRC%" --native-file tools\native-win.ini ^
    -Dbuildtype=debug ^
    -Duse_libpng=enabled ^
    -Dr_default=null -Dr_null=enabled -Dr_gl33=disabled -Dr_gles30=disabled -Dr_sdlgpu=disabled ^
    -Da_default=null -Da_null=enabled -Da_sdl=disabled ^
    -Dshader_transpiler=disabled -Dvalidate_glsl=disabled ^
    -Dtests=disabled -Ddocs=disabled ^
    -Ddeveloper=false
if errorlevel 1 goto :err
meson compile -C "%BUILDDIR%" -j4
if errorlevel 1 goto :err
echo [build] OK
exit /b 0
:err
echo [build] FAILED
exit /b 1
