@echo off
cd /d "%~dp0"
git add .
git commit -m "Update PC"
git push origin main --force
pause