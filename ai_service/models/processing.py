import uuid
from django.db import models
from django.utils import timezone


class ProcessingJob(models.Model):
    """
    Tracks AI processing jobs for receipts
    Links to receipt_service.Receipt via receipt_id
    """
    
    class ProcessingStatus(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'
    
    class ProcessingStage(models.TextChoices):
        OCR = 'ocr', 'OCR Processing'
        CATEGORIZATION = 'categorization', 'AI Categorization'
        DATA_EXTRACTION = 'data_extraction', 'Data Extraction'
        COMPLETED = 'completed', 'Completed'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receipt_id = models.UUIDField(db_index=True, help_text="Foreign key to receipt_service.Receipt")
    user_id = models.UUIDField(db_index=True, help_text="Foreign key to auth_service.User")
    
    # Processing state
    status = models.CharField(max_length=20, choices=ProcessingStatus.choices, default=ProcessingStatus.QUEUED)
    current_stage = models.CharField(max_length=30, choices=ProcessingStage.choices, default=ProcessingStage.OCR)
    progress_percentage = models.IntegerField(default=0, help_text="Processing progress 0-100")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Processing metadata
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)
    
    # Error tracking
    error_message = models.TextField(blank=True)
    error_stage = models.CharField(max_length=30, blank=True)
    error_details = models.JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'ai_processing_jobs'
        indexes = [
            models.Index(fields=['receipt_id']),
            models.Index(fields=['user_id']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['current_stage']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"ProcessingJob {self.id} - {self.status}"


class OCRResult(models.Model):
    """
    Stores OCR processing results
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    processing_job = models.OneToOneField(ProcessingJob, on_delete=models.CASCADE, related_name='ocr_result')
    
    # OCR results
    extracted_text = models.TextField(help_text="Full OCR extracted text")
    confidence_score = models.FloatField(help_text="Overall OCR confidence 0.0-1.0")
    language_detected = models.CharField(max_length=10, default='en', help_text="Detected language code")
    
    # Processing metadata
    ocr_engine = models.CharField(max_length=50, default='google_vision', help_text="OCR engine used")
    processing_time_seconds = models.FloatField(help_text="Time taken for OCR processing")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ai_ocr_results'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"OCRResult for job {self.processing_job.id} - {self.confidence_score:.2f}"
    
    @property
    def is_high_confidence(self) -> bool:
        """Check if OCR confidence is high enough"""
        return self.confidence_score >= 0.7
    
    @property
    def text_preview(self) -> str:
        """Get preview of extracted text"""
        return self.extracted_text[:100] + "..." if len(self.extracted_text) > 100 else self.extracted_text


class CategoryPrediction(models.Model):
    """
    Stores AI category predictions for receipts
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    processing_job = models.OneToOneField(ProcessingJob, on_delete=models.CASCADE, related_name='category_prediction')
    
    # Prediction results
    predicted_category_id = models.UUIDField(help_text="Predicted category ID from receipt_service")
    confidence_score = models.FloatField(help_text="Prediction confidence 0.0-1.0")
    reasoning = models.TextField(help_text="AI reasoning for the prediction")
    
    # Alternative predictions
    alternative_predictions = models.JSONField(
        default=list, 
        help_text="List of alternative category predictions with confidence scores"
    )
    
    # Processing metadata
    model_version = models.CharField(max_length=50, default='gemini-2.5-flash', help_text="AI model used")
    processing_time_seconds = models.FloatField(help_text="Time taken for categorization")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ai_category_predictions'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"CategoryPrediction {self.predicted_category_id} - {self.confidence_score:.2f}"
    
    @property
    def is_high_confidence(self) -> bool:
        """Check if prediction confidence is high enough"""
        return self.confidence_score >= 0.6
    
    def get_top_alternatives(self, limit: int = 3) -> list:
        """Get top alternative predictions"""
        return sorted(
            self.alternative_predictions, 
            key=lambda x: x.get('confidence', 0), 
            reverse=True
        )[:limit]


class ExtractedData(models.Model):
    """
    Stores structured data extracted from receipt text
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    processing_job = models.OneToOneField(ProcessingJob, on_delete=models.CASCADE, related_name='extracted_data')
    
    # Extracted structured data
    vendor_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,  # ← Make nullable
        default='Unknown',  # ← Add default
        help_text="Extracted vendor/merchant name"
    )
    receipt_date = models.DateField(null=True, blank=True, help_text="Extracted receipt date")
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Extracted total amount"
    )
    
    currency = models.CharField(
        max_length=3,
        default='USD',
        null=True,
        blank=True,
        help_text="Currency code (ISO 4217)"
    )
    
    # Additional extracted information
    tax_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Extracted tax amount"
    )
    
    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Extracted subtotal"
    )
    
    # Line items
    line_items = models.JSONField(
        default=list,
        blank=True,
        help_text="Extracted line items"
    )
    
    # Confidence scores for each field
    confidence_scores = models.JSONField(
        default=dict, 
        help_text="Confidence scores for each extracted field"
    )
    
    # Processing metadata
    extraction_method = models.CharField(max_length=50, default='gemini_parsing', help_text="Extraction method used")
    processing_time_seconds = models.FloatField(help_text="Time taken for data extraction")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ai_extracted_data'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"ExtractedData for job {self.processing_job.id} - {self.vendor_name}"
    
    @property
    def formatted_amount(self) -> str:
        """Get formatted amount with currency"""
        if self.total_amount and self.currency:
            from receipt_service.utils.currency_utils import currency_manager
            return currency_manager.format_amount(self.total_amount, self.currency)
        return ""
    
    @property
    def has_high_confidence_amount(self) -> bool:
        """Check if amount extraction has high confidence"""
        return self.confidence_scores.get('total_amount', 0) >= 0.8
    
    @property
    def has_high_confidence_vendor(self) -> bool:
        """Check if vendor extraction has high confidence"""
        return self.confidence_scores.get('vendor_name', 0) >= 0.7
    
    def get_summary(self) -> dict:
        """Get summary of extracted data"""
        return {
            'vendor': self.vendor_name,
            'date': self.receipt_date.isoformat() if self.receipt_date else None,
            'amount': float(self.total_amount) if self.total_amount else None,
            'formatted_amount': self.formatted_amount,
            'currency': self.currency,
            'items_count': len(self.line_items),
            'confidence_scores': self.confidence_scores
        }
