#!/bin/sh
set -e
python manage.py collectstatic --noinput || true
python manage.py migrate --noinput
exec "$@"
