"""
Unit tests for auth_service/api/v1/serializers.py
Tests serializer validation, field constraints, and data transformation
Uses Django's database for model validation
"""
import pytest
import uuid
from decimal import Decimal
from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model


# DON'T import serializers at module level - import inside tests
# from auth_service.api.v1.serializers import ...


@pytest.fixture
def user_data():
    """Sample user data"""
    return {
        'email': 'test@example.com',
        'first_name': 'John',
        'last_name': 'Doe'
    }


@pytest.fixture
def sample_user(db):
    """Create sample user in database"""
    User = get_user_model()
    user = User.objects.create_user(
        username='existing',
        email='existing@example.com',
        first_name='Existing',
        last_name='User'
    )
    user.is_email_verified = True
    user.save()
    return user


@pytest.mark.django_db
class TestRequestMagicLinkSerializer:
    """Test magic link request serializer"""
    
    def test_valid_email(self):
        """Test valid email passes validation"""
        from auth_service.api.v1.serializers import RequestMagicLinkSerializer
        
        data = {'email': 'user@example.com'}
        serializer = RequestMagicLinkSerializer(data=data)
        
        assert serializer.is_valid()
        assert serializer.validated_data['email'] == 'user@example.com'
    
    def test_email_normalization(self):
        """Test email is normalized to lowercase"""
        from auth_service.api.v1.serializers import RequestMagicLinkSerializer
        
        data = {'email': 'USER@EXAMPLE.COM'}
        serializer = RequestMagicLinkSerializer(data=data)
        
        assert serializer.is_valid()
        assert serializer.validated_data['email'] == 'user@example.com'
    
    def test_email_whitespace_stripped(self):
        """Test email whitespace is stripped"""
        from auth_service.api.v1.serializers import RequestMagicLinkSerializer
        
        data = {'email': '  user@example.com  '}
        serializer = RequestMagicLinkSerializer(data=data)
        
        assert serializer.is_valid()
        assert serializer.validated_data['email'] == 'user@example.com'
    
    def test_invalid_email_format(self):
        """Test invalid email format fails"""
        from auth_service.api.v1.serializers import RequestMagicLinkSerializer
        
        invalid_emails = [
            'notanemail',
            'missing@domain',
            '@example.com',
            'user@',
            'user @example.com',
        ]
        
        for email in invalid_emails:
            data = {'email': email}
            serializer = RequestMagicLinkSerializer(data=data)
            
            assert not serializer.is_valid()
            assert 'email' in serializer.errors
    
    def test_missing_email(self):
        """Test missing email field"""
        from auth_service.api.v1.serializers import RequestMagicLinkSerializer
        
        data = {}
        serializer = RequestMagicLinkSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'email' in serializer.errors


@pytest.mark.django_db
class TestMagicLinkLoginSerializer:
    """Test magic link login serializer"""
    
    def test_valid_token(self):
        """Test valid token passes validation"""
        from auth_service.api.v1.serializers import MagicLinkLoginSerializer
        
        data = {'token': 'valid_token_123456789'}
        serializer = MagicLinkLoginSerializer(data=data)
        
        assert serializer.is_valid()
        assert serializer.validated_data['token'] == 'valid_token_123456789'
    
    def test_token_whitespace_stripped(self):
        """Test token whitespace is stripped"""
        from auth_service.api.v1.serializers import MagicLinkLoginSerializer
        
        data = {'token': '  token_with_spaces  '}
        serializer = MagicLinkLoginSerializer(data=data)
        
        assert serializer.is_valid()
        assert serializer.validated_data['token'] == 'token_with_spaces'
    
    def test_short_token_fails(self):
        """Test too short token fails"""
        from auth_service.api.v1.serializers import MagicLinkLoginSerializer
        
        data = {'token': 'short'}
        serializer = MagicLinkLoginSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'token' in serializer.errors
    
    def test_empty_token_fails(self):
        """Test empty token fails"""
        from auth_service.api.v1.serializers import MagicLinkLoginSerializer
        
        data = {'token': ''}
        serializer = MagicLinkLoginSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'token' in serializer.errors
    
    def test_missing_token(self):
        """Test missing token field"""
        from auth_service.api.v1.serializers import MagicLinkLoginSerializer
        
        data = {}
        serializer = MagicLinkLoginSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'token' in serializer.errors


@pytest.mark.django_db
class TestUserProfileSerializer:
    """Test user profile serializer"""
    
    def test_serialize_user(self, sample_user):
        """Test serializing user object"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        serializer = UserProfileSerializer(sample_user)
        
        data = serializer.data
        assert str(data['id']) == str(sample_user.id)
        assert data['email'] == 'existing@example.com'
        assert data['first_name'] == 'Existing'
        assert data['last_name'] == 'User'
        assert data['is_email_verified'] is True
    
    def test_full_name_computation(self, sample_user):
        """Test full name is computed correctly"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        serializer = UserProfileSerializer(sample_user)
        
        assert serializer.data['full_name'] == 'Existing User'
    
    def test_full_name_with_only_first_name(self, sample_user):
        """Test full name when only first name exists"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        sample_user.last_name = ''
        sample_user.save()
        
        serializer = UserProfileSerializer(sample_user)
        
        assert serializer.data['full_name'] == 'Existing'
    
    def test_full_name_fallback_to_email(self, sample_user):
        """Test full name falls back to email prefix"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        sample_user.first_name = ''
        sample_user.last_name = ''
        sample_user.save()
        
        serializer = UserProfileSerializer(sample_user)
        
        assert serializer.data['full_name'] == 'existing'
    
    def test_account_status_active(self, sample_user):
        """Test account status is active"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        serializer = UserProfileSerializer(sample_user)
        
        assert serializer.data['account_status'] == 'active'
    
    def test_account_status_inactive(self, sample_user):
        """Test account status is inactive"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        sample_user.is_active = False
        sample_user.save()
        
        serializer = UserProfileSerializer(sample_user)
        
        assert serializer.data['account_status'] == 'inactive'
    
    def test_update_first_name(self, sample_user):
        """Test updating first name"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        data = {'first_name': 'Updated'}
        serializer = UserProfileSerializer(sample_user, data=data, partial=True)
        
        assert serializer.is_valid()
        serializer.save()
        
        sample_user.refresh_from_db()
        assert sample_user.first_name == 'Updated'
    
    def test_email_is_read_only(self, sample_user):
        """Test email cannot be updated"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        data = {'email': 'newemail@example.com'}
        serializer = UserProfileSerializer(sample_user, data=data, partial=True)
        
        assert serializer.is_valid()
        serializer.save()
        
        sample_user.refresh_from_db()
        assert sample_user.email == 'existing@example.com'  # Unchanged
    
    def test_validate_first_name_too_long(self, sample_user):
        """Test first name too long fails"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        data = {'first_name': 'A' * 200}
        serializer = UserProfileSerializer(sample_user, data=data, partial=True)
        
        assert not serializer.is_valid()
        assert 'first_name' in serializer.errors
    
    def test_validate_first_name_invalid_chars(self, sample_user):
        """Test first name with invalid characters fails"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        invalid_names = ['John123', 'John@Smith', 'John<Script>']
        
        for name in invalid_names:
            data = {'first_name': name}
            serializer = UserProfileSerializer(sample_user, data=data, partial=True)
            
            assert not serializer.is_valid()
            assert 'first_name' in serializer.errors
    
    def test_validate_first_name_with_hyphen(self, sample_user):
        """Test first name with hyphen is valid"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        data = {'first_name': 'Mary-Jane'}
        serializer = UserProfileSerializer(sample_user, data=data, partial=True)
        
        assert serializer.is_valid()
    
    def test_validate_first_name_with_apostrophe(self, sample_user):
        """Test first name with apostrophe is valid"""
        from auth_service.api.v1.serializers import UserProfileSerializer
        
        data = {'first_name': "O'Connor"}
        serializer = UserProfileSerializer(sample_user, data=data, partial=True)
        
        assert serializer.is_valid()


@pytest.mark.django_db
class TestUpdateEmailSerializer:
    """Test email update serializer"""
    
    def test_valid_new_email(self):
        """Test valid new email"""
        from auth_service.api.v1.serializers import UpdateEmailSerializer
        
        data = {'new_email': 'newemail@example.com'}
        serializer = UpdateEmailSerializer(data=data)
        
        assert serializer.is_valid()
        assert serializer.validated_data['new_email'] == 'newemail@example.com'
    
    def test_email_normalization(self):
        """Test email is normalized"""
        from auth_service.api.v1.serializers import UpdateEmailSerializer
        
        data = {'new_email': 'NEW@EXAMPLE.COM'}
        serializer = UpdateEmailSerializer(data=data)
        
        assert serializer.is_valid()
        assert serializer.validated_data['new_email'] == 'new@example.com'
    
    def test_email_too_short(self):
        """Test email too short fails"""
        from auth_service.api.v1.serializers import UpdateEmailSerializer
        
        data = {'new_email': 'a@b'}
        serializer = UpdateEmailSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'new_email' in serializer.errors
    
    def test_email_too_long(self):
        """Test email too long fails"""
        from auth_service.api.v1.serializers import UpdateEmailSerializer
        
        data = {'new_email': 'a' * 300 + '@example.com'}
        serializer = UpdateEmailSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'new_email' in serializer.errors
