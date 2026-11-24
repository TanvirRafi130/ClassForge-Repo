#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "Setting up ClassForge..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
[ -f .profile ] || cp .profile.example .profile
echo
echo "Done. Edit .profile to pick a notes engine, then run ./run.sh"
