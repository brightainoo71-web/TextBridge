# syntax=docker/dockerfile:1
# TextBridge Production Dockerfile
# Multi-stage, non-root, hardened Python 3.12 image

FROM python:3.12-slim-bookworm AS base

# Set environment flags
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install essential system dependencies and PostgreSQL client libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create a dedicated non-root application user
RUN groupadd -g 1000 textbridge && \
    useradd -u 1000 -g textbridge -s /bin/bash -m textbridge

# Copy dependency requirements
COPY requirements.txt /app/

# Install Python production dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application codebase
COPY . /app/

# Ensure runtime directories exist with appropriate ownership
RUN mkdir -p /app/staticfiles /app/media /app/logs && \
    chown -R textbridge:textbridge /app

# Make the startup entrypoint executable
RUN chmod +x /app/docker-entrypoint.sh

# Switch to non-root user
USER textbridge

# Expose Gunicorn application port
EXPOSE 8000

# Default entrypoint and command
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
