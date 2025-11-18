"""
Django admin configuration for ai_service
Manage AI processing jobs, OCR results, category predictions, and extracted data
"""
from django.contrib import admin
from django.utils.html import format_html
from .models.processing import (
    ProcessingJob,
    OCRResult,
    CategoryPrediction,
    ExtractedData
)


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    """Admin for AI processing jobs"""
    
    list_display = [
        'id_preview',
        'status_badge',
        'current_stage',
        'progress_bar',
        'retry_count',
        'created_at',
        'processing_time'
    ]
    list_filter = [
        'status',
        'current_stage',
        'created_at',
        'started_at'
    ]
    search_fields = [
        'id',
        'receipt_id',
        'user_id'
    ]
    readonly_fields = [
        'id',
        'receipt_id',
        'user_id',
        'created_at',
        'started_at',
        'completed_at',
        'processing_time_display'
    ]
    ordering = ['-created_at']
    
    fieldsets = (
        ('Job Info', {
            'fields': (
                'id',
                'receipt_id',
                'user_id'
            )
        }),
        ('Processing State', {
            'fields': (
                'status',
                'current_stage',
                'progress_percentage'
            )
        }),
        ('Retry Logic', {
            'fields': (
                'retry_count',
                'max_retries'
            )
        }),
        ('Error Tracking', {
            'fields': (
                'error_message',
                'error_stage',
                'error_details'
            )
        }),
        ('Timestamps', {
            'fields': (
                'created_at',
                'started_at',
                'completed_at',
                'processing_time_display'
            )
        }),
    )
    
    def id_preview(self, obj):
        """Show shortened ID"""
        return f"{str(obj.id)[:8]}..."
    id_preview.short_description = 'Job ID'
    
    def status_badge(self, obj):
        """Show colored status badge"""
        colors = {
            'queued': 'gray',
            'processing': 'blue',
            'completed': 'green',
            'failed': 'red',
            'cancelled': 'orange'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.status.upper()
        )
    status_badge.short_description = 'Status'
    
    def progress_bar(self, obj):
        """Show progress bar"""
        return format_html(
            '<div style="width: 100px; background-color: #f0f0f0; border-radius: 3px;">'
            '<div style="width: {}%; height: 20px; background-color: #4CAF50; border-radius: 3px; text-align: center; color: white; font-size: 11px; line-height: 20px;">{}</div>'
            '</div>',
            obj.progress_percentage,
            f"{obj.progress_percentage}%"
        )
    progress_bar.short_description = 'Progress'
    
    def processing_time(self, obj):
        """Calculate processing time"""
        if obj.started_at and obj.completed_at:
            duration = (obj.completed_at - obj.started_at).total_seconds()
            return f"{duration:.2f}s"
        elif obj.started_at:
            return "In progress..."
        return "Not started"
    processing_time.short_description = 'Duration'
    
    def processing_time_display(self, obj):
        """Detailed processing time"""
        return self.processing_time(obj)
    processing_time_display.short_description = 'Processing Duration'
    
    def has_add_permission(self, request):
        """Disable manual job creation"""
        return False


@admin.register(OCRResult)
class OCRResultAdmin(admin.ModelAdmin):
    """Admin for OCR results"""
    
    list_display = [
        'job_id_preview',
        'confidence_badge',
        'language_detected',
        'ocr_engine',
        'processing_time_display',
        'text_length',
        'created_at'
    ]
    list_filter = [
        'ocr_engine',
        'language_detected',
        'created_at'
    ]
    search_fields = [
        'processing_job__id',
        'extracted_text'
    ]
    readonly_fields = [
        'id',
        'processing_job',
        'extracted_text_display',
        'created_at',
        'updated_at'
    ]
    ordering = ['-created_at']
    
    fieldsets = (
        ('OCR Result Info', {
            'fields': (
                'id',
                'processing_job',
                'extracted_text_display'
            )
        }),
        ('Confidence & Quality', {
            'fields': (
                'confidence_score',
                'language_detected'
            )
        }),
        ('Processing Metadata', {
            'fields': (
                'ocr_engine',
                'processing_time_seconds'
            )
        }),
        ('Timestamps', {
            'fields': (
                'created_at',
                'updated_at'
            )
        }),
    )
    
    def job_id_preview(self, obj):
        """Show job ID"""
        return f"{str(obj.processing_job.id)[:8]}..."
    job_id_preview.short_description = 'Job'
    
    def confidence_badge(self, obj):
        """Show confidence score badge"""
        color = 'green' if obj.is_high_confidence else 'orange'
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{:.1%}</span>',
            color,
            obj.confidence_score
        )
    confidence_badge.short_description = 'Confidence'
    
    def processing_time_display(self, obj):
        """Show processing time"""
        return f"{obj.processing_time_seconds:.2f}s"
    processing_time_display.short_description = 'Time'
    
    def text_length(self, obj):
        """Show text length"""
        return f"{len(obj.extracted_text)} chars"
    text_length.short_description = 'Length'
    
    def extracted_text_display(self, obj):
        """Show formatted extracted text"""
        return format_html('<pre style="white-space: pre-wrap; max-height: 300px; overflow-y: auto;">{}</pre>', obj.extracted_text)
    extracted_text_display.short_description = 'Extracted Text'
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related('processing_job')
    
    def has_add_permission(self, request):
        """Disable manual creation"""
        return False


@admin.register(CategoryPrediction)
class CategoryPredictionAdmin(admin.ModelAdmin):
    """Admin for category predictions"""
    
    list_display = [
        'job_id_preview',
        'predicted_category_short',
        'confidence_badge',
        'model_version',
        'processing_time_display',
        'created_at'
    ]
    list_filter = [
        'model_version',
        'created_at'
    ]
    search_fields = [
        'processing_job__id',
        'predicted_category_id',
        'reasoning'
    ]
    readonly_fields = [
        'id',
        'processing_job',
        'created_at',
        'updated_at',
        'alternatives_display'
    ]
    ordering = ['-created_at']
    
    fieldsets = (
        ('Prediction Info', {
            'fields': (
                'id',
                'processing_job',
                'predicted_category_id',
                'confidence_score',
                'reasoning'
            )
        }),
        ('Alternatives', {
            'fields': (
                'alternatives_display',
            )
        }),
        ('Metadata', {
            'fields': (
                'model_version',
                'processing_time_seconds'
            )
        }),
        ('Timestamps', {
            'fields': (
                'created_at',
                'updated_at'
            )
        }),
    )
    
    def job_id_preview(self, obj):
        """Show job ID"""
        return f"{str(obj.processing_job.id)[:8]}..."
    job_id_preview.short_description = 'Job'
    
    def predicted_category_short(self, obj):
        """Show predicted category ID"""
        return f"{str(obj.predicted_category_id)[:8]}..."
    predicted_category_short.short_description = 'Category'
    
    def confidence_badge(self, obj):
        """Show confidence badge"""
        color = 'green' if obj.is_high_confidence else 'orange'
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{:.1%}</span>',
            color,
            obj.confidence_score
        )
    confidence_badge.short_description = 'Confidence'
    
    def processing_time_display(self, obj):
        """Show processing time"""
        return f"{obj.processing_time_seconds:.2f}s"
    processing_time_display.short_description = 'Time'
    
    def alternatives_display(self, obj):
        """Show alternative predictions"""
        alternatives = obj.get_top_alternatives()
        if not alternatives:
            return "None"
        
        html = '<ul>'
        for alt in alternatives:
            html += f"<li>{alt.get('category_name', 'Unknown')}: {alt.get('confidence', 0):.1%}</li>"
        html += '</ul>'
        return format_html(html)
    alternatives_display.short_description = 'Alternative Predictions'
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related('processing_job')
    
    def has_add_permission(self, request):
        """Disable manual creation"""
        return False


@admin.register(ExtractedData)
class ExtractedDataAdmin(admin.ModelAdmin):
    """Admin for extracted receipt data"""
    
    list_display = [
        'job_id_preview',
        'vendor_name',
        'amount_display',
        'receipt_date',
        'confidence_summary',
        'items_count',
        'created_at'
    ]
    list_filter = [
        'extraction_method',
        'created_at',
        'receipt_date'
    ]
    search_fields = [
        'processing_job__id',
        'vendor_name'
    ]
    readonly_fields = [
        'id',
        'processing_job',
        'formatted_amount',
        'created_at',
        'updated_at',
        'confidence_breakdown'
    ]
    ordering = ['-created_at']
    
    fieldsets = (
        ('Extracted Data', {
            'fields': (
                'id',
                'processing_job',
                'vendor_name',
                'receipt_date',
                'total_amount',
                'currency',
                'formatted_amount'
            )
        }),
        ('Additional Info', {
            'fields': (
                'tax_amount',
                'subtotal',
                'line_items'
            )
        }),
        ('Confidence Scores', {
            'fields': (
                'confidence_breakdown',
            )
        }),
        ('Metadata', {
            'fields': (
                'extraction_method',
                'processing_time_seconds'
            )
        }),
        ('Timestamps', {
            'fields': (
                'created_at',
                'updated_at'
            )
        }),
    )
    
    def job_id_preview(self, obj):
        """Show job ID"""
        return f"{str(obj.processing_job.id)[:8]}..."
    job_id_preview.short_description = 'Job'
    
    def amount_display(self, obj):
        """Show formatted amount"""
        return obj.formatted_amount or "N/A"
    amount_display.short_description = 'Amount'
    
    def confidence_summary(self, obj):
        """Show confidence summary"""
        amount_ok = obj.has_high_confidence_amount
        vendor_ok = obj.has_high_confidence_vendor
        
        if amount_ok and vendor_ok:
            return format_html('<span style="color: green;">✓ High</span>')
        elif amount_ok or vendor_ok:
            return format_html('<span style="color: orange;">~ Medium</span>')
        return format_html('<span style="color: red;">✗ Low</span>')
    confidence_summary.short_description = 'Confidence'
    
    def items_count(self, obj):
        """Show number of line items"""
        return len(obj.line_items)
    items_count.short_description = 'Items'
    
    def confidence_breakdown(self, obj):
        """Show confidence scores breakdown"""
        html = '<table>'
        for field, score in obj.confidence_scores.items():
            color = 'green' if score >= 0.7 else 'orange' if score >= 0.5 else 'red'
            html += f'<tr><td>{field}:</td><td style="color: {color};">{score:.1%}</td></tr>'
        html += '</table>'
        return format_html(html)
    confidence_breakdown.short_description = 'Confidence Breakdown'
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related('processing_job')
    
    def has_add_permission(self, request):
        """Disable manual creation"""
        return False
