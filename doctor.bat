@echo off
chcp 65001 >nul
setlocal
if not defined COMFYUI_PYTHON (
  echo 请使用 ComfyUI 的 Python 执行 scripts\check_standalone.py
  echo 或设置 COMFYUI_PYTHON 指向那个 python.exe。
  pause
  exit /b 1
)
"%COMFYUI_PYTHON%" "%~dp0scripts\check_standalone.py" %*
pause
