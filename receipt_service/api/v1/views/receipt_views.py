from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from shared.utils.responses import success_response, created_response
from ....services.receipt_import_service import service_import
from receipt_service.utils.exceptions import (
    FileUploadException,
    InvalidFileFormatException,
    FileSizeExceededException,
    DuplicateReceiptException,
    FileStorageException,
    MonthlyUploadLimitExceededException,
    ReceiptNotFoundException,
    ReceiptAccessDeniedException,
    ReceiptNotProcessedException,
    ReceiptAlreadyConfirmedException,
    ReceiptProcessingInProgressException,
    CategoryNotFoundException,
    CategoryInactiveException,
    QuotaCalculationException,
    ValidationException,
    DatabaseOperationException,
    ReceiptProcessingFailedException
)
from ..serializers.receipt_serializers import (
    ReceiptUploadSerializer,
    ReceiptDetailSerializer,
    ReceiptListSerializer,
    ReceiptConfirmSerializer,
    ReceiptStatusSerializer,
    UploadHistorySerializer
)
from rest_framework.response import Response
from ..serializers.ledger_serializers import QuotaStatusSerializer
import logging
from rest_framework import status, generics
from django.core.cache import cache
from ....utils.pagination import LargeResultSetPagination
from typing import Optional


logger = logging.getLogger(__name__)


class ReceiptUploadView(APIView):
    """Handle receipt file uploads with comprehensive validation"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        """Upload receipt file"""
        try:
            # Validate upload data
            serializer = ReceiptUploadSerializer(data=request.data)
            if not serializer.is_valid():
                raise ValidationException(
                    detail="Invalid upload data",
                    context=serializer.errors
                )
            
            uploaded_file = serializer.validated_data['file']
            
            # Prepare metadata
            metadata = {
                'ip_address': request.META.get('REMOTE_ADDR'),
            }
            
            # Upload receipt
            receipt_service = service_import.receipt_service
            result = receipt_service.upload_receipt(request.user, uploaded_file, metadata)
            
            return created_response(
                message=result['message'],
                data={
                    'receipt_id': result['receipt_id'],
                    'status': result['status'],
                    'processing_queued': result.get('processing_queued', False),
                    'estimated_time': result.get('estimated_time'),
                    'next_steps': {
                        'check_status': f"/receipts/v1/upload-status/{result['receipt_id']}/",
                        'view_details': f"/receipts/v1/{result['receipt_id']}/"
                    }
                }
            )
        
        except (MonthlyUploadLimitExceededException, FileUploadException, 
                InvalidFileFormatException, FileSizeExceededException, 
                DuplicateReceiptException, FileStorageException, ValidationException):
            raise
        except Exception as e:
            logger.error(f"Unexpected error in receipt upload: {str(e)}", exc_info=True)
            raise FileUploadException(
                detail="An unexpected error occurred during file upload",
                context={'error': str(e)}
            )


class ReceiptUploadStatusView(APIView):
    """Check receipt processing status"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, upload_id):
        """Get receipt processing status"""
        try:
            receipt_service = service_import.receipt_service
            status_data = receipt_service.get_processing_status(request.user, upload_id)
            
            # Use serializer for consistent formatting
            serializer = ReceiptStatusSerializer(status_data)
            
            return success_response(
                message="Processing status retrieved successfully",
                data=serializer.data
            )
            
        except (ReceiptNotFoundException, ReceiptAccessDeniedException):
            raise
        except DatabaseOperationException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting upload status: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Failed to retrieve processing status",
                context={'upload_id': upload_id}
            )


class ReceiptExtractedDataView(APIView):
    """Get extracted data from AI processing"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, receipt_id):
        """Get extracted data for a receipt"""
        try:

            # ✅ FIX: Check receipt access and status first
            receipt_service = service_import.receipt_service
            receipt = receipt_service.get_receipt_details(request.user, receipt_id)
            
            # Only allow access if receipt is processed or confirmed
            if receipt['status'] not in ['processed', 'confirmed']:
                raise ReceiptNotProcessedException(
                    detail=f"Receipt must be processed to view extracted data. Current status: {receipt['status']}",
                    context={'receipt_id': receipt_id, 'current_status': receipt['status']}
                )
            
            from ai_service.services.ai_model_service import model_service as ai_model_service
            
            # Get latest processing job
            processing_job = ai_model_service.processing_job_model.objects.filter(
                receipt_id=receipt_id,
                user_id=request.user.id
            ).order_by('-created_at').first()
            
            if not processing_job:
                # No processing job exists yet
                return success_response(
                    message="Receipt is queued for AI processing",
                    data={
                        'receipt_id': str(receipt_id),
                        'status': 'pending',
                        'message': 'AI processing has not started yet. Check back in a moment.'
                    },
                    status_code=status.HTTP_202_ACCEPTED
                )
            
            # Check processing job status
            if processing_job.status == 'queued':
                return success_response(
                    message="Receipt is queued for processing",
                    data={
                        'receipt_id': str(receipt_id),
                        'status': 'queued',
                        'message': 'Receipt is in the processing queue'
                    },
                    status_code=status.HTTP_202_ACCEPTED
                )
            
            if processing_job.status == 'processing':
                return success_response(
                    message="Receipt is being processed",
                    data={
                        'receipt_id': str(receipt_id),
                        'status': 'processing',
                        'progress': processing_job.progress_percentage,
                        'current_stage': processing_job.current_stage,
                        'message': f'Processing: {processing_job.current_stage}'
                    },
                    status_code=status.HTTP_202_ACCEPTED
                )
            
            if processing_job.status == 'failed':
                raise ReceiptProcessingFailedException(
                    detail="AI processing failed",
                    context={
                        'receipt_id': str(receipt_id),
                        'error_message': processing_job.error_message,
                        'failed_stage': processing_job.error_stage,
                        'retry_count': processing_job.retry_count
                    }
                )
            
            # Status must be 'completed'
            if processing_job.status != 'completed':
                raise ReceiptNotProcessedException(
                    detail=f"Unexpected processing status: {processing_job.status}",
                    context={'receipt_id': str(receipt_id)}
                )
            
            # Get extracted data
            extracted_data = ai_model_service.extracted_data_model.objects.filter(
                processing_job=processing_job
            ).first()
            
            if not extracted_data:
                raise ReceiptNotProcessedException(
                    detail="No extracted data available",
                    context={'receipt_id': str(receipt_id)}
                )
            
            # Get OCR result
            ocr_result = ai_model_service.ocr_result_model.objects.filter(
                processing_job=processing_job
            ).first()
            
            # Get category prediction
            category_prediction = ai_model_service.category_prediction_model.objects.filter(
                processing_job=processing_job
            ).first()
            
            # Build response
            response_data = {
                'receipt_id': str(receipt_id),
                'processing_job_id': str(processing_job.id),
                'status': 'completed',
                'processed_at': processing_job.completed_at.isoformat() if processing_job.completed_at else None,
                'extracted_data': {
                    'vendor_name': extracted_data.vendor_name or 'Unknown',
                    'receipt_date': extracted_data.receipt_date.isoformat() if extracted_data.receipt_date else None,
                    'total_amount': float(extracted_data.total_amount) if extracted_data.total_amount else None,
                    'currency': extracted_data.currency,
                    'tax_amount': float(extracted_data.tax_amount) if extracted_data.tax_amount else None,
                    'subtotal': float(extracted_data.subtotal) if extracted_data.subtotal else None,
                    'line_items': extracted_data.line_items or []
                },
                'confidence_scores': extracted_data.confidence_scores or {},
            }
            
            # Add OCR data if available
            if ocr_result:
                response_data['ocr_data'] = {
                    'text': ocr_result.extracted_text,
                    'confidence': float(ocr_result.confidence_score)
                }
            
            # Add category if available
            if category_prediction and category_prediction.predicted_category_id:
                # Get category details
                from receipt_service.services.category_service import CategoryService
                category_service = CategoryService()
                
                try:
                    category = category_service.get_category_by_id(
                        str(category_prediction.predicted_category_id),
                        check_active=False
                    )
                    response_data['predicted_category'] = {
                        'category_id': str(category_prediction.predicted_category_id),
                        'category_name': category.name,
                        'category_slug': category.slug,
                        'category_icon': category.icon,
                        'category_color': category.color,
                        'confidence': float(category_prediction.confidence_score),
                        'reasoning': category_prediction.reasoning,
                        'alternatives': category_prediction.alternative_predictions or [],
                    }
                except Exception as e:
                    logger.warning(f"Failed to get category details: {str(e)}")
                    response_data['predicted_category'] = {
                        'category_id': str(category_prediction.predicted_category_id),
                        'confidence': float(category_prediction.confidence_score),
                        'reasoning': category_prediction.reasoning,
                    }
            
            
            return success_response(
                message="Extracted data retrieved successfully",
                data=response_data
            )
                
        except (ReceiptNotFoundException, ReceiptNotProcessedException, 
                ReceiptProcessingFailedException):
            raise
        except Exception as e:
            logger.error(f"Error retrieving extracted data: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Failed to retrieve extracted data",
                context={'receipt_id': str(receipt_id)}
            )

class ReceiptDetailView(APIView):
    """Get receipt details and processing status"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, receipt_id):
        """Get receipt details with AI results"""
        try:
            receipt_service = service_import.receipt_service
            
            # Get receipt details (includes AI results if processed)
            receipt_data = receipt_service.get_receipt_details(request.user, receipt_id)
            
            # Serialize directly - receipt_data is already a dict!
            serializer = ReceiptDetailSerializer(receipt_data)
            
            return success_response(
                message="Receipt details retrieved successfully",
                data=serializer.data
            )
            
        except (ReceiptNotFoundException, ReceiptAccessDeniedException):
            raise
        except Exception as e:
            logger.error(f"Error retrieving receipt details: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Failed to retrieve receipt details",
                context={'receipt_id': receipt_id}
            )

class ReceiptConfirmView(APIView):
    """Confirm receipt data and create ledger entry"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request, receipt_id):
        """Confirm receipt data and create ledger entry"""
        try:
            serializer = ReceiptConfirmSerializer(
                data=request.data,
                context={
                    'request': request,
                    'receipt_id': receipt_id
                }
            )
            if not serializer.is_valid():
                raise ValidationException(
                    detail="Invalid confirmation data",
                    context=serializer.errors
                )
            
            confirmation_data = serializer.validated_data.copy()
            confirmation_data['ip_address'] = request.META.get('REMOTE_ADDR')
            
            receipt_service = service_import.receipt_service
            result = receipt_service.confirm_receipt(
                request.user, 
                receipt_id, 
                confirmation_data
            )
            
            return created_response(
                message=result['message'],
                data={
                    'ledger_entry_id': result['ledger_entry_id'],
                    'receipt_id': result['receipt_id'],
                    'accuracy_metrics': result['accuracy_metrics'],  # ← Now includes proper metrics
                    'next_steps': {
                        'view_entry': f"/ledger/v1//entries/{result['ledger_entry_id']}/",
                        'view_summary': "/ledger/v1//summary/"
                    }
                }
            )
            
        except (ReceiptNotFoundException, ReceiptAccessDeniedException, 
                ReceiptNotProcessedException, ReceiptAlreadyConfirmedException, 
                ReceiptProcessingInProgressException, CategoryNotFoundException, 
                CategoryInactiveException, ValidationException):
            raise
        except DatabaseOperationException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error confirming receipt: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Unexpected error during confirmation",
                context={'receipt_id': receipt_id}
            )

# receipt_service/api/v1/views/receipt_views.py

class ReceiptListView(generics.ListAPIView):
    """Get paginated list of user receipts"""
    permission_classes = [IsAuthenticated]
    serializer_class = ReceiptListSerializer
    pagination_class = LargeResultSetPagination  # ✅ Use non-cached pagination
    
    def list(self, request, *args, **kwargs):
        """List receipts with filters"""
        try:
            # Parse and validate filters
            status_filter = self._validate_status_filter(request.GET.get('status'))
            ordering = self._validate_ordering(request.GET.get('ordering', '-created_at'))
            
            # Get queryset
            queryset = self.filter_queryset(self.get_queryset())
            
            # Paginate
            page = self.paginate_queryset(queryset)
            
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                
                # Get paginated response (includes count, next, previous, results)
                paginated_response = self.get_paginated_response(serializer.data)
                
                # Add custom metadata to response
                response_data = paginated_response.data
                response_data['filters'] = {
                    'status': status_filter,
                    'ordering': ordering
                }
                response_data['available_actions'] = {
                    'upload_new': '/receipts/v1/upload/',
                    'check_quota': '/api/v1/user/quota-status/'
                }
                
                return Response(response_data, status=status.HTTP_200_OK)
            
            # No pagination (fallback - shouldn't happen with pagination_class set)
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except ValidationException:
            raise
        except Exception as e:
            logger.error(f"Receipt list failed: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Failed to retrieve receipts"
            )
    
    def get_queryset(self):
        """Get filtered and ordered queryset"""
        from ....services.receipt_model_service import model_service
        
        queryset = model_service.receipt_model.objects.filter(
            user=self.request.user
        ).select_related('ledger_entry__category')
        
        # Apply status filter
        status_filter = self.request.GET.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Apply ordering
        ordering = self._validate_ordering(
            self.request.GET.get('ordering', '-created_at')
        )
        queryset = queryset.order_by(ordering)
        
        return queryset
    
    def _validate_status_filter(self, status: Optional[str]) -> Optional[str]:
        """Validate status filter parameter"""
        if not status:
            return None
        
        valid_statuses = [
            'uploaded', 'queued', 'processing', 'processed', 
            'confirmed', 'failed', 'cancelled'
        ]
        
        if status not in valid_statuses:
            raise ValidationException(
                detail=f"Invalid status filter. Valid: {', '.join(valid_statuses)}",
                context={'provided_status': status}
            )
        
        return status
    
    def _validate_ordering(self, ordering: str) -> str:
        """Validate ordering parameter"""
        valid_orderings = [
            'created_at', '-created_at', 
            'updated_at', '-updated_at',
            'total_amount', '-total_amount'
        ]
        
        if ordering not in valid_orderings:
            logger.warning(f"Invalid ordering '{ordering}', using default '-created_at'")
            return '-created_at'
        
        return ordering

class UserQuotaStatusView(APIView):
    """Get user's quota status"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get current quota status"""
        try:
            quota_service = service_import.quota_service
            quota_status = quota_service.check_upload_quota(request.user)
            
            serializer = QuotaStatusSerializer(quota_status)
            
            return success_response(
                message="Quota status retrieved successfully",
                data=serializer.data
            )
            
        except QuotaCalculationException as e:
            raise e
        except Exception as e:
            logger.error(f"Unexpected error getting quota status: {str(e)}")
            raise QuotaCalculationException(
                detail="Failed to retrieve quota status"
            )


class UserUploadHistoryView(APIView):
    """Get user's upload history"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get monthly upload history"""
        try:
            # Validate months parameter
            months = int(request.GET.get('months', 12))
            if months < 1 or months > 24:
                raise ValidationException(
                    detail="Months parameter must be between 1 and 24",
                    context={'provided_months': months, 'valid_range': '1-24'}
                )
            
            # Get history from quota service
            quota_service = service_import.quota_service
            history_data = quota_service.get_quota_history(request.user, months=months)
            
            # history_data structure depends on your service implementation
            # Check if it returns a dict with 'history' and 'summary' keys
            # OR if it returns a list directly
            
            if isinstance(history_data, dict):
                # If service returns {'history': [...], 'summary': {...}}
                monthly_stats = history_data.get('history', [])
                summary = history_data.get('summary', {})
            elif isinstance(history_data, list):
                # If service returns a list directly
                monthly_stats = history_data
                summary = self._calculate_summary(monthly_stats)
            else:
                # Fallback - empty data
                monthly_stats = []
                summary = {}
            
            # Serialize
            serializer = UploadHistorySerializer(monthly_stats, many=True)
            
            return success_response(
                message="Upload history retrieved successfully",
                data={
                    'monthly_stats': serializer.data,
                    'summary': summary,
                    'period_months': months
                }
            )
            
        except ValidationException:
            raise
        except QuotaCalculationException:
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error getting upload history: {str(e)}", 
                exc_info=True
            )
            raise QuotaCalculationException(
                detail="Failed to retrieve upload history",
                context={'error': str(e)}
            )
    
    def _calculate_summary(self, monthly_stats: list) -> dict:
        """Calculate summary from monthly stats if not provided by service"""
        total_uploads = sum(stat.get('upload_count', 0) for stat in monthly_stats)
        total_confirmed = sum(stat.get('confirmed_count', 0) for stat in monthly_stats)
        total_failed = sum(stat.get('failed_count', 0) for stat in monthly_stats)
        
        from decimal import Decimal
        total_amount = sum(
            Decimal(str(stat.get('total_amount', 0))) 
            for stat in monthly_stats
        )
        
        return {
            'total_uploads': total_uploads,
            'total_confirmed': total_confirmed,
            'total_failed': total_failed,
            'total_amount': float(total_amount),
            'average_monthly_uploads': round(total_uploads / len(monthly_stats), 1) if monthly_stats else 0,
            'success_rate': round((total_confirmed / total_uploads * 100), 1) if total_uploads > 0 else 0
        }
