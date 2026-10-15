@echo off
"%~dp0runtime\python.exe" "%~dp0backend\engine.py" --doctor
exit /b %errorlevel%
