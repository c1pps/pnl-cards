#!/bin/sh
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
(sleep 2; python3 -m webbrowser http://127.0.0.1:5173) &
python3 app.py
