@echo off
REM FetchOrigin.bat
REM Di chuyen toi thu muc repo
cd /d C:\Users\Admin\Documents\ktbproject

REM Lay du lieu moi nhat tu GitHub
git fetch origin

REM Reset ve commit moi nhat tren branch main
git reset --hard origin/main

echo.
echo Repo da duoc dong bo tu GitHub ve thanh cong!
pause
