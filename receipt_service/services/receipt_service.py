# from django.db import transaction
# from django.utils import timezone
# from typing import Dict, Any, Optional
# from decimal import Decimal, InvalidOperation
# import base64
# import logging
# from .receipt_model_service import model_service
# from .file_service import FileService
# from .quota_service import QuotaService
# from .category_service import CategoryService
# from ..utils.exceptions import (
#     ReceiptNotFoundException,
#     ReceiptAccessDeniedException,
#     ReceiptNotProcessedException,
#     ReceiptAlreadyConfirmedException,
#     ReceiptProcessingInProgressException,
#     ReceiptConfirmationException,
#     CategoryNotFoundException,
#     CategoryInactiveException,
#     LedgerEntryCreationException,
#     DatabaseOperationException,
#     FileRetrievalException,
#     MonthlyUploadLimitExceededException,
#     FileUploadException,
#     InvalidFileFormatException,
#     FileSizeExceededException,
#     DuplicateReceiptException,
#     FileStorageException
# )


# logger = logging.getLogger(__name__)


# class ReceiptService:
#     """
#     Main receipt business logic service
#     Orchestrates file handling, processing, and confirmation workflows with AI integration
#     """
    
#     def __init__(self):
#         self.file_service = FileService()
#         self.quota_service = QuotaService()
#         self.category_service = CategoryService()
    
#     def upload_receipt(self, user, uploaded_file, metadata: Optional[Dict] = None) -> Dict[str, Any]:
#         """
#         Complete receipt upload workflow with quota validation and AI processing
#         """
#         try:
#             # Validate quota first (fail-fast)
#             self.quota_service.validate_upload_allowed(user)
            
#             receipt_id = None
            
#             with transaction.atomic():
#                 # Store file and create receipt record
#                 result = self.file_service.store_receipt_file(user, uploaded_file, metadata)
#                 receipt_id = result['receipt_id']
                
#                 # Increment quota
#                 self.quota_service.increment_upload_count(user)
            
#             # Queue async AI processing task (outside transaction)
#             processing_queued = False
#             status = 'uploaded'
#             message = 'Receipt uploaded successfully.'
#             estimated_time = None
            
#             try:
#                 self._queue_ai_processing_task(
#                     receipt_id=str(receipt_id),
#                     user_id=str(user.id)
#                 )
#                 processing_queued = True
#                 status = 'queued'
#                 message = 'Receipt uploaded successfully. AI processing has been queued.'
#                 estimated_time = '30-60 seconds'
                
#                 logger.info(f"AI processing task queued for receipt {receipt_id}")
                
#             except Exception as e:
#                 logger.error(f"Failed to queue AI processing for receipt {receipt_id}: {str(e)}")
                
#                 # Update receipt status to indicate processing failed to queue
#                 try:
#                     receipt = model_service.receipt_model.objects.get(id=receipt_id)
#                     receipt.status = 'uploaded'
#                     receipt.processing_stage = 'upload_complete'
#                     receipt.processing_error = f"Failed to queue processing: {str(e)[:500]}"
#                     receipt.save(update_fields=['status', 'processing_stage', 'processing_error', 'updated_at'])
#                 except Exception as update_error:
#                     logger.error(f"Failed to update receipt status after queue failure: {str(update_error)}")
            
#             logger.info(f"Receipt uploaded successfully: {receipt_id} for user {user.id} (queued={processing_queued})")
            
#             return {
#                 'receipt_id': str(receipt_id),
#                 'status': status,
#                 'message': message,
#                 'estimated_processing_time': estimated_time,
#                 'processing_queued': processing_queued,
#                 'next_steps': {
#                     'check_status': f'/receipts/v1/upload-status/{receipt_id}/',
#                     'view_details': f'/receipts/v1/{receipt_id}/'
#                 }
#             }
            
#         except (MonthlyUploadLimitExceededException, FileUploadException, InvalidFileFormatException,
#                 FileSizeExceededException, DuplicateReceiptException, FileStorageException):
#             raise
#         except Exception as e:
#             logger.error(f"Receipt upload failed for user {user.id}: {str(e)}", exc_info=True)
#             raise FileUploadException(
#                 detail="Receipt upload failed",
#                 context={'user_id': str(user.id)}
#             )


#     def _queue_ai_processing_task(self, receipt_id: str, user_id: str):
#         """
#         Queue async AI processing task using Celery
        
#         Uses the already-stored file from storage backend
        
#         Args:
#             receipt_id: Receipt UUID
#             user_id: User UUID
            
#         Raises:
#             Exception: If task queueing fails
#         """
#         try:
#             from ai_service.tasks.ai_tasks import process_receipt_ai_task
            
#             # Get receipt to get storage path
#             receipt = model_service.receipt_model.objects.get(id=receipt_id)
            
#             storage_path = receipt.file_path.name
#             if not storage_path:
#                 raise ValueError(f"Receipt {receipt_id} has no storage_path")
            
#             logger.debug(f"Queueing AI task for receipt {receipt_id} with storage path: {storage_path}")
            
#             # Queue the task with storage path
#             # Task will read file from storage backend
#             task = process_receipt_ai_task.delay(
#                 receipt_id=receipt_id,
#                 user_id=user_id,
#                 storage_path = storage_path
#             )
            
#             # Update receipt status
#             receipt.status = 'queued'
#             receipt.processing_stage = 'queued'
#             receipt.processing_started_at = timezone.now()
#             receipt.save(update_fields=['status', 'processing_stage', 'processing_started_at', 'updated_at'])
            
#             logger.info(f"AI processing task queued: {task.id} for receipt {receipt_id}")
            
#         except model_service.receipt_model.DoesNotExist:
#             logger.error(f"Receipt {receipt_id} not found for AI processing")
#             raise ValueError(f"Receipt {receipt_id} not found")
#         except ImportError:
#             logger.error("AI service tasks module not available")
#             raise Exception("AI service not properly configured")
#         except Exception as e:
#             logger.error(f"Failed to queue AI processing task for receipt {receipt_id}: {str(e)}", exc_info=True)
#             raise
    
#     def get_processing_status(self, user, receipt_id: str) -> Dict[str, Any]:
#         """
#         Get AI processing status for a receipt
#         """
#         try:
#             receipt = model_service.receipt_model.objects.get(id=receipt_id)
            
#             # Check user access
#             if receipt.user_id != user.id:
#                 raise ReceiptAccessDeniedException(
#                     detail="You do not have permission to access this receipt",
#                     context={'receipt_id': receipt_id, 'user_id': str(user.id)}
#                 )
            
#             # Get AI processing status
#             try:
#                 from ai_service.services.processing_pipeline import ProcessingPipelineService
                
#                 pipeline = ProcessingPipelineService()
#                 ai_status = pipeline.get_processing_status(receipt_id, str(user.id))
                
#                 return {
#                     'receipt_id': receipt_id,
#                     'status': ai_status['status'],
#                     'current_stage': ai_status.get('current_stage', receipt.processing_stage),
#                     'progress_percentage': ai_status.get('progress_percentage', 0),
#                     'message': self._get_status_message(ai_status['status']),
#                     'started_at': ai_status.get('started_at'),
#                     'completed_at': ai_status.get('completed_at'),
#                     'estimated_completion_seconds': ai_status.get('estimated_completion_seconds'),
#                     'error_message': ai_status.get('error_message'),
#                     'can_retry': ai_status.get('can_retry', False)
#                 }
                
#             except ImportError:
#                 # Fallback to receipt model status if AI service not available
#                 return {
#                     'receipt_id': receipt_id,
#                     'status': receipt.status,
#                     'processing_stage': receipt.processing_stage,
#                     'message': self._get_status_message(receipt.status)
#                 }
                
#         except model_service.receipt_model.DoesNotExist:
#             raise ReceiptNotFoundException(
#                 detail="Receipt not found",
#                 context={'receipt_id': receipt_id, 'user_id': str(user.id)}
#             )
#         except ReceiptAccessDeniedException:
#             raise
#         except Exception as e:
#             logger.error(f"Failed to get processing status for receipt {receipt_id}: {str(e)}")
#             raise DatabaseOperationException(
#                 detail="Failed to retrieve processing status",
#                 context={'receipt_id': receipt_id}
#             )
    
#     def get_extracted_data(self, user, receipt_id: str) -> Dict[str, Any]:
#         """
#         Get AI-extracted data from processed receipt
#         """
#         try:
#             receipt = model_service.receipt_model.objects.select_related('suggested_category').get(
#                 id=receipt_id
#             )
            
#             # Check user access
#             if receipt.user_id != user.id:
#                 raise ReceiptAccessDeniedException(
#                     detail="You do not have permission to access this receipt",
#                     context={'receipt_id': receipt_id, 'user_id': str(user.id)}
#                 )
            
#             # Check if receipt is processed
#             if receipt.status not in ['processed', 'confirmed']:
#                 raise ReceiptNotProcessedException(
#                     detail="Receipt has not been processed yet",
#                     context={'receipt_id': receipt_id, 'current_status': receipt.status}
#                 )
            
#             # Get AI processing results
#             try:
#                 from .receipt_model_service import model_service as ai_models
                
#                 # Get processing job
#                 processing_job = ai_models.processing_job_model.objects.filter(
#                     receipt_id=receipt_id,
#                     user_id=user.id
#                 ).first()
                
#                 extracted_data = {
#                     'receipt_id': receipt_id,
#                     'status': 'ready' if receipt.can_be_confirmed() else 'not_ready',
#                     'extracted_text': receipt.extracted_text or '',
#                     'extracted_date': receipt.extracted_date.isoformat() if receipt.extracted_date else None,
#                     'extracted_vendor': receipt.extracted_vendor or '',
#                     'extracted_amount': float(receipt.extracted_amount) if receipt.extracted_amount else None,
#                     'extracted_currency': receipt.extracted_currency or 'USD',
#                     'extracted_items': receipt.extracted_items or [],
#                     'ocr_confidence': receipt.ocr_confidence_score or 0.0,
#                 }
                
#                 # Add AI categorization if available
#                 if receipt.suggested_category:
#                     extracted_data['suggested_category'] = {
#                         'id': str(receipt.suggested_category.id),
#                         'name': receipt.suggested_category.name,
#                         'slug': receipt.suggested_category.slug,
#                         'icon': receipt.suggested_category.icon,
#                         'color': receipt.suggested_category.color,
#                         'confidence': receipt.ai_confidence_score or 0.0,
#                         'reasoning': receipt.ai_reasoning or ''
#                     }
                    
#                     # Get alternative suggestions if available
#                     if processing_job:
#                         try:
#                             category_prediction = processing_job.category_prediction
#                             if category_prediction and category_prediction.alternative_predictions:
#                                 extracted_data['alternative_categories'] = [
#                                     {
#                                         'id': alt['category_id'],
#                                         'confidence': alt['confidence'],
#                                         'reasoning': alt.get('reasoning', '')
#                                     }
#                                     for alt in category_prediction.alternative_predictions[:3]
#                                 ]
#                         except Exception as e:
#                             logger.warning(f"Failed to get alternative predictions: {str(e)}")
                
#                 # Add processing metadata
#                 if processing_job:
#                     extracted_data['processing_metadata'] = {
#                         'job_id': str(processing_job.id),
#                         'processing_time_seconds': processing_job.duration_seconds,
#                         'completed_at': processing_job.completed_at.isoformat() if processing_job.completed_at else None
#                     }
                
#                 extracted_data['ready_for_confirmation'] = receipt.can_be_confirmed()
                
#                 return extracted_data
                
#             except ImportError:
#                 # Fallback to receipt model data only
#                 return {
#                     'receipt_id': receipt_id,
#                     'status': 'ready' if receipt.can_be_confirmed() else 'not_ready',
#                     'extracted_text': receipt.extracted_text or '',
#                     'extracted_date': receipt.extracted_date.isoformat() if receipt.extracted_date else None,
#                     'extracted_vendor': receipt.extracted_vendor or '',
#                     'extracted_amount': float(receipt.extracted_amount) if receipt.extracted_amount else None,
#                     'extracted_currency': receipt.extracted_currency or 'USD',
#                     'suggested_category_id': str(receipt.suggested_category_id) if receipt.suggested_category_id else None,
#                     'confidence_score': receipt.ai_confidence_score or 0.0,
#                     'ready_for_confirmation': receipt.can_be_confirmed()
#                 }
                
#         except model_service.receipt_model.DoesNotExist:
#             raise ReceiptNotFoundException(
#                 detail="Receipt not found",
#                 context={'receipt_id': receipt_id, 'user_id': str(user.id)}
#             )
#         except (ReceiptAccessDeniedException, ReceiptNotProcessedException):
#             raise
#         except Exception as e:
#             logger.error(f"Failed to get extracted data for receipt {receipt_id}: {str(e)}")
#             raise DatabaseOperationException(
#                 detail="Failed to retrieve extracted data",
#                 context={'receipt_id': receipt_id}
#             )
    
#     def update_processing_status(self, receipt_id: str, status: str, result: Dict):
#         """
#         Update receipt processing status (called by AI service)
#         """
#         try:
#             with transaction.atomic():
#                 receipt = model_service.receipt_model.objects.get(id=receipt_id)
#                 print('FINAL RESULT:')
#                 logger.info(f"FINAL RESULT: {result}")
#                 # Update basic status
#                 receipt.status = status
#                 receipt.processing_stage = result.get('current_stage', 'completed')
                
#                 if status == 'completed':
#                     receipt.processing_completed_at = timezone.now()
                    
#                     # Update with AI results
#                     if 'ocr_result' in result:
#                         ocr = result['ocr_result']
#                         receipt.extracted_text = ocr.get('extracted_text', '')
#                         receipt.ocr_confidence_score = ocr.get('confidence_score', 0.0)
                    
#                     if 'extracted_data' in result:
#                         data = result['extracted_data']
#                         receipt.extracted_date = data.get('receipt_date')
#                         receipt.extracted_vendor = data.get('vendor_name', '')
#                         receipt.extracted_amount = data.get('total_amount')
#                         receipt.extracted_currency = data.get('currency', 'USD')
#                         receipt.extracted_items = data.get('line_items', [])
                    
#                     if 'categorization_result' in result:
#                         cat = result['categorization_result']
#                         receipt.suggested_category_id = cat.get('predicted_category_id')
#                         receipt.ai_confidence_score = cat.get('confidence_score', 0.0)
#                         receipt.ai_reasoning = cat.get('reasoning', '')
                    
#                     # Update status to processed
#                     receipt.status = 'processed'
                    
#                 elif status == 'failed':
#                     error_msg = result.get('error', 'Processing failed')
#                     receipt.processing_error = error_msg
#                     receipt.processing_attempts += 1
                
#                 receipt.save()
                
#                 logger.info(f"Receipt {receipt_id} status updated to {status}")
                
#         except model_service.receipt_model.DoesNotExist:
#             logger.error(f"Receipt {receipt_id} not found for status update")
#         except Exception as e:
#             logger.error(f"Failed to update receipt status for {receipt_id}: {str(e)}")
    
#     def get_receipt_details(self, user, receipt_id: str) -> Dict[str, Any]:
#         """
#         Get comprehensive receipt details with processing status
#         """
#         try:
#             receipt = model_service.receipt_model.objects.select_related('suggested_category').get(
#                 id=receipt_id
#             )
            
#             # Check user access
#             if receipt.user_id != user.id:
#                 raise ReceiptAccessDeniedException(
#                     detail="You do not have permission to access this receipt",
#                     context={'receipt_id': receipt_id, 'user_id': str(user.id)}
#                 )
            
#             # Build response data
#             response = {
#                 'id': str(receipt.id),
#                 'original_filename': receipt.original_filename,
#                 'status': receipt.status,
#                 'processing_stage': receipt.processing_stage,
#                 'file_size': receipt.file_size,
#                 'file_size_mb': round(receipt.file_size / (1024 * 1024), 2),
#                 'mime_type': receipt.mime_type,
#                 'upload_date': receipt.created_at.isoformat(),
#                 'processing_started_at': receipt.processing_started_at.isoformat() if receipt.processing_started_at else None,
#                 'processing_completed_at': receipt.processing_completed_at.isoformat() if receipt.processing_completed_at else None,
#                 'processing_duration_seconds': receipt.processing_duration_seconds,
#                 'processing_attempts': receipt.processing_attempts,
#                 'can_be_confirmed': receipt.can_be_confirmed()
#             }
            
#             # Add extracted data if available
#             if receipt.status in ['processed', 'confirmed']:
#                 response['extracted_data'] = {
#                     'text': receipt.extracted_text,
#                     'date': receipt.extracted_date.isoformat() if receipt.extracted_date else None,
#                     'vendor': receipt.extracted_vendor,
#                     'amount': float(receipt.extracted_amount) if receipt.extracted_amount else None,
#                     'currency': receipt.extracted_currency,
#                     'items': receipt.extracted_items or []
#                 }
                
#                 # Add AI suggestion if available
#                 if receipt.suggested_category:
#                     response['ai_suggestion'] = {
#                         'category': {
#                             'id': str(receipt.suggested_category.id),
#                             'name': receipt.suggested_category.name,
#                             'icon': receipt.suggested_category.icon,
#                             'color': receipt.suggested_category.color
#                         },
#                         'confidence_score': receipt.ai_confidence_score,
#                         'reasoning': receipt.ai_reasoning
#                     }
                
#                 response['ocr_confidence'] = receipt.ocr_confidence_score
            
#             # Add error information if processing failed
#             if receipt.status == 'failed':
#                 response['error'] = {
#                     'message': receipt.processing_error,
#                     'attempts': receipt.processing_attempts,
#                     'stage': receipt.processing_stage
#                 }
            
#             # Add secure file URL
#             try:
#                 file_url = self.file_service.get_secure_file_url(receipt)
#                 if file_url:
#                     response['file_url'] = file_url
#             except FileRetrievalException as e:
#                 logger.warning(f"Could not generate file URL for receipt {receipt_id}: {str(e)}")
            
#             # Add next actions based on status
#             response['next_actions'] = self._get_next_actions(receipt)
            
#             return response
            
#         except model_service.receipt_model.DoesNotExist:
#             raise ReceiptNotFoundException(
#                 detail="Receipt not found",
#                 context={'receipt_id': receipt_id, 'user_id': str(user.id)}
#             )
#         except (ReceiptAccessDeniedException, FileRetrievalException):
#             raise
#         except Exception as e:
#             logger.error(f"Failed to get receipt details for {receipt_id}: {str(e)}")
#             raise DatabaseOperationException(
#                 detail="Failed to retrieve receipt details",
#                 context={'receipt_id': receipt_id}
#             )
    
#     def confirm_receipt(self, user, receipt_id: str, confirmation_data: Dict[str, Any]) -> Dict[str, Any]:
#         """
#         Confirm receipt data and create ledger entry
#         """
#         try:
#             receipt = model_service.receipt_model.objects.select_related('suggested_category').get(
#                 id=receipt_id
#             )
            
#             # Check user access
#             if receipt.user_id != user.id:
#                 raise ReceiptAccessDeniedException(
#                     detail="You do not have permission to confirm this receipt",
#                     context={'receipt_id': receipt_id, 'user_id': str(user.id)}
#                 )
            
#             # Validate receipt can be confirmed
#             self._validate_receipt_for_confirmation(receipt)
            
#             # Validate confirmation data
#             self._validate_confirmation_data(confirmation_data)
            
#             with transaction.atomic():
#                 # Get and validate category
#                 try:
#                     category = model_service.category_model.objects.get(
#                         id=confirmation_data['category_id']
#                     )
                    
#                     if not category.is_active:
#                         raise CategoryInactiveException(
#                             detail=f"Category '{category.name}' is no longer active",
#                             context={'category_id': str(category.id), 'category_name': category.name}
#                         )
                        
#                 except model_service.category_model.DoesNotExist:
#                     raise CategoryNotFoundException(
#                         detail="Selected category not found",
#                         context={'category_id': confirmation_data['category_id']}
#                     )
                
#                 # Determine user corrections
#                 corrections = self._detect_user_corrections(receipt, confirmation_data, category)
                
#                 # Create ledger entry
#                 try:
#                     ledger_entry = model_service.ledger_entry_model.objects.create(
#                         user=user,
#                         receipt=receipt,
#                         category=category,
#                         date=confirmation_data['date'],
#                         vendor=confirmation_data.get('vendor', '').strip(),
#                         amount=Decimal(str(confirmation_data['amount'])),
#                         currency=confirmation_data.get('currency', 'USD'),
#                         description=confirmation_data.get('description', '').strip(),
#                         ai_confidence_score=receipt.ai_confidence_score,
#                         user_corrected_amount=corrections['amount'],
#                         user_corrected_category=corrections['category'],
#                         user_corrected_vendor=corrections['vendor'],
#                         user_corrected_date=corrections['date'],
#                         is_business_expense=confirmation_data.get('is_business_expense', False),
#                         is_reimbursable=confirmation_data.get('is_reimbursable', False),
#                         created_from_ip=confirmation_data.get('ip_address')
#                     )
#                 except Exception as e:
#                     logger.error(f"Failed to create ledger entry for receipt {receipt_id}: {str(e)}")
#                     raise LedgerEntryCreationException(
#                         detail="Failed to create ledger entry",
#                         context={'receipt_id': receipt_id, 'user_id': str(user.id)}
#                     )
                
#                 # Update receipt status
#                 try:
#                     receipt.status = 'confirmed'
#                     receipt.save(update_fields=['status', 'updated_at'])
#                 except Exception as e:
#                     logger.error(f"Failed to update receipt status for {receipt_id}: {str(e)}")
#                     raise DatabaseOperationException(
#                         detail="Failed to update receipt status",
#                         context={'receipt_id': receipt_id}
#                     )
                
#                 # Update user category preferences
#                 try:
#                     self.category_service.update_user_category_usage(user, category)
#                 except Exception as e:
#                     logger.warning(f"Failed to update category usage for user {user.id}: {str(e)}")
                
#                 # Invalidate user cache (for AI personalization)
#                 try:
#                     from ai_service.services.cache_service import ai_cache_service
#                     ai_cache_service.invalidate_user_cache(str(user.id))
#                 except Exception as e:
#                     logger.warning(f"Failed to invalidate AI cache for user {user.id}: {str(e)}")
                
#                 logger.info(f"Receipt confirmed: {receipt_id} -> Ledger entry: {ledger_entry.id}")
                
#                 return {
#                     'ledger_entry_id': str(ledger_entry.id),
#                     'receipt_id': str(receipt.id),
#                     'message': 'Receipt confirmed and added to your expense ledger',
#                     'accuracy_metrics': {
#                         'ai_was_accurate': ledger_entry.was_ai_accurate,
#                         'accuracy_score': ledger_entry.accuracy_score,
#                         'user_corrections': corrections
#                     }
#                 }
                
#         except model_service.receipt_model.DoesNotExist:
#             raise ReceiptNotFoundException(
#                 detail="Receipt not found",
#                 context={'receipt_id': receipt_id, 'user_id': str(user.id)}
#             )
#         except (ReceiptAccessDeniedException, ReceiptNotProcessedException, ReceiptAlreadyConfirmedException, 
#                 ReceiptProcessingInProgressException, ReceiptConfirmationException, CategoryNotFoundException, 
#                 CategoryInactiveException, LedgerEntryCreationException, DatabaseOperationException):
#             raise
#         except Exception as e:
#             logger.error(f"Unexpected error confirming receipt {receipt_id}: {str(e)}")
#             raise DatabaseOperationException(
#                 detail="Unexpected error occurred during receipt confirmation"
#             )
    
#     def get_user_receipts(self, user, status: Optional[str] = None, 
#                          limit: int = 20, offset: int = 0) -> Dict[str, Any]:
#         """
#         Get paginated list of user receipts with optional status filtering
#         """
#         try:
#             queryset = model_service.receipt_model.objects.filter(user=user).order_by('-created_at')
            
#             if status:
#                 # Validate status value
#                 valid_statuses = ['uploaded', 'queued', 'processing', 'processed', 'confirmed', 'failed', 'cancelled']
#                 if status not in valid_statuses:
#                     raise ReceiptConfirmationException(
#                         detail=f"Invalid status filter. Valid options: {', '.join(valid_statuses)}",
#                         context={'provided_status': status, 'valid_statuses': valid_statuses}
#                     )
#                 queryset = queryset.filter(status=status)
            
#             total_count = queryset.count()
#             receipts = queryset.select_related('suggested_category')[offset:offset + limit]
            
#             receipt_list = []
#             for receipt in receipts:
#                 receipt_data = {
#                     'id': str(receipt.id),
#                     'original_filename': receipt.original_filename,
#                     'status': receipt.status,
#                     'processing_stage': receipt.processing_stage,
#                     'upload_date': receipt.created_at.isoformat(),
#                     'file_size': receipt.file_size,
#                     'file_size_mb': round(receipt.file_size / (1024 * 1024), 2),
#                     'can_be_confirmed': receipt.can_be_confirmed()
#                 }
                
#                 # Add extracted amount if available
#                 if receipt.extracted_amount:
#                     receipt_data['extracted_amount'] = float(receipt.extracted_amount)
#                     receipt_data['extracted_currency'] = receipt.extracted_currency
                
#                 # Add suggested category if available
#                 if receipt.suggested_category:
#                     receipt_data['suggested_category'] = {
#                         'id': str(receipt.suggested_category.id),
#                         'name': receipt.suggested_category.name,
#                         'icon': receipt.suggested_category.icon,
#                         'color': receipt.suggested_category.color
#                     }
                
#                 # Add processing info
#                 if receipt.processing_completed_at:
#                     receipt_data['processing_completed_at'] = receipt.processing_completed_at.isoformat()
#                     receipt_data['processing_duration_seconds'] = receipt.processing_duration_seconds
                
#                 receipt_list.append(receipt_data)
            
#             return {
#                 'receipts': receipt_list,
#                 'pagination': {
#                     'total_count': total_count,
#                     'limit': limit,
#                     'offset': offset,
#                     'has_more': (offset + limit) < total_count,
#                     'current_page': (offset // limit) + 1,
#                     'total_pages': (total_count + limit - 1) // limit
#                 },
#                 'summary': {
#                     'total_receipts': total_count,
#                     'status_filter': status
#                 }
#             }
            
#         except ReceiptConfirmationException:
#             raise
#         except Exception as e:
#             logger.error(f"Failed to get receipts for user {user.id}: {str(e)}")
#             raise DatabaseOperationException(
#                 detail="Failed to retrieve user receipts",
#                 context={'user_id': str(user.id), 'status_filter': status}
#             )
    
#     # Helper methods
    
#     def _get_status_message(self, status: str) -> str:
#         """Get user-friendly status message"""
#         messages = {
#             'uploaded': 'Receipt uploaded successfully',
#             'queued': 'Receipt queued for AI processing',
#             'processing': 'AI is processing your receipt...',
#             'processed': 'Receipt processed successfully - ready for confirmation',
#             'confirmed': 'Receipt confirmed and added to ledger',
#             'failed': 'Receipt processing failed',
#             'cancelled': 'Receipt processing cancelled'
#         }
#         return messages.get(status, 'Unknown status')
    
#     def _get_next_actions(self, receipt) -> list:
#         """Get available next actions for receipt"""
#         actions = []
        
#         if receipt.status == 'processed' and receipt.can_be_confirmed():
#             actions.append({
#                 'action': 'confirm',
#                 'method': 'POST',
#                 'endpoint': f'/receipts/v1/{receipt.id}/confirm/',
#                 'description': 'Confirm and create ledger entry'
#             })
#             actions.append({
#                 'action': 'view_extracted_data',
#                 'method': 'GET',
#                 'endpoint': f'/receipts/v1/{receipt.id}/extracted-data/',
#                 'description': 'View extracted data details'
#             })
        
#         if receipt.status in ['queued', 'processing']:
#             actions.append({
#                 'action': 'check_status',
#                 'method': 'GET',
#                 'endpoint': f'/receipts/v1/upload-status/{receipt.id}/',
#                 'description': 'Check processing status'
#             })
        
#         if receipt.status == 'failed':
#             actions.append({
#                 'action': 'retry',
#                 'method': 'POST',
#                 'endpoint': f'/receipts/v1/{receipt.id}/retry/',
#                 'description': 'Retry processing'
#             })
        
#         return actions
    
#     def _validate_receipt_for_confirmation(self, receipt):
#         """Validate receipt can be confirmed"""
#         if receipt.status == 'confirmed':
#             raise ReceiptAlreadyConfirmedException(
#                 detail="Receipt has already been confirmed",
#                 context={'receipt_id': str(receipt.id), 'confirmed_at': receipt.updated_at.isoformat()}
#             )
        
#         if receipt.status in ['processing', 'queued']:
#             raise ReceiptProcessingInProgressException(
#                 detail="Receipt is still being processed. Please wait for completion.",
#                 context={
#                     'receipt_id': str(receipt.id), 
#                     'current_stage': receipt.processing_stage,
#                     'estimated_completion': '30-60 seconds'
#                 }
#             )
        
#         if receipt.status == 'failed':
#             raise ReceiptNotProcessedException(
#                 detail="Receipt processing failed and cannot be confirmed. Please re-upload the receipt.",
#                 context={
#                     'receipt_id': str(receipt.id),
#                     'error_message': receipt.processing_error,
#                     'attempts': receipt.processing_attempts
#                 }
#             )
        
#         if receipt.status != 'processed':
#             raise ReceiptNotProcessedException(
#                 detail="Receipt must be successfully processed before it can be confirmed",
#                 context={'receipt_id': str(receipt.id), 'current_status': receipt.status}
#             )
    
#     def _validate_confirmation_data(self, data: Dict[str, Any]):
#         """Validate confirmation data structure and values"""
#         required_fields = ['date', 'amount', 'category_id']
        
#         # Check required fields
#         missing_fields = [field for field in required_fields if field not in data or data[field] is None]
#         if missing_fields:
#             raise ReceiptConfirmationException(
#                 detail=f"Missing required fields: {', '.join(missing_fields)}",
#                 context={'missing_fields': missing_fields, 'required_fields': required_fields}
#             )
        
#         # Validate amount
#         try:
#             amount = Decimal(str(data['amount']))
#             if amount <= 0:
#                 raise ReceiptConfirmationException(
#                     detail="Amount must be greater than zero",
#                     context={'provided_amount': str(data['amount'])}
#                 )
#             if amount > Decimal('999999.99'):
#                 raise ReceiptConfirmationException(
#                     detail="Amount exceeds maximum allowed value",
#                     context={'provided_amount': str(data['amount']), 'max_amount': '999999.99'}
#                 )
#         except (ValueError, TypeError, InvalidOperation):
#             raise ReceiptConfirmationException(
#                 detail="Invalid amount format. Please provide a valid numeric value.",
#                 context={'provided_amount': str(data.get('amount', 'None'))}
#             )
        
#         # Validate date
#         if hasattr(data['date'], 'year'):
#             current_year = timezone.now().year
#             if data['date'].year < 2000 or data['date'].year > current_year:
#                 raise ReceiptConfirmationException(
#                     detail=f"Invalid date. Year must be between 2000 and {current_year}",
#                     context={'provided_date': data['date'].isoformat()}
#                 )
        
#         # Validate optional fields
#         if 'vendor' in data and data['vendor'] and len(str(data['vendor']).strip()) > 255:
#             raise ReceiptConfirmationException(
#                 detail="Vendor name is too long (maximum 255 characters)",
#                 context={'vendor_length': len(str(data['vendor']).strip())}
#             )
        
#         if 'description' in data and data['description'] and len(str(data['description']).strip()) > 1000:
#             raise ReceiptConfirmationException(
#                 detail="Description is too long (maximum 1000 characters)",
#                 context={'description_length': len(str(data['description']).strip())}
#             )
    
#     def _detect_user_corrections(self, receipt, confirmation_data: Dict, category) -> Dict[str, bool]:
#         """Detect what user corrected compared to AI suggestions"""
#         corrections = {
#             'amount': False,
#             'category': False,
#             'vendor': False,
#             'date': False
#         }
        
#         try:
#             # Amount correction
#             if receipt.extracted_amount and confirmation_data.get('amount'):
#                 corrections['amount'] = (receipt.extracted_amount != Decimal(str(confirmation_data['amount'])))
            
#             # Category correction
#             if receipt.suggested_category_id:
#                 corrections['category'] = (str(receipt.suggested_category_id) != str(category.id))
            
#             # Vendor correction
#             receipt_vendor = (receipt.extracted_vendor or '').strip()
#             confirmation_vendor = (confirmation_data.get('vendor', '') or '').strip()
#             corrections['vendor'] = receipt_vendor.lower() != confirmation_vendor.lower()
            
#             # Date correction
#             if receipt.extracted_date and confirmation_data.get('date'):
#                 corrections['date'] = (receipt.extracted_date != confirmation_data['date'])
            
#         except Exception as e:
#             logger.warning(f"Error detecting user corrections: {str(e)}")
        
#         return corrections



# receipt_service/services/receipt_service.py

from django.db import transaction
from django.utils import timezone
from typing import Dict, Any, Optional, List
from decimal import Decimal, InvalidOperation
import logging

from .receipt_model_service import model_service
from .file_service import FileService
from .quota_service import QuotaService
from .category_service import CategoryService
from ..utils.exceptions import (
    ReceiptNotFoundException,
    ReceiptAccessDeniedException,
    ReceiptNotProcessedException,
    ReceiptAlreadyConfirmedException,
    ReceiptProcessingInProgressException,
    ReceiptConfirmationException,
    CategoryNotFoundException,
    CategoryInactiveException,
    DatabaseOperationException,
    FileRetrievalException,
    MonthlyUploadLimitExceededException,
    FileUploadException,
    InvalidFileFormatException,
    FileSizeExceededException,
    DuplicateReceiptException,
    FileStorageException,
    LedgerEntryCreationException
)
from shared.utils.exceptions import ValidationException

logger = logging.getLogger(__name__)


class ReceiptService:
    """
    Receipt business logic service
    Queries AI processing results from ai_service models (no data duplication)
    """
    
    def __init__(self):
        self.file_service = FileService()
        self.quota_service = QuotaService()
        self.category_service = CategoryService()
    
    def get_receipt_status(self, receipt_id: str) -> str:
        """
        Get the current status of a receipt by id.
        
        Args:
            receipt_id: Receipt identifier (UUID string)
        
        Returns:
            Current status string of the receipt
            Returns None if receipt not found
        """
        try:
            receipt = model_service.receipt_model.objects.only('status').get(id=receipt_id)
            return receipt.status
        except model_service.receipt_model.DoesNotExist:
            logger.warning(f"Receipt {receipt_id} not found when fetching status")
            return None
        except Exception as e:
            logger.error(f"Error fetching receipt status for {receipt_id}: {str(e)}", exc_info=True)
            return None
        
    def upload_receipt(
        self, 
        user, 
        uploaded_file, 
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Upload receipt and queue AI processing
        """
        try:
            # Validate quota first (fail-fast)
            self.quota_service.validate_upload_allowed(user)
            
            receipt_id = None
            
            with transaction.atomic():
                # Store file and create receipt record
                result = self.file_service.store_receipt_file(user, uploaded_file, metadata)
                receipt_id = result['receipt_id']
                is_retry = result.get('is_retry', False)
            
            # Queue AI processing (outside transaction)
            processing_queued = False
            status = 'uploaded'
            
            try:
                self._queue_ai_processing_task(
                    receipt_id=str(receipt_id),
                    user_id=str(user.id)
                )
                processing_queued = True
                status = 'queued'
                
                logger.info(f"AI processing queued for receipt {receipt_id}")
                
            except Exception as e:
                logger.error(f"Failed to queue AI processing: {str(e)}", exc_info=True)
            
            return {
                'receipt_id': str(receipt_id),
                'status': status,
                'message': 'Receipt uploaded successfully',
                'processing_queued': processing_queued,
                'estimated_time': '30-45 seconds' if processing_queued else None
            }
            
        except (MonthlyUploadLimitExceededException, FileUploadException, 
                InvalidFileFormatException, FileSizeExceededException, 
                DuplicateReceiptException, FileStorageException):
            raise
        except Exception as e:
            logger.error(f"Receipt upload failed: {str(e)}", exc_info=True)
            raise FileUploadException(
                detail="Receipt upload failed",
                context={'user_id': str(user.id)}
            )
    
    def _queue_ai_processing_task(self, receipt_id: str, user_id: str):
        """Queue AI processing task"""
        try:
            from ai_service.tasks.ai_tasks import process_receipt_ai_task
            
            # Get receipt to get storage path
            receipt = model_service.receipt_model.objects.get(id=receipt_id)
            storage_path = receipt.file_path.name
            
            if not storage_path:
                raise ValueError(f"Receipt {receipt_id} has no storage path")
            
            # Queue task
            task = process_receipt_ai_task.delay(
                receipt_id=receipt_id,
                user_id=user_id,
                storage_path=storage_path
            )
            
            # Update receipt status to queued
            receipt.status = 'queued'
            receipt.processing_started_at = timezone.now()
            receipt.save(update_fields=['status', 'processing_started_at'])
            
            logger.info(f"AI task queued: {task.id} for receipt {receipt_id}")
            
        except Exception as e:
            logger.error(f"Failed to queue AI task: {str(e)}", exc_info=True)
            raise
    
    def get_processing_status(self, user, receipt_id: str) -> Dict[str, Any]:
        """
        Get AI processing status
        Queries ProcessingJob model from ai_service
        """
        try:
            receipt = model_service.receipt_model.objects.get(id=receipt_id)
            
            # Check access
            if receipt.user_id != user.id:
                raise ReceiptAccessDeniedException(
                    detail="Access denied",
                    context={'receipt_id': receipt_id}
                )
            
            # Get AI processing status
            try:
                from ai_service.services.ai_model_service import model_service as ai_model_service
                
                processing_job = ai_model_service.processing_job_model.objects.filter(
                    receipt_id=receipt_id,
                    user_id=user.id
                ).order_by('-created_at').first()
                
                if not processing_job:
                    return {
                        'receipt_id': receipt_id,
                        'status': 'pending',
                        'message': 'Processing not started yet'
                    }
                
                return {
                    'receipt_id': receipt_id,
                    'status': processing_job.status,
                    'current_stage': processing_job.current_stage,
                    'progress_percentage': processing_job.progress_percentage,
                    'started_at': processing_job.created_at.isoformat() if processing_job.created_at else None,
                    'completed_at': processing_job.completed_at.isoformat() if processing_job.completed_at else None,
                    'error_message': processing_job.error_message if processing_job.status == 'failed' else None,
                }
                
            except ImportError:
                # Fallback to receipt status
                return {
                    'receipt_id': receipt_id,
                    'status': receipt.status,
                    'message': self._get_status_message(receipt.status)
                }
                
        except model_service.receipt_model.DoesNotExist:
            raise ReceiptNotFoundException(
                detail="Receipt not found",
                context={'receipt_id': receipt_id}
            )
    
    def get_receipt_details(self, user, receipt_id: str) -> Dict[str, Any]:
        """
        Get comprehensive receipt details
        Queries AI results from ai_service models
        """
        try:
            receipt = model_service.receipt_model.objects.get(id=receipt_id)
            
            # Check access
            if receipt.user_id != user.id:
                raise ReceiptAccessDeniedException(
                    detail="Access denied",
                    context={'receipt_id': receipt_id}
                )
            
            # Base receipt info
            response = {
                'id': str(receipt.id),
                'original_filename': receipt.original_filename,
                'status': receipt.status,
                'file_size': receipt.file_size,
                'file_size_mb': round(receipt.file_size / (1024 * 1024), 2),
                'mime_type': receipt.mime_type,
                'upload_date': receipt.created_at.isoformat(),
                'processing_started_at': receipt.processing_started_at.isoformat() if receipt.processing_started_at else None,
                'processing_completed_at': receipt.processing_completed_at.isoformat() if receipt.processing_completed_at else None,
                'can_be_confirmed': receipt.can_be_confirmed,
            }
            
            # Get AI results if processed
            if receipt.status in ['processed', 'confirmed']:
                ai_results = self._get_ai_processing_results(receipt_id, user.id)
                if ai_results:
                    response.update(ai_results)
            
            # Add file URL
            try:
                response['file_url'] = self.file_service.get_secure_file_url(receipt)
            except FileRetrievalException:
                pass
            
            return response
            
        except model_service.receipt_model.DoesNotExist:
            raise ReceiptNotFoundException(
                detail="Receipt not found",
                context={'receipt_id': receipt_id}
            )
            
    
    def _get_ai_processing_results(self, receipt_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get AI processing results from ai_service models
        """
        try:
            from ai_service.services.ai_model_service import model_service
            logger.info(f"Looking for ProcessingJob: receipt_id={receipt_id}, user_id={user_id}")
            # Get the most recent processing job
            processing_job = model_service.processing_job_model.objects.filter(
                receipt_id=receipt_id,
                user_id=user_id
            ).order_by('-created_at').first()
            
            if not processing_job:
                logger.warning(f"No ProcessingJob found for receipt {receipt_id}")
                return None
            
            # ✅ Debug: Log job status
            logger.info(f"Found job: id={processing_job.id}, status={processing_job.status}, stage={processing_job.current_stage}")
            
            if processing_job.status != 'completed':
                logger.warning(f"Job not completed: status={processing_job.status}")
                return None
            
            duration_seconds = 0
            if processing_job.started_at and processing_job.completed_at:
                duration_seconds = (processing_job.completed_at - processing_job.started_at).total_seconds()

            result: Dict[str, Any] = {
                'processing_duration_seconds': round(duration_seconds, 2),
                'processing_progress': 100,
            }
            
            # Get OCR result (if exists)
            try:
                ocr_result = model_service.ocr_result_model.objects.get(processing_job=processing_job)
                result['ocr_data'] = {
                    'extracted_text': ocr_result.extracted_text,
                    'confidence_score': float(ocr_result.confidence_score),
                }
            except model_service.ocr_result_model.DoesNotExist:
                result['ocr_data'] = None
            
            # Get extracted data (if exists)
            try:
                extracted_data = model_service.extracted_data_model.objects.get(processing_job=processing_job)
                result['extracted_data'] = {
                    'vendor_name': extracted_data.vendor_name or 'Unknown',
                    'receipt_date': extracted_data.receipt_date.isoformat() if extracted_data.receipt_date else None,
                    'total_amount': float(extracted_data.total_amount) if extracted_data.total_amount else None,
                    'currency': extracted_data.currency or 'USD',
                    'tax_amount': float(extracted_data.tax_amount) if extracted_data.tax_amount else None,
                    'subtotal': float(extracted_data.subtotal) if extracted_data.subtotal else None,
                    'line_items': extracted_data.line_items or [],
                    'confidence_scores': extracted_data.confidence_scores or {
                        'vendor_name': 0.0,
                        'date': 0.0,
                        'amount': 0.0,
                        'overall': 0.0
                    },
                }
                logger.info(f"Found extracted_data: vendor={extracted_data.vendor_name}")
            except model_service.extracted_data_model.DoesNotExist:
                result['extracted_data'] = {
                    'vendor_name': 'Unknown',
                    'receipt_date': None,
                    'total_amount': None,
                    'currency': 'USD',
                    'tax_amount': None,
                    'subtotal': None,
                    'line_items': [],
                    'confidence_scores': {
                        'vendor_name': 0.0,
                        'date': 0.0,
                        'amount': 0.0,
                        'overall': 0.0
                    },
                }
            
            # Get category prediction (if exists)
            try:
                cat_pred = model_service.category_prediction_model.objects.get(processing_job=processing_job)
                
                # Get category details
                category = None
                if cat_pred.predicted_category_id:
                    try:
                        from receipt_service.services.receipt_import_service import service_import
                        category_service = service_import.category_service
                        category = category_service.get_category_by_id(cat_pred.predicted_category_id)
                    except:
                        pass
                
                result['ai_suggestion'] = {
                    'category': {
                        'id': str(category.id),
                        'name': category.name,
                        'icon': category.icon,
                        'color': category.color,
                    } if category else None,
                    'confidence_score': float(cat_pred.confidence_score),
                    'reasoning': cat_pred.reasoning or '',
                    'alternatives': cat_pred.alternative_predictions or [],
                }
            except model_service.category_prediction_model.DoesNotExist:
                result['ai_suggestion'] = None
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get AI results for receipt {receipt_id}: {str(e)}", exc_info=True)
            return None
    
    def update_processing_status(
        self,
        receipt_id: str,
        status: str,
        result: Dict = None
    ) -> None:
        """
        Update receipt processing status with immediate commit
        """
        try:
            # ✅ FIX: Use atomic to ensure transaction commits immediately
            with transaction.atomic():
                receipt = model_service.receipt_model.objects.select_for_update().get(id=receipt_id)
                
                # Check if already confirmed
                if receipt.status == 'confirmed':
                    logger.warning(f"Attempted to update confirmed receipt {receipt_id} to {status}")
                    return
                
                receipt.status = status
                
                if status == 'processing':
                    if not receipt.processing_started_at:
                        receipt.processing_started_at = timezone.now()
                elif status in ['processed', 'failed']:
                    receipt.processing_completed_at = timezone.now()
                
                receipt.save(update_fields=[
                    'status', 
                    'processing_started_at', 
                    'processing_completed_at', 
                    'updated_at'
                ])
            
            # ✅ Log AFTER transaction commits
            logger.info(f"Receipt {receipt_id} status updated to {status}")
            
            # ✅ FIX: Sync quota only when processed/confirmed
            if status in ['processed', 'confirmed']:
                try:
                    self.quota_service.sync_user_quota(str(receipt.user_id))
                except Exception as e:
                    logger.warning(f"Quota sync failed after processing: {str(e)}")
                    # Don't fail the status update if quota sync fails
            
        except model_service.receipt_model.DoesNotExist:
            logger.error(f"Receipt {receipt_id} not found for status update")
            raise ReceiptNotFoundException(
                detail="Receipt not found",
                context={'receipt_id': receipt_id}
            )
        except Exception as e:
            logger.error(f"Failed to update receipt status for {receipt_id}: {str(e)}")
            raise DatabaseOperationException(
                detail="Failed to update receipt status",
                context={'receipt_id': receipt_id, 'error': str(e)}
            )
    
    def confirm_receipt(
        self,
        user,
        receipt_id: str,
        confirmation_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Confirm receipt and create ledger entry"""
        try:
            # ✅ FIX: Wrap entire confirmation in transaction
            with transaction.atomic():
                receipt = model_service.receipt_model.objects.select_for_update().get(
                    id=receipt_id
                )
                
                # Check access
                if receipt.user_id != user.id:
                    raise ReceiptAccessDeniedException(
                        detail="Access denied",
                        context={'receipt_id': receipt_id}
                    )
                
                # Check if already confirmed (double-check with ledger)
                if hasattr(receipt, 'ledger_entry'):
                    raise ReceiptAlreadyConfirmedException(
                        detail="Receipt already has a ledger entry",
                        context={'receipt_id': receipt_id, 'ledger_id': str(receipt.ledger_entry.id)}
                    )
                
                # Validate can confirm
                self._validate_receipt_for_confirmation(receipt)
                
                # Get AI results for defaults
                ai_results = self._get_ai_processing_results(receipt_id, str(user.id))
                
                # Get category
                try:
                    category = model_service.category_model.objects.get(
                        id=confirmation_data['category_id']
                    )
                    
                    if not category.is_active:
                        raise CategoryInactiveException(
                            detail=f"Category '{category.name}' is inactive",
                            context={'category_id': str(category.id)}
                        )
                except model_service.category_model.DoesNotExist:
                    raise CategoryNotFoundException(
                        detail="Category not found",
                        context={'category_id': confirmation_data['category_id']}
                    )
                
                # Build ledger data with AI defaults
                ledger_data = self._build_ledger_data(
                    confirmation_data,
                    ai_results,
                    user,
                    receipt,
                    category
                )
                
                # Detect corrections
                corrections = self._detect_user_corrections(ai_results, ledger_data, category)
                
                # Create ledger entry
                try:
                    ledger_entry = model_service.ledger_entry_model.objects.create(
                        user=user,
                        receipt=receipt,
                        category=category,
                        date=ledger_data['date'],
                        vendor=ledger_data['vendor'],
                        amount=ledger_data['amount'],
                        currency=ledger_data['currency'],
                        description=ledger_data['description'],
                        tags=ledger_data['tags'],
                        user_corrected_amount=corrections['amount'],
                        user_corrected_category=corrections['category'],
                        user_corrected_vendor=corrections['vendor'],
                        user_corrected_date=corrections['date'],
                        is_business_expense=ledger_data['is_business_expense'],
                        is_reimbursable=ledger_data['is_reimbursable'],
                        created_from_ip=ledger_data['ip_address'],
                    )
                except Exception as e:
                    logger.error(f"Ledger entry creation failed: {str(e)}", exc_info=True)
                    raise LedgerEntryCreationException(
                        detail="Failed to create ledger entry",
                        context={'receipt_id': receipt_id, 'error': str(e)}
                    )
                
                # Update receipt status
                receipt.status = 'confirmed'
                receipt.save(update_fields=['status', 'updated_at'])
                
                # Update category usage
                try:
                    self.category_service.update_user_category_usage(user, category)
                except Exception as e:
                    logger.warning(f"Failed to update category usage: {str(e)}")
                
                # Sync quota after confirmation
                try:
                    self.quota_service.sync_user_quota(str(user.id))
                except Exception as e:
                    logger.warning(f"Quota sync failed after confirmation: {str(e)}")
                
                logger.info(f"Receipt confirmed: {receipt_id} -> Ledger: {ledger_entry.id}")
                
                return {
                    'ledger_entry_id': str(ledger_entry.id),
                    'receipt_id': str(receipt.id),
                    'message': 'Receipt confirmed successfully',
                    'accuracy_metrics': {
                        'corrections_made': corrections,
                        'was_ai_accurate': ledger_entry.was_ai_accurate,
                        'accuracy_score': ledger_entry.accuracy_score
                    }
                }
                
        except model_service.receipt_model.DoesNotExist:
            raise ReceiptNotFoundException(
                detail="Receipt not found",
                context={'receipt_id': receipt_id}
            )
        except (ReceiptAccessDeniedException, ReceiptAlreadyConfirmedException,
                ReceiptNotProcessedException, CategoryNotFoundException,
                CategoryInactiveException, LedgerEntryCreationException):
            raise
        except Exception as e:
            logger.error(f"Unexpected error confirming receipt {receipt_id}: {str(e)}")
            raise DatabaseOperationException(
                detail="Unexpected error during confirmation",
                context={'receipt_id': receipt_id, 'error': str(e)}
            )


    def _build_ledger_data(
        self,
        confirmation_data: Dict,
        ai_results: Dict,
        user,
        receipt,
        category
    ) -> Dict[str, Any]:
        """Build final ledger data with defaults from AI results"""
        
        # Extract AI data if available
        extracted_data = ai_results.get('extracted_data', {}) if ai_results else {}
        
        # Build ledger data - user confirmation takes precedence, AI as fallback
        return {
            'date': confirmation_data['date'],  # Required from user
            'vendor': confirmation_data.get('vendor', extracted_data.get('vendor_name', '')).strip(),
            'amount': Decimal(str(confirmation_data['amount'])),  # Required from user
            'currency': confirmation_data.get('currency', extracted_data.get('currency', 'USD')),
            'description': confirmation_data.get('description', '').strip(),
            'tags': confirmation_data.get('tags', []),
            'is_business_expense': confirmation_data.get('is_business_expense', False),
            'is_reimbursable': confirmation_data.get('is_reimbursable', False),
            'ip_address': confirmation_data.get('ip_address'),
        }
    
    def get_user_receipts(
        self, 
        user, 
        status: Optional[str] = None, 
        limit: int = 20, 
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get paginated list of user receipts"""
        try:
            queryset = model_service.receipt_model.objects.filter(
                user=user
            ).select_related('ledger_entry').order_by('-created_at')  # ← Optimize query
            
            if status:
                valid_statuses = ['uploaded', 'queued', 'processing', 'processed', 'confirmed', 'failed']
                if status not in valid_statuses:
                    raise ValidationException(
                        detail=f"Invalid status. Valid: {', '.join(valid_statuses)}",
                        context={'provided_status': status}
                    )
                queryset = queryset.filter(status=status)
            
            total_count = queryset.count()
            receipts = queryset[offset:offset + limit]
            
            # Get all receipt IDs for AI data lookup
            receipt_ids = [str(r.id) for r in receipts if r.status == 'processed']
            
            # Bulk fetch AI results for processed receipts
            ai_results_map = {}
            if receipt_ids:
                ai_results_map = self._get_bulk_ai_results(receipt_ids, str(user.id))
            
            # Build receipt list
            receipt_list = []
            for receipt in receipts:
                receipt_data = {
                    'id': str(receipt.id),
                    'original_filename': receipt.original_filename,
                    'status': receipt.status,
                    'upload_date': receipt.created_at.isoformat(),
                    'file_size_mb': round(receipt.file_size / (1024 * 1024), 2),
                    'can_be_confirmed': receipt.can_be_confirmed,
                    'amount': None,
                    'currency': None,
                    'vendor': None,
                    'date': None,
                    'category': None,
                }
                
                # Get data based on status
                if receipt.status == 'confirmed' and hasattr(receipt, 'ledger_entry'):
                    ledger = receipt.ledger_entry
                    receipt_data.update({
                        'amount': float(ledger.amount),
                        'currency': ledger.currency,
                        'vendor': ledger.vendor,
                        'date': ledger.date.isoformat(),
                        'category': {
                            'id': str(ledger.category.id),
                            'name': ledger.category.name,
                            'icon': ledger.category.icon,
                            'color': ledger.category.color,
                        },
                        'data_source': 'confirmed'
                    })
                    
                elif receipt.status == 'processed':
                    ai_results = ai_results_map.get(str(receipt.id))
                    if ai_results and 'extracted_data' in ai_results:
                        ed = ai_results['extracted_data']
                        receipt_data.update({
                            'amount': ed.get('total_amount'),
                            'currency': ed.get('currency'),
                            'vendor': ed.get('vendor_name'),
                            'date': ed.get('receipt_date'),
                            'data_source': 'ai_extracted'
                        })
                        
                        if 'ai_suggestion' in ai_results:
                            receipt_data['category'] = ai_results['ai_suggestion'].get('category')
                
                receipt_list.append(receipt_data)
            
            return {
                'receipts': receipt_list,
                'pagination': {
                    'total_count': total_count,
                    'limit': limit,
                    'offset': offset,
                    'has_more': (offset + limit) < total_count,
                    'current_page': (offset // limit) + 1,
                    'total_pages': (total_count + limit - 1) // limit
                }
            }
            
        except ValidationException:
            raise
        except Exception as e:
            logger.error(f"Failed to get receipts: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Failed to retrieve receipts",
                context={'user_id': str(user.id)}
            )
    
    def _get_bulk_ai_results(self, receipt_ids: List[str], user_id: str) -> Dict[str, Dict]:
        """Bulk fetch AI results for multiple receipts - optimized"""
        try:
            from ai_service.services.ai_model_service import model_service as ai_model_service
            
            # Get all processing jobs in one query
            jobs = ai_model_service.processing_job_model.objects.filter(
                receipt_id__in=receipt_ids,
                user_id=user_id,
                status='completed'
            ).order_by('receipt_id', '-created_at').distinct('receipt_id')
            
            # Bulk fetch extracted data
            extracted_data_list = ai_model_service.extracted_data_model.objects.filter(
                processing_job__in=jobs
            ).select_related('processing_job')
            
            results = {}
            for ed in extracted_data_list:
                receipt_id = str(ed.processing_job.receipt_id)
                results[receipt_id] = {
                    'extracted_data': {
                        'vendor_name': ed.vendor_name,
                        'receipt_date': ed.receipt_date.isoformat() if ed.receipt_date else None,
                        'total_amount': float(ed.total_amount) if ed.total_amount else None,
                        'currency': ed.currency,
                    }
                }
            
            return results
            
        except Exception as e:
            logger.warning(f"Failed to bulk fetch AI results: {str(e)}")
            return {}
    
    # Helper methods
    
    def _get_status_message(self, status: str) -> str:
        """Get user-friendly status message"""
        messages = {
            'uploaded': 'Uploaded',
            'queued': 'Queued for processing',
            'processing': 'Processing...',
            'processed': 'Ready for confirmation',
            'confirmed': 'Confirmed',
            'failed': 'Processing failed'
        }
        return messages.get(status, 'Unknown')
    
    def _validate_receipt_for_confirmation(self, receipt):
        """Validate receipt can be confirmed"""
        if receipt.status == 'confirmed':
            raise ReceiptAlreadyConfirmedException(
                detail="Receipt already confirmed",
                context={'receipt_id': str(receipt.id)}
            )
        
        if receipt.status in ['processing', 'queued']:
            raise ReceiptProcessingInProgressException(
                detail="Receipt is still processing",
                context={'receipt_id': str(receipt.id)}
            )
        
        if receipt.status != 'processed':
            raise ReceiptNotProcessedException(
                detail="Receipt must be processed first",
                context={'receipt_id': str(receipt.id), 'status': receipt.status}
            )
    
    def _validate_confirmation_data(self, data: Dict[str, Any]):
        """Validate confirmation data"""
        required = ['date', 'amount', 'category_id']
        
        missing = [f for f in required if f not in data or data[f] is None]
        if missing:
            raise ReceiptConfirmationException(
                detail=f"Missing fields: {', '.join(missing)}",
                context={'missing_fields': missing}
            )
        
        # Validate amount
        try:
            amount = Decimal(str(data['amount']))
            if amount <= 0:
                raise ReceiptConfirmationException(
                    detail="Amount must be positive",
                    context={'amount': str(data['amount'])}
                )
        except (ValueError, InvalidOperation):
            raise ReceiptConfirmationException(
                detail="Invalid amount format",
                context={'amount': str(data.get('amount'))}
            )
    
    def _detect_user_corrections(
        self, 
        ai_results: Dict, 
        ledger_data: Dict, 
        category
    ) -> Dict[str, bool]:
        """Detect user corrections vs AI suggestions"""
        corrections = {
            'amount': False,
            'category': False,
            'vendor': False,
            'date': False
        }
        
        if not ai_results:
            return corrections
        
        try:
            # Check extracted data
            if 'extracted_data' in ai_results:
                ed = ai_results['extracted_data']
                
                # Amount correction
                if ed.get('total_amount'):
                    ai_amount = Decimal(str(ed['total_amount']))
                    corrections['amount'] = ai_amount != ledger_data['amount']
                
                # Vendor correction
                ai_vendor = (ed.get('vendor_name') or '').strip().lower()
                user_vendor = ledger_data['vendor'].strip().lower()
                corrections['vendor'] = ai_vendor != user_vendor and ai_vendor != ''
                
                # Date correction
                if ed.get('receipt_date'):
                    from datetime import datetime
                    if isinstance(ed['receipt_date'], str):
                        ai_date = datetime.fromisoformat(ed['receipt_date']).date()
                    else:
                        ai_date = ed['receipt_date']
                    corrections['date'] = ai_date != ledger_data['date']
            
            # Check category correction
            if 'ai_suggestion' in ai_results and ai_results['ai_suggestion'].get('category'):
                ai_cat_id = ai_results['ai_suggestion']['category']['id']
                corrections['category'] = ai_cat_id != str(category.id)
                
        except Exception as e:
            logger.warning(f"Error detecting corrections: {str(e)}")
        
        return corrections