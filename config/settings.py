import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(BASE_DIR / '.env')

# Core Security Settings
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-dev-key-brightsms-fallback')
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '*').split(',') if h.strip()]
if '.pythonanywhere.com' not in ALLOWED_HOSTS and '*' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('.pythonanywhere.com')

# Platform Customization & Branding
PLATFORM_NAME = os.getenv('PLATFORM_NAME', 'TextBridge')
PLATFORM_TAGLINE = os.getenv('PLATFORM_TAGLINE', 'Enterprise Multi-Tenant SMS & Messaging Infrastructure')
PRIMARY_CURRENCY = os.getenv('PRIMARY_CURRENCY', 'GHS')
CURRENCY_SYMBOL = os.getenv('CURRENCY_SYMBOL', 'GH₵')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # TextBridge / BrightSMS Core Applications
    'accounts.apps.AccountsConfig',
    'contacts.apps.ContactsConfig',
    'billing.apps.BillingConfig',
    'messaging.apps.MessagingConfig',
    'analytics.apps.AnalyticsConfig',
]

AUTH_USER_MODEL = 'accounts.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.TenantMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.platform_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database Configuration
if os.getenv('DB_ENGINE') == 'django.db.backends.postgresql' or os.getenv('DATABASE_URL'):
    import urllib.parse
    db_url = os.getenv('DATABASE_URL', '')
    if db_url:
        parsed = urllib.parse.urlparse(db_url)
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': parsed.path.lstrip('/'),
                'USER': parsed.username,
                'PASSWORD': parsed.password,
                'HOST': parsed.hostname,
                'PORT': parsed.port or 5432,
                'CONN_MAX_AGE': int(os.getenv('CONN_MAX_AGE', '600')),
            }
        }
    else:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': os.getenv('DB_NAME', 'textbridge_db'),
                'USER': os.getenv('DB_USER', 'postgres'),
                'PASSWORD': os.getenv('DB_PASSWORD', 'postgres'),
                'HOST': os.getenv('DB_HOST', 'localhost'),
                'PORT': os.getenv('DB_PORT', '5432'),
                'CONN_MAX_AGE': int(os.getenv('CONN_MAX_AGE', '600')),
            }
        }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Accra'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage" if not DEBUG else "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'accounts:dashboard_redirect'
LOGOUT_REDIRECT_URL = 'accounts:login'

# SMS Provider settings
ACTIVE_SMS_PROVIDER = os.getenv('ACTIVE_SMS_PROVIDER', 'MOCK')
MNOTIFY_API_KEY = os.getenv('MNOTIFY_API_KEY', '')
MNOTIFY_BASE_URL = os.getenv('MNOTIFY_BASE_URL', 'https://api.mnotify.com/api')

# Payment settings
PAYMENT_SANDBOX_MODE = os.getenv('PAYMENT_SANDBOX_MODE', 'True').lower() in ('true', '1', 'yes')
PAYSTACK_PUBLIC_KEY = os.getenv('PAYSTACK_PUBLIC_KEY', 'pk_test_sample')
PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY', 'sk_test_sample')
PAYSTACK_BASE_URL = os.getenv('PAYSTACK_BASE_URL', 'https://api.paystack.co')

# Celery & Asynchronous Background Task Queue Settings
USE_CELERY = os.getenv('USE_CELERY', 'False').lower() in ('true', '1', 'yes')
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://127.0.0.1:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 min maximum execution per batch
CELERY_BEAT_SCHEDULE = {
    'dispatch-scheduled-campaigns-every-minute': {
        'task': 'messaging.tasks.process_scheduled_campaigns_task',
        'schedule': 60.0,
    },
    'dispatch-daily-birthdays-hourly': {
        'task': 'contacts.tasks.dispatch_daily_birthdays_task',
        'schedule': 3600.0,
    },
}

# Email Configuration (Multi-Provider: Gmail SMTP, Resend, or Console Fallback)
GMAIL_USER = os.getenv('GMAIL_USER', '').strip()
GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD', '').replace(' ', '').strip()
RESEND_API_KEY = os.getenv('RESEND_API_KEY', '').strip()

if GMAIL_USER and GMAIL_APP_PASSWORD:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = GMAIL_USER
    EMAIL_HOST_PASSWORD = GMAIL_APP_PASSWORD
    DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', f"{PLATFORM_NAME} <{GMAIL_USER}>")
elif RESEND_API_KEY:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.resend.com')
    EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
    EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'resend')
    EMAIL_HOST_PASSWORD = RESEND_API_KEY
    DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', f"{PLATFORM_NAME} <onboarding@resend.dev>")
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    DEFAULT_FROM_EMAIL = f"{PLATFORM_NAME} <noreply@textbridge.gh>"


# CSRF Trusted Origins for live domain and callbacks
CSRF_TRUSTED_ORIGINS = [
    orig.strip()
    for orig in os.getenv('CSRF_TRUSTED_ORIGINS', 'http://127.0.0.1:8000,http://localhost:8000').split(',')
    if orig.strip()
]
CSRF_TRUSTED_ORIGINS.extend(['https://*.pythonanywhere.com', 'http://*.pythonanywhere.com'])

# Production Security Hardening
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

if not DEBUG:
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1', 'yes')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

