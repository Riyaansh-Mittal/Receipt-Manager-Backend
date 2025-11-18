from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, MagicLink, EmailVerification, TokenBlacklist, LoginAttempt

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = [
        'email',
        'first_name',
        'last_name',
        'is_email_verified',
        'monthly_upload_count',
        'created_at'
    ]
    list_filter = ['is_email_verified', 'is_active', 'is_staff', 'created_at']
    search_fields = ['email', 'first_name', 'last_name']
    ordering = ['-created_at']

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal Info'), {'fields': ('first_name', 'last_name')}),
        (_('Permissions'), {
            'fields': (
                'is_active',
                'is_staff',
                'is_superuser',
                'is_email_verified',
                'groups',
                'user_permissions'
            ),
        }),
        (_('Usage & Security'), {
            'fields': (
                'monthly_upload_count',
                'upload_reset_date'
            )
        }),
        (_('Important Dates'), {'fields': ('created_at', 'updated_at')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'first_name', 'last_name', 'is_staff', 'is_superuser'),
        }),
    )

    readonly_fields = ['created_at', 'updated_at']
    filter_horizontal = ('groups', 'user_permissions',)

@admin.register(MagicLink)
class MagicLinkAdmin(admin.ModelAdmin):
    list_display = ['email', 'is_used', 'created_at', 'expires_at', 'used_at']
    list_filter = ['is_used', 'created_at', 'expires_at']
    search_fields = ['email']
    readonly_fields = ['token', 'created_at', 'used_at', 'created_from_ip', 'used_from_ip']
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False

@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'email', 'is_verified', 'created_at', 'verified_at']
    list_filter = ['is_verified', 'created_at']
    search_fields = ['user__email', 'email']
    readonly_fields = ['token', 'created_at', 'verified_at']
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False

@admin.register(TokenBlacklist)
class TokenBlacklistAdmin(admin.ModelAdmin):
    list_display = ['user', 'token_type', 'reason', 'blacklisted_at', 'expires_at', 'jti_preview']
    list_filter = ['token_type', 'reason', 'blacklisted_at']
    search_fields = ['user__email', 'jti']
    readonly_fields = ['jti', 'blacklisted_at', 'created_from_ip']
    ordering = ['-blacklisted_at']

    def jti_preview(self, obj):
        return f"{obj.jti[:15]}..."
    jti_preview.short_description = 'JTI'

    def has_add_permission(self, request):
        return False

@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ['email', 'success', 'ip_address', 'created_at', 'failure_reason']
    list_filter = ['success', 'created_at']
    search_fields = ['email', 'ip_address']
    readonly_fields = ['created_at', 'user_agent']
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
