import logging
import os
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from typing import Dict, Any

logger = logging.getLogger(__name__)


@shared_task
def cleanup_expired_export_files() -> Dict[str, Any]:
    """
    Clean up export files older than 24 hours
    """
    try:
        import tempfile
        
        deleted_count = 0
        error_count = 0
        total_size_freed = 0
        
        # Get all export task keys from cache
        # This is a simplified version - in production with Redis, use SCAN
        temp_dir = tempfile.gettempdir()
        current_time = timezone.now()
        cutoff_time = current_time - timedelta(hours=24)
        
        # Iterate through potential export files
        for filename in os.listdir(temp_dir):
            if filename.startswith('ledger_export_') or filename.startswith('tmp'):
                file_path = os.path.join(temp_dir, filename)
                
                try:
                    # Check file age
                    file_mtime = timezone.datetime.fromtimestamp(
                        os.path.getmtime(file_path),
                        tz=timezone.get_current_timezone()
                    )
                    
                    if file_mtime < cutoff_time:
                        file_size = os.path.getsize(file_path)
                        os.unlink(file_path)
                        deleted_count += 1
                        total_size_freed += file_size
                        logger.info(f"Deleted expired export file: {filename}")
                
                except Exception as e:
                    logger.warning(f"Failed to delete export file {filename}: {str(e)}")
                    error_count += 1
        
        result = {
            'deleted_files': deleted_count,
            'errors': error_count,
            'size_freed_mb': round(total_size_freed / (1024 * 1024), 2),
            'cleanup_time': current_time.isoformat()
        }

        if deleted_count > 100:
            logger.warning(f"High export file accumulation: {deleted_count} files deleted")
        
        logger.info(f"Export file cleanup completed: {result}")
        return result
    
    except Exception as e:
        logger.error(f"Export file cleanup failed: {str(e)}")
        return {
            'deleted_files': 0,
            'errors': 1,
            'error_message': str(e)
        }


@shared_task
def cleanup_stale_export_tasks() -> Dict[str, Any]:
    """
    Clean up stale export task metadata from cache
    Tasks older than 48 hours are considered stale
    Uses Redis SCAN for safe pattern-based deletion
    """
    try:
        current_time = timezone.now()
        cutoff_time = current_time - timedelta(hours=48)
        
        cleaned_count = 0
        error_count = 0
        checked_count = 0
        
        # Get Redis client from cache backend
        try:
            # For django-redis cache backend
            redis_client = cache.client.get_client()
        except AttributeError:
            # Fallback for other cache backends
            logger.warning("Cache backend doesn't support Redis SCAN. Using basic cleanup.")
            return _basic_cache_cleanup(cutoff_time)
        
        # Use SCAN to safely iterate through export task keys
        batch_size = 100
        keys_to_delete = []
        
        try:
            # Scan for all export_task:* keys
            for key in redis_client.scan_iter(match='export_task:*', count=batch_size):
                checked_count += 1
                
                # Decode key if bytes
                if isinstance(key, bytes):
                    key = key.decode('utf-8')
                
                try:
                    # Get task data to check timestamp
                    task_data = cache.get(key)
                    
                    if task_data:
                        # Check if task is stale based on created_at
                        created_at_str = task_data.get('created_at')
                        if created_at_str:
                            try:
                                created_at = timezone.datetime.fromisoformat(created_at_str)
                                
                                if created_at < cutoff_time:
                                    keys_to_delete.append(key)
                                    
                                    # Also collect related keys
                                    task_id = key.replace('export_task:', '')
                                    keys_to_delete.extend([
                                        f"export_task:{task_id}:status",
                                        f"export_task:{task_id}:progress",
                                        f"export_task:{task_id}:result",
                                        f"export_task:{task_id}:error"
                                    ])
                                    
                                    # Delete in batches of 50 to avoid blocking
                                    if len(keys_to_delete) >= 50:
                                        cache.delete_many(keys_to_delete)
                                        cleaned_count += len(keys_to_delete)
                                        keys_to_delete = []
                                        
                            except (ValueError, TypeError) as e:
                                logger.debug(f"Invalid created_at format for {key}: {e}")
                    else:
                        # Task data is None, delete the key
                        keys_to_delete.append(key)
                        
                except Exception as e:
                    logger.debug(f"Error checking task {key}: {str(e)}")
                    error_count += 1
            
            # Delete remaining keys
            if keys_to_delete:
                cache.delete_many(keys_to_delete)
                cleaned_count += len(keys_to_delete)
            
            result = {
                'cleaned_tasks': cleaned_count,
                'checked_tasks': checked_count,
                'errors': error_count,
                'cleanup_time': current_time.isoformat(),
                'method': 'redis_scan'
            }
            
            logger.info(f"Stale export task cleanup completed: {result}")
            return result
        
        except Exception as e:
            logger.error(f"Redis SCAN cleanup failed: {str(e)}")
            error_count += 1
            raise
    
    except Exception as e:
        logger.error(f"Stale export task cleanup failed: {str(e)}")
        return {
            'cleaned_tasks': 0,
            'checked_tasks': 0,
            'errors': 1,
            'error_message': str(e),
            'method': 'failed'
        }


def _basic_cache_cleanup(cutoff_time) -> Dict[str, Any]:
    """
    Fallback cleanup for non-Redis cache backends
    Maintains a list of task IDs in a separate cache key
    """
    try:
        cleaned_count = 0
        error_count = 0
        
        # Get list of tracked task IDs
        task_id_list_key = 'export_task_ids_registry'
        task_ids = cache.get(task_id_list_key, [])
        
        remaining_task_ids = []
        
        for task_id in task_ids:
            task_key = f"export_task:{task_id}"
            task_data = cache.get(task_key)
            
            if task_data:
                created_at_str = task_data.get('created_at')
                if created_at_str:
                    try:
                        created_at = timezone.datetime.fromisoformat(created_at_str)
                        
                        if created_at < cutoff_time:
                            # Delete stale task and related keys
                            cache.delete_many([
                                task_key,
                                f"{task_key}:status",
                                f"{task_key}:progress",
                                f"{task_key}:result",
                                f"{task_key}:error"
                            ])
                            cleaned_count += 1
                        else:
                            remaining_task_ids.append(task_id)
                    except (ValueError, TypeError):
                        remaining_task_ids.append(task_id)
                else:
                    remaining_task_ids.append(task_id)
            # If task_data is None, don't add to remaining (already deleted)
        
        # Update registry with remaining tasks
        cache.set(task_id_list_key, remaining_task_ids, timeout=86400 * 30)  # 30 days
        
        result = {
            'cleaned_tasks': cleaned_count,
            'checked_tasks': len(task_ids),
            'errors': error_count,
            'cleanup_time': timezone.now().isoformat(),
            'method': 'basic_fallback'
        }
        
        logger.info(f"Basic cache cleanup completed: {result}")
        return result
    
    except Exception as e:
        logger.error(f"Basic cache cleanup failed: {str(e)}")
        return {
            'cleaned_tasks': 0,
            'checked_tasks': 0,
            'errors': 1,
            'error_message': str(e),
            'method': 'basic_fallback_failed'
        }
