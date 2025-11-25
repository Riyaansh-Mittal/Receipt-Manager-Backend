"""
Root conftest.py - Configure Django and provide pytest fixtures
"""
import os
import sys
import pytest
from datetime import timedelta

# ========== DJANGO CONFIGURATION - RUNS BEFORE EVERYTHING ==========

# Get project root directory (where conftest.py lives)
project_root = os.getcwd()
SECRET_KEY = os.environ.get("SECRET_KEY", "test-secret-key-for-testing-only")

# Clean up sys.path to avoid duplicates
project_root_normalized = os.path.normpath(project_root)
sys.path = [os.path.normpath(p) for p in sys.path]  # Normalize all paths
if project_root_normalized not in sys.path:
    sys.path.insert(0, project_root_normalized)

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'receiptmanager.settings')

# Configure Django if not already configured
import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY='test-secret-key-for-testing-only-never-use-in-production',
        AUTH_USER_MODEL='auth_service.User',
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        },
        INSTALLED_APPS=[
            'django.contrib.admin',
            'django.contrib.contenttypes',
            'django.contrib.auth',
            'rest_framework',
            'shared',
            'auth_service.apps.AuthServiceConfig',
            'receipt_service.apps.ReceiptServiceConfig',
            'ai_service.apps.AiServiceConfig'
        ],
        MIDDLEWARE=[
            'corsheaders.middleware.CorsMiddleware',
            'django.middleware.security.SecurityMiddleware',
            'django.contrib.sessions.middleware.SessionMiddleware',
            'django.middleware.common.CommonMiddleware',
            'shared.middleware.logging_middleware.LoggingContextMiddleware',
            'django.contrib.auth.middleware.AuthenticationMiddleware',
            'shared.middleware.security_middleware.SecurityMiddleware',
            'shared.middleware.security_middleware.IPWhitelistMiddleware',
            'auth_service.middleware.jwt_blacklist_middleware.JWTBlacklistMiddleware',
            'django.contrib.messages.middleware.MessageMiddleware',
            'django.middleware.clickjacking.XFrameOptionsMiddleware',
            'shared.middleware.logging_middleware.StructuredLoggingMiddleware',
            'shared.middleware.drf_exceptions.DRFExceptionMiddleware',
        ],
        ROOT_URLCONF='receiptmanager.urls',
        CACHES={
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'test-cache',
            }
        },
        USE_TZ=True,
        TIME_ZONE='UTC',
        USE_I18N=True,
        USE_L10N=True,
        RECEIPT_MAX_FILE_SIZE=10 * 1024 * 1024,
        EXCHANGE_RATE_API_KEY='test_api_key_1234567890_for_testing_only',
        EXCHANGE_RATE_API_TIMEOUT=10,
        EXCHANGE_RATE_MAX_RETRIES=3,
        EXCHANGE_RATE_FAILURE_THRESHOLD=3,
        EXCHANGE_RATE_RECOVERY_TIMEOUT=300,
        EXCHANGE_RATE_SUCCESS_THRESHOLD=2,
        EXCHANGE_RATE_CACHE_TIMEOUT=3600,
        FALLBACK_CACHE_TIMEOUT=86400,
        DEFAULT_CURRENCY='USD',
        BASE_CURRENCY='USD',
        REST_FRAMEWORK={
            'DEFAULT_AUTHENTICATION_CLASSES': [
                'rest_framework_simplejwt.authentication.JWTAuthentication',
                'rest_framework.authentication.SessionAuthentication',
            ],
            'DEFAULT_PERMISSION_CLASSES': [
                'rest_framework.permissions.IsAuthenticated',
            ],
            'PAGE_SIZE': 20,
            'EXCEPTION_HANDLER': 'shared.utils.exceptions.exception_handler',
        },
        PASSWORD_HASHERS=[
            'django.contrib.auth.hashers.MD5PasswordHasher',
        ],
        DEFAULT_FROM_EMAIL='noreply@test.com',
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        FRONTEND_URL='http://localhost:3000',
        SIMPLE_JWT={
            'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
            'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
            'ROTATE_REFRESH_TOKENS': True,
            'BLACKLIST_AFTER_ROTATION': True,
            'UPDATE_LAST_LOGIN': True,
            'ALGORITHM': 'HS256',
            'SIGNING_KEY': SECRET_KEY,
            'AUTH_HEADER_TYPES': ('Bearer',),
            'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
            'USER_ID_FIELD': 'id',
            'USER_ID_CLAIM': 'user_id',
            'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
            'TOKEN_TYPE_CLAIM': 'token_type',
            'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',
            'JTI_CLAIM': 'jti',
        },
        MAGIC_LINK_RATE_LIMIT_PER_EMAIL=5,
        MAGIC_LINK_RATE_LIMIT_PER_IP=20,
        LOGIN_RATE_LIMIT_PER_IP=20,
        TOKEN_REFRESH_RATE_LIMIT=50,
    )
    django.setup()

def pytest_configure(config):
    if not settings.configured:
        django.setup()

# ========== PYTEST FIXTURES ==========

@pytest.fixture(autouse=True)
def clear_cache():
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()

@pytest.fixture(autouse=True)
def reset_db_for_unit_tests(request):
    if 'unit' in request.keywords:
        pass
    yield

@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()

@pytest.fixture
def authenticated_user(db):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.create_user(
        email='test@example.com',
        first_name='Test',
        last_name='User'
    )
    return user

@pytest.fixture
def authenticated_client(api_client, authenticated_user):
    api_client.force_authenticate(user=authenticated_user)
    return api_client, authenticated_user

@pytest.fixture
def auth_api_client(authenticated_client):
    client, user = authenticated_client
    return client

from receipt_service.services.receipt_model_service import model_service

@pytest.fixture
def create_category(db):
    def _create_category(name='Test Category'):
        Category = model_service.category_model
        return Category.objects.create(
            name=name,
            slug=name.lower().replace(' ', '-'),
            icon='📁',
            color='#6c757d',
        )
    return _create_category

@pytest.fixture
def create_user(db):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    def _create_user(email='user@example.com'):
        return User.objects.create_user(email=email, password='password')
    return _create_user

@pytest.fixture
def create_receipt(db, create_user):
    def _create_receipt(user=None):
        if user is None:
            user = create_user()
        Receipt = model_service.receipt_model
        return Receipt.objects.create(
            user=user,
            original_filename='test.pdf',
            file_path='test/path/test.pdf',
            file_size=1024,
            mime_type='application/pdf',
            file_hash='hash123',
            status='uploaded',
            upload_ip_address='127.0.0.1',
        )
    return _create_receipt

@pytest.fixture
def create_ledger(db, create_user, create_category, create_receipt):
    def _create_ledger(user=None, category=None, receipt=None):
        if user is None:
            user = create_user()
        if category is None:
            category = create_category()
        if receipt is None:
            receipt = create_receipt(user=user)
        LedgerEntry = model_service.ledger_entry_model
        return LedgerEntry.objects.create(
            user=user,
            receipt=receipt,
            category=category,
            date='2023-01-01',
            vendor='Test Vendor',
            amount=100.0,
            currency='USD',
            description='Test Ledger Entry',
            tags='tag1,tag2',
            user_corrected_amount=None,
            user_corrected_category=None,
            user_corrected_vendor=None,
            user_corrected_date=None,
            is_business_expense=False,
            is_reimbursable=True,
            created_from_ip='127.0.0.1',
        )
    return _create_ledger
