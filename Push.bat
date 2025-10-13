@echo off
REM === Tự động commit và push code lên GitHub ===

cd /d "%~dp0"
echo Đang thêm thay đổi...
git add .

echo.
echo Tạo commit...
git commit -m "Update PC"

echo.
echo Đẩy lên branch main...
git push origin main

echo.
echo ✅ Hoàn tất! Đã push lên GitHub.
pause