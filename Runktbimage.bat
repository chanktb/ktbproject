@echo off
REM =================================================================
REM                      CAU HINH BAN DAU
REM =================================================================
REM Chuyen console sang che do UTF-8 de hien thi tieng Viet chinh xac.
chcp 65001 >nul

REM Buoc Python su dung UTF-8, giai quyet triet de loi UnicodeEncodeError.
set PYTHONUTF8=1

REM Dat tieu de cho cua so terminal.
title ktbimage

REM Lấy thư mục hiện tại của file .bat
cd /d "%~dp0"

REM Chạy module Python
python -m ktbimage.main

pause