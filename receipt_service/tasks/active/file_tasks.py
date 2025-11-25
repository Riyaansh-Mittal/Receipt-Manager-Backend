# receipt_service/tasks/file_tasks.py

import logging
from typing import Dict, Any

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q

logger = logging.getLogger(__name__)


@shared_task
def update_storage_statistics() -> Dict[str, Any]:
    """Update cached storage statistics"""
    try:
        from ...services.receipt_model_service import model_service
        
        Receipt = model_service.receipt_model
        
        # Calculate overall statistics
        stats = Receipt.objects.aggregate(
            total_receipts=Count('id'),
            total_size_bytes=Sum('file_size'),
            avg_file_size=Avg('file_size'),
            processed_count=Count('id', filter=Q(status='processed')),
            confirmed_count=Count('id', filter=Q(status='confirmed')),
            failed_count=Count('id', filter=Q(status='failed')),
            queued_count=Count('id', filter=Q(status='queued'))
        )
        
        # Convert to readable format
        total_size_mb = (stats['total_size_bytes'] or 0) / (1024 * 1024)
        avg_size_mb = (stats['avg_file_size'] or 0) / (1024 * 1024)
        
        # Status breakdown
        status_breakdown = list(Receipt.objects.values('status').annotate(
            count=Count('id')
        ).order_by('-count'))
        
        # MIME type breakdown
        mime_breakdown = list(Receipt.objects.exclude(
            mime_type__isnull=True
        ).values('mime_type').annotate(
            count=Count('id'),
            total_size=Sum('file_size')
        ).order_by('-count')[:10])
        
        # User breakdown (top 10)
        user_breakdown = list(Receipt.objects.values('user_id').annotate(
            count=Count('id'),
            total_size=Sum('file_size')
        ).order_by('-count')[:10])
        
        analytics = {
            'overall': {
                'total_receipts': stats['total_receipts'],
                'total_size_mb': round(total_size_mb, 2),
                'avg_file_size_mb': round(avg_size_mb, 2),
                'processed_count': stats['processed_count'],
                'confirmed_count': stats['confirmed_count'],
                'failed_count': stats['failed_count'],
                'queued_count': stats['queued_count'],
                'success_rate': round((stats['processed_count'] / max(stats['total_receipts'], 1)) * 100, 2)
            },
            'by_status': status_breakdown,
            'by_mime_type': mime_breakdown,
            'top_users': user_breakdown,
            'last_updated': timezone.now().isoformat()
        }
        
        # Cache for 1 hour
        cache.set('receipt_storage_statistics', analytics, timeout=3600)
        
        logger.info(f"Storage stats updated: {stats['total_receipts']} receipts, {total_size_mb:.2f}MB")
        
        return {
            'status': 'success',
            'statistics': analytics
        }
        
    except Exception as e:
        logger.error(f"Storage statistics update failed: {str(e)}", exc_info=True)
        return {
            'status': 'failed',
            'error': str(e)
        }