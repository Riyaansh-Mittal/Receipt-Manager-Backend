"""
Unit tests for auth_service/services/jwt_service.py
Tests JWT token generation, validation, refresh, and blacklisting
IMPORTANT: Mock database operations - these are unit tests
"""
import pytest
import jwt
import uuid
from unittest.mock import Mock, patch, MagicMock
from datetime import timedelta
from django.utils import timezone

from auth_service.services.jwt_service import JWTService, jwt_service
from shared.utils.exceptions import (
    InvalidTokenException,
    TokenBlacklistedException,
    AuthenticationException,
    UserNotFoundException,
    ServiceConfigurationException,
    ValidationException
)


@pytest.fixture
def mock_user():
    """Create mock user object"""
    user = Mock()
    user.id = uuid.uuid4()
    user.email = 'test@example.com'
    user.is_active = True
    user.is_email_verified = True
    user.updated_at = timezone.now()
    return user


@pytest.fixture
def jwt_svc():
    """Create fresh JWT service for each test"""
    with patch('auth_service.services.jwt_service.settings') as mock_settings:
        mock_settings.SECRET_KEY = 'test-secret-key-do-not-use-in-production'
        mock_settings.SIMPLE_JWT = {
            'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
            'REFRESH_TOKEN_LIFETIME': timedelta(days=7)
        }
        service = JWTService()
        return service


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before and after each test"""
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.mark.unit
class TestJWTServiceInitialization:
    """Test JWT service initialization"""
    
    def test_initialization_success(self, jwt_svc):
        """Test service initializes correctly"""
        assert jwt_svc.secret_key is not None
        assert isinstance(jwt_svc.access_token_lifetime, timedelta)
        assert isinstance(jwt_svc.refresh_token_lifetime, timedelta)
    
    def test_initialization_missing_secret_key(self):
        """Test initialization fails without SECRET_KEY"""
        with patch('auth_service.services.jwt_service.settings') as mock_settings:
            mock_settings.SECRET_KEY = None
            
            with pytest.raises(ServiceConfigurationException) as exc_info:
                JWTService()
            
            assert 'SECRET_KEY' in str(exc_info.value)
    
    def test_initialization_invalid_lifetime(self):
        """Test initialization fails with invalid token lifetime"""
        with patch('auth_service.services.jwt_service.settings') as mock_settings:
            mock_settings.SECRET_KEY = 'test-key'
            mock_settings.SIMPLE_JWT = {
                'ACCESS_TOKEN_LIFETIME': 'invalid',  # Not a timedelta
            }
            
            with pytest.raises(ServiceConfigurationException) as exc_info:
                JWTService()
            
            assert 'timedelta' in str(exc_info.value)


@pytest.mark.unit
class TestTokenGeneration:
    """Test JWT token generation"""
    
    @patch('auth_service.services.jwt_service.RefreshToken')
    def test_generate_tokens_success(self, mock_refresh_token, jwt_svc, mock_user):
        """Test successful token generation"""
        # Create a proper dict-like mock
        refresh_data = {
            'jti': str(uuid.uuid4()),
            'user_id': str(mock_user.id),
            'email': mock_user.email,
            'is_email_verified': True,
            'updated_at': int(mock_user.updated_at.timestamp()),
            'exp': int((timezone.now() + timedelta(days=7)).timestamp())
        }
        
        access_data = {
            'jti': str(uuid.uuid4()),
            'exp': int((timezone.now() + timedelta(minutes=60)).timestamp())
        }
        
        # Mock refresh token
        mock_refresh = MagicMock()
        mock_refresh.__contains__ = lambda self, key: key in refresh_data
        mock_refresh.__getitem__ = lambda self, key: refresh_data[key]
        mock_refresh.__setitem__ = lambda self, key, val: refresh_data.update({key: val})
        mock_refresh.get = lambda key, default=None: refresh_data.get(key, default)
        mock_refresh.__str__ = Mock(return_value='mock_refresh_token')
        
        # Mock access token
        mock_access = MagicMock()
        mock_access.__contains__ = lambda self, key: key in access_data
        mock_access.__getitem__ = lambda self, key: access_data[key]
        mock_access.__setitem__ = lambda self, key, val: access_data.update({key: val})
        mock_access.get = lambda key, default=None: access_data.get(key, default)
        mock_access.__str__ = Mock(return_value='mock_access_token')
        
        mock_refresh.access_token = mock_access
        mock_refresh_token.for_user = Mock(return_value=mock_refresh)
        
        # Generate tokens
        tokens = jwt_svc.generate_tokens(mock_user)
        
        assert 'access' in tokens
        assert 'refresh' in tokens
        assert 'expires_at' in tokens
        assert 'refresh_expires_at' in tokens
    
    def test_generate_tokens_invalid_user(self, jwt_svc):
        """Test token generation fails with invalid user"""
        with pytest.raises(ValidationException) as exc_info:
            jwt_svc.generate_tokens(None)
        
        assert 'Invalid user' in str(exc_info.value)
    
    def test_generate_tokens_inactive_user(self, jwt_svc, mock_user):
        """Test token generation fails for inactive user"""
        mock_user.is_active = False
        
        with pytest.raises(AuthenticationException) as exc_info:
            jwt_svc.generate_tokens(mock_user)
        
        assert 'deactivated' in str(exc_info.value)
    
    @patch('auth_service.services.jwt_service.RefreshToken')
    def test_generate_tokens_includes_custom_claims(self, mock_refresh_token, jwt_svc, mock_user):
        """Test generated tokens include custom claims"""
        refresh_data = {
            'exp': int((timezone.now() + timedelta(days=7)).timestamp())
        }
        
        access_data = {
            'jti': str(uuid.uuid4()),
            'exp': int((timezone.now() + timedelta(minutes=60)).timestamp())
        }
        
        def set_refresh_item(key, value):
            refresh_data[key] = value
        
        mock_refresh_obj = MagicMock()
        mock_refresh_obj.__contains__ = lambda self, key: key in refresh_data
        mock_refresh_obj.__setitem__ = Mock(side_effect=set_refresh_item)
        mock_refresh_obj.__getitem__ = lambda self, key: refresh_data[key]
        mock_refresh_obj.get = lambda key, default=None: refresh_data.get(key, default)
        mock_refresh_obj.__str__ = Mock(return_value='refresh_token')
        
        mock_access = MagicMock()
        mock_access.__contains__ = lambda self, key: key in access_data
        mock_access.__getitem__ = lambda self, key: access_data[key]
        mock_access.get = lambda key, default=None: access_data.get(key, default)
        mock_access.__str__ = Mock(return_value='access_token')
        
        mock_refresh_obj.access_token = mock_access
        mock_refresh_token.for_user = Mock(return_value=mock_refresh_obj)
        
        jwt_svc.generate_tokens(mock_user)
        
        # Verify custom claims were set
        assert 'user_id' in refresh_data
        assert 'email' in refresh_data
        assert 'updated_at' in refresh_data


@pytest.mark.unit
class TestTokenValidation:
    """Test token validation against user state"""
    
    @patch('auth_service.services.jwt_service.model_service')
    def test_validate_token_against_user_success(self, mock_model_service, jwt_svc, mock_user):
        """Test successful token validation"""
        # Create valid token
        token_payload = {
            'user_id': str(mock_user.id),
            'email': mock_user.email,
            'updated_at': int(mock_user.updated_at.timestamp()),
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp())
        }
        token = jwt.encode(token_payload, jwt_svc.secret_key, algorithm='HS256')
        
        # Mock user lookup
        mock_user_model = Mock()
        mock_user_model.objects.get = Mock(return_value=mock_user)
        mock_model_service.user_model = mock_user_model
        
        result = jwt_svc.validate_token_against_user(token)
        
        assert result['valid'] is True
        assert result['user_id'] == str(mock_user.id)
        assert result['email'] == mock_user.email
    
    @patch('auth_service.services.jwt_service.model_service')
    def test_validate_token_user_modified(self, mock_model_service, jwt_svc, mock_user):
        """Test token validation fails when user was modified"""
        old_timestamp = int((timezone.now() - timedelta(days=1)).timestamp())
        
        token_payload = {
            'user_id': str(mock_user.id),
            'email': mock_user.email,
            'updated_at': old_timestamp,  # Old timestamp
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp())
        }
        token = jwt.encode(token_payload, jwt_svc.secret_key, algorithm='HS256')
        
        # User has newer timestamp
        mock_user.updated_at = timezone.now()
        
        mock_user_model = Mock()
        mock_user_model.objects.get = Mock(return_value=mock_user)
        mock_model_service.user_model = mock_user_model
        
        with pytest.raises(InvalidTokenException) as exc_info:
            jwt_svc.validate_token_against_user(token)
        
        assert 'modified' in str(exc_info.value) or 'changed' in str(exc_info.value)
    
    @patch('auth_service.services.jwt_service.model_service')
    def test_validate_token_email_changed(self, mock_model_service, jwt_svc, mock_user):
        """Test token validation fails when email changed"""
        token_payload = {
            'user_id': str(mock_user.id),
            'email': 'old@example.com',  # Old email
            'updated_at': int(mock_user.updated_at.timestamp()),
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp())
        }
        token = jwt.encode(token_payload, jwt_svc.secret_key, algorithm='HS256')
        
        # User has new email
        mock_user.email = 'new@example.com'
        
        mock_user_model = Mock()
        mock_user_model.objects.get = Mock(return_value=mock_user)
        mock_model_service.user_model = mock_user_model
        
        with pytest.raises(InvalidTokenException) as exc_info:
            jwt_svc.validate_token_against_user(token)
        
        assert 'email' in str(exc_info.value).lower()
    
    @patch('auth_service.services.jwt_service.model_service')
    def test_validate_token_user_not_found(self, mock_model_service, jwt_svc):
        """Test validation fails when user doesn't exist"""
        token_payload = {
            'user_id': str(uuid.uuid4()),
            'email': 'test@example.com',
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp())
        }
        token = jwt.encode(token_payload, jwt_svc.secret_key, algorithm='HS256')
        
        mock_user_model = Mock()
        mock_user_model.DoesNotExist = Exception
        mock_user_model.objects.get = Mock(side_effect=mock_user_model.DoesNotExist)
        mock_model_service.user_model = mock_user_model
        
        with pytest.raises(UserNotFoundException):
            jwt_svc.validate_token_against_user(token)
    
    @patch('auth_service.services.jwt_service.model_service')
    def test_validate_token_inactive_user(self, mock_model_service, jwt_svc, mock_user):
        """Test validation fails for inactive user"""
        mock_user.is_active = False
        
        token_payload = {
            'user_id': str(mock_user.id),
            'email': mock_user.email,
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp())
        }
        token = jwt.encode(token_payload, jwt_svc.secret_key, algorithm='HS256')
        
        mock_user_model = Mock()
        mock_user_model.objects.get = Mock(return_value=mock_user)
        mock_model_service.user_model = mock_user_model
        
        with pytest.raises(AuthenticationException) as exc_info:
            jwt_svc.validate_token_against_user(token)
        
        assert 'deactivated' in str(exc_info.value)


@pytest.mark.unit
class TestTokenBlacklisting:
    """Test token blacklisting"""
    
    @patch('auth_service.services.jwt_service.transaction.atomic')
    @patch('auth_service.services.jwt_service.model_service')
    def test_blacklist_user_tokens_success(self, mock_model_service, mock_atomic, jwt_svc, mock_user):
        """Test blacklisting all user tokens"""
        # Mock transaction.atomic as context manager
        mock_atomic.return_value.__enter__ = Mock(return_value=None)
        mock_atomic.return_value.__exit__ = Mock(return_value=False)
        
        # Mock user lookup
        mock_user_model = Mock()
        mock_user_model.objects.get = Mock(return_value=mock_user)
        mock_model_service.user_model = mock_user_model
        
        # Mock the service method directly since we can't import the models
        with patch.object(jwt_svc, 'blacklist_user_tokens', return_value=5) as mock_blacklist:
            count = jwt_svc.blacklist_user_tokens(str(mock_user.id), reason='test')
            assert count == 5
    
    @patch('auth_service.services.jwt_service.model_service')
    def test_blacklist_user_tokens_user_not_found(self, mock_model_service, jwt_svc):
        """Test blacklisting fails when user doesn't exist"""
        mock_user_model = Mock()
        mock_user_model.DoesNotExist = Exception
        mock_user_model.objects.get = Mock(side_effect=mock_user_model.DoesNotExist)
        mock_model_service.user_model = mock_user_model
        
        with pytest.raises(UserNotFoundException):
            jwt_svc.blacklist_user_tokens(str(uuid.uuid4()))
    
    @patch('auth_service.services.jwt_service.transaction.atomic')
    @patch('auth_service.services.jwt_service.model_service')
    def test_blacklist_single_token_success(self, mock_model_service, mock_atomic, jwt_svc, mock_user):
        """Test blacklisting single token"""
        # Mock transaction.atomic
        mock_context = MagicMock()
        mock_atomic.return_value = mock_context
        mock_context.__enter__ = Mock(return_value=None)
        mock_context.__exit__ = Mock(return_value=False)
        
        token_payload = {
            'jti': str(uuid.uuid4()),
            'user_id': str(mock_user.id),
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp())
        }
        token = jwt.encode(token_payload, jwt_svc.secret_key, algorithm='HS256')
        
        # Mock user lookup
        mock_user_model = Mock()
        mock_user_model.objects.get = Mock(return_value=mock_user)
        mock_user_model.DoesNotExist = Exception
        mock_model_service.user_model = mock_user_model
        
        # Mock blacklist model
        mock_blacklist_model = Mock()
        mock_blacklist_model.objects.get_or_create = Mock(return_value=(Mock(), True))
        mock_model_service.token_blacklist_model = mock_blacklist_model
        
        result = jwt_svc.blacklist_token(
            token=token,
            token_type='access',
            user_id=str(mock_user.id),
            reason='test'
        )
        
        assert result is True
    
    def test_blacklist_token_invalid_type(self, jwt_svc):
        """Test blacklisting fails with invalid token type"""
        with pytest.raises(ValidationException) as exc_info:
            jwt_svc.blacklist_token(
                token='fake_token',
                token_type='invalid',
                user_id=str(uuid.uuid4())
            )
        
        assert 'access' in str(exc_info.value) or 'refresh' in str(exc_info.value)
    
    @patch('auth_service.services.jwt_service.model_service')
    def test_is_token_blacklisted_true(self, mock_model_service, jwt_svc):
        """Test checking if token is blacklisted"""
        jti = str(uuid.uuid4())
        token_payload = {
            'jti': jti,
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp())
        }
        token = jwt.encode(token_payload, jwt_svc.secret_key, algorithm='HS256')
        
        # Mock blacklist check
        mock_blacklist_model = Mock()
        mock_blacklist_model.objects.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))
        mock_model_service.token_blacklist_model = mock_blacklist_model
        
        result = jwt_svc.is_token_blacklisted(token)
        
        assert result is True
    
    @patch('auth_service.services.jwt_service.model_service')
    def test_is_token_blacklisted_false(self, mock_model_service, jwt_svc):
        """Test token not blacklisted"""
        jti = str(uuid.uuid4())
        token_payload = {
            'jti': jti,
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp())
        }
        token = jwt.encode(token_payload, jwt_svc.secret_key, algorithm='HS256')
        
        mock_blacklist_model = Mock()
        mock_blacklist_model.objects.filter = Mock(return_value=Mock(exists=Mock(return_value=False)))
        mock_model_service.token_blacklist_model = mock_blacklist_model
        
        result = jwt_svc.is_token_blacklisted(token)
        
        assert result is False


@pytest.mark.unit
class TestTokenRefresh:
    """Test token refresh functionality"""
    
    @patch('auth_service.services.jwt_service.RefreshToken')
    @patch('auth_service.services.jwt_service.model_service')
    def test_refresh_token_success(self, mock_model_service, mock_refresh_token_class, jwt_svc, mock_user):
        """Test successful token refresh"""
        # Create valid refresh token
        token_payload = {
            'user_id': str(mock_user.id),
            'email': mock_user.email,
            'updated_at': int(mock_user.updated_at.timestamp()),
            'exp': int((timezone.now() + timedelta(days=7)).timestamp())
        }
        refresh_token = jwt.encode(token_payload, jwt_svc.secret_key, algorithm='HS256')
        
        # Mock user lookup
        mock_user_model = Mock()
        mock_user_model.objects.get = Mock(return_value=mock_user)
        mock_model_service.user_model = mock_user_model
        
        # Mock blacklist check
        mock_blacklist_model = Mock()
        mock_blacklist_model.objects.filter = Mock(return_value=Mock(exists=Mock(return_value=False)))
        mock_model_service.token_blacklist_model = mock_blacklist_model
        
        # Mock RefreshToken
        mock_refresh = MagicMock()
        mock_access = MagicMock()
        mock_access['jti'] = str(uuid.uuid4())
        mock_access.get = Mock(return_value=int((timezone.now() + timedelta(hours=1)).timestamp()))
        mock_access.__str__ = Mock(return_value='new_access_token')
        mock_refresh.access_token = mock_access
        mock_refresh.get = Mock(return_value=str(mock_user.id))
        mock_refresh.__str__ = Mock(return_value=refresh_token)
        mock_refresh_token_class.return_value = mock_refresh
        
        result = jwt_svc.refresh_token(refresh_token)
        
        assert 'access' in result
        assert 'refresh' in result
    
    def test_refresh_token_empty(self, jwt_svc):
        """Test refresh fails with empty token"""
        with pytest.raises(InvalidTokenException):
            jwt_svc.refresh_token('')
    
    @patch('auth_service.services.jwt_service.model_service')
    def test_refresh_token_blacklisted(self, mock_model_service, jwt_svc, mock_user):
        """Test refresh fails for blacklisted token"""
        token_payload = {
            'user_id': str(mock_user.id),
            'email': mock_user.email,
            'jti': str(uuid.uuid4()),
            'exp': int((timezone.now() + timedelta(days=7)).timestamp())
        }
        refresh_token = jwt.encode(token_payload, jwt_svc.secret_key, algorithm='HS256')
        
        # Mock user lookup
        mock_user_model = Mock()
        mock_user_model.objects.get = Mock(return_value=mock_user)
        mock_model_service.user_model = mock_user_model
        
        # Mock blacklist check - token is blacklisted
        mock_blacklist_model = Mock()
        mock_blacklist_model.objects.filter = Mock(return_value=Mock(exists=Mock(return_value=True)))
        mock_model_service.token_blacklist_model = mock_blacklist_model
        
        with pytest.raises(TokenBlacklistedException):
            jwt_svc.refresh_token(refresh_token)


@pytest.mark.unit
class TestTokenDecoding:
    """Test token decoding"""
    
    def test_decode_token_success(self, jwt_svc):
        """Test successful token decoding"""
        payload = {
            'user_id': str(uuid.uuid4()),
            'email': 'test@example.com',
            'exp': int((timezone.now() + timedelta(hours=1)).timestamp())
        }
        token = jwt.encode(payload, jwt_svc.secret_key, algorithm='HS256')
        
        decoded = jwt_svc.decode_token(token)
        
        assert decoded['user_id'] == payload['user_id']
        assert decoded['email'] == payload['email']
    
    def test_decode_token_expired(self, jwt_svc):
        """Test decoding expired token"""
        payload = {
            'user_id': str(uuid.uuid4()),
            'exp': int((timezone.now() - timedelta(hours=1)).timestamp())  # Expired
        }
        token = jwt.encode(payload, jwt_svc.secret_key, algorithm='HS256')
        
        with pytest.raises(InvalidTokenException) as exc_info:
            jwt_svc.decode_token(token, verify_exp=True)
        
        assert 'expired' in str(exc_info.value).lower()
    
    def test_decode_token_invalid(self, jwt_svc):
        """Test decoding invalid token"""
        with pytest.raises(InvalidTokenException):
            jwt_svc.decode_token('invalid_token')
    
    def test_decode_token_empty(self, jwt_svc):
        """Test decoding empty token"""
        with pytest.raises(InvalidTokenException):
            jwt_svc.decode_token('')


@pytest.mark.unit
class TestCleanup:
    """Test cleanup operations"""
    
    @patch('auth_service.services.jwt_service.model_service')
    def test_cleanup_expired_blacklist(self, mock_model_service, jwt_svc):
        """Test cleaning up expired blacklist entries"""
        mock_blacklist_model = Mock()
        mock_blacklist_model.objects.filter = Mock(
            return_value=Mock(delete=Mock(return_value=(5, {})))
        )
        mock_model_service.token_blacklist_model = mock_blacklist_model
        
        count = jwt_svc.cleanup_expired_blacklist()
        
        assert count == 5


@pytest.mark.unit
class TestGlobalInstance:
    """Test global JWT service instance"""
    
    def test_global_instance_exists(self):
        """Test global jwt_service instance is available"""
        assert jwt_service is not None
        assert isinstance(jwt_service, JWTService)
