"""
Django admin configuration for receipt_service
Manage receipts, categories, ledger entries, and user preferences
"""
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models.receipt import Receipt
from .models.category import Category, UserCategoryPreference
from .models.ledger import LedgerEntry


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    """Admin for receipt management"""
    
    list_display = [
        'id_preview',
        'user_email',
        'original_filename',
        'status_badge',
        'file_size_mb',
        'created_at',
        'file_preview'
    ]
    list_filter = [
        'status',
        'created_at',
        'processing_started_at',
        'mime_type'
    ]
    search_fields = [
        'user__email',
        'original_filename',
        'file_hash'
    ]
    readonly_fields = [
        'id',
        'file_hash',
        'created_at',
        'updated_at',
        'processing_duration_display',
        'file_preview_large'
    ]
    ordering = ['-created_at']
    
    fieldsets = (
        ('Receipt Info', {
            'fields': (
                'id',
                'user',
                'original_filename',
                'file_path',
                'file_preview_large'
            )
        }),
        ('File Metadata', {
            'fields': (
                'file_size',
                'mime_type',
                'file_hash'
            )
        }),
        ('Processing Status', {
            'fields': (
                'status',
                'processing_started_at',
                'processing_completed_at',
                'processing_duration_display'
            )
        }),
        ('Security', {
            'fields': (
                'upload_ip_address',
                'user_agent'
            )
        }),
        ('Timestamps', {
            'fields': (
                'created_at',
                'updated_at'
            )
        }),
    )
    
    def id_preview(self, obj):
        """Show shortened ID"""
        return f"{str(obj.id)[:8]}..."
    id_preview.short_description = 'ID'
    
    def user_email(self, obj):
        """Show user email with link"""
        url = reverse('admin:auth_service_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.email)
    user_email.short_description = 'User'
    
    def status_badge(self, obj):
        """Show colored status badge"""
        colors = {
            'uploaded': 'gray',
            'queued': 'blue',
            'processing': 'orange',
            'processed': 'green',
            'confirmed': 'darkgreen',
            'failed': 'red',
            'cancelled': 'gray'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.status.upper()
        )
    status_badge.short_description = 'Status'
    
    def file_size_mb(self, obj):
        """Show file size in MB"""
        return f"{obj.file_size / (1024 * 1024):.2f} MB"
    file_size_mb.short_description = 'Size'
    
    def processing_duration_display(self, obj):
        """Show processing duration"""
        if obj.processing_duration_seconds:
            return f"{obj.processing_duration_seconds} seconds"
        return "N/A"
    processing_duration_display.short_description = 'Processing Time'
    
    def file_preview(self, obj):
        """Show small file preview"""
        if obj.file_path and obj.mime_type.startswith('image'):
            try:
                url = obj.file_path.url
                return format_html('<img src="{}" style="max-height: 50px; max-width: 100px;"/>', url)
            except:
                return "No preview"
        return "PDF" if obj.mime_type == 'application/pdf' else "File"
    file_preview.short_description = 'Preview'
    
    def file_preview_large(self, obj):
        """Show larger file preview in detail view"""
        if obj.file_path and obj.mime_type.startswith('image'):
            try:
                url = obj.file_path.url
                return format_html('<img src="{}" style="max-width: 500px;"/>', url)
            except:
                return "No preview available"
        return "PDF file (no preview)"
    file_preview_large.short_description = 'File Preview'
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related('user')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin for expense categories"""
    
    list_display = [
        'display_with_icon',
        'slug',
        'color_preview',
        'is_active',
        'display_order',
        'usage_count'
    ]
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'slug']
    readonly_fields = ['slug', 'created_at', 'updated_at']
    ordering = ['display_order', 'name']
    
    fieldsets = (
        ('Category Info', {
            'fields': ('name', 'slug', 'icon', 'color')
        }),
        ('Display Settings', {
            'fields': ('is_active', 'display_order')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def display_with_icon(self, obj):
        """Show category with icon"""
        return f"{obj.icon} {obj.name}"
    display_with_icon.short_description = 'Category'
    
    def color_preview(self, obj):
        """Show color box"""
        return format_html(
            '<div style="width: 50px; height: 20px; background-color: {}; border: 1px solid #ccc;"></div>',
            obj.color
        )
    color_preview.short_description = 'Color'
    
    def usage_count(self, obj):
        """Show how many times category is used"""
        count = obj.ledger_entries.count()
        return f"{count} entries"
    usage_count.short_description = 'Usage'


@admin.register(UserCategoryPreference)
class UserCategoryPreferenceAdmin(admin.ModelAdmin):
    """Admin for user category preferences"""
    
    list_display = [
        'user_email',
        'category_display',
        'usage_count',
        'last_used'
    ]
    list_filter = ['last_used', 'created_at']
    search_fields = ['user__email', 'category__name']
    readonly_fields = ['created_at', 'last_used']
    ordering = ['-usage_count']
    
    fieldsets = (
        ('Preference Info', {
            'fields': ('user', 'category', 'usage_count')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'last_used')
        }),
    )
    
    def user_email(self, obj):
        """Show user email"""
        return obj.user.email
    user_email.short_description = 'User'
    
    def category_display(self, obj):
        """Show category with icon"""
        return f"{obj.category.icon} {obj.category.name}"
    category_display.short_description = 'Category'
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related('user', 'category')


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    """Admin for confirmed ledger entries"""
    
    list_display = [
        'id_preview',
        'user_email',
        'vendor',
        'amount_display',
        'category_display',
        'date',
        'accuracy_display',
        'created_at'
    ]
    list_filter = [
        'date',
        'category',
        'is_business_expense',
        'is_recurring',
        'user_corrected_amount',
        'user_corrected_category',
        'created_at'
    ]
    search_fields = [
        'user__email',
        'vendor',
        'description',
        'tags'
    ]
    readonly_fields = [
        'id',
        'receipt',
        'created_at',
        'updated_at',
        'accuracy_display_detail'
    ]
    ordering = ['-date', '-created_at']
    
    fieldsets = (
        ('Entry Info', {
            'fields': (
                'id',
                'user',
                'receipt',
                'category'
            )
        }),
        ('Transaction Details', {
            'fields': (
                'date',
                'vendor',
                'amount',
                'currency',
                'description',
                'tags'
            )
        }),
        ('AI Accuracy Tracking', {
            'fields': (
                'user_corrected_amount',
                'user_corrected_category',
                'user_corrected_vendor',
                'user_corrected_date',
                'accuracy_display_detail'
            )
        }),
        ('Business Metadata', {
            'fields': (
                'is_recurring',
                'is_business_expense',
                'is_reimbursable'
            )
        }),
        ('Audit Info', {
            'fields': (
                'created_at',
                'updated_at',
                'created_from_ip'
            )
        }),
    )
    
    def id_preview(self, obj):
        """Show shortened ID"""
        return f"{str(obj.id)[:8]}..."
    id_preview.short_description = 'ID'
    
    def user_email(self, obj):
        """Show user email"""
        return obj.user.email
    user_email.short_description = 'User'
    
    def amount_display(self, obj):
        """Show formatted amount"""
        return f"{obj.currency} {obj.amount}"
    amount_display.short_description = 'Amount'
    
    def category_display(self, obj):
        """Show category with icon"""
        return f"{obj.category.icon} {obj.category.name}"
    category_display.short_description = 'Category'
    
    def accuracy_display(self, obj):
        """Show AI accuracy badge"""
        score = obj.accuracy_score
        color = 'green' if score == 1.0 else 'orange' if score >= 0.5 else 'red'
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{:.0%}</span>',
            color,
            score
        )
    accuracy_display.short_description = 'AI Accuracy'
    
    def accuracy_display_detail(self, obj):
        """Show detailed accuracy breakdown"""
        corrections = []
        if obj.user_corrected_amount:
            corrections.append('Amount')
        if obj.user_corrected_category:
            corrections.append('Category')
        if obj.user_corrected_vendor:
            corrections.append('Vendor')
        if obj.user_corrected_date:
            corrections.append('Date')
        
        if not corrections:
            return format_html('<span style="color: green;">✓ All AI predictions were accurate</span>')
        
        return format_html(
            '<span style="color: orange;">⚠ User corrected: {}</span>',
            ', '.join(corrections)
        )
    accuracy_display_detail.short_description = 'Correction Details'
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related('user', 'category', 'receipt')
