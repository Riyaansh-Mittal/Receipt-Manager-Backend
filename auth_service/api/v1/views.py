from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import UserRateThrottle, AnonRateThrottle
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.core.cache import cache
from rest_framework.exceptions import ValidationError as DRFValidationError
import logging
from typing import Dict, Any
from django.utils import timezone
from datetime import datetime
from django.conf import settings

from ...services.auth_import_service import import_service
from ...services.auth_model_service import model_service
from shared.utils.responses import success_response
from shared.utils.exceptions import (
    # Validation exceptions
    ValidationException,
    
    # Authentication exceptions
    AuthenticationException,
    AuthorizationException,  # Now we'll use this
    InvalidTokenException,
    TokenExpiredException,
    
    # User management exceptions
    UserNotFoundException,
    EmailAlreadyExistsException,
    
    # Email exceptions
    EmailServiceException,
    InvalidEmailVerificationTokenException,
    EmailVerificationTokenExpiredException,
    
    # Service exceptions
    ServiceUnavailableException,
    DatabaseOperationException,
    
    # Security exceptions
    RateLimitExceededException,
    SecurityViolationException,
    
    # Business logic exceptions
    BusinessLogicException,
    QuotaExceededException,

    # Magic link specific exceptions
    InvalidMagicLinkException,
    MagicLinkExpiredException,
    MagicLinkAlreadyUsedException,
    TokenGenerationException,
    TokenBlacklistedException
)
from .serializers import (
    RequestMagicLinkSerializer,
    MagicLinkLoginSerializer,
    UserProfileSerializer,
    UpdateEmailSerializer,
    EmailVerificationSerializer,
    RefreshTokenSerializer
)
from ...tasks import (
    send_welcome_email_async
)

logger = logging.getLogger(__name__)

# auth_service/api/v1/views.py

class RequestMagicLinkView(APIView):
    """Request magic link for authentication"""
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    
    def post(self, request):
        """Send magic link to email"""
        try:
            # Validate input
            serializer = RequestMagicLinkSerializer(data=request.data)
            
            if not serializer.is_valid():
                raise ValidationException(
                    detail="Invalid request data",
                    context={'errors': serializer.errors}
                )
            
            email = serializer.validated_data['email']
            
            # Get client info
            client_ip = getattr(request, 'client_ip', request.META.get('REMOTE_ADDR'))
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            # Security validation
            self._validate_request_security(request, email)
            
            # Generate magic link token
            auth_service = import_service.auth_service
            magic_link_data = auth_service.request_magic_link(
                email=email,
                request_ip=client_ip,
                user_agent=user_agent
            )
            
            # Send email asynchronously using Celery task
            from auth_service.tasks import send_magic_link_email_async
            
            # Queue the email task
            task = send_magic_link_email_async.delay(
                email=email,
                token=magic_link_data['token']
            )
            
            logger.info(
                f"Magic link requested for {email}, task_id: {task.id}"
            )
            
            return success_response(
                message="Magic link sent to your email address",
                data={
                    'email': email,
                    'expires_at': magic_link_data['expires_at'],
                }
            )
            
        except (ValidationException, RateLimitExceededException, 
                SecurityViolationException, DatabaseOperationException):
            raise
        
        except Exception as e:
            logger.error(
                f"Unexpected error in magic link request: {str(e)}", 
                exc_info=True
            )
            raise ServiceUnavailableException(
                "Magic link service temporarily unavailable"
            )
    
    def _validate_request_security(self, request, email: str):
        """Additional security validation"""
        client_ip = getattr(request, 'client_ip', request.META.get('REMOTE_ADDR'))
        
        # Check for suspicious patterns
        cache_key = f"magic_link_emails_per_ip:{client_ip}"
        unique_emails = cache.get(cache_key, set())
        
        if isinstance(unique_emails, set) and len(unique_emails) >= 10:
            raise SecurityViolationException(
                "Suspicious activity detected from this IP address",
                context={'ip_address': client_ip}
            )
        
        # Add current email to set
        if isinstance(unique_emails, set):
            unique_emails.add(email)
            cache.set(cache_key, unique_emails, timeout=3600)

class MagicLinkLoginView(APIView):
    """
    Authenticate using magic link
    
    ✅ Tokens include updated_at claim automatically
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    
    def post(self, request):
        """Verify magic link and login user"""
        try:
            serializer = MagicLinkLoginSerializer(data=request.data)
            
            if not serializer.is_valid():
                raise ValidationException(
                    detail="Invalid request data",
                    context={'errors': serializer.errors}
                )
            
            token = serializer.validated_data['token']
            client_ip = getattr(request, 'client_ip', request.META.get('REMOTE_ADDR'))
            
            self._validate_login_security(request, token)
            
            # Verify magic link
            auth_service = import_service.auth_service
            user_data, is_new_user = auth_service.verify_magic_link(token, client_ip)
            
            # ✅ Tokens in response already include updated_at claim
            
            if is_new_user:
                try:
                    send_welcome_email_async.delay(
                        user_data['user']['email'],
                        user_data['user']['first_name'] or 'User'
                    )
                except Exception as e:
                    logger.warning(f"Failed to queue welcome email: {str(e)}")
            
            logger.info(f"Successful login for: {user_data['user']['email']}")
            
            response_message = (
                "Welcome! Account created successfully." if is_new_user 
                else "Login successful"
            )
            
            return success_response(
                message=response_message,
                data={
                    'user': user_data['user'],
                    'tokens': user_data['tokens'],  # ✅ Includes updated_at
                    'is_new_user': is_new_user
                }
            )
            
        except (ValidationException, InvalidMagicLinkException,
                MagicLinkExpiredException, MagicLinkAlreadyUsedException,
                InvalidTokenException,
                SecurityViolationException, DatabaseOperationException,
                TokenGenerationException, RateLimitExceededException,
                TokenExpiredException, TokenBlacklistedException):
            raise
            
        except Exception as e:
            logger.error(f"Unexpected error in magic link login: {str(e)}")
            raise ServiceUnavailableException("Login service temporarily unavailable")
    
    def _validate_login_security(self, request, token: str):
        """Additional login security validation"""
        client_ip = getattr(request, 'client_ip', request.META.get('REMOTE_ADDR'))
        
        cache_key = f"login_attempts_ip:{client_ip}"
        attempts = cache.get(cache_key, 0)
        
        if attempts >= 20:
            raise SecurityViolationException(
                "Too many login attempts from this IP address",
                context={'ip_address': client_ip, 'retry_after': 3600}
            )
        
        cache.set(cache_key, attempts + 1, timeout=3600)

class UserProfileView(APIView):
    """
    User profile management
    NOTE: Email updates are handled by UpdateEmailView
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get user profile"""
        try:
            serializer = UserProfileSerializer(request.user)
            return success_response(
                message="Profile retrieved successfully",
                data=serializer.data
            )
        except Exception as e:
            logger.error(f"Profile retrieval failed: {str(e)}", exc_info=True)
            raise ServiceUnavailableException(
                "Profile service temporarily unavailable"
            )
    
    def put(self, request):
        """
        Update user profile (NON-EMAIL fields only)
        Email updates use dedicated endpoint
        """
        try:
            # Remove email if present
            data = request.data.copy()
            if 'email' in data:
                raise ValidationException(
                    detail="Email cannot be updated here",
                    context={
                        'suggestion': 'Use POST /api/v1/email/update/ to change email'
                    }
                )
            
            serializer = UserProfileSerializer(
                request.user,
                data=data,
                partial=True
            )
            
            try:
                serializer.is_valid(raise_exception=True)
            except DRFValidationError as e:
                raise ValidationException(
                    detail="Invalid profile data",
                    context={'validation_errors': e.detail}
                )
            
            user = serializer.save()
            
            logger.info(f"Profile updated: user={user.id}")
            
            return success_response(
                message="Profile updated successfully",
                data=UserProfileSerializer(user).data
            )
            
        except ValidationException:
            raise
        except Exception as e:
            logger.error(f"Profile update failed: {str(e)}", exc_info=True)
            raise ServiceUnavailableException(
                "Profile update service temporarily unavailable"
            )

class UpdateEmailView(APIView):
    """
    Update user email address
    
    ✅ RESPONSIBILITY 1: Blacklists ALL tokens on email change request
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]
    
    def post(self, request):
        """Request email change with token invalidation"""
        try:
            serializer = UpdateEmailSerializer(data=request.data)
            
            try:
                serializer.is_valid(raise_exception=True)
            except DRFValidationError as e:
                raise ValidationException(
                    detail="Invalid email data",
                    context={'validation_errors': e.detail}
                )
            
            new_email = serializer.validated_data['new_email']
            
            # Request email change (blacklists tokens internally)
            auth_service = import_service.auth_service
            result = auth_service.request_email_change(
                str(request.user.id),
                new_email
            )
            
            logger.info(f"Email change requested: user={request.user.id}")
            
            return success_response(
                message="Email update requested. Check your new email for verification. You have been logged out for security.",
                data={
                    'current_email': result['current_email'],
                    'pending_email': result['pending_email'],
                    'verification_required': True,
                    'expires_at': result['verification_expires_at'],
                    'requires_relogin': result['requires_relogin']
                }
            )
            
        except (ValidationException, BusinessLogicException, 
                EmailAlreadyExistsException, QuotaExceededException):
            raise
        
        except Exception as e:
            logger.error(f"Email update failed: {str(e)}", exc_info=True)
            raise ServiceUnavailableException(
                "Email update service temporarily unavailable"
            )



class EmailVerificationView(APIView):
    """
    Verify email address
    
    ✅ RESPONSIBILITY 3: Returns new tokens after verification
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    
    def post(self, request):
        """Verify email and return new tokens"""
        try:
            serializer = EmailVerificationSerializer(data=request.data)
            
            try:
                serializer.is_valid(raise_exception=True)
            except DRFValidationError as e:
                raise ValidationException(
                    detail="Invalid verification data",
                    context={'validation_errors': e.detail}
                )
            
            token = serializer.validated_data['token']
            
            # Verify email (generates new tokens internally)
            auth_service = import_service.auth_service
            result = auth_service.verify_email(token)
            
            logger.info(f"Email verified: {result['email']}")
            
            # ✅ Check if tokens were generated
            if result.get('tokens'):
                message = "Email verified successfully. You can now use your new email."
            else:
                message = "Email verified successfully. Please login with your new email."
                result['requires_manual_login'] = True
            
            return success_response(
                message=message,
                data=result  # ✅ Includes tokens if generated
            )
            
        except (InvalidEmailVerificationTokenException, 
                EmailVerificationTokenExpiredException,
                EmailAlreadyExistsException) as e:
            raise ValidationException(
                detail=str(e),
                context={
                    'suggestion': 'Request a new verification email if token expired'
                }
            )
        
        except Exception as e:
            logger.error(f"Verification failed: {str(e)}", exc_info=True)
            raise AuthenticationException("Email verification failed")

class ResendVerificationView(APIView):
    """Resend verification email"""
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]
    
    def post(self, request):
        """Resend verification for current or pending email"""
        try:
            auth_service = import_service.auth_service
            result = auth_service.resend_verification_email(str(request.user.id))
            
            return success_response(
                message=result.get('message', 'Verification email sent'),
                data={
                    'current_email': result['current_email'],
                    'verification_email': result['verification_email'],
                    'is_email_change': result['is_email_change'],
                    'expires_at': result['expires_at']
                }
            )
            
        except (BusinessLogicException, QuotaExceededException) as e:
            raise ValidationException(detail=str(e))
        
        except Exception as e:
            logger.error(f"Resend failed: {str(e)}", exc_info=True)
            raise ServiceUnavailableException(
                "Verification service temporarily unavailable"
            )

class RefreshTokenView(APIView):
    """
    Refresh JWT access token
    
    ✅ RESPONSIBILITY 2: Validates token against user state
    """
    permission_classes = [AllowAny]
    throttle_classes = [UserRateThrottle]
    
    def post(self, request):
        """Refresh access token with user state validation"""
        try:
            serializer = RefreshTokenSerializer(data=request.data)
            
            if not serializer.is_valid():
                raise ValidationException(
                    detail="Invalid token data",
                    context={'errors': serializer.errors}
                )
            
            refresh_token = serializer.validated_data['refresh']
            
            self._validate_token_refresh_security(request, refresh_token)
            
            # ✅ This validates token against user.updated_at internally
            # Will fail if user changed email/password after token issued
            auth_service = import_service.auth_service
            new_tokens = auth_service.refresh_jwt_token(refresh_token)
            
            return success_response(
                message="Token refreshed successfully",
                data={'tokens': new_tokens}
            )
            
        except InvalidTokenException as e:
            # ✅ Token invalid due to user state change
            raise ValidationException(
                detail=str(e),
                context={
                    'requires_relogin': True,
                    'reason': 'user_data_changed',
                    'suggestion': 'Please login again'
                }
            )
        
        except (ValidationException, TokenExpiredException,
                TokenBlacklistedException, SecurityViolationException):
            raise
        
        except Exception as e:
            logger.error(f"Token refresh failed: {str(e)}")
            raise AuthenticationException("Token refresh failed")
    
    def _validate_token_refresh_security(self, request, refresh_token: str):
        """Additional token refresh security validation"""
        client_ip = getattr(request, 'client_ip', request.META.get('REMOTE_ADDR'))
        
        cache_key = f"token_refresh_ip:{client_ip}"
        attempts = cache.get(cache_key, 0)
        
        if attempts >= 50:
            raise SecurityViolationException(
                "Too many token refresh attempts from this IP",
                context={'ip_address': client_ip, 'retry_after': 3600}
            )
        
        cache.set(cache_key, attempts + 1, timeout=3600)

class UserStatsView(APIView):
    """User statistics and usage with authorization"""
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]
    
    @method_decorator(cache_page(300))
    def get(self, request) -> Dict[str, Any]:
        """Get user statistics with access validation"""
        try:
            # Validate user access
            if not request.user.is_active:
                raise AuthorizationException("Account must be active to view statistics")
            
            user = request.user
            
            # Get cached stats or calculate
            cache_key = f"user_stats:{user.id}"
            stats = cache.get(cache_key)
            
            if not stats:
                # Calculate stats with error handling
                try:
                    stats = {
                        'upload_count': user.monthly_upload_count,
                        'upload_limit': 50,
                        'remaining_uploads': max(0, 50 - user.monthly_upload_count),
                        'account_age_days': (timezone.now() - user.created_at).days,
                        'email_verified': user.is_email_verified,
                        'account_status': 'active' if user.is_active else 'inactive',
                    }
                    
                    # Cache stats for 5 minutes
                    cache.set(cache_key, stats, timeout=300)
                    
                except Exception as e:
                    logger.error(f"Error calculating user stats: {str(e)}")
                    raise ServiceUnavailableException("Statistics service temporarily unavailable")
            
            return success_response(
                message="User statistics retrieved",
                data=stats
            )
            
        except (AuthorizationException, ServiceUnavailableException):
            raise
        except Exception as e:
            logger.error(f"Error retrieving stats for user {request.user.id}: {str(e)}")
            raise ServiceUnavailableException("Statistics service temporarily unavailable")

class LogoutView(APIView):
    """
    Enhanced logout with JWT token blacklisting
    
    ✅ Properly blacklists tokens and cleans up session
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]
    
    def post(self, request):
        """Logout user and blacklist tokens"""
        try:
            # Validate user can logout
            self._validate_logout_permissions(request.user)
            
            # Get tokens from request
            refresh_token = request.data.get('refresh')
            access_token = None
            
            # Extract access token from header
            auth_header = request.META.get('HTTP_AUTHORIZATION')
            if auth_header and auth_header.startswith('Bearer '):
                access_token = auth_header.split(' ')[1]
            
            # Validate at least one token is provided
            if not refresh_token and not access_token:
                raise ValidationException(
                    "At least one token (access or refresh) must be provided for logout"
                )
            
            jwt_service = import_service.jwt_service
            client_ip = getattr(request, 'client_ip', request.META.get('REMOTE_ADDR'))
            user_id = str(request.user.id)
            
            blacklisted_tokens = []
            blacklist_errors = []
            
            # Blacklist refresh token
            if refresh_token:
                try:
                    if jwt_service.blacklist_token(
                        token=refresh_token,
                        token_type='refresh',
                        user_id=user_id,
                        reason='logout',
                        ip_address=client_ip
                    ):
                        blacklisted_tokens.append('refresh')
                        logger.info(
                            f"Refresh token blacklisted for user: {request.user.email}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to blacklist refresh token: {str(e)}")
                    blacklist_errors.append(f'refresh token error: {str(e)}')
            
            # Blacklist access token
            if access_token:
                try:
                    if jwt_service.blacklist_token(
                        token=access_token,
                        token_type='access',
                        user_id=user_id,
                        reason='logout',
                        ip_address=client_ip
                    ):
                        blacklisted_tokens.append('access')
                        logger.info(
                            f"Access token blacklisted for user: {request.user.email}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to blacklist access token: {str(e)}")
                    blacklist_errors.append(f'access token error: {str(e)}')
            
            # Log logout attempt
            self._log_logout_attempt(request.user, client_ip, success=True)
            
            logger.info(f"User logged out successfully: {request.user.email}")
            
            # Prepare response data
            response_data = {
                'user_id': user_id,
                'blacklisted_tokens': blacklisted_tokens,
                'logout_time': timezone.now().isoformat()
            }
            
            if blacklist_errors:
                response_data['warnings'] = blacklist_errors
                logger.warning(
                    f"Logout completed with warnings for user {user_id}: "
                    f"{blacklist_errors}"
                )
            
            return success_response(
                message="Logged out successfully",
                data=response_data
            )
            
        except (ValidationException, AuthorizationException):
            raise
        
        except Exception as e:
            logger.error(
                f"Unexpected error during logout for user {request.user.id}: {str(e)}"
            )
            
            # Log failed logout
            client_ip = getattr(request, 'client_ip', request.META.get('REMOTE_ADDR'))
            self._log_logout_attempt(request.user, client_ip, success=False, error=str(e))
            
            # Still return success to avoid confusion
            return success_response(
                message="Logged out successfully",
                data={
                    'user_id': str(request.user.id),
                    'logout_time': timezone.now().isoformat(),
                    'note': 'Token cleanup may be pending'
                }
            )
    
    def _validate_logout_permissions(self, user):
        """Validate user can perform logout"""
        if not user or not user.is_authenticated:
            raise AuthenticationException("User must be authenticated to logout")
    
    def _log_logout_attempt(self, user, ip_address: str, success: bool, error: str = None):
        """Log logout attempt for security monitoring"""
        try:
            LoginAttempt = model_service.login_attempt_model
            
            LoginAttempt.objects.create(
                email=user.email,
                ip_address=ip_address or '0.0.0.0',
                success=success,
                failure_reason=f'logout_error: {error}' if error else 'logout_success'
            )
        except Exception as e:
            logger.warning(f"Failed to log logout attempt: {str(e)}")


class CheckTokenStatusView(APIView):
    """
    Check if current token is valid
    
    ✅ NEW: Validates token against user state (email changes, etc.)
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]
    
    def get(self, request):
        """Check current token status with user state validation"""
        try:
            access_token = None
            auth_header = request.META.get('HTTP_AUTHORIZATION')
            
            if auth_header and auth_header.startswith('Bearer '):
                access_token = auth_header.split(' ')[1]
            else:
                raise ValidationException("No access token found in request")
            
            jwt_service = import_service.jwt_service
            
            # ✅ NEW: Validate token against user state
            try:
                validation_result = jwt_service.validate_token_against_user(access_token)
                is_valid_for_user = True
                validation_message = None
            except InvalidTokenException as e:
                is_valid_for_user = False
                validation_message = str(e)
            
            # Check if token is blacklisted
            is_blacklisted = jwt_service.is_token_blacklisted(access_token)
            
            # Decode token to get expiry info
            try:
                decoded_token = jwt_service.decode_token(access_token, verify_exp=False)
                exp_timestamp = decoded_token.get('exp')
                updated_at_timestamp = decoded_token.get('updated_at')
                token_email = decoded_token.get('email')
                
                if exp_timestamp:
                    expires_at = timezone.make_aware(
                        datetime.fromtimestamp(exp_timestamp),
                        timezone.get_current_timezone()
                    )
                    now = timezone.now()
                    time_until_expiry = expires_at - now
                else:
                    expires_at = None
                    time_until_expiry = None
                
                # ✅ NEW: Check if user was modified after token issue
                user_modified = False
                if updated_at_timestamp and hasattr(request.user, 'updated_at'):
                    current_updated_at = int(request.user.updated_at.timestamp())
                    user_modified = current_updated_at > updated_at_timestamp
                    
            except Exception as e:
                logger.warning(f"Could not decode token for status check: {str(e)}")
                expires_at = None
                time_until_expiry = None
                token_email = None
                user_modified = False
            
            # ✅ Comprehensive token status
            token_status = {
                'is_valid': (
                    not is_blacklisted and 
                    is_valid_for_user and
                    (time_until_expiry is None or time_until_expiry.total_seconds() > 0) and
                    not user_modified
                ),
                'is_blacklisted': is_blacklisted,
                'is_valid_for_user': is_valid_for_user,
                'validation_message': validation_message,
                'user_modified_after_token': user_modified,
                'token_email': token_email,
                'current_email': request.user.email,
                'email_mismatch': token_email and token_email != request.user.email,
                'expires_at': expires_at.isoformat() if expires_at else None,
                'seconds_until_expiry': (
                    int(time_until_expiry.total_seconds()) 
                    if time_until_expiry and time_until_expiry.total_seconds() > 0 
                    else None
                ),
                'user_id': str(request.user.id),
                'user_email': request.user.email,
                'requires_relogin': (
                    is_blacklisted or 
                    not is_valid_for_user or 
                    user_modified or
                    (token_email and token_email != request.user.email)
                )
            }
            
            return success_response(
                message="Token status retrieved",
                data=token_status
            )
            
        except (ValidationException, InvalidTokenException):
            raise
        
        except Exception as e:
            logger.error(f"Error checking token status: {str(e)}")
            raise ServiceUnavailableException(
                "Token status service temporarily unavailable"
            )