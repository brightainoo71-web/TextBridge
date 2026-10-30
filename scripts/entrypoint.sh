#!/bin/sh
set -e

echo "=== TextBridge Container Starting ==="

# Wait for PostgreSQL if configured
if [ "$DB_ENGINE" = "django.db.backends.postgresql" ] || [ -n "$DATABASE_URL" ]; then
    echo "Waiting for PostgreSQL database to accept connections..."
    while ! nc -z ${DB_HOST:-db} ${DB_PORT:-5432}; do
        sleep 0.5
    done
    echo "PostgreSQL is reachable!"
fi

# Run database migrations
echo "Applying database migrations..."
python manage.py migrate --noinput

# Collect static assets into STATIC_ROOT
echo "Collecting static assets..."
python manage.py collectstatic --noinput

echo "=== System Initialization Complete ==="

# Execute the main container command (Gunicorn or Celery)
exec "$@"
