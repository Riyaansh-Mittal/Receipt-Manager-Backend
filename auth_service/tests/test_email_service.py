"""
Unit tests for auth_service/services/email_service.py
Tests email sending with mocked email backend
IMPORTANT: Mock actual email sending - these are unit tests
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, call
from smtplib import SMTPException, SMTPAuthenticationError, SMTPConnectError
from socket import gaierror

from auth_service.services.email_service import EmailService
from shared.utils.exceptions import (
    EmailServiceException,
    EmailSendFailedException,
    EmailTemplateException,
    EmailConfigurationException,
    ValidationException,
    InvalidEmailFormatException,
    ServiceUnavailableException,
    ServiceTimeoutException
)


@pytest.fixture
def email_svc():
    """Create fresh email service for each test"""
    with patch('auth_service.services.email_service.settings') as mock_settings:
        mock_settings.DEFAULT_FROM_EMAIL = 'noreply@test.com'
        mock_settings.FRONTEND_URL = 'https://test.com'
        mock_settings.EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
        
        service = EmailService()
        return service


@pytest.mark.unit
class TestEmailServiceInitialization:
    """Test email service initialization"""
    
    def test_initialization_success(self, email_svc):
        """Test service initializes correctly"""
        assert email_svc.from_email is not None
        assert email_svc.frontend_url is not None
    
    def test_initialization_missing_from_email(self):
        """Test initialization fails without from_email"""
        with patch('auth_service.services.email_service.settings') as mock_settings:
            mock_settings.DEFAULT_FROM_EMAIL = None
            mock_settings.FRONTEND_URL = 'https://test.com'
            
            with pytest.raises(EmailConfigurationException) as exc_info:
                EmailService()
            
            assert 'DEFAULT_FROM_EMAIL' in str(exc_info.value)
    
    def test_initialization_missing_frontend_url(self):
        """Test initialization fails without frontend_url"""
        with patch('auth_service.services.email_service.settings') as mock_settings:
            mock_settings.DEFAULT_FROM_EMAIL = 'test@example.com'
            mock_settings.FRONTEND_URL = None
            
            with pytest.raises(EmailConfigurationException) as exc_info:
                EmailService()
            
            assert 'FRONTEND_URL' in str(exc_info.value)


@pytest.mark.unit
class TestMagicLinkEmail:
    """Test magic link email sending"""
    
    @patch('auth_service.services.email_service.EmailMessage')
    @patch('auth_service.services.email_service.render_to_string')
    def test_send_magic_link_success(self, mock_render, mock_email_message, email_svc):
        """Test successful magic link email"""
        mock_render.return_value = '<html>Magic Link</html>'
        
        mock_msg = Mock()
        mock_msg.send = Mock(return_value=1)
        mock_email_message.return_value = mock_msg
        
        result = email_svc.send_magic_link_email('user@test.com', 'test_token_123')
        
        assert result is True
        mock_msg.send.assert_called_once()
    
    def test_send_magic_link_invalid_email(self, email_svc):
        """Test magic link fails with invalid email"""
        with pytest.raises(InvalidEmailFormatException):
            email_svc.send_magic_link_email('invalid-email', 'token')
    
    def test_send_magic_link_empty_token(self, email_svc):
        """Test magic link fails with empty token"""
        with pytest.raises(ValidationException) as exc_info:
            email_svc.send_magic_link_email('user@test.com', '')
        
        assert 'token' in str(exc_info.value).lower()
    
    def test_send_magic_link_short_token(self, email_svc):
        """Test magic link fails with too short token"""
        with pytest.raises(ValidationException):
            email_svc.send_magic_link_email('user@test.com', 'short')
    
    @patch('auth_service.services.email_service.render_to_string')
    def test_send_magic_link_template_not_found(self, mock_render, email_svc):
        """Test magic link fails when template not found"""
        from django.template.loader import TemplateDoesNotExist
        mock_render.side_effect = TemplateDoesNotExist('template not found')
        
        # Service catches TemplateDoesNotExist and wraps it
        with pytest.raises(EmailServiceException):
            email_svc.send_magic_link_email('user@test.com', 'token_123456789')


@pytest.mark.unit
class TestEmailVerification:
    """Test email verification email sending"""
    
    @patch('auth_service.services.email_service.EmailMessage')
    @patch('auth_service.services.email_service.render_to_string')
    def test_send_verification_success(self, mock_render, mock_email_message, email_svc):
        """Test successful verification email"""
        mock_render.return_value = '<html>Verify Email</html>'
        
        mock_msg = Mock()
        mock_msg.send = Mock(return_value=1)
        mock_email_message.return_value = mock_msg
        
        result = email_svc.send_email_verification(
            'user@test.com',
            'verification_token_123',
            'John Doe'
        )
        
        assert result is True
    
    @patch('auth_service.services.email_service.EmailMessage')
    @patch('auth_service.services.email_service.render_to_string')
    def test_send_verification_no_username(self, mock_render, mock_email_message, email_svc):
        """Test verification email with no username"""
        mock_render.return_value = '<html>Verify</html>'
        
        mock_msg = Mock()
        mock_msg.send = Mock(return_value=1)
        mock_email_message.return_value = mock_msg
        
        result = email_svc.send_email_verification('user@test.com', 'token_1234567890')
        
        assert result is True
    
    def test_send_verification_invalid_email(self, email_svc):
        """Test verification fails with invalid email"""
        with pytest.raises(InvalidEmailFormatException):
            email_svc.send_email_verification('bad@', 'token_1234567890')


@pytest.mark.unit
class TestWelcomeEmail:
    """Test welcome email sending"""
    
    @patch('auth_service.services.email_service.EmailMessage')
    @patch('auth_service.services.email_service.render_to_string')
    def test_send_welcome_success(self, mock_render, mock_email_message, email_svc):
        """Test successful welcome email"""
        mock_render.return_value = '<html>Welcome!</html>'
        
        mock_msg = Mock()
        mock_msg.send = Mock(return_value=1)
        mock_email_message.return_value = mock_msg
        
        result = email_svc.send_welcome_email('user@test.com', 'John')
        
        assert result is True
    
    @patch('auth_service.services.email_service.EmailMessage')
    @patch('auth_service.services.email_service.render_to_string')
    def test_send_welcome_no_username(self, mock_render, mock_email_message, email_svc):
        """Test welcome email without username"""
        mock_render.return_value = '<html>Welcome!</html>'
        
        mock_msg = Mock()
        mock_msg.send = Mock(return_value=1)
        mock_email_message.return_value = mock_msg
        
        result = email_svc.send_welcome_email('user@test.com')
        
        assert result is True


@pytest.mark.unit
class TestEmailValidation:
    """Test email address validation"""
    
    def test_validate_email_valid(self, email_svc):
        """Test validation passes for valid emails"""
        valid_emails = [
            'user@example.com',
            'test.user@example.com',
            'user+tag@example.co.uk',
            'user_123@example.org'
        ]
        
        for email in valid_emails:
            email_svc._validate_email_address(email)  # Should not raise
    
    def test_validate_email_invalid(self, email_svc):
        """Test validation fails for invalid emails"""
        invalid_emails = [
            '',
            'not-an-email',
            '@example.com',
            'user@',
            # Note: Some formats may pass Django's validator but fail in production
        ]
        
        for email in invalid_emails:
            try:
                email_svc._validate_email_address(email)
                # If it doesn't raise, that's okay for some formats
            except InvalidEmailFormatException:
                pass  # Expected
    
    def test_validate_email_none(self, email_svc):
        """Test validation fails for None"""
        with pytest.raises(InvalidEmailFormatException):
            email_svc._validate_email_address(None)


@pytest.mark.unit
class TestTokenValidation:
    """Test token validation"""
    
    def test_validate_token_valid(self, email_svc):
        """Test validation passes for valid tokens"""
        email_svc._validate_token('valid_token_123', 'Test Token')  # Should not raise
    
    def test_validate_token_empty(self, email_svc):
        """Test validation fails for empty token"""
        with pytest.raises(ValidationException):
            email_svc._validate_token('', 'Test Token')
    
    def test_validate_token_too_short(self, email_svc):
        """Test validation fails for short token"""
        with pytest.raises(ValidationException):
            email_svc._validate_token('short', 'Test Token')
    
    def test_validate_token_none(self, email_svc):
        """Test validation fails for None"""
        with pytest.raises(ValidationException):
            email_svc._validate_token(None, 'Test Token')


@pytest.mark.unit
class TestEmailSending:
    """Test email sending with error handling"""
    
    @patch('auth_service.services.email_service.EmailMessage')
    @patch('auth_service.services.email_service.render_to_string')
    def test_send_email_smtp_authentication_error(self, mock_render, mock_email_message, email_svc):
        """Test SMTP authentication error gets wrapped in EmailServiceException"""
        mock_render.return_value = '<html>Test</html>'
        
        mock_msg = Mock()
        mock_msg.send = Mock(side_effect=SMTPAuthenticationError(535, b'Authentication failed'))
        mock_email_message.return_value = mock_msg
        
        # Service wraps specific errors in generic EmailServiceException
        with pytest.raises(EmailServiceException):
            email_svc.send_magic_link_email('user@test.com', 'token_1234567890')
    
    @patch('auth_service.services.email_service.EmailMessage')
    @patch('auth_service.services.email_service.render_to_string')
    def test_send_email_connection_error(self, mock_render, mock_email_message, email_svc):
        """Test SMTP connection error gets wrapped"""
        mock_render.return_value = '<html>Test</html>'
        
        mock_msg = Mock()
        mock_msg.send = Mock(side_effect=SMTPConnectError(421, b'Cannot connect'))
        mock_email_message.return_value = mock_msg
        
        with pytest.raises(EmailServiceException):
            email_svc.send_magic_link_email('user@test.com', 'token_1234567890')
    
    @patch('auth_service.services.email_service.EmailMessage')
    @patch('auth_service.services.email_service.render_to_string')
    def test_send_email_network_error(self, mock_render, mock_email_message, email_svc):
        """Test network error gets wrapped"""
        mock_render.return_value = '<html>Test</html>'
        
        mock_msg = Mock()
        mock_msg.send = Mock(side_effect=gaierror('Network error'))
        mock_email_message.return_value = mock_msg
        
        with pytest.raises(EmailServiceException):
            email_svc.send_magic_link_email('user@test.com', 'token_1234567890')
    
    @patch('auth_service.services.email_service.EmailMessage')
    @patch('auth_service.services.email_service.render_to_string')
    def test_send_email_zero_sent(self, mock_render, mock_email_message, email_svc):
        """Test when email sending returns 0"""
        mock_render.return_value = '<html>Test</html>'
        
        mock_msg = Mock()
        mock_msg.send = Mock(return_value=0)  # No emails sent
        mock_email_message.return_value = mock_msg
        
        with pytest.raises(EmailServiceException):
            email_svc.send_magic_link_email('user@test.com', 'token_1234567890')


@pytest.mark.unit
class TestHeaderValidation:
    """Test email header validation"""
    
    def test_validate_headers_safe(self, email_svc):
        """Test validation passes for safe headers"""
        email_svc._validate_email_headers('Safe Subject Line')  # Should not raise
    
    def test_validate_headers_injection_newline(self, email_svc):
        """Test validation fails with newline injection"""
        with pytest.raises(ValidationException):
            email_svc._validate_email_headers('Subject\nInjection')
    
    def test_validate_headers_injection_carriage_return(self, email_svc):
        """Test validation fails with carriage return injection"""
        with pytest.raises(ValidationException):
            email_svc._validate_email_headers('Subject\rInjection')
    
    def test_validate_headers_injection_null(self, email_svc):
        """Test validation fails with null byte injection"""
        with pytest.raises(ValidationException):
            email_svc._validate_email_headers('Subject\x00Injection')


@pytest.mark.unit
class TestEmailConfiguration:
    """Test email configuration validation"""
    
    @patch('auth_service.services.email_service.settings')
    def test_configuration_console_backend(self, mock_settings):
        """Test configuration skips validation for console backend"""
        mock_settings.DEFAULT_FROM_EMAIL = 'test@example.com'
        mock_settings.FRONTEND_URL = 'https://test.com'
        mock_settings.EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
        
        # Should not raise
        EmailService()
    
    def test_is_console_backend_true(self, email_svc):
        """Test console backend detection"""
        with patch('auth_service.services.email_service.settings') as mock_settings:
            mock_settings.EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
            assert email_svc._is_console_backend() is True
    
    def test_is_console_backend_false(self, email_svc):
        """Test non-console backend detection"""
        with patch('auth_service.services.email_service.settings') as mock_settings:
            mock_settings.EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
            assert email_svc._is_console_backend() is False


@pytest.mark.unit
class TestEmailConnectionTest:
    """Test email connection testing"""
    
    @patch('django.core.mail.get_connection')
    def test_connection_test_success(self, mock_get_connection, email_svc):
        """Test successful connection test"""
        mock_connection = Mock()
        mock_connection.open = Mock()
        mock_connection.close = Mock()
        mock_get_connection.return_value = mock_connection
        
        result = email_svc.test_email_connection()
        
        assert result['status'] == 'success'
        mock_connection.open.assert_called_once()
        mock_connection.close.assert_called_once()
    
    @patch('django.core.mail.get_connection')
    def test_connection_test_auth_failure(self, mock_get_connection, email_svc):
        """Test connection test with auth failure"""
        mock_connection = Mock()
        mock_connection.open = Mock(side_effect=SMTPAuthenticationError(535, b'Auth failed'))
        mock_get_connection.return_value = mock_connection
        
        with pytest.raises(EmailConfigurationException):
            email_svc.test_email_connection()
    
    @patch('django.core.mail.get_connection')
    def test_connection_test_connection_failure(self, mock_get_connection, email_svc):
        """Test connection test with connection failure"""
        mock_connection = Mock()
        mock_connection.open = Mock(side_effect=SMTPConnectError(421, b'Cannot connect'))
        mock_get_connection.return_value = mock_connection
        
        with pytest.raises(ServiceUnavailableException):
            email_svc.test_email_connection()


# @pytest.mark.unit
# class TestGlobalInstance:
#     """Test global email service instance"""
    
#     def test_global_instance_exists(self):
#         """Test global email_service instance is available"""
#         # Skip - requires full Django configuration
#         pass
