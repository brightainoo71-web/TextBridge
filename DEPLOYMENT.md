# 🚀 TextBridge Production Deployment & Dockerization Guide

This guide details the complete production architecture, deployment instructions, and maintenance procedures for hosting **TextBridge**—the multi-tenant telecom SMS SaaS platform in Ghana.

---

## 🏗️ 1. Architecture Overview

TextBridge runs on a containerized microservice topology orchestrated via Docker Compose:

```
                      [ Internet / HTTPS (Port 443) ]
                                    │
                                    ▼
                     ┌─────────────────────────────┐
                     │   Nginx Reverse Proxy &     │
                     │   SSL Termination (Rate-Ltd)│
                     └──────────────┬──────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │ /static/, /media/   │ Dynamic HTTP / API  │
              ▼                     ▼                     ▼
     ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
     │ Static Volumes  │   │ Gunicorn + Web  │   │ Certbot ACME    │
     │ (WhiteNoise/CSS)│   │ (Django Core)   │   │ SSL Renewals    │
     └─────────────────┘   └────────┬────────┘   └─────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
     ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
     │  PostgreSQL 16  │   │  Redis 7-Alpine │   │ Celery Workers  │
     │  Database       │   │  Cache & Broker │   │ & Beat Runner   │
     └─────────────────┘   └─────────────────┘   └─────────────────┘
```

### Components

| Service | Technology | Role |
| :--- | :--- | :--- |
| **`web`** | Python 3.12 + Gunicorn | Serves web views, tenant dashboard, and REST API |
| **`celery_worker`** | Celery 5.4 (4 processes) | Asynchronous bulk telecom SMS dispatching & webhooks |
| **`celery_beat`** | Celery Beat Scheduler | Dispatches scheduled campaigns (every 60s) & birthday SMS |
| **`db`** | PostgreSQL 16 Alpine | Persistent database with row-level locked credit ledger |
| **`redis`** | Redis 7 Alpine | High-speed cache and asynchronous message broker |
| **`nginx`** | Nginx Alpine | Reverse proxy, SSL, gzip compression, and rate limiting |

---

## 🖥️ 2. Recommended Server Specifications

For production handling up to 500,000 SMS broadcasts/month:

- **OS**: Ubuntu 22.04 LTS or 24.04 LTS (x86_64)
- **CPU**: 2 vCPUs
- **RAM**: 4 GB RAM (minimum 2 GB with 2 GB swap)
- **Disk**: 40 GB NVMe SSD
- **Providers**: DigitalOcean Droplet ($24/mo), Hetzner Cloud (€5/mo), Linode, or AWS EC2 `t3.medium`

---

## ⚡ 3. Step-by-Step VPS Deployment

### Step 1: Install Docker & Docker Compose on Ubuntu

Connect to your VPS via SSH as `root`:

```bash
# Update package repositories
sudo apt update && sudo apt upgrade -y

# Install Docker Engine & Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Verify Docker installation
docker --version
docker compose version
```

---

### Step 2: Clone the TextBridge Repository

```bash
cd /opt
sudo git clone https://github.com/brightainoo71-web/TextBridge.git
cd TextBridge
```

---

### Step 3: Configure Environment Secrets

Copy the production environment template:

```bash
cp .env.production.example .env
nano .env
```

Set the following critical values:

1. **`SECRET_KEY`**: Generate a strong 50-character random string:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(50))"
   ```
2. **`ALLOWED_HOSTS`**: Set your domain (e.g. `textbridge.app,www.textbridge.app`).
3. **`CSRF_TRUSTED_ORIGINS`**: Set `https://textbridge.app,https://www.textbridge.app`.
4. **`DB_PASSWORD`**: Choose a secure database password.
5. **`ACTIVE_SMS_PROVIDER`**: Set to `MNOTIFY` and enter your live `MNOTIFY_API_KEY`.
6. **`PAYMENT_SANDBOX_MODE`**: Set to `False` and enter your live `PAYSTACK_PUBLIC_KEY` & `PAYSTACK_SECRET_KEY`.
7. **`GMAIL_USER` & `GMAIL_APP_PASSWORD`**: Set for transactional email receipts.

Save and exit (`Ctrl + O`, `Enter`, `Ctrl + X`).

---

### Step 4: Build & Launch Containers

Run the build and startup command in detached mode:

```bash
docker compose up -d --build
```

Monitor container health and startup logs:

```bash
docker compose ps
docker compose logs -f web
```

The `docker-entrypoint.sh` script will automatically:
- Wait for PostgreSQL to become healthy.
- Apply all database migrations (`migrate`).
- Collect and compress static assets (`collectstatic`).
- Start the Gunicorn WSGI application on port 8000.

---

### Step 5: Create Platform Superadmin Account

Create the administrative account to access the TextBridge Admin Console:

```bash
docker compose exec web python manage.py createsuperuser
```

Enter your admin email (e.g. `admin@textbridge.app`) and a strong password.

---

### Step 6: SSL / HTTPS Configuration (Let's Encrypt)

Install Certbot on the host to obtain free trusted SSL certificates:

```bash
sudo apt install -y certbot

# Obtain SSL Certificate (replace textbridge.app with your domain)
sudo certbot certonly --webroot -w /opt/TextBridge/nginx -d textbridge.app -d www.textbridge.app --email admin@textbridge.app --agree-tos --non-interactive
```

Update `nginx/nginx.conf` with your certificate paths:
```nginx
server {
    listen 443 ssl http2;
    server_name textbridge.app www.textbridge.app;

    ssl_certificate /etc/letsencrypt/live/textbridge.app/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/textbridge.app/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ...
}
```

Reload Nginx:
```bash
docker compose exec nginx nginx -s reload
```

---

## 🛠️ 4. Operational Maintenance & Commands

### Viewing Live Logs

```bash
# Web application logs
docker compose logs -f web

# Celery background workers
docker compose logs -f celery_worker

# Celery automated scheduler
docker compose logs -f celery_beat

# PostgreSQL logs
docker compose logs -f db
```

### Running Management Commands Inside Containers

```bash
# Process scheduled campaigns manually
docker compose exec web python manage.py process_scheduled_campaigns

# Run daily birthday SMS greetings (Dry Run)
docker compose exec web python manage.py dispatch_birthday_sms --dry-run

# Run daily birthday SMS greetings (Live Dispatch)
docker compose exec web python manage.py dispatch_birthday_sms
```

### Automated Database Backups (Cron Job)

Create a backup script `/opt/backup_textbridge.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/textbridge"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
FILENAME="$BACKUP_DIR/textbridge_db_$TIMESTAMP.sql.gz"

docker compose -f /opt/TextBridge/docker-compose.yml exec -T db pg_dump -U textbridge_user textbridge_db | gzip > "$FILENAME"

# Retain backups for 30 days
find "$BACKUP_DIR" -type f -name "*.sql.gz" -mtime +30 -delete
echo "Backup saved to $FILENAME"
```

Make executable and add to crontab:
```bash
chmod +x /opt/backup_textbridge.sh
crontab -e
# Add line to run daily at 02:00 AM:
0 2 * * * /opt/backup_textbridge.sh >> /var/log/textbridge_backup.log 2>&1
```

---

## ☁️ 5. Alternative Cloud PaaS Deployment (Render / Railway)

If you prefer a fully managed PaaS without managing a Linux server:

### Deploying to Render.com
1. Create a **PostgreSQL** database on Render (Starter or Standard tier).
2. Create a **Redis** instance on Render.
3. Create a **Web Service** on Render connected to `brightainoo71-web/TextBridge`:
   - Environment: `Python 3`
   - Build Command: `pip install -r requirements.txt && python manage.py collectstatic --noinput`
   - Start Command: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3`
4. Set Environment Variables in the Render Dashboard matching `.env.production.example`.
5. Create a **Background Worker** on Render for Celery:
   - Start Command: `celery -A config worker -l info --concurrency=4`
