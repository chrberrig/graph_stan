#!/usr/bin/env bash
set -euo pipefail

VENV_NAME=".venv"

if [[ ! -d "$VENV_NAME" ]]; then
  python3 -m venv "$VENV_NAME"
  echo "Virtual environment $VENV_NAME created"
fi

echo "activating virtual environment"
# 'source' is a bash builtin
source "$VENV_NAME/bin/activate"

# Now pip is the venv pip
python -m pip install --upgrade pip
pip install -r requirements.txt

