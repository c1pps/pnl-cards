@echo off
cd /d %~dp0
python -m pip install -q -r requirements.txt
python -c "import extract_terminal,sys; sys.exit(0 if extract_terminal._find_tesseract() else 1)"
if errorlevel 1 (
  echo.
  echo Tesseract est introuvable. C'est le moteur qui lit les images.
  echo Installe-le avec cette commande puis relance start.bat :
  echo     winget install --id UB-Mannheim.TesseractOCR
  echo ou telecharge : https://github.com/UB-Mannheim/tesseract/wiki
  echo.
  pause
  exit /b
)
start "" http://127.0.0.1:5173
python app.py
pause
