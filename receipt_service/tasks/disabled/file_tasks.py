# receipt_service/tasks/file_tasks.py

import logging
import tempfile
import os
from typing import Dict, Any

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q

logger = logging.getLogger(__name__)


@shared_task
def cleanup_old_temp_files() -> Dict[str, Any]:
    """Clean up old temporary files from temp directory"""
    try:
        import shutil
        from pathlib import Path
        
        temp_dir = Path(tempfile.gettempdir())
        cleaned_count = 0
        errors = []
        
        # Clean files older than 24 hours
        cutoff_time = timezone.now().timestamp() - (24 * 3600)
        
        # Receipt-related temp file patterns
        patterns = ['receipt_*', 'ledger_export_*', 'upload_*']
        
        for pattern in patterns:
            for temp_file in temp_dir.glob(pattern):
                try:
                    if temp_file.stat().st_mtime < cutoff_time:
                        if temp_file.is_file():
                            temp_file.unlink()
                            cleaned_count += 1
                        elif temp_file.is_dir():
                            shutil.rmtree(temp_file)
                            cleaned_count += 1
                except Exception as e:
                    errors.append(f"Failed to clean {temp_file}: {str(e)}")
        
        logger.info(f"Cleaned {cleaned_count} temporary files")
        
        return {
            'status': 'success',
            'cleaned_count': cleaned_count,
            'errors': errors,
            'completed_at': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Temp file cleanup failed: {str(e)}", exc_info=True)
        return {
            'status': 'failed',
            'error': str(e)
        }


@shared_task(
    bind=True,
    name='receipt_service.tasks.export_ledger_async_task',  # ← Fix: Explicit task name
    rate_limit='10/m',
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=3600,
    time_limit=7200
)
def export_ledger_async_task(
    self, 
    task_id: str, 
    filters: dict, 
    format_type: str, 
    user_id: str
) -> dict:
    """
    Async ledger export with progress tracking
    Stores file path in cache for later download
    """
    task_key = f"export_task:{task_id}"
    status_key = f"{task_key}:status"
    progress_key = f"{task_key}:progress"
    result_key = f"{task_key}:file_path"  # ← Fix: Consistent key name
    error_key = f"{task_key}:error"
    
    temp_file_path = None
    
    try:
        # Mark as processing
        cache.set(status_key, "processing", timeout=86400)
        cache.set(progress_key, 10, timeout=86400)
        
        logger.info(f"Starting export task {task_id} for user {user_id}")
        
        # Create temp file with proper directory
        temp_dir = tempfile.gettempdir()
        temp_file = tempfile.NamedTemporaryFile(
            mode='w+',
            suffix=f'.{format_type}',
            delete=False,
            prefix=f'ledger_export_{task_id}_',
            dir=temp_dir
        )
        temp_file_path = temp_file.name
        temp_file.close()
        
        logger.info(f"Created temp file: {temp_file_path}")
        cache.set(progress_key, 30, timeout=86400)
        
        # Get user
        from auth_service.services.auth_model_service import model_service as auth_model_service
        User = auth_model_service.user_model
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise ValueError(f"User {user_id} not found")
        
        cache.set(progress_key, 50, timeout=86400)
        
        # Perform export
        logger.info(f"Exporting as {format_type}")
        if format_type == 'csv':
            _export_to_csv(temp_file_path, filters, user)
        elif format_type == 'json':
            _export_to_json(temp_file_path, filters, user)
        else:
            raise ValueError(f"Unsupported format: {format_type}")
        
        cache.set(progress_key, 90, timeout=86400)
        
        # Verify file
        if not os.path.exists(temp_file_path):
            raise Exception(f"Export file was not created: {temp_file_path}")
        
        file_size = os.path.getsize(temp_file_path)
        if file_size == 0:
            raise Exception("Export file is empty")
        
        logger.info(f"Export file created: {temp_file_path} ({file_size} bytes)")
        
        # ✅ FIX: Store file path with proper key and longer timeout
        cache.set(result_key, temp_file_path, timeout=86400)  # 24 hours
        cache.set(progress_key, 100, timeout=86400)
        cache.set(status_key, "completed", timeout=86400)
        
        # Verify it was stored
        stored_path = cache.get(result_key)
        logger.info(f"Stored file path in cache: {stored_path}")
        
        logger.info(f"Export task {task_id} completed successfully")
        
        return {
            'status': 'success',
            'task_id': task_id,
            'file_path': temp_file_path,
            'file_size': file_size
        }
    
    except Exception as exc:
        logger.error(f"Export task {task_id} failed: {str(exc)}", exc_info=True)
        
        # Update cache with error
        cache.set(status_key, "failed", timeout=86400)
        cache.set(error_key, str(exc), timeout=86400)
        cache.set(progress_key, 0, timeout=86400)
        
        # Cleanup temp file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
                logger.info(f"Cleaned up failed export file: {temp_file_path}")
            except Exception as cleanup_exc:
                logger.warning(f"Failed to delete temp file: {str(cleanup_exc)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            countdown = min(2 ** self.request.retries * 60, 3600)
            logger.info(f"Retrying export task {task_id} in {countdown}s")
            raise self.retry(exc=exc, countdown=countdown)
        else:
            logger.error(f"Max retries exceeded for export task {task_id}")
            return {
                'status': 'failed',
                'task_id': task_id,
                'error': str(exc)
            }


# Export helper functions with proper filters

def _export_to_csv(file_path: str, filters: dict, user) -> None:
    """Export ledger entries to CSV"""
    import csv
    from receipt_service.services.receipt_model_service import model_service
    
    LedgerEntry = model_service.ledger_entry_model
    queryset = _build_export_queryset(LedgerEntry, user, filters)
    
    logger.info(f"Exporting {queryset.count()} entries to CSV")
    
    with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        
        # Header
        writer.writerow([
            'ID', 'Date', 'Vendor', 'Description', 'Amount', 'Currency',
            'Category', 'Business Expense', 'Reimbursable', 'Tags',
            'Receipt ID', 'Created At'
        ])
        
        # Data
        for entry in queryset.iterator(chunk_size=1000):
            writer.writerow([
                str(entry.id),
                entry.date.isoformat(),
                entry.vendor or '',
                entry.description or '',
                str(entry.amount),
                entry.currency,
                entry.category.name if entry.category else '',
                'Yes' if entry.is_business_expense else 'No',
                'Yes' if entry.is_reimbursable else 'No',
                ', '.join(entry.tags) if entry.tags else '',
                str(entry.receipt_id) if entry.receipt_id else '',
                entry.created_at.isoformat()
            ])
    
    logger.info(f"CSV export completed: {file_path}")


def _export_to_json(file_path: str, filters: dict, user) -> None:
    """Export ledger entries to JSON"""
    import json
    from receipt_service.services.receipt_model_service import model_service
    
    LedgerEntry = model_service.ledger_entry_model
    queryset = _build_export_queryset(LedgerEntry, user, filters)
    
    logger.info(f"Exporting {queryset.count()} entries to JSON")
    
    entries = []
    for entry in queryset.iterator(chunk_size=1000):
        entries.append({
            'id': str(entry.id),
            'date': entry.date.isoformat(),
            'vendor': entry.vendor,
            'description': entry.description,
            'amount': float(entry.amount),
            'currency': entry.currency,
            'category': {
                'id': str(entry.category.id),
                'name': entry.category.name
            } if entry.category else None,
            'is_business_expense': entry.is_business_expense,
            'is_reimbursable': entry.is_reimbursable,
            'tags': entry.tags,
            'receipt_id': str(entry.receipt_id) if entry.receipt_id else None,
            'created_at': entry.created_at.isoformat()
        })
    
    with open(file_path, 'w', encoding='utf-8') as jsonfile:
        json.dump({
            'entries': entries,
            'total': len(entries),
            'filters': filters,
            'exported_at': timezone.now().isoformat()
        }, jsonfile, indent=2)
    
    logger.info(f"JSON export completed: {file_path}")


def _build_export_queryset(LedgerEntry, user, filters: dict):
    """
    Build filtered queryset for export
    Uses SAME filters as list view
    """
    queryset = LedgerEntry.objects.filter(
        user=user
    ).select_related('category', 'receipt')
    
    # Apply ALL possible filters
    if filters.get('start_date'):
        from datetime import datetime
        if isinstance(filters['start_date'], str):
            start_date = datetime.fromisoformat(filters['start_date']).date()
        else:
            start_date = filters['start_date']
        queryset = queryset.filter(date__gte=start_date)
    
    if filters.get('end_date'):
        from datetime import datetime
        if isinstance(filters['end_date'], str):
            end_date = datetime.fromisoformat(filters['end_date']).date()
        else:
            end_date = filters['end_date']
        queryset = queryset.filter(date__lte=end_date)
    
    if filters.get('category_id'):
        queryset = queryset.filter(category_id=filters['category_id'])
    
    if filters.get('min_amount'):
        queryset = queryset.filter(amount__gte=filters['min_amount'])
    
    if filters.get('max_amount'):
        queryset = queryset.filter(amount__lte=filters['max_amount'])
    
    if filters.get('vendor_search'):
        queryset = queryset.filter(vendor__icontains=filters['vendor_search'])
    
    if filters.get('is_business_expense') is not None:
        queryset = queryset.filter(
            is_business_expense=filters['is_business_expense']
        )
    
    if filters.get('is_reimbursable') is not None:
        queryset = queryset.filter(
            is_reimbursable=filters['is_reimbursable']
        )
    
    if filters.get('currency'):
        queryset = queryset.filter(currency=filters['currency'])
    
    logger.info(f"Built queryset with filters: {filters}")
    
    return queryset.order_by('-date', '-created_at')


@shared_task
def check_storage_health() -> Dict[str, Any]:
    """Check storage backend health"""
    try:
        from ...utils.storage_backends import receipt_storage
        from django.core.files.base import ContentFile
        
        # Test write
        test_content = b"health_check_test"
        test_path = f"health_checks/test_{timezone.now().timestamp()}.txt"
        
        try:
            # Save test file
            saved_path = receipt_storage.save(test_path, ContentFile(test_content))
            
            # Verify exists
            exists = receipt_storage.exists(saved_path)
            
            # Read test
            if exists:
                with receipt_storage.open(saved_path, 'rb') as f:
                    content = f.read()
                    read_success = content == test_content
            else:
                read_success = False
            
            # Clean up
            receipt_storage.delete(saved_path)
            
            return {
                'status': 'healthy' if (exists and read_success) else 'degraded',
                'backend': receipt_storage.storage.__class__.__name__,
                'write_test': 'passed' if exists else 'failed',
                'read_test': 'passed' if read_success else 'failed',
                'checked_at': timezone.now().isoformat()
            }
            
        except Exception as e:
            return {
                'status': 'unhealthy',
                'backend': receipt_storage.storage.__class__.__name__,
                'error': str(e),
                'checked_at': timezone.now().isoformat()
            }
            
    except Exception as e:
        logger.error(f"Storage health check failed: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'checked_at': timezone.now().isoformat()
        }


@shared_task
def check_duplicate_receipts() -> Dict[str, Any]:
    """Check for duplicate receipts by file hash"""
    try:
        from ...services.receipt_model_service import model_service
        
        Receipt = model_service.receipt_model
        
        # Find duplicates
        duplicates = Receipt.objects.values('file_hash', 'user_id').annotate(
            count=Count('id')
        ).filter(count__gt=1).order_by('-count')
        
        duplicate_groups = []
        for dup in duplicates[:100]:
            receipt_ids = list(Receipt.objects.filter(
                file_hash=dup['file_hash'],
                user_id=dup['user_id']
            ).values_list('id', flat=True))
            
            duplicate_groups.append({
                'file_hash': dup['file_hash'],
                'user_id': str(dup['user_id']),
                'count': dup['count'],
                'receipt_ids': [str(rid) for rid in receipt_ids]
            })
        
        logger.info(f"Found {len(duplicate_groups)} duplicate groups")
        
        return {
            'status': 'success',
            'duplicate_groups': len(duplicate_groups),
            'duplicates': duplicate_groups,
            'checked_at': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Duplicate check failed: {str(e)}", exc_info=True)
        return {
            'status': 'failed',
            'error': str(e)
        }


@shared_task
def daily_maintenance_task() -> Dict[str, Any]:
    """Daily maintenance - cleanup and stats update"""
    results = {
        'temp_cleanup': None,
        'statistics_update': None,
        'completed_at': timezone.now().isoformat()
    }
    
    try:
        # Clean temp files
        results['temp_cleanup'] = cleanup_old_temp_files()
        
        # Update statistics
        results['statistics_update'] = update_storage_statistics()
        
        logger.info(f"Daily maintenance completed: {results}")
        
    except Exception as e:
        logger.error(f"Daily maintenance failed: {str(e)}", exc_info=True)
        results['error'] = str(e)
    
    return results