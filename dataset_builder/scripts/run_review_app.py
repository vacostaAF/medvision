import subprocess, sys
raise SystemExit(subprocess.call([sys.executable,'-m','streamlit','run','app/review_app.py']))
