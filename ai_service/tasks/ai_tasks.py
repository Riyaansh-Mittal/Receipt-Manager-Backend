# ai_service/tasks/ai_tasks.py

from celery import shared_task
from typing import Dict
from django.utils import timezone
import logging

from ..services.processing_pipeline import ProcessingPipelineService
from ..utils.exceptions import (
    ProcessingPipelineException,
    ImageCorruptedException,
    InvalidImageFormatException,
)

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=25)
def process_receipt_ai_task(self, receipt_id: str, user_id: str, storage_path: str) -> Dict[str, any]:
    """
    Async task for AI receipt processing
    """
    try:
        from receipt_service.services.receipt_import_service import service_import
        from receipt_service.services.quota_service import QuotaService
        logger.info(f"[Task {self.request.id}] Starting AI processing for receipt {receipt_id}")
        
        # ✅ FIX: Use ReceiptService method instead of standalone helper
        receipt_service = service_import.receipt_service
        receipt_service.update_processing_status(receipt_id, 'processing')
        
        # Load image data from storage
        try:
            image_data = _load_image_from_storage(storage_path)
        except ValueError as load_error:
            # ✅ Permanent file error - don't retry
            if "File not found" in str(load_error) or "Empty file" in str(load_error):
                logger.error(f"Permanent file error: {str(load_error)}")
                receipt_service.update_processing_status(receipt_id, 'failed')
                raise ProcessingPipelineException(
                    detail="Receipt file not found or corrupted",
                    context={'error': str(load_error)}
                )
            else:
                raise  # Unknown ValueError - retry
        
        # Process through pipeline
        pipeline = ProcessingPipelineService()
        result = pipeline.process_receipt(receipt_id, user_id, image_data)
        
        # ✅ FIX: Use ReceiptService method for status update
        receipt_service.update_processing_status(receipt_id, 'processed')
        
        # Only increment quota for successful AI processing (not fallback)
        if not result.get('used_fallback', False):
            QuotaService().increment_upload_count(user_id=user_id)
        
        logger.info(f"AI processing completed for receipt {receipt_id}")
        return {'status': 'success', 'receipt_id': receipt_id}
        
    except (ImageCorruptedException, InvalidImageFormatException, ProcessingPipelineException) as e:
        # ✅ Permanent errors - DON'T RETRY
        logger.error(f"Permanent error: {str(e)}")
        receipt_service.update_processing_status(receipt_id, 'failed')
        raise
        
    except Exception as e:
        # ✅ Only retry unknown errors
        logger.error(f"Unexpected error (will retry): {str(e)}")
        try:
            countdown = 60 * (2 ** self.request.retries)
            self.retry(countdown=countdown, exc=e)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded")
            receipt_service.update_processing_status(receipt_id, 'failed')
            raise


@shared_task(bind=True, max_retries=2)
def batch_process_receipts_task(self, receipt_batch: list) -> Dict[str, any]:
    """
    Batch process multiple receipts
    Useful for processing uploaded files in bulk
    """
    results = []
    
    for receipt_data in receipt_batch:
        try:
            result = process_receipt_ai_task.apply_async(
                args=[
                    receipt_data['receipt_id'],
                    receipt_data['user_id'],
                    receipt_data['storage_path']
                ],
                countdown=5  # Small delay to avoid overwhelming queue
            )
            
            results.append({
                'receipt_id': receipt_data['receipt_id'],
                'task_id': result.id,
                'status': 'queued'
            })
            
        except Exception as e:
            logger.error(
                f"Failed to queue receipt {receipt_data['receipt_id']}: {str(e)}",
                exc_info=True
            )
            results.append({
                'receipt_id': receipt_data['receipt_id'],
                'status': 'failed',
                'error': str(e)
            })
    
    return {
        'batch_size': len(receipt_batch),
        'queued': len([r for r in results if r['status'] == 'queued']),
        'failed': len([r for r in results if r['status'] == 'failed']),
        'results': results
    }


@shared_task
def cleanup_expired_processing_jobs() -> Dict[str, any]:
    """
    Clean up old processing jobs and their related data
    Scheduled task - runs daily
    """
    try:
        from ..services.ai_model_service import model_service
        from datetime import timedelta
        
        # Keep for 30 days (configurable)
        cutoff_date = timezone.now() - timedelta(days=30)
        
        # Find old completed/failed jobs
        expired_jobs = model_service.processing_job_model.objects.filter(
            created_at__lt=cutoff_date,
            status__in=['completed', 'failed', 'cancelled']
        )
        
        deleted_count = 0
        error_count = 0
        
        for job in expired_jobs:
            try:
                # Django will cascade delete related OCRResult, ExtractedData, CategoryPrediction
                # if models have CASCADE on_delete
                job.delete()
                deleted_count += 1
                
            except Exception as e:
                logger.error(f"Failed to delete job {job.id}: {str(e)}")
                error_count += 1
        
        logger.info(
            f"Cleanup completed: {deleted_count} jobs deleted, {error_count} errors"
        )
        
        return {
            'deleted_jobs': deleted_count,
            'errors': error_count,
            'cutoff_date': cutoff_date.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Cleanup task failed: {str(e)}", exc_info=True)
        return {'error': str(e)}


# ai_service/tasks/ai_tasks.py

@shared_task
def health_check_ai_services() -> Dict[str, any]:
    """
    Periodic health check for AI services
    Scheduled task - runs every 5 minutes
    Only checks enabled services based on configuration
    """
    try:
        from django.conf import settings
        
        health_status = {
            'timestamp': timezone.now().isoformat(),
            'services': {},
            'config': {
                'gemini_only': getattr(settings, 'USE_GEMINI_ONLY_IMAGE_INPUT', False)
            }
        }
        
        # ===========================
        # Check OCR Service (if enabled)
        # ===========================
        use_gemini_only = getattr(settings, 'USE_GEMINI_ONLY_IMAGE_INPUT', False)
        
        if not use_gemini_only:
            # OCR is active - check it
            try:
                from ..services.ocr_service import get_ocr_service
                
                ocr_service = get_ocr_service()
                engine_info = ocr_service.get_engine_info()
                status = 'healthy' if engine_info.get('available', False) else 'unhealthy'
                
                health_status['services']['ocr'] = {
                    'status': status,
                    'engine': engine_info.get('engine', 'unknown'),
                }
                
            except Exception as e:
                logger.error(f"OCR health check failed: {str(e)}")
                health_status['services']['ocr'] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }
        else:
            # Gemini-only mode: skip OCR entirely
            logger.debug("OCR health check skipped (Gemini-only mode enabled)")
            health_status['services']['ocr'] = {
                'status': 'disabled',
                'reason': 'Gemini-only mode enabled'
            }
        
        # ===========================
        # Check Gemini Service (Always)
        # ===========================
        try:
            from ..services.gemini_extraction_service import gemini_extractor
            
            if gemini_extractor._gemini_client:
                health_status['services']['gemini'] = {
                    'status': 'healthy',
                    'model': gemini_extractor.model_name,
                    'timeout': gemini_extractor.timeout
                }
            else:
                health_status['services']['gemini'] = {
                    'status': 'unhealthy',
                    'error': gemini_extractor._initialization_error or 'Client not initialized'
                }
        except Exception as e:
            logger.error(f"Gemini health check failed: {str(e)}")
            health_status['services']['gemini'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
        
        # ===========================
        # Check Database Connectivity
        # ===========================
        try:
            from ..services.ai_model_service import model_service
            
            count = model_service.processing_job_model.objects.count()
            health_status['services']['database'] = {
                'status': 'healthy',
                'processing_jobs_count': count
            }
        except Exception as e:
            logger.error(f"Database health check failed: {str(e)}")
            health_status['services']['database'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
        
        # ===========================
        # Overall Status
        # ===========================
        # Check only healthy services (skip 'disabled' ones)
        service_statuses = [
            service.get('status') 
            for service in health_status['services'].values()
            if service.get('status') != 'disabled'
        ]
        
        all_healthy = all(
            status == 'healthy' 
            for status in service_statuses
        )
        
        health_status['overall_status'] = 'healthy' if all_healthy else 'degraded'
        
        if not all_healthy:
            logger.warning(f"AI services health check: {health_status['overall_status']}")
        
        return health_status
        
    except Exception as e:
        logger.error(f"Health check task failed: {str(e)}", exc_info=True)
        return {
            'overall_status': 'unhealthy',
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }

# Helper functions

def _load_image_from_storage(storage_path: str) -> bytes:
    """
    Load image from storage backend
    
    Args:
        storage_path: Path to file in storage
        
    Returns:
        Image bytes
        
    Raises:
        ValueError: If file not found or cannot be read
    """
    try:
        from receipt_service.utils.storage_backends import receipt_storage
        
        logger.debug(f"Loading image from storage: {storage_path}")
        
        # Check if file exists
        if not receipt_storage.storage.exists(storage_path):
            raise FileNotFoundError(f"File not found in storage: {storage_path}")
        
        # Read file
        with receipt_storage.storage.open(storage_path, 'rb') as f:
            content = f.read()
        
        if not content or len(content) == 0:
            raise ValueError(f"Empty file in storage: {storage_path}")
        
        logger.debug(f"Loaded {len(content)} bytes from storage")
        return content
        
    except FileNotFoundError as e:
        logger.error(f"File not found in storage: {storage_path}")
        raise ValueError(f"File not found: {storage_path}") from e
        
    except Exception as e:
        logger.error(f"Failed to load image: {str(e)}", exc_info=True)
        raise ValueError(f"Failed to load image from storage: {str(e)}") from e
