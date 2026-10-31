# TextBridge — Multi-Business SMS SaaS Platform

[![Python](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.1-green.svg)](https://www.djangoproject.com/)
[![Market](https://img.shields.io/badge/Market-Ghana%20(GHS)-gold.svg)]()
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)]()

**BrightSMS** (name configurable via `PLATFORM_NAME`) is a production-oriented, multi-tenant bulk SMS messaging SaaS platform designed for gyms, schools, churches, retail businesses, healthcare clinics, and SMEs. It empowers businesses to purchase SMS credit packages in Ghanaian Cedi (GH₵ / GHS) and broadcast personalized campaigns to their customer base through a responsive, mobile-first web interface without interacting directly with external telecom APIs.

---

## 1. Key Architectural Features

- **Multi-Tenant Workspace Isolation**: Every registered business operates in a strictly isolated workspace. Views, models, forms, and exports enforce tenant boundaries.
- **Accurate Ghanaian Phone Normalization**: Automatically normalizes and validates Ghanaian phone numbers (MTN, Telecel/Vodafone, AT/AirtelTigo, Glo) into standard international E.164 format (`233XXXXXXXXX`).
- **Spreadsheet Importer (CSV & Excel .xlsx)**: Upload customer contacts with preview, column mapping, duplicate detection, invalid number rejection, and downloadable error reports.
- **Auditable Credit Ledger & Concurrency Safety**: Financial-grade ledger (`CreditLedgerEntry`) with row-level locking (`select_for_update`) to prevent race conditions, double-spending, negative balances, and duplicate webhook credits.
- **Telecom SMS Segmentation Calculator**: Real-time GSM 7-bit (160 chars) and Unicode / UCS-2 (70 chars) character counting with dynamic cost estimation and personalization tags (`{{name}}`, `{{first_name}}`, `{{phone}}`).
- **Dual-Mode SMS Integration**:
  - **Mock Sandbox Provider**: Simulates gateway acceptance, delivery, network timeouts, and failure cases (e.g. numbers ending in `0000`) without spending real money.
  - **Live mNotify Gateway Adapter**: Official integration for production delivery in Ghana.
- **Dual-Mode Payment Integration**:
  - **Dev Sandbox Simulator**: Simulates Paystack / Mobile Money checkout for instant end-to-end testing.
  - **Paystack Live Adapter**: Handles card and mobile money checkouts with HMAC-SHA512 webhook verification.
- **Anti-Abuse & Suppression Engine**: Opt-out lists and consent records automatically suppress unsubscribed recipients from future campaigns.
- **Executive Administration & Financial Reporting**: Real-time platform metrics, gross sales, estimated telecom provider costs, contribution margins, and audit logs.

---

## 2. Technology Stack

- **Backend**: Python 3.14+, Django 6.1
- **Database**: SQLite (default local development) / PostgreSQL (production)
- **Frontend**: Django Templates, Bootstrap 5.3, Bootstrap Icons, Vanilla JS
- **Spreadsheet Processing**: `openpyxl`, `csv`
- **SMS Gateway**: Pluggable provider adapter (`MockSMSProvider`, `MNotifySMSProvider`)
- **Payment Gateway**: Pluggable provider adapter (`SandboxPaymentAdapter`, `PaystackPaymentAdapter`)
- **Configuration**: `python-dotenv` with `.env`

---

## 3. Quick Start Guide

### Step 1: Clone and Set Up Virtual Environment

```bash
# Navigate to project directory
cd TextBridge

# Create and activate virtual environment
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install django openpyxl requests python-dotenv
```

### Step 2: Configure Environment Variables

Create `.env` by copying `.env.example`:

```bash
copy .env.example .env
```

Default local development values:
```env
SECRET_KEY=dev-secret-key-brightsms-2026-production-ready
DEBUG=True
ALLOWED_HOSTS=*
PLATFORM_NAME=BrightSMS
PLATFORM_TAGLINE=Multi-Business SMS & Customer Engagement Platform
PRIMARY_CURRENCY=GHS
CURRENCY_SYMBOL=GH₵
ACTIVE_SMS_PROVIDER=MOCK
PAYMENT_SANDBOX_MODE=True
USE_CELERY=False
```

### Step 3: Run Database Migrations

```bash
python manage.py migrate
```

### Step 4: Seed Initial SMS Packages and Demo Data

```bash
# Seed retail SMS credit packages (Starter 100, Bronze 500, Silver 1,000, Gold 5,000, Enterprise 10,000)
python manage.py seed_sms_packages

# Seed platform superadmin and demo business (IronFit Gym)
python manage.py seed_demo_data
```

### Step 5: Start the Development Server

```bash
python manage.py runserver
```

Open your browser at `http://127.0.0.1:8000/`.

---

## 4. Default Seeded Accounts for Testing

| Role | Email | Password | Initial Balance |
| :--- | :--- | :--- | :--- |
| **Platform Superadmin** | `admin@brightsms.com` | `Admin12345!` | Full platform administration |
| **Demo Business (Gym)** | `owner@ironfitgym.com` | `GymOwner123!` | 500 SMS Credits, 5 contacts |

---

## 5. Running Automated Tests

BrightSMS includes a test suite covering tenant isolation, Ghanaian phone number normalization, CSV/XLSX imports, credit ledger concurrency, SMS segmentation, and campaign dispatch.

Execute tests anytime with:

```bash
python manage.py test
```

Expected result:
```
Ran 14 tests in ...s
OK
```

---

## 6. Provider Configuration Guide

### A. Live SMS Gateway (mNotify)
To connect live SMS delivery for Ghana:
1. Obtain an API key from [mNotify Developer Portal](https://developer.mnotify.com).
2. Register your business Alphanumeric Sender ID on mNotify.
3. Update `.env`:
   ```env
   ACTIVE_SMS_PROVIDER=MNOTIFY
   MNOTIFY_API_KEY=your_actual_mnotify_api_key
   MNOTIFY_BASE_URL=https://api.mnotify.com/api
   ```
4. Restart Django. Campaigns will now transmit through mNotify.

> **Important Funding Note**: Collecting customer payments via Paystack does **not** automatically deposit funds into your mNotify telecom wallet. Platform owners must maintain a prepaid wallet balance on mNotify independently.

### B. Live Payments (Paystack)
To accept live Mobile Money (MTN, Telecel, AT) and Debit Card payments in Ghana:
1. Create a merchant account at [Paystack](https://paystack.com).
2. Set your webhook URL in Paystack Dashboard to: `https://yourdomain.com/billing/webhook/paystack/`.
3. Update `.env`:
   ```env
   PAYMENT_SANDBOX_MODE=False
   PAYSTACK_PUBLIC_KEY=pk_live_...
   PAYSTACK_SECRET_KEY=sk_live_...
   ```

---

## 7. Production Deployment (PostgreSQL + Gunicorn + Nginx)

1. **Database**: In `.env`, configure PostgreSQL:
   ```env
   DB_ENGINE=django.db.backends.postgresql
   DB_NAME=brightsms_db
   DB_USER=postgres_user
   DB_PASSWORD=secure_password
   DB_HOST=127.0.0.1
   DB_PORT=5432
   ```
2. **Collect Static Files**:
   ```bash
   python manage.py collectstatic --noinput
   ```
3. **Run Production Server**:
   ```bash
   gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
   ```
4. **Automated Database Backups**:
   ```bash
   # Scheduled nightly PostgreSQL backup via crontab:
   pg_dump -U postgres_user brightsms_db > /backups/brightsms_$(date +\%Y\%m\%d).sql
   ```

---

## 8. Regulatory & Anti-Abuse Compliance

- **Consent & Lawful Basis**: Businesses are required to obtain lawful consent before sending marketing communications.
- **Opt-Out & Suppression**: Contacts added to the suppression list or unsubscribed are automatically excluded from all broadcasts.
- **Sender ID Verification**: Sender IDs are limited to 11 alphanumeric characters per GSM telecom standards and can be reviewed before approval.
