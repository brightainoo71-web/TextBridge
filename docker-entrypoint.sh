#!/bin/sh
set -e

echo "[TextBridge Entrypoint] Initializing production container environment..."

# Wait for PostgreSQL database if DB_HOST is set
if [ -n "$DB_HOST" ]; then
    echo "[TextBridge Entrypoint] Waiting for database at $DB_HOST:${DB_PORT:-5432}..."
    while ! nc -z "$DB_HOST" "${DB_PORT:-5432}"; do
        sleep 0.5
    done
    echo "[TextBridge Entrypoint] Database is ready and accepting connections."
fi

# Run database migrations automatically in web container
if [ "$1" = "gunicorn" ] || [ "$1" = "python" ]; then
    echo "[TextBridge Entrypoint] Running database migrations..."
    python manage.py migrate --noinput

    echo "[TextBridge Entrypoint] Collecting static assets..."
    python manage.py collectstatic --noinput --clear || true

    echo "[TextBridge Entrypoint] Database and static files initialized successfully."
fi

# Execute the main container command
echo "[TextBridge Entrypoint] Starting process: $@"
exec "$@"
