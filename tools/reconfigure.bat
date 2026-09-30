@echo off
rem Reconfigure the existing meson build dir with the standard flag set.
setlocal
set "ROOT=%~dp0.."
set "SRC=%ROOT%\third_party\taisei-sim"
set "BUILDDIR=%SRC%\build"
set "PATH=%ROOT%\third_party\mingw\mingw64\bin;%ROOT%\third_party\gettext\mingw64\bin;%ROOT%\venv\Scripts;%PATH%"
set "CC=gcc"
set "CXX=g++"
rem Suppress CMake dev-level policy warnings (CMP0200 etc.): their text lines
crash meson's CMake trace parser (JSONDecodeError, "Unhandled python
exception") when a cmake subproject is re-analysed. CMAKE_ARGS is picked up
by every CMake invocation, incl. the sdl3-cmake-wrapper subproject.
set "CMAKE_ARGS=-DCMAKE_POLICY_WARNING_DEV=NO"
cd /d "%ROOT%"
meson setup --reconfigure "%BUILDDIR%" "%SRC%" --native-file tools\native-win.ini ^
    -Dbuildtype=debug ^
    -Duse_libpng=enabled ^
    -Dr_default=null -Dr_null=enabled -Dr_gl33=disabled -Dr_gles30=disabled -Dr_sdlgpu=disabled ^
    -Da_default=null -Da_null=enabled -Da_sdl=disabled ^
    -Dshader_transpiler=disabled -Dvalidate_glsl=disabled ^
    -Dtests=disabled -Ddocs=disabled ^
    -Ddeveloper=false
exit /b %errorlevel%
