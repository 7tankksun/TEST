@echo off
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
streamlit run app.py --server.address 127.0.0.1 --server.port 8509
