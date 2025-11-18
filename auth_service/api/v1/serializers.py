from rest_framework import serializers
from django.core.validators import validate_email
from django.contrib.auth.password_validation import validate_password

from ...services.auth_model_service import model_service

class RequestMagicLinkSerializer(serializers.Serializer):
    """Serializer for magic link request"""
    email = serializers.EmailField()
    
    def validate_email(self, value):
        """Validate email format"""
        try:
            validate_email(value)
        except Exception as e:
            raise serializers.ValidationError("Invalid email format")
        
        return value.lower().strip()

class MagicLinkLoginSerializer(serializers.Serializer):
    """Serializer for magic link login"""
    token = serializers.CharField(max_length=255)
    
    def validate_token(self, value):
        """Validate token format"""
        if not value or len(value) < 10:
            raise serializers.ValidationError("Invalid token format")
        return value.strip()

class UserProfileSerializer(serializers.ModelSerializer):
    """
    User profile serializer
    Email is READ-ONLY - use dedicated endpoint to change email
    """
    full_name = serializers.SerializerMethodField()
    account_status = serializers.SerializerMethodField()
    
    class Meta:
        model = model_service.user_model
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name',
            'is_email_verified', 'monthly_upload_count',
            'account_status', 'created_at', 'updated_at'
        ]
        # Email is READ-ONLY - cannot be updated via profile
        read_only_fields = [
            'id', 'email', 'is_email_verified', 
            'monthly_upload_count', 'created_at', 'updated_at'
        ]
    
    def get_full_name(self, obj):
        """Get user's full name"""
        if obj.first_name and obj.last_name:
            return f"{obj.first_name} {obj.last_name}"
        return obj.first_name or obj.email.split('@')[0]
    
    def get_account_status(self, obj):
        """Get account status"""
        if not obj.is_active:
            return 'inactive'
        return 'active'
    
    def validate_first_name(self, value):
        """Validate first name"""
        if value:
            value = value.strip()
            if len(value) < 1:
                raise serializers.ValidationError("First name cannot be empty")
            if len(value) > 150:
                raise serializers.ValidationError("First name too long (max 150 chars)")
            # No special characters
            if not value.replace(' ', '').replace('-', '').replace("'", '').isalpha():
                raise serializers.ValidationError(
                    "First name contains invalid characters"
                )
        return value
    
    def validate_last_name(self, value):
        """Validate last name"""
        if value:
            value = value.strip()
            if len(value) < 1:
                raise serializers.ValidationError("Last name cannot be empty")
            if len(value) > 150:
                raise serializers.ValidationError("Last name too long (max 150 chars)")
            if not value.replace(' ', '').replace('-', '').replace("'", '').isalpha():
                raise serializers.ValidationError(
                    "Last name contains invalid characters"
                )
        return value


class UpdateEmailSerializer(serializers.Serializer):
    """
    Email update request serializer
    Validates new email address
    """
    new_email = serializers.EmailField(required=True)
    
    def validate_new_email(self, value):
        """
        Validate new email address
        Note: Backend will also check if email exists
        """
        if not value:
            raise serializers.ValidationError("Email address is required")
        
        # Normalize email
        value = value.lower().strip()
        
        # Basic format validation
        if len(value) < 5 or len(value) > 254:
            raise serializers.ValidationError("Invalid email length")
        
        # Check local and domain parts
        if '@' not in value:
            raise serializers.ValidationError("Invalid email format")
        
        local, domain = value.rsplit('@', 1)
        
        if len(local) < 1 or len(local) > 64:
            raise serializers.ValidationError("Invalid email local part")
        
        if len(domain) < 3 or '.' not in domain:
            raise serializers.ValidationError("Invalid email domain")
        
        # Check for consecutive dots
        if '..' in value:
            raise serializers.ValidationError("Invalid email format")
        
        return value
    
    def validate(self, data):
        """Cross-field validation"""
        # Additional validation if needed
        return data


class EmailVerificationSerializer(serializers.Serializer):
    """
    Email verification token serializer
    Validates verification token format
    """
    token = serializers.CharField(
        required=True,
        min_length=10,
        max_length=255,
        trim_whitespace=True
    )
    
    def validate_token(self, value):
        """Validate token format"""
        if not value:
            raise serializers.ValidationError("Verification token is required")
        
        # Remove whitespace
        value = value.strip()
        
        # Check length
        if len(value) < 10:
            raise serializers.ValidationError(
                "Invalid verification token format"
            )
        
        # Check for invalid characters (basic check)
        # Token should be URL-safe base64
        import string
        valid_chars = string.ascii_letters + string.digits + '-_'
        if not all(c in valid_chars for c in value):
            raise serializers.ValidationError(
                "Invalid characters in verification token"
            )
        
        return value

class RefreshTokenSerializer(serializers.Serializer):
    """Serializer for token refresh"""
    refresh = serializers.CharField()
    
    def validate_refresh(self, value):
        """Validate refresh token format"""
        if not value:
            raise serializers.ValidationError("Refresh token is required")
        return value.strip()