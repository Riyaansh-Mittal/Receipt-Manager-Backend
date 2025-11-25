# receipt_service/tasks/cleanup_tasks.py

import logging
from typing import Dict, Any
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from django.db import models
from django.core.cache import cache

from ...services.receipt_model_service import model_service

logger = logging.getLogger(__name__)

@shared_task
def update_category_usage_stats() -> Dict[str, Any]:
    """
    Update category usage statistics
    Helps improve AI suggestions over time
    """
    try:
        Category = model_service.category_model
        LedgerEntry = model_service.ledger_entry_model
        
        categories = Category.objects.all()
        updated_count = 0
        
        for category in categories:
            # Count ledger entries using this category
            usage_count = LedgerEntry.objects.filter(category=category).count()
            
            # Get last used date
            last_used_entry = LedgerEntry.objects.filter(
                category=category
            ).order_by('-created_at').first()
            
            last_used = last_used_entry.created_at if last_used_entry else None
            
            # Update if changed
            if category.usage_count != usage_count or category.last_used != last_used:
                category.usage_count = usage_count
                category.last_used = last_used
                category.save(update_fields=['usage_count', 'last_used'])
                updated_count += 1
        
        # Clear category caches
        cache_keys = [
            'categories_all_False',
            'categories_all_True',
        ]
        cache.delete_many(cache_keys)
        
        result = {
            'categories_updated': updated_count,
            'total_categories': categories.count(),
            'update_time': timezone.now().isoformat()
        }
        
        logger.info(f"Category usage stats updated: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to update category stats: {str(e)}", exc_info=True)
        return {
            'categories_updated': 0,
            'error': str(e)
        }


@shared_task
def cleanup_expired_cache_entries() -> Dict[str, Any]:
    """
    Clean up expired cache entries
    For cache backends that don't auto-expire
    """
    try:
        # Cache key patterns to clean
        cache_patterns = [
            'receipt_stats',
            'user_receipts_stats',
            'spending_summary',
            'user_category_stats',
            'quota_status'
        ]
        
        cleaned_count = 0
        
        # Get users to clean their caches
        from auth_service.services.auth_model_service import model_service as auth_model_service
        User = auth_model_service.user_model
        
        # Clean old user-specific caches (last 100 users as sample)
        for user in User.objects.all()[:100]:
            keys_to_delete = [
                f"spending_summary_{user.id}_monthly",
                f"spending_summary_{user.id}_yearly",
                f"spending_summary_{user.id}_weekly",
                f"user_category_stats_{user.id}_12",
                f"user_categories_{user.id}_10",
            ]
            
            try:
                cache.delete_many(keys_to_delete)
                cleaned_count += len(keys_to_delete)
            except Exception as e:
                logger.warning(f"Failed to clean cache for user {user.id}: {str(e)}")
        
        result = {
            'cleaned_entries': cleaned_count,
            'cleanup_time': timezone.now().isoformat()
        }
        
        logger.info(f"Cache cleanup completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Cache cleanup failed: {str(e)}", exc_info=True)
        return {'error': str(e)}


@shared_task
def generate_daily_stats_report() -> Dict[str, Any]:
    """
    Generate daily statistics report for monitoring
    """
    try:
        Receipt = model_service.receipt_model
        LedgerEntry = model_service.ledger_entry_model
        
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)
        
        # Calculate receipt stats
        total_receipts = Receipt.objects.count()
        created_yesterday = Receipt.objects.filter(created_at__date=yesterday).count()
        
        # Get file size stats
        file_stats = Receipt.objects.aggregate(
            total_size=models.Sum('file_size'),
            avg_size=models.Avg('file_size')
        )
        
        # Status breakdown
        status_counts = {}
        for status_choice in ['uploaded', 'queued', 'processing', 'processed', 'confirmed', 'failed']:
            count = Receipt.objects.filter(status=status_choice).count()
            status_counts[status_choice] = count
        
        daily_stats = {
            'date': today.isoformat(),
            'receipts': {
                'total': total_receipts,
                'created_yesterday': created_yesterday,
                'by_status': status_counts,
            },
            'storage': {
                'total_size_mb': round((file_stats['total_size'] or 0) / (1024 * 1024), 2),
                'avg_size_kb': round((file_stats['avg_size'] or 0) / 1024, 2),
            },
            'ledger': {
                'total_entries': LedgerEntry.objects.count(),
                'entries_yesterday': LedgerEntry.objects.filter(
                    created_at__date=yesterday
                ).count()
            },
            'generated_at': timezone.now().isoformat()
        }
        
        # Cache stats for 7 days
        cache.set(
            f'daily_stats:{today.isoformat()}', 
            daily_stats, 
            timeout=86400 * 7
        )
        
        logger.info(f"Daily stats generated: {daily_stats}")
        return daily_stats
        
    except Exception as e:
        logger.error(f"Failed to generate daily stats: {str(e)}", exc_info=True)
        return {
            'error': str(e),
            'date': timezone.now().date().isoformat()
        }