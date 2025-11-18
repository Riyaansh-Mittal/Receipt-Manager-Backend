from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class BaseServiceException(APIException):
    """Base exception for all service exceptions"""
    default_code = "service_error"
    default_detail = "A service error occurred"

    def __init__(
        self,
        detail: Optional[str] = None,
        code: Optional[str] = None,
        status_code: int = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        resolved_code = code or getattr(self, "default_code", "error")
        resolved_detail = detail or getattr(self, "default_detail", "An error occurred")
    
        # CRITICAL: Only set status_code if explicitly provided
        # Otherwise, use the class attribute (which subclasses define)
        if status_code is not None:
            self.status_code = status_code
        elif not hasattr(self.__class__, 'status_code'):
            # If no class attribute and no parameter, use 500
            self.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        # else: use the class attribute that's already there

        super().__init__(detail=resolved_detail, code=resolved_code)
        # Set other attributes
        self.code = resolved_code
        self.detail = resolved_detail
        self.context = context or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": getattr(self, "code", "error"),
                "message": str(self.detail),
                "status_code": self.status_code,
                "context": self.context,
                "type": self.__class__.__name__,
            }
        }

# ========================
# Authentication & Authorization Exceptions
# ========================
class AuthenticationException(BaseServiceException):
    default_code = 'authentication_failed'
    default_detail = 'Authentication failed'
    status_code = status.HTTP_401_UNAUTHORIZED

class AuthorizationException(BaseServiceException):
    default_code = 'authorization_failed'
    default_detail = 'Authorization failed'
    status_code = status.HTTP_403_FORBIDDEN

class InvalidTokenException(AuthenticationException):
    default_code = 'invalid_token'
    default_detail = 'Invalid or expired token'

class TokenExpiredException(AuthenticationException):
    default_code = 'token_expired'
    default_detail = 'Token has expired'

class TokenBlacklistedException(AuthenticationException):
    default_code = 'token_blacklisted'
    default_detail = 'Token has been revoked'

class MagicLinkAlreadyUsedException(AuthenticationException):
    default_code = 'magic_link_used'
    default_detail = 'This magic link has already been used. Please request a new one.'
    status_code = status.HTTP_400_BAD_REQUEST  # 400, not 401

class MagicLinkExpiredException(AuthenticationException):
    default_code = 'magic_link_expired'
    default_detail = 'This magic link has expired. Please request a new one.'
    status_code = status.HTTP_400_BAD_REQUEST  # 400, not 401

class InvalidMagicLinkException(AuthenticationException):
    default_code = 'invalid_magic_link'
    default_detail = 'Invalid magic link. Please request a new one.'
    status_code = status.HTTP_400_BAD_REQUEST  # 400, not 401

# ========================
# User Management Exceptions
# ========================
class UserNotFoundException(BaseServiceException):
    default_code = 'user_not_found'
    default_detail = 'User not found'
    status_code = status.HTTP_404_NOT_FOUND

class EmailAlreadyExistsException(BaseServiceException):
    default_code = 'email_exists'
    default_detail = 'Email address already exists'
    status_code = status.HTTP_409_CONFLICT

class EmailNotVerifiedException(BaseServiceException):
    default_code = 'email_not_verified'
    default_detail = 'Email address is not verified'
    status_code = status.HTTP_403_FORBIDDEN

class InvalidEmailVerificationTokenException(BaseServiceException):
    default_code = 'invalid_verification_token'
    default_detail = 'Invalid email verification token'
    status_code = status.HTTP_400_BAD_REQUEST

class EmailVerificationTokenExpiredException(BaseServiceException):
    default_code = 'verification_token_expired'
    default_detail = 'Email verification token has expired'
    status_code = status.HTTP_400_BAD_REQUEST

# ========================
# Database & Cache Exceptions
# ========================
class DatabaseOperationException(BaseServiceException):
    default_code = 'database_error'
    default_detail = 'Database operation failed'
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

class CacheOperationException(BaseServiceException):
    default_code = 'cache_error'
    default_detail = 'Cache operation failed'
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

class ModelCreationException(DatabaseOperationException):
    default_code = 'model_creation_failed'
    default_detail = 'Failed to create database record'

class ModelUpdateException(DatabaseOperationException):
    default_code = 'model_update_failed'
    default_detail = 'Failed to update database record'

class ModelDeletionException(DatabaseOperationException):
    default_code = 'model_deletion_failed'
    default_detail = 'Failed to delete database record'

# ========================
# Email Service Exceptions
# ========================
class EmailServiceException(BaseServiceException):
    default_code = 'email_service_error'
    default_detail = 'Email service error'
    status_code = status.HTTP_502_BAD_GATEWAY

class EmailSendFailedException(EmailServiceException):
    default_code = 'email_send_failed'
    default_detail = 'Failed to send email'

class EmailTemplateException(EmailServiceException):
    default_code = 'email_template_error'
    default_detail = 'Email template processing failed'

class EmailConfigurationException(EmailServiceException):
    default_code = 'email_config_error'
    default_detail = 'Email service configuration error'

# ========================
# Rate Limiting & Security Exceptions
# ========================
class RateLimitExceededException(BaseServiceException):
    default_code = "rate_limit_exceeded"
    default_detail = "Rate limit exceeded"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS

    def __init__(self, detail=None, retry_after: int = None, **kwargs):
        super().__init__(detail=detail, **kwargs)
        if retry_after:
            self.context['retry_after'] = retry_after

class SecurityViolationException(BaseServiceException):
    default_code = 'security_violation'
    default_detail = 'Security policy violation detected'
    status_code = status.HTTP_403_FORBIDDEN

class SuspiciousActivityException(SecurityViolationException):
    default_code = 'suspicious_activity'
    default_detail = 'Suspicious activity detected'

class IPBlockedException(SecurityViolationException):
    default_code = 'ip_blocked'
    default_detail = 'IP address has been blocked'

# ========================
# Token Generation Exceptions
# ========================
class TokenGenerationException(BaseServiceException):
    default_code = 'token_generation_failed'
    default_detail = 'Failed to generate authentication token'
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

class CryptographicException(BaseServiceException):
    default_code = 'cryptographic_error'
    default_detail = 'Cryptographic operation failed'
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

# ========================
# Validation Exceptions
# ========================
class ValidationException(BaseServiceException):
    default_code = "validation_error"
    default_detail = "Validation failed"
    status_code = status.HTTP_400_BAD_REQUEST

class InvalidEmailFormatException(ValidationException):
    default_code = 'invalid_email_format'
    default_detail = 'Invalid email address format'

class InvalidUserDataException(ValidationException):
    default_code = 'invalid_user_data'
    default_detail = 'Invalid user data provided'

class MissingRequiredFieldException(ValidationException):
    default_code = 'missing_required_field'
    default_detail = 'Required field is missing'

# ========================
# Resource Exceptions
# ========================
class ResourceNotFoundException(BaseServiceException):
    default_code = 'resource_not_found'
    default_detail = 'Requested resource not found'
    status_code = status.HTTP_404_NOT_FOUND

class ResourceConflictException(BaseServiceException):
    default_code = 'resource_conflict'
    default_detail = 'Resource conflict detected'
    status_code = status.HTTP_409_CONFLICT

class ResourceGoneException(BaseServiceException):
    default_code = 'resource_gone'
    default_detail = 'Requested resource is no longer available'
    status_code = status.HTTP_410_GONE

# ========================
# Service Layer Exceptions
# ========================
class ServiceConfigurationException(BaseServiceException):
    default_code = 'service_config_error'
    default_detail = 'Service configuration error'
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

class ServiceUnavailableException(BaseServiceException):
    default_code = 'service_unavailable'
    default_detail = 'Service is temporarily unavailable'
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

class ExternalServiceException(BaseServiceException):
    default_code = 'external_service_error'
    default_detail = 'External service error'
    status_code = status.HTTP_502_BAD_GATEWAY

class ServiceTimeoutException(BaseServiceException):
    default_code = 'service_timeout'
    default_detail = 'Service operation timed out'
    status_code = status.HTTP_504_GATEWAY_TIMEOUT

# ========================
# Business Logic Exceptions
# ========================
class BusinessLogicException(BaseServiceException):
    default_code = 'business_logic_error'
    default_detail = 'Business logic validation failed'
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

class OperationNotAllowedException(BusinessLogicException):
    default_code = 'operation_not_allowed'
    default_detail = 'Operation is not allowed in current state'

class QuotaExceededException(BusinessLogicException):
    default_code = 'quota_exceeded'
    default_detail = 'User quota has been exceeded'

# ========================
# Enhanced Exception Handler
# ========================
def format_exception_response(exc, context=None):
    """Enhanced exception response formatter with comprehensive logging"""
    
    # Extract request information for logging
    request = context.get("request") if context else None
    user_id = getattr(request.user, 'id', 'anonymous') if request and hasattr(request, 'user') else 'anonymous'
    ip_address = request.META.get('REMOTE_ADDR', 'unknown') if request else 'unknown'
    
    # Log exception details
    log_context = {
        'user_id': user_id,
        'ip_address': ip_address,
        'path': request.path if request else 'unknown',
        'method': request.method if request else 'unknown',
        'exception_type': exc.__class__.__name__
    }

    if isinstance(exc, BaseServiceException):
        # Our custom exceptions - log at appropriate level
        if exc.status_code >= 500:
            logger.error(f"Server error: {str(exc)}", extra=log_context, exc_info=True)
        elif exc.status_code >= 400:
            logger.warning(f"Client error: {str(exc)}", extra=log_context)
        else:
            logger.info(f"Service exception: {str(exc)}", extra=log_context)
        
        response_data = exc.to_dict()
        
    elif isinstance(exc, APIException):
        # DRF exceptions
        logger.warning(f"DRF Exception: {str(exc)}", extra=log_context)
        
        response_data = {
            "error": {
                "code": getattr(exc, "code", getattr(exc, "default_code", "api_error")),
                "message": str(getattr(exc, "detail", exc)),
                "status_code": getattr(exc, "status_code", status.HTTP_400_BAD_REQUEST),
                "type": exc.__class__.__name__,
                "context": getattr(exc, "context", {}),
            }
        }
        
    else:
        # Unexpected exceptions - always log as error
        logger.error(f"Unexpected exception: {str(exc)}", extra=log_context, exc_info=True)
        
        response_data = {
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred",
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "type": "UnexpectedException",
                "context": {}
            }
        }

    # Add correlation ID if available
    correlation_id = getattr(request, 'correlation_id', None) if request else None
    if correlation_id:
        response_data["error"]["correlation_id"] = correlation_id

    return Response(response_data, status=response_data["error"]["status_code"])

def exception_handler(exc, context):
    """Custom exception handler for DRF"""
    return format_exception_response(exc, context)