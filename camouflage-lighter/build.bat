@echo off
chcp 65001 >nul
echo Installing Python dependencies...
pip install -r requirements.txt -q
echo Building lighter EXE...
pyinstaller --onefile --windowed --name "Camouflage" --add-data "native;native" --add-data "mesh-profiles;mesh-profiles" --distpath "." --noconfirm main.py
echo.
echo Build done. Output: Camouflage.exe
