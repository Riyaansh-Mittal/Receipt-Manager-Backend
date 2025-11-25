import secrets
import hashlib
from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
from django.db.models import Q
from django.db import transaction, IntegrityError
from typing import Dict, Tuple
import logging

from .auth_model_service import model_service
from .auth_import_service import import_service
from shared.utils.exceptions import (
    # Authentication exceptions
    InvalidMagicLinkException,
    MagicLinkExpiredException,
    MagicLinkAlreadyUsedException,
    InvalidTokenException,
    AuthenticationException,
    
    # User management exceptions
    UserNotFoundException,
    EmailAlreadyExistsException,
    InvalidEmailVerificationTokenException,
    EmailVerificationTokenExpiredException,
    
    # Database exceptions
    DatabaseOperationException,
    CacheOperationException,
    
    # Security exceptions
    RateLimitExceededException,
    SuspiciousActivityException,
    
    # Token generation exceptions
    TokenGenerationException,
    TokenExpiredException,
    TokenBlacklistedException,

    # Validation exceptions
    ValidationException,
    InvalidEmailFormatException,
    QuotaExceededException,
    
    # Service exceptions
    ServiceConfigurationException,
    BusinessLogicException
)

logger = logging.getLogger(__name__)

class AuthService:
    """Enhanced Authentication service with comprehensive exception handling"""
    
    def __init__(self):
        try:
            self.magic_link_expiry = getattr(settings, 'MAGIC_LINK_EXPIRY_MINUTES', 60)
            self.max_update_email_attempts_per_day = getattr(settings, 'MAX_UPDATE_EMAIL_ATTEMPTS_PER_DAY', 3)
        except Exception as e:
            logger.error(f"Failed to initialize AuthService: {str(e)}")
            raise ServiceConfigurationException("Authentication service configuration error")
    
    def request_magic_link(
        self, 
        email: str, 
        request_ip: str = None,
        user_agent: str = None
    ) -> dict:
        """
        Generate magic link - ✅ FIX: Store USER_ID, not just email
        """
        try:
            self._validate_email_format(email)
            self._check_magic_link_rate_limit(email, request_ip)
            
            # Generate token
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            
            # ✅ FIX: Check if user exists (for login) or new (for signup)
            User = model_service.user_model
            user = User.objects.filter(email__iexact=email).first()
            
            # Create magic link with transaction
            with transaction.atomic():
                MagicLink = model_service.magic_link_model
                magic_link = MagicLink.objects.create(
                    email=email,
                    token=token_hash,
                    expires_at=timezone.now() + timedelta(minutes=self.magic_link_expiry),
                    created_from_ip=request_ip,
                    user_agent=user_agent or ''
                )
            
            # Cache with user_id if exists
            try:
                cache_key = f"magic_link:{token_hash}"
                cache_data = {
                    'email': email,
                    'magic_link_id': str(magic_link.id)
                }
                if user:
                    cache_data['user_id'] = str(user.id)
                
                cache.set(cache_key, cache_data, timeout=self.magic_link_expiry * 60)
            except Exception as e:
                logger.warning(f"Cache operation failed: {str(e)}")
            
            logger.info(
                f"Magic link generated for: {email}, "
                f"user_exists={user is not None}"
            )
            
            return {
                'token': raw_token,
                'expires_at': magic_link.expires_at.isoformat()
            }
            
        except (RateLimitExceededException, ValidationException):
            raise
        
        except Exception as e:
            logger.error(
                f"Unexpected error in magic link generation: {str(e)}", 
                exc_info=True
            )
            raise ServiceConfigurationException("Magic link generation failed")
    
    def verify_magic_link(
        self, 
        token: str, 
        request_ip: str = None
    ) -> Tuple[Dict, bool]:
        """
        Verify magic link and authenticate user
        
        ✅ FIX: Magic link uses email at creation time, not current user email
        This prevents issues when email is changed but not verified
        
        Args:
            token: Magic link token
            request_ip: Client IP address
            
        Returns:
            Tuple of (user_data_dict, is_new_user_bool)
        """
        import time  # Add this import at top of file if not already there
        
        # Validate token format
        if not token or len(token.strip()) < 10:
            raise InvalidMagicLinkException("Invalid token format")
        
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        logger.info(f"Verifying magic link - Token hash: {token_hash[:20]}...")
        
        # Try cache first
        cache_key = f"magic_link:{token_hash}"
        cached_data = None
        try:
            cached_data = cache.get(cache_key)
        except Exception as e:
            logger.warning(f"Cache lookup failed: {str(e)}")
        
        MagicLink = model_service.magic_link_model
        User = model_service.user_model
        
        # Step 1: Verify and mark magic link as used (atomic with retry)
        magic_link = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    # Use select_for_update with NOWAIT to fail fast on lock
                    try:
                        if cached_data:
                            magic_link = MagicLink.objects.select_for_update(nowait=True).get(
                                id=cached_data['magic_link_id']
                            )
                        else:
                            magic_link = MagicLink.objects.select_for_update(nowait=True).get(
                                token=token_hash,
                                is_used=False
                            )
                    except MagicLink.DoesNotExist:
                        # Check if it was used by concurrent request
                        if MagicLink.objects.filter(token=token_hash, is_used=True).exists():
                            raise MagicLinkAlreadyUsedException("Magic link already used")
                        raise InvalidMagicLinkException("Invalid magic link token")
                    except Exception:
                        # Lock timeout - another request is processing
                        if attempt < max_retries - 1:
                            time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                            continue
                        raise DatabaseOperationException("Failed to acquire lock for magic link")
                    
                    # Validate expiration
                    if magic_link.is_expired():
                        raise MagicLinkExpiredException("Magic link has expired")
                    
                    # Mark as used
                    magic_link.mark_as_used(request_ip)
                    break  # Success - exit retry loop
                    
            except (InvalidMagicLinkException, MagicLinkExpiredException, 
                    MagicLinkAlreadyUsedException, DatabaseOperationException):
                raise
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Magic link verification failed after {max_retries} attempts: {str(e)}")
                    raise DatabaseOperationException("Failed to verify magic link")
                # Continue to next retry
        
        # Step 2: Always clear cache after verification attempt
        try:
            cache.delete(cache_key)
        except Exception as e:
            logger.warning(f"Cache clear failed: {str(e)}")
        
        # ✅ FIX: Step 3 - Use magic link email (email at creation time)
        # NOT user.email (which may have changed)
        magic_link_email = magic_link.email
        is_new_user = False
        user = None
        
        try:
            # Try to get existing user by the email used in magic link
            # This is the email when magic link was created
            try:
                user = User.objects.select_related().get(
                    Q(email__iexact=magic_link_email)
                )
                
                # Check if account is locked
                if not user.is_active:
                    raise AuthenticationException(
                        "Account is deactivated",
                        context={'user_id': str(user.id)}
                    )
                
                # ✅ IMPORTANT: Don't update user.email here
                # User might have a pending email change
                # Only update authentication-related fields
                
                logger.info(
                    f"Existing user authenticated: {user.email} "
                    f"(magic link email: {magic_link_email})"
                )
                
            except User.DoesNotExist:
                # User doesn't exist - create new one
                try:
                    with transaction.atomic():
                        user = User.objects.create_user(
                            email=magic_link_email,
                            is_email_verified=True,  # Magic link verifies email
                        )
                        is_new_user = True
                        
                        logger.info(f"New user created: {user.email}")
                        
                except IntegrityError as ie:
                    # Race condition: user created by concurrent request
                    logger.warning(f"Concurrent user creation detected: {str(ie)}")
                    
                    # Fetch the user that was just created
                    try:
                        user = User.objects.get(
                            Q(email__iexact=magic_link_email)
                        )
                        
                        is_new_user = False
                        logger.info(
                            f"User retrieved after concurrent creation: {user.email}"
                        )
                        
                    except User.DoesNotExist:
                        logger.error(
                            f"User not found after IntegrityError: {magic_link_email}"
                        )
                        raise DatabaseOperationException(
                            "User creation failed due to database inconsistency"
                        )
        
        except (AuthenticationException, DatabaseOperationException):
            raise
        except Exception as e:
            logger.error(f"User lookup/creation failed: {str(e)}", exc_info=True)
            raise DatabaseOperationException("Failed to retrieve or create user")
        
        # Verify user object exists
        if not user:
            raise DatabaseOperationException("Failed to retrieve user")
        
        # Step 4: Generate JWT tokens with updated_at claim
        try:
            jwt_service = import_service.jwt_service
            token_data = jwt_service.generate_tokens(user)  # ✅ Now includes updated_at
        except Exception as e:
            logger.error(
                f"Token generation failed for user {user.email}: {str(e)}"
            )
            raise TokenGenerationException(
                "Failed to generate authentication tokens",
                context={'user_id': str(user.id)}
            )
        
        # Step 5: Log successful authentication
        try:
            self._log_login_attempt(
                email=magic_link_email,
                ip_address=request_ip,
                success=True
            )
        except Exception as e:
            logger.warning(f"Failed to log login attempt: {str(e)}")
        
        logger.info(
            f"Magic link authentication successful: {user.email} "
            f"(new_user={is_new_user}, user_id={user.id})"
        )
        
        # Step 6: Optionally sync quota to ensure fresh count on login
        try:
            from receipt_service.services.quota_service import QuotaService
            QuotaService().sync_user_quota(str(user.id))
        except Exception as e:
            logger.warning(f"Quota sync failed during login: {str(e)}")
            # Don't fail login if quota sync fails
        
        # Step 7: Build response with current user email
        return {
            'user': {
                'id': str(user.id),
                'email': user.email,  # Current email (may differ from magic_link_email)
                'first_name': user.first_name or '',
                'last_name': user.last_name or '',
                'is_email_verified': user.is_email_verified,
                'monthly_upload_count': user.monthly_upload_count,
                'created_at': user.created_at.isoformat()
            },
            'tokens': {
                'access': token_data['access'],
                'refresh': token_data['refresh'],
                'expires_at': token_data['expires_at'],
                'refresh_expires_at': token_data['refresh_expires_at']
            },
            'is_new_user': is_new_user
        }, is_new_user
    
    def request_email_change(
        self, 
        user_id: str, 
        new_email: str
    ) -> dict:
        """
        Request email change - TWO PHASE COMMIT
        Phase 1: Create pending verification (this method)
        Phase 2: Update email on verification (verify_email method)
        """
        try:
            User = model_service.user_model
            EmailVerification = model_service.email_verification_model
            
            # Get user
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise UserNotFoundException("User not found")
            
            # Validate email format
            self._validate_email_format(new_email)
            
            # Check if new email is same as current
            if user.email.lower() == new_email.lower():
                raise BusinessLogicException(
                    "New email must be different from current email"
                )
            
            # Check if new email already in use by ANOTHER user
            if User.objects.filter(email__iexact=new_email).exclude(id=user_id).exists():
                raise EmailAlreadyExistsException(
                    "Email address already in use by another account"
                )
            
            # Check if there's a pending verification for this email
            pending_verification = EmailVerification.objects.filter(
                user=user,
                email__iexact=new_email,
                is_verified=False
            ).first()
            
            if pending_verification and not pending_verification.is_expired():
                # Allow retry with same email
                logger.info(
                    f"Resending verification for pending email change: {new_email}"
                )
                raw_token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
                
                # Update existing verification
                pending_verification.token = token_hash
                pending_verification.expires_at = timezone.now() + timedelta(hours=24)
                pending_verification.created_at = timezone.now()
                pending_verification.save()
                
                verification = pending_verification
            else:
                # Check rate limiting
                self._check_email_change_rate_limit(user)
                
                # Create new verification
                with transaction.atomic():
                    # Delete old pending verifications for this user
                    deleted_count = EmailVerification.objects.filter(
                        user=user,
                        is_verified=False
                    ).delete()[0]
                    
                    if deleted_count > 0:
                        logger.info(
                            f"Deleted {deleted_count} expired verifications for user {user.id}"
                        )
                    
                    # Generate token
                    raw_token = secrets.token_urlsafe(32)
                    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
                    
                    
                    # ✅ FIX: DON'T update user email yet
                    # Store new email in EmailVerification ONLY
                    verification = EmailVerification.objects.create(
                        user=user,
                        email=new_email,  # Pending email stored here
                        token=token_hash,
                        expires_at=timezone.now() + timedelta(hours=24)
                    )

                    # ✅ NEW: Update user.updated_at to invalidate old tokens
                    user.updated_at = timezone.now()
                    user.save(update_fields=['updated_at'])
                    
                    logger.info(
                        f"Email change verification created: user={user.id}, "
                        f"current_email={user.email}, pending_email={new_email}"
                    )

            # ✅ CRITICAL: Blacklist ALL tokens for this user
            # This happens OUTSIDE the transaction to avoid lock contention
            try:
                jwt_service = import_service.jwt_service
                blacklisted_count = jwt_service.blacklist_user_tokens(
                    user_id=str(user.id),
                    reason='email_change'
                )
                
                logger.info(
                    f"Blacklisted {blacklisted_count} tokens for user "
                    f"{user.email} due to email change request"
                )
                
            except Exception as blacklist_error:
                logger.error(
                    f"Failed to blacklist tokens during email change: "
                    f"{str(blacklist_error)}"
                )
                # Don't fail the email change request if blacklisting fails
                # Tokens will be invalidated by updated_at claim anyway
            
            # Queue verification email
            try:
                from auth_service.tasks import send_verification_email_async
                
                send_verification_email_async.delay(
                    user_email=new_email,  # Send to NEW email
                    user_name=user.first_name or user.email.split('@')[0],
                    token=raw_token
                )
                
                logger.info(f"Verification email queued for {new_email}")
                
            except Exception as email_error:
                logger.error(
                    f"Failed to queue verification email: {str(email_error)}"
                )
                # Don't fail - user can retry
            
            return {
                'user_id': str(user.id),
                'current_email': user.email,  # OLD email still active
                'pending_email': new_email,   # NEW email pending verification
                'verification_required': True,
                'verification_expires_at': verification.expires_at.isoformat(),
                'requires_relogin': True,  # ✅ Signal to frontend
                'message': 'Verification email sent. Your current email remains active until verified.',
            }
            
        except (UserNotFoundException, BusinessLogicException, 
                EmailAlreadyExistsException, ValidationException):
            raise
        
        except Exception as e:
            logger.error(
                f"Unexpected error in email change: {str(e)}", 
                exc_info=True
            )
            raise ServiceConfigurationException("Email change failed")
    
    def verify_email(self, token: str) -> dict:
        """
        Verify email - THIS is where email actually changes
        
        ✅ Two-phase commit:
        1. request_email_change() - Creates pending verification
        2. verify_email() - Atomically updates user email
        
        Handles:
        - Race conditions
        - Email conflicts
        - Expired tokens
        - Already verified tokens
        """
        try:
            if not token or len(token.strip()) < 10:
                raise InvalidEmailVerificationTokenException(
                    "Invalid verification token format"
                )
            
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            
            logger.info(f"Verifying email with token hash: {token_hash[:16]}...")
            
            EmailVerification = model_service.email_verification_model
            User = model_service.user_model
            
            # Find verification record
            try:
                verification = EmailVerification.objects.get(
                    token=token_hash,
                    is_verified=False
                )
                
                logger.info(
                    f"Found verification: user={verification.user.email}, "
                    f"pending_email={verification.email}, "
                    f"created={verification.created_at}"
                )
                
            except EmailVerification.DoesNotExist:
                logger.warning(f"No verification found for token: {token_hash[:16]}")
                raise InvalidEmailVerificationTokenException(
                    "Invalid or already used verification token"
                )
            
            # Check expiration
            if verification.is_expired():
                logger.warning(f"Token expired: {verification.expires_at}")
                raise EmailVerificationTokenExpiredException(
                    "Verification token has expired. Please request a new one."
                )
            
            # ✅ Update user email atomically with verification
            with transaction.atomic():
                # Lock verification record
                verification_locked = EmailVerification.objects.select_for_update().get(
                    id=verification.id
                )
                user = verification_locked.user
                
                # Double-check not verified by concurrent request
                if verification_locked.is_verified:
                    raise InvalidEmailVerificationTokenException(
                        "This email has already been verified"
                    )
                
                old_email = user.email
                new_email = verification_locked.email
                
                # ✅ CRITICAL: Check if new email is now taken by another user
                # (could happen between request_email_change and verify_email)
                email_conflict = User.objects.filter(
                    email__iexact=new_email
                ).exclude(id=user.id).exists()
                
                if email_conflict:
                    logger.warning(
                        f"Email conflict detected: {new_email} now taken by another user"
                    )
                    # Mark verification as used (consumed)
                    verification_locked.is_verified = True
                    verification_locked.save(update_fields=['is_verified'])
                    
                    raise EmailAlreadyExistsException(
                        "This email address is now in use by another account. "
                        "Please request a new email change."
                    )
                
                # ✅ Check if this is initial signup verification or email change
                is_email_change = (old_email.lower() != new_email.lower())
                
                # ✅ ATOMIC: Update user email AND mark as verified
                user.email = new_email
                user.is_email_verified = True
                user.updated_at = timezone.now()
                user.save(update_fields=['email', 'is_email_verified'])
                
                verification_locked.mark_as_verified()

                # ✅ FIX: Refresh to get updated verified_at timestamp
                verification_locked.refresh_from_db()
                
                logger.info(
                    f"Email verified: user={user.id}, "
                    f"old={old_email}, new={new_email}, "
                    f"is_change={is_email_change}"
                )
            
            # ✅ CRITICAL: Generate NEW tokens with updated email
            # Old tokens are already blacklisted from email change request
            new_tokens = None
            try:
                jwt_service = import_service.jwt_service
                token_data = jwt_service.generate_tokens(user)
                
                new_tokens = {
                    'access': token_data['access'],
                    'refresh': token_data['refresh'],
                    'expires_at': token_data['expires_at'],
                    'refresh_expires_at': token_data['refresh_expires_at']
                }
                
                logger.info(
                    f"Generated new tokens for user {user.email} after email verification"
                )
                
            except Exception as token_error:
                logger.error(
                    f"Failed to generate tokens after verification: {str(token_error)}"
                )
                # Don't fail verification if token generation fails
                # User can login manually
            
            return {
                'user_id': str(user.id),
                'email': new_email,
                'previous_email': old_email if is_email_change else None,
                'verified_at': verification_locked.verified_at.isoformat(),  # Now has value
                'is_email_change': is_email_change,
                'tokens': new_tokens,  # ✅ Include new tokens
                'message': (
                    'Email changed and verified successfully. You can now use your new email to login.' 
                    if is_email_change
                    else 'Email verified successfully'
                )
            }
            
        except (InvalidEmailVerificationTokenException, 
                EmailVerificationTokenExpiredException,
                EmailAlreadyExistsException):
            raise
        
        except Exception as e:
            logger.error(
                f"Unexpected error in verification: {str(e)}", 
                exc_info=True
            )
            raise ServiceConfigurationException("Email verification failed")
    
    def resend_verification_email(self, user_id: str) -> dict:
        """
        Resend verification email
        
        ✅ FIX: Checks for pending email change and resends to pending email
        """
        try:
            User = model_service.user_model
            EmailVerification = model_service.email_verification_model
            
            # Get user
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise UserNotFoundException("User not found")
            
            # ✅ FIX: Check for pending email change verification
            pending_verification = EmailVerification.objects.filter(
                user=user,
                is_verified=False
            ).order_by('-created_at').first()
            
            if pending_verification and not pending_verification.is_expired():
                # There's a pending email change - resend to NEW email
                target_email = pending_verification.email
                is_email_change = (target_email.lower() != user.email.lower())
                
                logger.info(
                    f"Pending verification found: user_email={user.email}, "
                    f"pending_email={target_email}, is_change={is_email_change}"
                )
                
            elif user.is_email_verified:
                # Current email already verified, no pending change
                raise BusinessLogicException(
                    "Email is already verified. "
                    "Use email update endpoint to change email."
                )
            else:
                # No pending verification, user needs to verify current email
                target_email = user.email
                is_email_change = False
            
            # Check rate limiting
            self._check_resend_rate_limit(user)
            
            # Create/update verification token
            with transaction.atomic():
                if pending_verification and not pending_verification.is_expired():
                    # Update existing verification with new token
                    raw_token = secrets.token_urlsafe(32)
                    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
                    
                    pending_verification.token = token_hash
                    pending_verification.expires_at = timezone.now() + timedelta(hours=24)
                    pending_verification.created_at = timezone.now()
                    pending_verification.save()
                    
                    verification = pending_verification
                    logger.info(f"Updated existing verification for {target_email}")
                else:
                    # Delete old expired verifications
                    EmailVerification.objects.filter(
                        user=user,
                        email=target_email,
                        is_verified=False
                    ).delete()
                    
                    # Generate new token
                    raw_token = secrets.token_urlsafe(32)
                    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
                    
                    # Create verification record
                    verification = EmailVerification.objects.create(
                        user=user,
                        email=target_email,
                        token=token_hash,
                        expires_at=timezone.now() + timedelta(hours=24)
                    )
                    logger.info(f"Created new verification for {target_email}")
            
            # Send email to target email
            try:
                from auth_service.tasks import send_verification_email_async
                
                send_verification_email_async.delay(
                    user_email=target_email,
                    user_name=user.first_name or user.email.split('@')[0],
                    token=raw_token
                )
                
                logger.info(f"Verification email queued for {target_email}")
                
            except Exception as email_error:
                logger.error(f"Failed to queue email: {str(email_error)}")
                # Don't fail - user can retry
            
            return {
                'user_id': str(user.id),
                'current_email': user.email,
                'verification_email': target_email,
                'is_email_change': is_email_change,
                'expires_at': verification.expires_at.isoformat(),
                'message': (
                    f'Verification email sent to {target_email}' if is_email_change
                    else 'Verification email resent'
                )
            }
            
        except (UserNotFoundException, BusinessLogicException):
            raise
        except Exception as e:
            logger.error(f"Resend failed: {str(e)}", exc_info=True)
            raise ServiceConfigurationException("Failed to resend verification")
    
    def _check_email_change_rate_limit(self, user):
        """Check email change rate limit"""
        EmailVerification = model_service.email_verification_model
        
        recent_changes = EmailVerification.objects.filter(
            user=user,
            created_at__gte=timezone.now() - timedelta(days=1)
        ).count()
        
        if recent_changes >= self.max_update_email_attempts_per_day:
            raise QuotaExceededException(
                f"Email change limit exceeded ({self.max_update_email_attempts_per_day} per day). Try again tomorrow."
            )
    
    def _check_resend_rate_limit(self, user):
        """Check resend rate limit"""
        from django.core.cache import cache
        
        cache_key = f"email_resend:{user.id}"
        resend_count = cache.get(cache_key, 0)
        
        if resend_count >= 3:
            raise QuotaExceededException(
                "Too many resend requests. Try again in 1 hour."
            )
        
        cache.set(cache_key, resend_count + 1, timeout=3600)
    
    def _validate_email_format(self, email: str):
        """Validate email format"""
        import re
        
        if not email or len(email) < 5:
            raise ValidationException("Invalid email format")
        
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            raise ValidationException("Invalid email format")
    
    def refresh_jwt_token(self, refresh_token: str) -> Dict:
        """
        Refresh JWT token with user state validation
        
        ✅ RESPONSIBILITY 2: Validates token against user.updated_at
        """
        try:
            if not refresh_token or not refresh_token.strip():
                raise InvalidTokenException("Refresh token is required")
            
            jwt_service = import_service.jwt_service
            
            # ✅ This now validates token against user state internally
            # Will fail if user.updated_at changed after token was issued
            return jwt_service.refresh_token(refresh_token)
            
        except (InvalidTokenException, TokenExpiredException, 
                TokenBlacklistedException) as e:
            # These exceptions indicate token is no longer valid
            raise
        except Exception as e:
            logger.error(f"Token refresh error: {str(e)}")
            raise TokenGenerationException("Token refresh failed")
    
    def _validate_email_format(self, email: str):
        """Validate email format"""
        if not email or not email.strip():
            raise InvalidEmailFormatException("Email address is required")
        
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email.strip()):
            raise InvalidEmailFormatException("Invalid email address format")
    
    def _check_magic_link_rate_limit(self, email: str, ip_address: str):
        """Enhanced rate limiting with better error handling"""
        try:
            # Email-based rate limiting (5 requests per hour)
            email_key = f"magic_link_rate_email:{email}"
            email_count = cache.get(email_key, 0)
            
            if email_count >= 5:
                raise RateLimitExceededException(
                    "Too many magic link requests for this email. Try again later.",
                    retry_after=3600
                )
            
            # IP-based rate limiting (20 requests per hour)
            if ip_address:
                ip_key = f"magic_link_rate_ip:{ip_address}"
                ip_count = cache.get(ip_key, 0)
                
                if ip_count >= 20:
                    # Log suspicious activity
                    logger.warning(f"Suspicious activity detected from IP: {ip_address}")
                    raise SuspiciousActivityException(
                        "Too many requests from this IP address. Try again later.",
                        context={'ip_address': ip_address, 'retry_after': 3600}
                    )
                
                # Increment counters
                try:
                    cache.set(ip_key, ip_count + 1, timeout=3600)
                except Exception as e:
                    logger.warning(f"Cache increment failed for IP rate limit: {str(e)}")
            
            try:
                cache.set(email_key, email_count + 1, timeout=3600)
            except Exception as e:
                logger.warning(f"Cache increment failed for email rate limit: {str(e)}")
                
        except (RateLimitExceededException, SuspiciousActivityException):
            raise
        except Exception as e:
            logger.error(f"Rate limit check failed: {str(e)}")
            raise CacheOperationException("Rate limit validation failed")
    
    def _log_login_attempt(self, email: str, ip_address: str, success: bool, failure_reason: str = None):
        """Log login attempt with error handling"""
        try:
            LoginAttempt = model_service.login_attempt_model
            
            LoginAttempt.objects.create(
                email=email,
                ip_address=ip_address or '0.0.0.0',
                success=success,
                failure_reason=failure_reason or ''
            )
        except Exception as e:
            # Don't fail the main operation if logging fails
            logger.error(f"Failed to log login attempt: {str(e)}")
