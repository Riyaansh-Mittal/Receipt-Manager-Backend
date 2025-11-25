# ai_service/services/processing_pipeline.py

import time
import logging
from typing import Dict, Any
from decimal import Decimal
from datetime import datetime, date
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from .ai_model_service import model_service
from .ocr_service import get_ocr_service
from .gemini_extraction_service import gemini_extractor
from receipt_service.services.receipt_import_service import service_import
from ..utils.exceptions import (
    ProcessingPipelineException,
    DataExtractionException,
    GeminiServiceException,
    ModelLoadingException,
    OCRServiceUnavailableException
)
from shared.utils.exceptions import DatabaseOperationException

logger = logging.getLogger(__name__)


class ProcessingPipelineService:
    """
    Complete AI processing pipeline for receipts
    
    Pipeline modes (controlled by settings.USE_GEMINI_ONLY_IMAGE_INPUT):
    - False (default): OCR → Gemini extraction + categorization
    - True: Direct image → Gemini extraction + categorization (skip OCR)
    
    Pipeline stages:
    1. Create processing job
    2. OCR with preprocessing (if not using direct image mode)
    3. Gemini extraction + categorization (ONE call)
    4. Store results in AI models
    5. Complete job
    """
    
    def __init__(self):
        self.use_gemini_only_image = getattr(settings, 'USE_GEMINI_ONLY_IMAGE_INPUT', False)
    
    def process_receipt(
        self, 
        receipt_id: str, 
        user_id: str,
        image_data: bytes
    ) -> Dict[str, Any]:
        """Process receipt through AI pipeline based on configured mode"""
        processing_job = None
        start_time = time.time()
        
        try:
            # Stage 0: Create processing job
            
            logger.info(
                f"Starting AI processing for receipt {receipt_id} "
                f"(mode: {'direct-image' if self.use_gemini_only_image else 'ocr-first'})"
            )

            # Check status before starting
            receipt_service = service_import.receipt_service
            receipt_status = receipt_service.get_receipt_status(receipt_id)
            if receipt_status == 'confirmed':
                # ✅ FIX: Early return without processing - don't update status
                logger.info(f"Receipt {receipt_id} already confirmed, skipping pipeline")
                return {
                    'status': 'skipped',
                    'reason': 'Receipt already confirmed',
                    'processing_time_seconds': 0
                }
            processing_job = self._create_processing_job(receipt_id, user_id)
            
            if self.use_gemini_only_image:
                # Direct image → Gemini mode (skip OCR)
                stage_result = self._run_gemini_image_only_stage(
                    processing_job,
                    image_data,
                    receipt_id,
                    user_id
                )
            else:
                # Traditional OCR → Gemini mode
                # Stage 1: OCR Processing
                self._update_job_stage(processing_job, 'ocr', 20)
                ocr_result = self._run_ocr_stage(
                    processing_job, 
                    image_data, 
                    receipt_id
                )
                
                # Stage 2: Gemini Extraction + Categorization
                self._update_job_stage(processing_job, 'data_extraction', 60)
                stage_result = self._run_gemini_stage(
                    processing_job,
                    ocr_result['extracted_text'],
                    receipt_id,
                    user_id
                )
            
            # Stage 3: Complete
            self._update_job_stage(processing_job, 'completed', 100)
            self._complete_processing_job(processing_job)
            
            processing_time = time.time() - start_time
            
            result = {
                'receipt_id': receipt_id,
                'processing_job_id': str(processing_job.id),
                'status': 'completed',
                'used_fallback': stage_result.get('used_fallback', False),
                'processing_time_seconds': round(processing_time, 2),
                'processing_mode': 'direct_image' if self.use_gemini_only_image else 'ocr_first',
            }
            
            logger.info(
                f"AI processing completed for {receipt_id} in {processing_time:.2f}s"
            )
            
            return result
            
        except (ProcessingPipelineException, DataExtractionException, 
                GeminiServiceException, ModelLoadingException) as known_exc:
            if processing_job:
                self._fail_processing_job(
                    processing_job, 
                    str(known_exc), 
                    processing_job.current_stage or 'unknown'
                )
            raise
            
        except Exception as general_exc:
            logger.error(
                f"AI processing failed for {receipt_id}: {str(general_exc)}", 
                exc_info=True
            )
            
            if processing_job:
                self._fail_processing_job(
                    processing_job, 
                    str(general_exc), 
                    processing_job.current_stage or 'initialization'
                )
            
            raise ProcessingPipelineException(
                detail="AI processing pipeline failed",
                context={
                    'receipt_id': receipt_id,
                    'stage': processing_job.current_stage if processing_job else 'init',
                    'error': str(general_exc)
                }
            )
    
    def _create_processing_job(self, receipt_id: str, user_id: str):
        """Create new processing job"""
        try:
            with transaction.atomic():
                processing_job = model_service.processing_job_model.objects.create(
                    receipt_id=receipt_id,
                    user_id=user_id,
                    status='queued',
                    current_stage='data_extraction' if self.use_gemini_only_image else 'ocr',
                    progress_percentage=0,
                    retry_count=0
                )
                
                logger.info(f"Processing job created: {processing_job.id}")
                return processing_job
                
        except Exception as e:
            logger.error(f"Failed to create job: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Failed to create processing job",
                context={'receipt_id': receipt_id}
            )
    
    def _update_job_stage(self, processing_job, stage: str, progress: int) -> None:
        """Update job stage and progress"""
        try:
            processing_job.current_stage = stage
            processing_job.progress_percentage = progress
            
            if stage == 'completed':
                processing_job.status = 'completed'
            elif progress > 0:
                processing_job.status = 'processing'
                if not processing_job.started_at:
                    processing_job.started_at = timezone.now()
            
            processing_job.save(update_fields=[
                'current_stage', 
                'progress_percentage', 
                'status',
                'started_at'
            ])
            
            logger.debug(f"Job stage updated: {stage} ({progress}%)")
            
        except Exception as e:
            logger.warning(f"Failed to update job stage: {str(e)}")
    
    def _run_ocr_stage(
        self, 
        processing_job, 
        image_data: bytes, 
        receipt_id: str
    ) -> Dict[str, Any]:
        """Run OCR stage (traditional pipeline)"""
        try:
            logger.info(f"Running OCR for receipt {receipt_id}")
            
            ocr_service = get_ocr_service()
            if ocr_service is None:
                raise OCRServiceUnavailableException("OCR service unavailable: configured for Gemini-image-only mode")

            ocr_start = time.time()
            ocr_result = ocr_service.extract_text_from_image(image_data, receipt_id)
            ocr_time = time.time() - ocr_start
            
            # Store OCR result
            self._store_ocr_result(processing_job, ocr_result, ocr_time)
            
            return ocr_result
            
        except Exception as e:
            logger.error(f"OCR stage failed: {str(e)}", exc_info=True)
            raise ProcessingPipelineException(
                detail="OCR processing failed",
                context={'receipt_id': receipt_id, 'error': str(e)}
            )
    
    def _run_gemini_stage(
        self,
        processing_job,
        ocr_text: str,
        receipt_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Run Gemini extraction + categorization from OCR text (traditional pipeline)"""
        logger.info(f"Running Gemini extraction from OCR text for {receipt_id}")
        
        categories = self._get_available_categories()
        
        gemini_start = time.time()
        try:
            gemini_result = gemini_extractor.extract_and_categorize(
                ocr_text=ocr_text,
                receipt_id=receipt_id,
                user_id=user_id,
                categories=categories
            )
        except (GeminiServiceException, DataExtractionException, ModelLoadingException) as e:
            logger.error(f"Gemini extraction failed: {str(e)}")
            raise ProcessingPipelineException(
                detail="AI extraction failed",
                context={'receipt_id': receipt_id, 'error': str(e)}
            )
        
        gemini_time = time.time() - gemini_start
        
        # Store results
        try:
            with transaction.atomic():
                self._store_extraction_result(
                    processing_job, 
                    gemini_result['extracted_data'],
                    gemini_result.get('extraction_confidence', {}),
                    gemini_time
                )
                
                self._store_category_prediction(
                    processing_job, 
                    gemini_result['category_prediction'],
                    gemini_time
                )
                
        except Exception as store_error:
            logger.error(f"Failed to store results: {str(store_error)}", exc_info=True)
            raise ProcessingPipelineException(
                detail="Failed to store extraction results",
                context={'receipt_id': receipt_id, 'error': str(store_error)}
            )
        
        return gemini_result
    
    def _run_gemini_image_only_stage(
        self,
        processing_job,
        image_data: bytes,
        receipt_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Run Gemini extraction + categorization from preprocessed image"""
        logger.info(f"Running Gemini direct image extraction for {receipt_id}")
        
        # Update job stage
        self._update_job_stage(processing_job, 'data_extraction', 90)
        
        categories = self._get_available_categories()
        gemini_start = time.time()
        
        try:
            gemini_result = gemini_extractor.extract_from_image(
                preprocessed_image=image_data,
                receipt_id=receipt_id,
                user_id=user_id,
                categories=categories
            )
        except DataExtractionException as e:
            logger.warning(f"Gemini soft failure, using fallback: {str(e)}")
            gemini_result = self._get_simple_fallback('Low quality image')
        except (GeminiServiceException, ModelLoadingException) as e:
            logger.error(f"Gemini hard failure: {str(e)}")
            raise ProcessingPipelineException(detail="AI extraction failed", context={'error': str(e)})
        
        gemini_time = time.time() - gemini_start
        
        # ✅ FIX: Store results with explicit transaction and verification
        try:
            with transaction.atomic():
                self._store_extraction_result(
                    processing_job, 
                    gemini_result['extracted_data'],
                    gemini_result.get('extraction_confidence', {}),
                    gemini_time
                )
                
                self._store_category_prediction(
                    processing_job, 
                    gemini_result['category_prediction'],
                    gemini_time
                )
                
                logger.info(f"Data stored for receipt {receipt_id}")
                
        except Exception as store_error:
            logger.error(f"Failed to store results: {str(store_error)}", exc_info=True)
            raise ProcessingPipelineException(
                detail="Failed to store extraction results",
                context={'receipt_id': receipt_id, 'error': str(store_error)}
            )
        
        used_fallback = gemini_result['extraction_confidence']['overall'] < 0.3
        return {'status': 'success', 'used_fallback': used_fallback}
    
    def _store_ocr_result(
        self, 
        processing_job, 
        ocr_result: Dict[str, Any],
        processing_time: float
    ) -> None:
        """Store OCR result (only in traditional OCR-first pipeline)"""
        try:
            with transaction.atomic():
                # Get OCR engine name from ocr_service
                ocr_service = get_ocr_service()
                engine_info = ocr_service.get_engine_info()
                ocr_engine = engine_info.get('engine', 'unknown')
                
                model_service.ocr_result_model.objects.create(
                    processing_job=processing_job,
                    extracted_text=ocr_result['extracted_text'],
                    confidence_score=ocr_result['confidence_score'],
                    language_detected='en',
                    ocr_engine=ocr_engine,
                    processing_time_seconds=processing_time
                )
                
            logger.debug("OCR result stored")
            
        except Exception as e:
            logger.error(f"Failed to store OCR result: {str(e)}", exc_info=True)
    
    def _store_extraction_result(
        self,
        processing_job,
        extracted_data: Dict[str, Any],
        confidence_scores: Dict[str, float],
        processing_time: float
    ) -> None:
        """Store extracted data with verification"""
        try:
            receipt_date = self._parse_date(extracted_data.get('receipt_date'))
            total_amount = self._parse_decimal(extracted_data.get('total_amount'))
            tax_amount = self._parse_decimal(extracted_data.get('tax_amount'))
            subtotal = self._parse_decimal(extracted_data.get('subtotal'))
            currency = extracted_data.get('currency') or 'USD'
            
            if not currency or currency.strip() == '':
                currency = 'USD'
            
            # ✅ FIX: Create and immediately save
            ext_data = model_service.extracted_data_model.objects.create(
                processing_job=processing_job,
                vendor_name=extracted_data.get('vendor_name') or 'Unknown',
                receipt_date=receipt_date,
                total_amount=total_amount,
                currency=currency,
                tax_amount=tax_amount,
                subtotal=subtotal,
                line_items=extracted_data.get('line_items', []),
                confidence_scores=confidence_scores,
                extraction_method='gemini_image',
                processing_time_seconds=processing_time
            )
            
            # ✅ FIX: Force save and verify
            ext_data.save()
            
            logger.info(f"Extraction data saved: job={processing_job.id}, vendor={ext_data.vendor_name}")
            
        except Exception as e:
            logger.error(f"Failed to store extraction: {str(e)}", exc_info=True)
            raise
    
    def _store_category_prediction(
        self,
        processing_job,
        category_prediction: Dict[str, Any],
        processing_time: float
    ) -> None:
        """Store category prediction with verification"""
        try:
            predicted_category_id = category_prediction.get('category_id')
            
            if not predicted_category_id:
                logger.warning(
                    f"Skipping category for job {processing_job.id}: missing category_id"
                )
                return
            
            # ✅ FIX: Create and immediately save
            cat_pred = model_service.category_prediction_model.objects.create(
                processing_job=processing_job,
                predicted_category_id=predicted_category_id,
                confidence_score=category_prediction.get('confidence', 0.5),
                reasoning=category_prediction.get('reasoning', ''),
                alternative_predictions=category_prediction.get('alternatives', []),
                model_version='gemini-2.0-flash-exp',
                processing_time_seconds=processing_time
            )
            
            # ✅ FIX: Force save and verify
            cat_pred.save()
            
            logger.info(
                f"Category saved: job={processing_job.id}, "
                f"category={cat_pred.predicted_category_id}, "
                f"confidence={cat_pred.confidence_score}"
            )
            
        except Exception as e:
            logger.error(f"Failed to store category: {str(e)}", exc_info=True)
            raise
    
    def _complete_processing_job(self, processing_job) -> None:
        """Mark job as completed and update receipt status"""
        try:
            # Update job
            with transaction.atomic():
                processing_job.status = 'completed'
                processing_job.current_stage = 'completed'
                processing_job.progress_percentage = 100
                processing_job.completed_at = timezone.now()
                processing_job.save(update_fields=['status', 'current_stage', 'progress_percentage', 'completed_at'])
            
            logger.info(f"Job {processing_job.id} marked as completed")
            
            # ✅ FIX: Update receipt status directly (don't use service import inside try block)
            from receipt_service.services.receipt_model_service import model_service as receipt_model_service
            
            with transaction.atomic():
                receipt = receipt_model_service.receipt_model.objects.select_for_update().get(id=processing_job.receipt_id)
                
                if receipt.status == 'confirmed':
                    logger.info(f"Receipt {receipt.id} already confirmed")
                    return
                
                receipt.status = 'processed'
                receipt.processing_completed_at = timezone.now()
                receipt.save(update_fields=['status', 'processing_completed_at'])
            
            logger.info(f"Receipt {processing_job.receipt_id} status updated to processed")
            
        except Exception as e:
            logger.error(f"Failed to complete job: {str(e)}", exc_info=True)
            raise ProcessingPipelineException(detail="Job completion failed", context={'error': str(e)})
    
    def _fail_processing_job(
        self, 
        processing_job, 
        error_message: str, 
        error_stage: str
    ) -> None:
        """Mark job as failed"""
        try:
            with transaction.atomic():
                processing_job.status = 'failed'
                processing_job.error_message = error_message[:2000]
                processing_job.error_stage = error_stage
                processing_job.completed_at = timezone.now()
                processing_job.retry_count = (processing_job.retry_count or 0) + 1
                processing_job.save(update_fields=[
                    'status',
                    'error_message',
                    'error_stage',
                    'completed_at',
                    'retry_count'
                ])
            
            try:
                from receipt_service.services.receipt_model_service import model_service as receipt_model_service
                
                receipt = receipt_model_service.receipt_model.objects.get(
                    id=processing_job.receipt_id
                )
                # ✅ FIX: Check if receipt is already confirmed or processed
                if receipt.status == 'confirmed' or receipt.status == 'processed':
                    logger.warning(
                        f"Receipt {receipt.id} already confirmed or processed, not marking as failed"
                    )
                    return  # Don't overwrite confirmed status
                
                receipt.status = 'failed'
                receipt.processing_completed_at = timezone.now()
                receipt.save(update_fields=['status', 'processing_completed_at'])
                
                logger.info(f"Updated receipt {receipt.id} status to failed")
                
            except Exception as receipt_error:
                logger.error(
                    f"Failed to update receipt status: {str(receipt_error)}",
                    exc_info=True
                )
                
            logger.error(f"Job failed: {processing_job.id} at {error_stage}")
            
        except Exception as e:
            logger.error(f"Failed to mark job as failed: {str(e)}", exc_info=True)
    
    def _get_available_categories(self) -> list:
        """Get available categories"""
        try:
            from receipt_service.services.category_service import CategoryService
            
            category_service = CategoryService()
            categories = category_service.get_all_categories(include_inactive=False)
            
            return categories
            
        except Exception as e:
            logger.error(f"Failed to get categories: {str(e)}", exc_info=True)
            return [{'id': 'unknown', 'name': 'Uncategorized'}]
    
    def _parse_date(self, value) -> date:
        """Parse date value"""
        if not value:
            return None
        
        try:
            if isinstance(value, str):
                return datetime.strptime(value, '%Y-%m-%d').date()
            elif isinstance(value, date):
                return value
            elif isinstance(value, datetime):
                return value.date()
        except Exception as e:
            logger.warning(f"Failed to parse date '{value}': {str(e)}")
        
        return None
    
    def _parse_decimal(self, value) -> Decimal:
        """Parse decimal value"""
        if value is None:
            return None
        
        try:
            return Decimal(str(value))
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse decimal '{value}': {str(e)}")
            return None


# Global instance
processing_pipeline = ProcessingPipelineService()
