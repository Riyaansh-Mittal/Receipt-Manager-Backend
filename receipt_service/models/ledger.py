import uuid
from django.db import models
from django.db.models import Sum
from decimal import Decimal


class LedgerEntryQuerySet(models.QuerySet):
    """Custom queryset for ledger entries with common filters"""
    
    def for_user(self, user):
        """Filter entries for specific user"""
        return self.filter(user=user)
    
    def for_date_range(self, start_date, end_date):
        """Filter entries for date range"""
        return self.filter(date__range=[start_date, end_date])
    
    def for_category(self, category):
        """Filter entries for specific category"""
        return self.filter(category=category)
    
    def for_month(self, year, month):
        """Filter entries for specific month"""
        return self.filter(date__year=year, date__month=month)
    
    def total_amount(self):
        """Calculate total amount for queryset"""
        result = self.aggregate(total=Sum('amount'))
        return result['total'] or Decimal('0.00')


class LedgerEntry(models.Model):
    """Final confirmed expense entries in user's ledger"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'auth_service.User', 
        on_delete=models.CASCADE, 
        related_name='ledger_entries'
    )
    receipt = models.OneToOneField(
        'Receipt', 
        on_delete=models.CASCADE, 
        related_name='ledger_entry'
    )
    category = models.ForeignKey(
        'Category', 
        on_delete=models.PROTECT, 
        related_name='ledger_entries'
    )
    
    # User-confirmed final data
    date = models.DateField(help_text="Transaction/receipt date")
    vendor = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        help_text="Final confirmed amount"
    )
    currency = models.CharField(max_length=3, default='USD')
    description = models.TextField(blank=True, max_length=1000)
    tags = models.JSONField(default=list, blank=True, help_text="User-defined tags")
    
    # Correction tracking - SET DURING CREATION, NOT IN save()!
    user_corrected_amount = models.BooleanField(
        default=False, 
        help_text="User modified extracted amount"
    )
    user_corrected_category = models.BooleanField(
        default=False, 
        help_text="User changed AI suggested category"
    )
    user_corrected_vendor = models.BooleanField(
        default=False, 
        help_text="User modified extracted vendor"
    )
    user_corrected_date = models.BooleanField(
        default=False, 
        help_text="User modified extracted date"
    )
    
    # Business metadata
    is_recurring = models.BooleanField(default=False)
    is_business_expense = models.BooleanField(default=False)
    is_reimbursable = models.BooleanField(default=False)
    
    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_from_ip = models.GenericIPAddressField(null=True, blank=True)
    
    objects = LedgerEntryQuerySet.as_manager()
    
    class Meta:
        db_table = 'receipt_ledger_entries'
        indexes = [
            models.Index(fields=['user', '-date']),
            models.Index(fields=['category', '-date']),
            models.Index(fields=['date', '-created_at']),
            models.Index(fields=['user', 'category', '-date']),
            models.Index(fields=['user', '-amount']),
            models.Index(fields=['is_business_expense', '-date']),
        ]
        ordering = ['-date', '-created_at']
        verbose_name = 'Ledger Entry'
        verbose_name_plural = 'Ledger Entries'
    
    def __str__(self):
        return f"{self.vendor or 'Unknown'} - ${self.amount} ({self.category.name})"
    
    @property
    def was_ai_accurate(self) -> bool:
        """Check if AI predictions were accurate"""
        return not any([
            self.user_corrected_amount,
            self.user_corrected_category,
            self.user_corrected_vendor,
            self.user_corrected_date
        ])
    
    @property
    def accuracy_score(self) -> float:
        """Calculate accuracy score based on corrections"""
        corrections = sum([
            self.user_corrected_amount,
            self.user_corrected_category, 
            self.user_corrected_vendor,
            self.user_corrected_date
        ])
        
        # Score: 1.0 if no corrections, reduce by 0.25 for each correction
        return max(0.0, 1.0 - (corrections * 0.25))
    
    # REMOVE THE save() METHOD ENTIRELY!
    # Corrections are set during creation by confirm_receipt()
    
    def get_monthly_total_for_user(self) -> Decimal:
        """Get total expenses for user in same month"""
        return LedgerEntry.objects.for_user(self.user).for_month(
            self.date.year, self.date.month
        ).total_amount()
    
    def get_category_total_for_user(self) -> Decimal:
        """Get total expenses for user in same category"""
        return LedgerEntry.objects.for_user(self.user).for_category(
            self.category
        ).total_amount()