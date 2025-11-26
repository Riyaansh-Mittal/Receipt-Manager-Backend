import uuid
from django.db import models
from django.core.validators import FileExtensionValidator
from django.utils import timezone
from django.conf import settings
from .ledger import LedgerEntry


def receipt_file_path(instance, filename):
    """Generate organized file path for receipt uploads"""
    ext = filename.split('.')[-1].lower()
    unique_filename = f"{uuid.uuid4()}.{ext}"
    date_path = timezone.now().strftime('%Y/%m/%d')
    # Don't add "receipts/" here - FileField adds it from upload_to
    return f"{instance.user.id}/{date_path}/{unique_filename}"

class Receipt(models.Model):
    """Receipt storage with processing metadata and extracted data"""
    
    STATUS_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('queued', 'Queued for Processing'),
        ('processing', 'Processing'),
        ('processed', 'Processed'),
        ('confirmed', 'Confirmed'),
        ('failed', 'Processing Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'auth_service.User', 
        on_delete=models.CASCADE, 
        related_name='receipts'
    )
    
    # File information
    original_filename = models.CharField(max_length=255)
    file_path = models.CharField(
        max_length=500,
        help_text="Relative path to file in storage backend"
    )
    file_size = models.PositiveIntegerField(help_text="File size in bytes")
    mime_type = models.CharField(max_length=50)
    file_hash = models.CharField(max_length=64, blank=True, help_text="SHA-256 hash for duplicate detection")
    
    # Processing status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded')
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processing_completed_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    upload_ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'receipts'
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['file_hash']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Receipt {self.original_filename} - {self.user.email} [{self.status}]"
    
    @property
    def can_be_confirmed(self) -> bool:
        """Check if receipt can be confirmed without extra query"""
        return self.status == 'processed' and not hasattr(self, '_ledger_entry_cache')
        
    def get_ledger_entry(self):
        """Get ledger entry with caching"""
        if not hasattr(self, '_ledger_entry_cache'):
            try:
                self._ledger_entry_cache = self.ledger_entry
            except LedgerEntry.DoesNotExist:
                self._ledger_entry_cache = None
        return self._ledger_entry_cache
    
    def get_file_url(self) -> str:
        """Get secure file URL"""
        if self.file_path:
            try:
                return self.file_path.url
            except ValueError:
                return None
        return None
