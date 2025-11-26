#!/usr/bin/env bash
set -o errexit

# 1) Install deps
pip install -r requirements.txt

# 2) Django collectstatic + migrations
python manage.py collectstatic --noinput
python manage.py migrate --noinput
