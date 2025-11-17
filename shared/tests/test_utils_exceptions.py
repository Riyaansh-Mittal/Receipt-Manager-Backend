"""
Unit tests for shared/utils/exceptions.py
Tests all custom exception classes and exception handler functionality
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from shared.utils.exceptions import (
    BaseServiceException,
    AuthenticationException,
    AuthorizationException,
    InvalidTokenException,
    TokenExpiredException,
    TokenBlacklistedException,
    MagicLinkAlreadyUsedException,
    MagicLinkExpiredException,
    InvalidMagicLinkException,
    AccountLockedException,
    UserNotFoundException,
    EmailAlreadyExistsException,
    EmailNotVerifiedException,
    InvalidEmailVerificationTokenException,
    EmailVerificationTokenExpiredException,
    DatabaseOperationException,
    CacheOperationException,
    ModelCreationException,
    ModelUpdateException,
    ModelDeletionException,
    EmailServiceException,
    EmailSendFailedException,
    EmailTemplateException,
    EmailConfigurationException,
    RateLimitExceededException,
    SecurityViolationException,
    SuspiciousActivityException,
    IPBlockedException,
    TokenGenerationException,
    CryptographicException,
    ValidationException,
    InvalidEmailFormatException,
    InvalidUserDataException,
    MissingRequiredFieldException,
    ResourceNotFoundException,
    ResourceConflictException,
    ResourceGoneException,
    ServiceConfigurationException,
    ServiceUnavailableException,
    ExternalServiceException,
    ServiceTimeoutException,
    BusinessLogicException,
    OperationNotAllowedException,
    QuotaExceededException,
    format_exception_response,
    exception_handler,
)


@pytest.mark.unit
class TestBaseServiceException:
    """Test base exception class"""

    def test_default_initialization(self):
        """Test exception with default values"""
        exc = BaseServiceException()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.code == "service_error"
        assert exc.detail == "A service error occurred"
        assert exc.context == {}

    def test_custom_detail(self):
        """Test exception with custom detail"""
        exc = BaseServiceException(detail="Custom error message")
        assert exc.detail == "Custom error message"

    def test_custom_code(self):
        """Test exception with custom code"""
        exc = BaseServiceException(code="custom_code")
        assert exc.code == "custom_code"

    def test_custom_status_code(self):
        """Test exception with custom status code"""
        exc = BaseServiceException(status_code=status.HTTP_400_BAD_REQUEST)
        assert exc.status_code == status.HTTP_400_BAD_REQUEST

    def test_custom_context(self):
        """Test exception with custom context"""
        context = {"user_id": 123, "action": "delete"}
        exc = BaseServiceException(context=context)
        assert exc.context == context

    def test_to_dict_method(self):
        """Test exception serialization to dictionary"""
        exc = BaseServiceException(
            detail="Test error",
            code="test_code",
            status_code=status.HTTP_400_BAD_REQUEST,
            context={"key": "value"}
        )
        result = exc.to_dict()
        
        assert result["error"]["code"] == "test_code"
        assert result["error"]["message"] == "Test error"
        assert result["error"]["status_code"] == status.HTTP_400_BAD_REQUEST
        assert result["error"]["context"] == {"key": "value"}
        assert result["error"]["type"] == "BaseServiceException"

    def test_inheritance_from_api_exception(self):
        """Test that BaseServiceException inherits from APIException"""
        exc = BaseServiceException()
        assert isinstance(exc, APIException)


@pytest.mark.unit
class TestAuthenticationExceptions:
    """Test authentication-related exceptions"""

    def test_authentication_exception_defaults(self):
        exc = AuthenticationException()
        assert exc.status_code == status.HTTP_401_UNAUTHORIZED
        assert exc.code == "authentication_failed"
        assert exc.detail == "Authentication failed"

    def test_authorization_exception_defaults(self):
        exc = AuthorizationException()
        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.code == "authorization_failed"

    def test_invalid_token_exception(self):
        exc = InvalidTokenException()
        assert exc.code == "invalid_token"
        assert exc.status_code == status.HTTP_401_UNAUTHORIZED

    def test_token_expired_exception(self):
        exc = TokenExpiredException()
        assert exc.code == "token_expired"

    def test_token_blacklisted_exception(self):
        exc = TokenBlacklistedException()
        assert exc.code == "token_blacklisted"

    def test_magic_link_already_used_exception(self):
        """Test that magic link used exception has 400 status, not 401"""
        exc = MagicLinkAlreadyUsedException()
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.code == "magic_link_used"
        assert "already been used" in exc.detail

    def test_magic_link_expired_exception(self):
        exc = MagicLinkExpiredException()
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.code == "magic_link_expired"

    def test_invalid_magic_link_exception(self):
        exc = InvalidMagicLinkException()
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.code == "invalid_magic_link"

    def test_account_locked_exception(self):
        exc = AccountLockedException()
        assert exc.code == "account_locked"
        assert "locked" in exc.detail.lower()


@pytest.mark.unit
class TestUserManagementExceptions:
    """Test user management exceptions"""

    def test_user_not_found_exception(self):
        exc = UserNotFoundException()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.code == "user_not_found"

    def test_email_already_exists_exception(self):
        exc = EmailAlreadyExistsException()
        assert exc.status_code == status.HTTP_409_CONFLICT
        assert exc.code == "email_exists"

    def test_email_not_verified_exception(self):
        exc = EmailNotVerifiedException()
        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.code == "email_not_verified"

    def test_invalid_email_verification_token_exception(self):
        exc = InvalidEmailVerificationTokenException()
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.code == "invalid_verification_token"

    def test_email_verification_token_expired_exception(self):
        exc = EmailVerificationTokenExpiredException()
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.code == "verification_token_expired"


@pytest.mark.unit
class TestDatabaseExceptions:
    """Test database and cache exceptions"""

    def test_database_operation_exception(self):
        exc = DatabaseOperationException()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.code == "database_error"

    def test_cache_operation_exception(self):
        exc = CacheOperationException()
        assert exc.code == "cache_error"

    def test_model_creation_exception(self):
        exc = ModelCreationException()
        assert exc.code == "model_creation_failed"
        assert isinstance(exc, DatabaseOperationException)

    def test_model_update_exception(self):
        exc = ModelUpdateException()
        assert exc.code == "model_update_failed"

    def test_model_deletion_exception(self):
        exc = ModelDeletionException()
        assert exc.code == "model_deletion_failed"


@pytest.mark.unit
class TestEmailServiceExceptions:
    """Test email service exceptions"""

    def test_email_service_exception(self):
        exc = EmailServiceException()
        assert exc.status_code == status.HTTP_502_BAD_GATEWAY
        assert exc.code == "email_service_error"

    def test_email_send_failed_exception(self):
        exc = EmailSendFailedException()
        assert exc.code == "email_send_failed"
        assert isinstance(exc, EmailServiceException)

    def test_email_template_exception(self):
        exc = EmailTemplateException()
        assert exc.code == "email_template_error"

    def test_email_configuration_exception(self):
        exc = EmailConfigurationException()
        assert exc.code == "email_config_error"


@pytest.mark.unit
class TestRateLimitingExceptions:
    """Test rate limiting and security exceptions"""

    def test_rate_limit_exceeded_exception(self):
        exc = RateLimitExceededException()
        assert exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert exc.code == "rate_limit_exceeded"

    def test_rate_limit_with_retry_after(self):
        """Test rate limit exception with retry_after context"""
        exc = RateLimitExceededException(retry_after=60)
        assert exc.context.get("retry_after") == 60

    def test_security_violation_exception(self):
        exc = SecurityViolationException()
        assert exc.status_code == status.HTTP_403_FORBIDDEN
        assert exc.code == "security_violation"

    def test_suspicious_activity_exception(self):
        exc = SuspiciousActivityException()
        assert exc.code == "suspicious_activity"
        assert isinstance(exc, SecurityViolationException)

    def test_ip_blocked_exception(self):
        exc = IPBlockedException()
        assert exc.code == "ip_blocked"


@pytest.mark.unit
class TestTokenGenerationExceptions:
    """Test token generation exceptions"""

    def test_token_generation_exception(self):
        exc = TokenGenerationException()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.code == "token_generation_failed"

    def test_cryptographic_exception(self):
        exc = CryptographicException()
        assert exc.code == "cryptographic_error"


@pytest.mark.unit
class TestValidationExceptions:
    """Test validation exceptions"""

    def test_validation_exception(self):
        exc = ValidationException()
        assert exc.status_code == status.HTTP_400_BAD_REQUEST
        assert exc.code == "validation_error"

    def test_invalid_email_format_exception(self):
        exc = InvalidEmailFormatException()
        assert exc.code == "invalid_email_format"
        assert isinstance(exc, ValidationException)

    def test_invalid_user_data_exception(self):
        exc = InvalidUserDataException()
        assert exc.code == "invalid_user_data"

    def test_missing_required_field_exception(self):
        exc = MissingRequiredFieldException()
        assert exc.code == "missing_required_field"


@pytest.mark.unit
class TestResourceExceptions:
    """Test resource exceptions"""

    def test_resource_not_found_exception(self):
        exc = ResourceNotFoundException()
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.code == "resource_not_found"

    def test_resource_conflict_exception(self):
        exc = ResourceConflictException()
        assert exc.status_code == status.HTTP_409_CONFLICT
        assert exc.code == "resource_conflict"

    def test_resource_gone_exception(self):
        exc = ResourceGoneException()
        assert exc.status_code == status.HTTP_410_GONE
        assert exc.code == "resource_gone"


@pytest.mark.unit
class TestServiceLayerExceptions:
    """Test service layer exceptions"""

    def test_service_configuration_exception(self):
        exc = ServiceConfigurationException()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert exc.code == "service_config_error"

    def test_service_unavailable_exception(self):
        exc = ServiceUnavailableException()
        assert exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert exc.code == "service_unavailable"

    def test_external_service_exception(self):
        exc = ExternalServiceException()
        assert exc.status_code == status.HTTP_502_BAD_GATEWAY
        assert exc.code == "external_service_error"

    def test_service_timeout_exception(self):
        exc = ServiceTimeoutException()
        assert exc.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        assert exc.code == "service_timeout"


@pytest.mark.unit
class TestBusinessLogicExceptions:
    """Test business logic exceptions"""

    def test_business_logic_exception(self):
        exc = BusinessLogicException()
        assert exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert exc.code == "business_logic_error"

    def test_operation_not_allowed_exception(self):
        exc = OperationNotAllowedException()
        assert exc.code == "operation_not_allowed"
        assert isinstance(exc, BusinessLogicException)

    def test_quota_exceeded_exception(self):
        exc = QuotaExceededException()
        assert exc.code == "quota_exceeded"


@pytest.mark.unit
class TestFormatExceptionResponse:
    """Test format_exception_response function"""

    def test_format_base_service_exception_server_error(self):
        """Test formatting of server error (5xx)"""
        exc = DatabaseOperationException(detail="DB connection failed")
        mock_request = Mock()
        mock_request.user = Mock(id=123)
        mock_request.META = {"REMOTE_ADDR": "192.168.1.1"}
        mock_request.path = "/api/test"
        mock_request.method = "POST"
        
        context = {"request": mock_request}
        
        with patch("shared.utils.exceptions.logger") as mock_logger:
            response = format_exception_response(exc, context)
            
            # Should log as error for 500
            mock_logger.error.assert_called_once()
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert isinstance(response, Response)

    def test_format_base_service_exception_client_error(self):
        """Test formatting of client error (4xx)"""
        exc = ValidationException(detail="Invalid input")
        mock_request = Mock()
        mock_request.user = Mock(id=123)
        mock_request.META = {"REMOTE_ADDR": "192.168.1.1"}
        mock_request.path = "/api/test"
        mock_request.method = "POST"
        
        context = {"request": mock_request}
        
        with patch("shared.utils.exceptions.logger") as mock_logger:
            response = format_exception_response(exc, context)
            
            # Should log as warning for 400
            mock_logger.warning.assert_called_once()
            assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_format_drf_api_exception(self):
        """Test formatting of DRF APIException"""
        exc = APIException(detail="DRF error")
        mock_request = Mock()
        mock_request.user = Mock(id=123)
        mock_request.META = {"REMOTE_ADDR": "192.168.1.1"}
        mock_request.path = "/api/test"
        mock_request.method = "GET"
        
        context = {"request": mock_request}
        
        with patch("shared.utils.exceptions.logger") as mock_logger:
            response = format_exception_response(exc, context)
            
            mock_logger.warning.assert_called_once()
            assert "error" in response.data
            assert response.data["error"]["type"] == "APIException"

    def test_format_unexpected_exception(self):
        """Test formatting of unexpected exception"""
        exc = ValueError("Unexpected error")
        mock_request = Mock()
        mock_request.user = Mock(id=123)
        mock_request.META = {"REMOTE_ADDR": "192.168.1.1"}
        mock_request.path = "/api/test"
        mock_request.method = "POST"
        
        context = {"request": mock_request}
        
        with patch("shared.utils.exceptions.logger") as mock_logger:
            response = format_exception_response(exc, context)
            
            # Should log as error with exc_info
            mock_logger.error.assert_called_once()
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert response.data["error"]["code"] == "internal_error"
            assert response.data["error"]["type"] == "UnexpectedException"

    def test_format_exception_with_correlation_id(self):
        """Test that correlation ID is included if present"""
        exc = ValidationException()
        mock_request = Mock()
        mock_request.user = Mock(id=123)
        mock_request.META = {"REMOTE_ADDR": "192.168.1.1"}
        mock_request.path = "/api/test"
        mock_request.method = "GET"
        mock_request.correlation_id = "test-correlation-123"
        
        context = {"request": mock_request}
        
        response = format_exception_response(exc, context)
        assert response.data["error"]["correlation_id"] == "test-correlation-123"

    def test_format_exception_no_context(self):
        """Test formatting exception without context"""
        exc = ValidationException()
        
        with patch("shared.utils.exceptions.logger") as mock_logger:
            response = format_exception_response(exc, None)
            
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            # Should still log but with 'unknown' values
            assert mock_logger.warning.called

    def test_format_exception_anonymous_user(self):
        """Test formatting exception for anonymous user"""
        exc = AuthenticationException()
        mock_request = Mock()
        mock_request.user = None
        mock_request.META = {"REMOTE_ADDR": "192.168.1.1"}
        mock_request.path = "/api/login"
        mock_request.method = "POST"
        
        context = {"request": mock_request}
        
        response = format_exception_response(exc, context)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.unit
class TestExceptionHandler:
    """Test exception_handler wrapper function"""

    def test_exception_handler_calls_format_exception_response(self):
        """Test that exception_handler delegates to format_exception_response"""
        exc = ValidationException()
        context = {"request": Mock()}
        
        with patch("shared.utils.exceptions.format_exception_response") as mock_format:
            mock_format.return_value = Response({"error": "test"})
            
            result = exception_handler(exc, context)
            
            mock_format.assert_called_once_with(exc, context)
            assert result == mock_format.return_value


@pytest.mark.unit
class TestExceptionEdgeCases:
    """Test edge cases and error conditions"""

    def test_exception_with_none_context_values(self):
        """Test exception with None in context dict"""
        exc = BaseServiceException(context={"key": None, "value": None})
        result = exc.to_dict()
        assert result["error"]["context"] == {"key": None, "value": None}

    def test_exception_with_empty_detail(self):
        """Test exception with empty string detail"""
        exc = BaseServiceException(detail="")
        # Should fall back to default
        assert exc.detail == "A service error occurred"

    def test_exception_detail_override_in_subclass(self):
        """Test that subclass defaults override parent defaults"""
        exc = UserNotFoundException()
        assert exc.detail == "User not found"
        assert exc.detail != BaseServiceException.default_detail

    def test_exception_string_representation(self):
        """Test string representation of exception"""
        exc = ValidationException(detail="Test validation error")
        assert "Test validation error" in str(exc)

    def test_exception_with_complex_context(self):
        """Test exception with nested context data"""
        complex_context = {
            "user": {"id": 123, "email": "test@example.com"},
            "errors": ["error1", "error2"],
            "metadata": {"timestamp": "2025-11-14", "version": "1.0"}
        }
        exc = BaseServiceException(context=complex_context)
        result = exc.to_dict()
        assert result["error"]["context"] == complex_context

    def test_multiple_exceptions_same_code_different_classes(self):
        """Test that different exception classes can have overlapping codes"""
        exc1 = ValidationException()
        exc2 = InvalidEmailFormatException()
        
        # Both are validation errors but different classes
        assert exc1.code == "validation_error"
        assert exc2.code == "invalid_email_format"
        assert type(exc1) != type(exc2)
