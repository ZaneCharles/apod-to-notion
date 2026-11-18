@echo off
REM Run apod_to_notion.py and append output to apod_log.txt
REM (comments in English on purpose: cmd.exe may garble Chinese in .bat files)
cd /d "%~dp0"
set PYTHONUTF8=1
echo ===== %date% %time% ===== >> apod_log.txt
python apod_to_notion.py >> apod_log.txt 2>&1
