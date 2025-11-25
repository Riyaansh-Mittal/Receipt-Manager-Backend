from decimal import Decimal
from datetime import date, timedelta
from rest_framework import serializers
from ....services.receipt_model_service import model_service
from ....utils.currency_utils import currency_manager
from shared.utils.exceptions import ValidationException

import logging
logger = logging.getLogger(__name__)


class ReceiptUploadSerializer(serializers.Serializer):
    """Serializer for receipt file uploads"""
    file = serializers.FileField(
        help_text="Receipt file (PDF, JPG, JPEG, or PNG, max 10MB)"
    )
    
    def validate_file(self, value):
        """File validation"""
        if not value:
            raise serializers.ValidationError("File is required")
        
        # Check file object
        if not hasattr(value, 'size') or not hasattr(value, 'name'):
            raise serializers.ValidationError("Invalid file object")
        
        # Size validation (10MB)
        max_size = 10 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError(
                f"File too large. Max {max_size / (1024*1024):.0f}MB, "
                f"got {value.size / (1024*1024):.1f}MB"
            )
        
        # Name length
        if len(value.name) > 255:
            raise serializers.ValidationError("Filename too long (max 255 chars)")
        
        # Extension validation
        allowed_extensions = ['.pdf', '.jpg', '.jpeg', '.png']
        file_ext = value.name.lower().split('.')[-1] if '.' in value.name else ''
        if f'.{file_ext}' not in allowed_extensions:
            raise serializers.ValidationError(
                f"Invalid format. Allowed: {', '.join(allowed_extensions)}"
            )
        
        # Content type validation
        allowed_types = [
            'application/pdf',
            'image/jpeg', 
            'image/jpg',
            'image/png'
        ]
        
        if hasattr(value, 'content_type') and value.content_type:
            if value.content_type not in allowed_types:
                raise serializers.ValidationError(
                    f"Invalid content type: {value.content_type}"
                )
        
        return value

class ReceiptListSerializer(serializers.ModelSerializer):
    """
    Simplified receipt list serializer
    Uses select_related in view for performance
    """
    upload_date = serializers.DateTimeField(source='created_at', read_only=True)
    file_size_mb = serializers.SerializerMethodField()
    processing_progress = serializers.SerializerMethodField()
    
    # Extracted/confirmed data
    amount = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()
    vendor = serializers.SerializerMethodField()
    date = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    formatted_amount = serializers.SerializerMethodField()
    
    class Meta:
        model = model_service.receipt_model
        fields = [
            'id', 'original_filename', 'status', 'upload_date', 
            'file_size_mb', 'processing_progress',
            'amount', 'currency', 'vendor', 'date', 'category',
            'formatted_amount'
        ]
    
    def get_file_size_mb(self, obj):
        return round(obj.file_size / (1024 * 1024), 2) if obj.file_size else 0.0
    
    def get_processing_progress(self, obj):
        progress_map = {
            'uploaded': 10, 'queued': 20, 'processing': 50,
            'processed': 90, 'confirmed': 100, 'failed': 0, 'cancelled': 0
        }
        return progress_map.get(obj.status, 0)
    
    def get_ledger_data(self, obj):
        """Helper to get ledger entry data cached per request"""
        # Use request-level cache instead of serializer-level
        request = self.context.get('request')
        if not request:
            return None
            
        cache_key = f'ledger_data_{obj.id}'
        if not hasattr(request, '_receipt_cache'):
            request._receipt_cache = {}
            
        if cache_key not in request._receipt_cache:
            if obj.status == 'confirmed' and hasattr(obj, 'ledger_entry'):
                ledger = obj.ledger_entry
                request._receipt_cache[cache_key] = {
                    'amount': float(ledger.amount),
                    'currency': ledger.currency,
                    'vendor': ledger.vendor,
                    'date': ledger.date.isoformat(),
                    'category': {
                        'id': str(ledger.category.id),
                        'name': ledger.category.name,
                        'icon': ledger.category.icon,
                        'color': ledger.category.color,
                    },
                }
            else:
                request._receipt_cache[cache_key] = None
                
        return request._receipt_cache[cache_key]
    
    def get_amount(self, obj):
        data = self.get_ledger_data(obj)
        return data['amount'] if data else None
    
    def get_currency(self, obj):
        data = self.get_ledger_data(obj)
        return data['currency'] if data else None
    
    def get_vendor(self, obj):
        data = self.get_ledger_data(obj)
        return data['vendor'] if data else None
    
    def get_date(self, obj):
        data = self.get_ledger_data(obj)
        return data['date'] if data else None
    
    def get_category(self, obj):
        data = self.get_ledger_data(obj)
        return data['category'] if data else None
    
    def get_formatted_amount(self, obj):
        data = self.get_ledger_data(obj)
        if data and data['amount'] and data['currency']:
            try:
                return currency_manager.format_amount(
                    data['amount'], 
                    data['currency']
                )
            except Exception:
                return f"{data['currency']} {data['amount']}"
        return None

class ReceiptDetailSerializer(serializers.Serializer):
    """Detailed receipt information with AI processing results"""
    
    # Basic receipt info
    id = serializers.UUIDField(read_only=True)
    original_filename = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    file_size = serializers.IntegerField(read_only=True)
    file_size_mb = serializers.FloatField(read_only=True)
    mime_type = serializers.CharField(read_only=True)
    upload_date = serializers.DateTimeField(read_only=True)
    
    # Processing timestamps
    processing_started_at = serializers.DateTimeField(read_only=True, allow_null=True)
    processing_completed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    
    # File access
    file_url = serializers.CharField(read_only=True, allow_null=True)
    
    # Status flags
    can_be_confirmed = serializers.BooleanField(read_only=True)
    
    # AI Results (optional - only present if processed)
    ocr_data = serializers.DictField(read_only=True, required=False, allow_null=True)
    extracted_data = serializers.DictField(read_only=True, required=False, allow_null=True)
    ai_suggestion = serializers.DictField(read_only=True, required=False, allow_null=True)
    
    # Computed fields
    processing_duration_seconds = serializers.SerializerMethodField()
    processing_progress = serializers.SerializerMethodField()
    next_actions = serializers.SerializerMethodField()
    
    def get_processing_duration_seconds(self, obj):
        """Calculate processing duration"""
        started = obj.get('processing_started_at')
        completed = obj.get('processing_completed_at')
        
        if not started:
            return 0
        
        if completed:
            from dateutil import parser
            
            try:
                start_dt = parser.isoparse(started) if isinstance(started, str) else started
                end_dt = parser.isoparse(completed) if isinstance(completed, str) else completed
                return int((end_dt - start_dt).total_seconds())
            except:
                return 0
        
        return 0
    
    def get_processing_progress(self, obj):
        """Get processing progress percentage based on status"""
        status_progress = {
            'uploaded': 10,
            'queued': 20,
            'processing': 50,
            'processed': 90,
            'confirmed': 100,
            'failed': 0,
            'cancelled': 0
        }
        
        status = obj.get('status', 'uploaded')
        return status_progress.get(status, 0)
    
    def get_next_actions(self, obj):
        """Get available next actions based on status"""
        actions = []
        status = obj.get('status')
        receipt_id = obj.get('id')
        
        if not receipt_id:
            return actions
        
        if status == 'processed' and obj.get('can_be_confirmed'):
            actions.append({
                'action': 'confirm',
                'method': 'POST',
                'url': f'/receipts/v1/{receipt_id}/confirm/',
                'description': 'Confirm and create ledger entry'
            })
        
        if status in ['processing', 'queued']:
            actions.append({
                'action': 'check_status',
                'method': 'GET', 
                'url': f'/receipts/v1/upload-status/{receipt_id}/',
                'description': 'Check processing status'
            })
        
        actions.append({
            'action': 'view_extracted_data',
            'method': 'GET',
            'url': f'/receipts/v1/{receipt_id}/extracted-data/',
            'description': 'View extracted data details'
        })
        
        return actions

class ReceiptConfirmSerializer(serializers.Serializer):
    """Serializer for receipt confirmation data with status validation"""
    
    # Required fields - user MUST confirm these
    date = serializers.DateField(
        required=True,
        help_text="Receipt date (YYYY-MM-DD)"
    )
    amount = serializers.DecimalField(
        required=True,
        max_digits=12, 
        decimal_places=2, 
        min_value=Decimal('0.01'),
        help_text="Receipt amount"
    )
    currency = serializers.CharField(
        required=True,
        max_length=3,
        help_text="Currency code (e.g., USD, EUR)"
    )
    category_id = serializers.UUIDField(
        required=True,
        help_text="Category ID for this expense"
    )
    
    # Optional fields - will use AI defaults if not provided
    vendor = serializers.CharField(
        max_length=255, 
        allow_blank=True, 
        required=False,
        help_text="Vendor/merchant name (uses AI extraction if not provided)"
    )
    description = serializers.CharField(
        max_length=1000, 
        allow_blank=True, 
        required=False,
        help_text="Additional description or notes"
    )
    is_business_expense = serializers.BooleanField(
        default=False,
        required=False,
        help_text="Mark as business expense"
    )
    is_reimbursable = serializers.BooleanField(
        default=False,
        required=False,
        help_text="Mark as reimbursable expense"
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        allow_empty=True,
        default=list,
        help_text="Optional tags for categorization"
    )
    
    def validate(self, data):
        """✅ FIX: Validate receipt status and prevent double confirmation"""
        request = self.context.get('request')
        if not request:
            raise ValidationException("Request context required")
        
        # Get receipt_id from context (view kwargs)
        receipt_id = None
        if 'view' in self.context:
            receipt_id = self.context['view'].kwargs.get('receipt_id')
        elif 'receipt_id' in self.context:
            receipt_id = self.context['receipt_id']
            
        if not receipt_id:
            raise ValidationException("Receipt ID required")
        
        try:
            receipt = model_service.receipt_model.objects.get(id=receipt_id)
        except model_service.receipt_model.DoesNotExist:
            raise ValidationException("Receipt not found")
        
        # ✅ FIX: Check receipt status
        if receipt.status != 'processed':
            raise ValidationException(
                f"Cannot confirm receipt with status '{receipt.status}'. Must be 'processed'."
            )
        
        # ✅ FIX: Check if already confirmed (double confirmation prevention)
        if hasattr(receipt, 'ledger_entry'):
            raise ValidationException("Receipt already has a ledger entry")
        
        return data
    
    def validate_date(self, value):
        """Date validation"""
        if value > date.today():
            raise ValidationException("Receipt date cannot be in the future")
        
        if value.year < 2000:
            raise ValidationException("Receipt date too old (minimum year: 2000)")
        
        two_years_ago = date.today() - timedelta(days=730)
        if value < two_years_ago:
            raise ValidationException("Receipt date is more than 2 years old")
        
        return value
    
    def validate_amount(self, value):
        """Amount validation"""
        if value <= 0:
            raise ValidationException("Amount must be greater than zero")
        
        if value > Decimal('999999.99'):
            raise ValidationException("Amount exceeds maximum allowed value")
        
        return value
    
    def validate_currency(self, value):
        """Currency validation"""
        if not value:
            raise ValidationException("Currency is required")
        
        value = value.upper()
        if not currency_manager.is_valid_currency(value):
            raise ValidationException(
                f"Invalid currency code. Supported: {', '.join(currency_manager.get_currency_codes())}"
            )
        
        return value
    
    def validate_category_id(self, value):
        """Category validation"""
        try:
            category = model_service.category_model.objects.get(id=value, is_active=True)
            return value
        except model_service.category_model.DoesNotExist:
            raise ValidationException("Invalid or inactive category")
    
    def validate_vendor(self, value):
        """Vendor validation"""
        if value:
            value = value.strip()
            if len(value) > 255:
                raise ValidationException("Vendor name too long (max 255 characters)")
            
            # Sanitize HTML/special chars
            import re
            if re.search(r'[<>"\']', value):
                raise ValidationException("Vendor name contains invalid characters")
        
        return value or ''
    
    def validate_tags(self, value):
        """Tags validation"""
        if value:
            if len(value) > 10:
                raise ValidationException("Maximum 10 tags allowed")
            
            for tag in value:
                if not tag.strip():
                    raise ValidationException("Empty tags not allowed")
                if len(tag.strip()) > 50:
                    raise ValidationException("Each tag max 50 characters")
        
        return [tag.strip() for tag in value] if value else []

class ReceiptStatusSerializer(serializers.Serializer):
    """Serializer for receipt processing status"""
    receipt_id = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    current_stage = serializers.CharField(read_only=True, allow_null=True)
    progress_percentage = serializers.IntegerField(read_only=True, allow_null=True)
    started_at = serializers.CharField(read_only=True, allow_null=True)
    completed_at = serializers.CharField(read_only=True, allow_null=True)
    error_message = serializers.CharField(read_only=True, allow_null=True)
    message = serializers.CharField(read_only=True, allow_null=True)

class UploadHistorySerializer(serializers.Serializer):
    """Serializer for upload history"""
    month = serializers.CharField(read_only=True)
    month_name = serializers.CharField(read_only=True, required=False)
    upload_count = serializers.IntegerField(read_only=True)
    confirmed_count = serializers.IntegerField(read_only=True)
    failed_count = serializers.IntegerField(read_only=True)
    processing_count = serializers.IntegerField(read_only=True, required=False)
    total_amount = serializers.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        read_only=True
    )
    formatted_total = serializers.CharField(read_only=True)