"""
Test-specific Django settings
This is loaded BEFORE pytest runs, solving the mail.outbox issue
"""
from pathlib import Path

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Security
DEBUG = True
SECRET_KEY = 'test-secret-key-not-for-production-use-only-testing'
ALLOWED_HOSTS = ['*']

# Database (in-memory for tests)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Applications
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.messages',
    'rest_framework',
    # Your apps
    'shared',
    'auth_service',
    'receipt_service',
    'ai_service',
]

# Middleware (minimal for tests)
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

ROOT_URLCONF = 'receiptmanager.urls'

# Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# Email Backend - THIS FIXES mail.outbox error
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Cache (in-memory for tests)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache',
    }
}

# Password Hashers (fast for tests)
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Internationalization
USE_I18N = True
USE_TZ = True
TIME_ZONE = 'UTC'

# Static files
STATIC_URL = '/static/'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': [],
    'TEST_REQUEST_DEFAULT_FORMAT': 'json',
}

# App-specific settings for tests
RECEIPT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
EXCHANGE_RATE_API_KEY = 'test_api_key_1234567890'
EXCHANGE_RATE_API_TIMEOUT = 10
EXCHANGE_RATE_MAX_RETRIES = 3
EXCHANGE_RATE_FAILURE_THRESHOLD = 3
EXCHANGE_RATE_RECOVERY_TIMEOUT = 300
EXCHANGE_RATE_SUCCESS_THRESHOLD = 2
EXCHANGE_RATE_CACHE_TIMEOUT = 3600
FALLBACK_CACHE_TIMEOUT = 86400
DEFAULT_CURRENCY = 'USD'
BASE_CURRENCY = 'USD'

# Celery (disabled for tests)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Logging (quiet for tests)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'handlers': {
        'null': {
            'class': 'logging.NullHandler',
        },
    },
    'root': {
        'handlers': ['null'],
        'level': 'DEBUG',
    },
}
