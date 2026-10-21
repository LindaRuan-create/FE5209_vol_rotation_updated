#!/bin/zsh
cd "$(dirname "$0")" || exit 1
run_status=0

if [[ ! -x .venv/bin/python ]]; then
  echo 'First run: creating the local Python environment...'
  if ! command -v python3 >/dev/null 2>&1; then
    echo 'Python 3.10 or later is required. Install Python, then double-click this file again.'
    run_status=1
  else
    python3 -m venv .venv
    run_status=$?
  fi
fi

if [[ $run_status -eq 0 ]]; then
  if ! .venv/bin/python -c "import importlib.util, sys; packages = ['IPython', 'numpy', 'pandas', 'matplotlib', 'scipy', 'statsmodels', 'arch', 'yfinance']; sys.exit(any(importlib.util.find_spec(p) is None for p in packages))" >/dev/null 2>&1; then
    echo 'Installing project dependencies. Internet access is required for this first-time setup...'
    .venv/bin/python -m pip install -r requirements.txt
    run_status=$?
  fi
fi

if [[ $run_status -eq 0 ]]; then
  .venv/bin/python run_all.py
  run_status=$?
fi

if [[ $run_status -eq 0 ]]; then
  open results/Report.html
else
  echo 'Run failed. No new completed report is confirmed.'
  echo 'See the error above, results/logs, and the setup instructions in README.md.'
fi
read '?Press Enter to close the window'
