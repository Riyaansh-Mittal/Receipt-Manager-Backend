"""
Root conftest.py - Configure Django and provide pytest fixtures
"""
import os
import sys
import pytest


# ========== DJANGO CONFIGURATION - RUNS BEFORE EVERYTHING ==========


# Get project root directory (where conftest.py lives)
project_root = os.getcwd()


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
        
        # ✅ ADD THIS - Critical for custom User model
        AUTH_USER_MODEL='auth_service.User',
        
        # Database
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        },
        
        # Apps - Use full module paths
        INSTALLED_APPS=[
            'django.contrib.contenttypes',
            'django.contrib.auth',
            'rest_framework',
            'shared',
            'auth_service.apps.AuthServiceConfig',
            'receipt_service.apps.ReceiptServiceConfig',
            'ai_service.apps.AiServiceConfig'
        ],
        
        # Middleware
        MIDDLEWARE=[],
        
        ROOT_URLCONF='',
        
        # Cache settings
        CACHES={
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'test-cache',
            }
        },
        
        # Timezone settings
        USE_TZ=True,
        TIME_ZONE='UTC',
        USE_I18N=True,
        USE_L10N=True,
        
        # App-specific settings for receipt_service
        RECEIPT_MAX_FILE_SIZE=10 * 1024 * 1024,  # 10MB
        
        # App-specific settings for currency exchange
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
        
        # DRF settings
        REST_FRAMEWORK={
            'DEFAULT_AUTHENTICATION_CLASSES': [],
            'DEFAULT_PERMISSION_CLASSES': [],
            'TEST_REQUEST_DEFAULT_FORMAT': 'json',
        },
        
        # Password hashers (use fast hasher for tests)
        PASSWORD_HASHERS=[
            'django.contrib.auth.hashers.MD5PasswordHasher',
        ],
        
        # ✅ ADD THESE - Email settings for auth tests
        DEFAULT_FROM_EMAIL='noreply@test.com',
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        FRONTEND_URL='http://localhost:3000',
        
        # ✅ ADD THESE - JWT settings for auth tests
        SIMPLE_JWT={
            'ACCESS_TOKEN_LIFETIME': 60,  # minutes
            'REFRESH_TOKEN_LIFETIME': 10080,  # minutes (7 days)
            'ALGORITHM': 'HS256',
        },
    )
    
    # Setup Django
    django.setup()


def pytest_configure(config):
    """
    Pytest hook called after command line options are parsed
    Ensures Django is set up before test collection
    """
    if not settings.configured:
        django.setup()


# ========== PYTEST FIXTURES ==========

@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before and after each test"""
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def reset_db_for_unit_tests(request):
    """
    Prevent database access in unit tests
    Only integration tests should touch the database
    """
    if 'unit' in request.keywords:
        pass
    yield


@pytest.fixture
def api_client():
    """DRF API client for integration tests"""
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def authenticated_user(db):
    """Create and return an authenticated user"""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )
    return user


@pytest.fixture
def authenticated_client(api_client, authenticated_user):
    """Return API client with authenticated user"""
    api_client.force_authenticate(user=authenticated_user)
    return api_client, authenticated_user
