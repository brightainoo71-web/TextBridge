# TextBridge Production Deployment Guide

This guide covers deploying **TextBridge** to any Linux Cloud Server (Ubuntu 22.04 / 24.04 on DigitalOcean, AWS EC2, Linode, or Hetzner) using Docker Compose, PostgreSQL 16, Redis 7, Celery, and Nginx.

---

## 1. Cloud Server Prerequisites

1. An Ubuntu 22.04 / 24.04 LTS server (minimum 2GB RAM recommended).
2. A registered domain pointing to your server's public IP (e.g., `A` record for `app.yourdomain.com`).
3. Docker & Docker Compose installed:
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   sudo usermod -aG docker $USER
   ```

---

## 2. Server Deployment in 4 Commands

### Step 1: Clone your repository on the server
```bash
git clone <your-repo-url> /opt/textbridge
cd /opt/textbridge
```

### Step 2: Configure Production Environment Variables
```bash
cp .env.production.example .env
nano .env
```
Update the following values:
- `SECRET_KEY`: Generate a random 50-character string.
- `ALLOWED_HOSTS`: Set to your live domain, e.g. `app.yourdomain.com,yourdomain.com`.
- `CSRF_TRUSTED_ORIGINS`: Set to `https://app.yourdomain.com`.
- `DB_PASSWORD`: Set a secure password for PostgreSQL.
- `PAYSTACK_PUBLIC_KEY` & `PAYSTACK_SECRET_KEY`: Put your live Paystack production keys when ready to collect real money.

### Step 3: Launch Containers with Docker Compose
```bash
docker compose up -d --build
```
This single command builds and starts:
- `textbridge_postgres`: PostgreSQL 16 database with persistent storage.
- `textbridge_redis`: In-memory broker for campaign message queues.
- `textbridge_web`: Gunicorn WSGI server handling HTTP traffic.
- `textbridge_celery_worker`: Background worker processing SMS dispatches.
- `textbridge_celery_beat`: Background scheduler executing scheduled campaigns.
- `textbridge_nginx`: Reverse proxy serving static files and routing traffic.

### Step 4: Create Superadministrator Account
```bash
docker compose exec web python manage.py createsuperuser
```
Enter your administrator email and password.

---

## 3. Adding Free SSL HTTPS (Let's Encrypt / Certbot)

Install Certbot on the host server:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d app.yourdomain.com
```
Certbot will automatically obtain an SSL certificate and configure HTTPS auto-renewal.

---

## 4. Webhook URLs Configuration

After your domain is active with HTTPS, set these webhook URLs in your provider dashboards:

1. **Paystack Dashboard** (`https://dashboard.paystack.com` &rarr; Settings &rarr; API Keys & Webhooks):
   ```
   https://app.yourdomain.com/billing/webhook/paystack/
   ```

2. **mNotify Dashboard** (`https://mnotify.com` &rarr; Settings &rarr; Delivery Reports Callback):
   ```
   https://app.yourdomain.com/messaging/webhook/mnotify/
   ```

---

## 5. Maintenance Commands

- **View live server logs**: `docker compose logs -f web`
- **View Celery broadcast worker logs**: `docker compose logs -f worker`
- **Restart all services**: `docker compose restart`
- **Stop all services**: `docker compose down`
- **Database backup**:
  ```bash
  docker compose exec -T db pg_dump -U textbridge_user textbridge_db > backup_$(date +%F).sql
  ```
