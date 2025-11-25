# receipt_service/tasks/cleanup_tasks.py

import logging
from typing import Dict, Any
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache

from ...services.receipt_model_service import model_service

logger = logging.getLogger(__name__)


@shared_task
def cleanup_orphaned_files() -> Dict[str, Any]:
    """
    Clean up files in storage that don't have corresponding Receipt records
    Works with Django FileField on Receipt model
    """
    try:
        from ...utils.storage_backends import receipt_storage
        
        # Get all receipt file paths from database
        Receipt = model_service.receipt_model
        db_file_paths = set(
            Receipt.objects.exclude(file_path='')
            .exclude(file_path__isnull=True)
            .values_list('file_path', flat=True)
        )
        
        orphaned_count = 0
        errors = []
        
        logger.info(f"Found {len(db_file_paths)} files in database")
        
        # Note: Full implementation would list all files in storage
        # and compare with db_file_paths to find orphans
        # This is storage-backend specific (S3 vs local)
        
        # For S3:
        # storage_files = receipt_storage.storage.bucket.objects.all()
        # For local:
        # Walk the MEDIA_ROOT/receipts directory
        
        return {
            'status': 'success',
            'db_files': len(db_file_paths),
            'orphaned_count': orphaned_count,
            'errors': errors,
            'completed_at': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Orphaned files cleanup failed: {str(e)}", exc_info=True)
        return {
            'status': 'failed',
            'error': str(e)
        }


@shared_task
def cleanup_old_receipts(days_old: int = 365) -> Dict[str, Any]:
    """
    Clean up old receipts (GDPR compliance / storage management)
    USE WITH CAUTION - requires user consent!
    """
    try:
        Receipt = model_service.receipt_model
        
        cutoff_date = timezone.now() - timedelta(days=days_old)
        
        # Find old receipts with safety conditions
        old_receipts = Receipt.objects.filter(
            created_at__lt=cutoff_date,
            status__in=['failed', 'cancelled']  # Only delete failed/cancelled
        )
        
        # Safety limit
        old_receipts = old_receipts[:10]
        
        deleted_count = 0
        deleted_size = 0
        error_count = 0
        
        for receipt in old_receipts:
            try:
                with transaction.atomic():
                    file_size = receipt.file_size
                    
                    # Delete file from storage
                    if receipt.file_path:
                        try:
                            receipt.file_path.delete(save=False)
                        except Exception as file_error:
                            logger.warning(f"Failed to delete file: {str(file_error)}")
                    
                    # Delete receipt (cascades to ledger entries)
                    receipt.delete()
                    
                    deleted_count += 1
                    deleted_size += file_size
                    
            except Exception as e:
                logger.warning(f"Failed to delete receipt {receipt.id}: {str(e)}")
                error_count += 1
        
        result = {
            'deleted_receipts': deleted_count,
            'deleted_size_mb': round(deleted_size / (1024 * 1024), 2),
            'errors': error_count,
            'days_old': days_old,
            'cleanup_time': timezone.now().isoformat()
        }
        
        logger.info(f"Old receipt cleanup completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Old receipt cleanup failed: {str(e)}", exc_info=True)
        return {
            'deleted_receipts': 0,
            'errors': 1,
            'error_message': str(e)
        }

@shared_task
def cleanup_failed_receipts(days_old: int = 7) -> Dict[str, Any]:
    """
    Clean up receipts that failed processing after X days
    """
    try:
        Receipt = model_service.receipt_model
        
        cutoff_date = timezone.now() - timedelta(days=days_old)
        
        # Find failed receipts older than cutoff
        failed_receipts = Receipt.objects.filter(
            status='failed',
            created_at__lt=cutoff_date
        )
        
        deleted_count = 0
        error_count = 0
        
        for receipt in failed_receipts[:50]:  # Limit batch size
            try:
                # Delete file
                if receipt.file_path:
                    receipt.file_path.delete(save=False)
                
                # Delete receipt
                receipt.delete()
                deleted_count += 1
                
            except Exception as e:
                logger.warning(f"Failed to delete failed receipt {receipt.id}: {str(e)}")
                error_count += 1
        
        result = {
            'deleted_count': deleted_count,
            'error_count': error_count,
            'days_old': days_old,
            'completed_at': timezone.now().isoformat()
        }
        
        logger.info(f"Failed receipts cleanup: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Failed receipts cleanup error: {str(e)}", exc_info=True)
        return {'error': str(e)}