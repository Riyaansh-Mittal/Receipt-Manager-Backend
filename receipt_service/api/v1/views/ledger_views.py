from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.http import HttpResponse, FileResponse
from rest_framework import generics, status
import uuid
from datetime import datetime
from django.db import transaction
from shared.utils.responses import success_response
from ....utils.pagination import CachedPagination
from ....services.receipt_import_service import service_import
from ....services.receipt_model_service import model_service
from receipt_service.utils.exceptions import (
    LedgerEntryNotFoundException,
    LedgerEntryUpdateException,
    DatabaseOperationException,
    ValidationException,
    BusinessLogicException
)
from ..serializers.ledger_serializers import (
    LedgerEntrySerializer,
    LedgerEntryDetailSerializer,
    LedgerEntryUpdateSerializer,
    LedgerSummarySerializer,
)
import logging
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError
import os


logger = logging.getLogger(__name__)


# receipt_service/api/v1/views/ledger_views.py

class LedgerEntryListView(generics.ListAPIView):
    """
    Get paginated list of ledger entries
    Direct database access - no service layer needed for simple queries
    """
    permission_classes = [IsAuthenticated]
    serializer_class = LedgerEntrySerializer
    pagination_class = CachedPagination
    
    def get_queryset(self):
        """
        Get filtered queryset directly
        DRF handles pagination, serialization, caching
        """
        # Base queryset with optimizations
        queryset = model_service.ledger_entry_model.objects.filter(
            user=self.request.user
        ).select_related('category', 'receipt').order_by('-date', '-created_at')
        
        # Apply filters directly
        queryset = self._apply_filters(queryset)
        
        return queryset
    
    def _apply_filters(self, queryset):
        """Apply filters from query parameters"""
        params = self.request.query_params
        
        # Date filters
        if params.get('start_date'):
            try:
                start_date = datetime.fromisoformat(params['start_date']).date()
                queryset = queryset.filter(date__gte=start_date)
            except ValueError:
                raise ValidationException(detail="Invalid start_date format. Use YYYY-MM-DD")
        
        if params.get('end_date'):
            try:
                end_date = datetime.fromisoformat(params['end_date']).date()
                queryset = queryset.filter(date__lte=end_date)
            except ValueError:
                raise ValidationException(detail="Invalid end_date format. Use YYYY-MM-DD")
        
        # Amount filters
        if params.get('min_amount'):
            try:
                min_amt = float(params['min_amount'])
                if min_amt < 0:
                    raise ValidationException(detail="Minimum amount cannot be negative")
                queryset = queryset.filter(amount__gte=min_amt)
            except ValueError:
                raise ValidationException(detail="Invalid min_amount format")
        
        if params.get('max_amount'):
            try:
                max_amt = float(params['max_amount'])
                if max_amt < 0:
                    raise ValidationException(detail="Maximum amount cannot be negative")
                queryset = queryset.filter(amount__lte=max_amt)
            except ValueError:
                raise ValidationException(detail="Invalid max_amount format")
        
        # Category filter
        if params.get('category_id'):
            try:
                uuid.UUID(params['category_id'])
                queryset = queryset.filter(category_id=params['category_id'])
            except ValueError:
                raise ValidationException(detail="Invalid category ID format")
        
        # Vendor search
        if params.get('vendor_search'):
            vendor = params['vendor_search'].strip()
            if len(vendor) >= 2:
                queryset = queryset.filter(vendor__icontains=vendor)
            else:
                raise ValidationException(detail="Vendor search term must be at least 2 characters")
        
        # Boolean filters
        if params.get('is_business_expense') is not None:
            queryset = queryset.filter(
                is_business_expense=(params['is_business_expense'].lower() == 'true')
            )
        
        if params.get('is_reimbursable') is not None:
            queryset = queryset.filter(
                is_reimbursable=(params['is_reimbursable'].lower() == 'true')
            )
        
        return queryset

class LedgerEntryDetailView(generics.RetrieveUpdateAPIView):
    """
    Get or update single ledger entry
    DELETE is not allowed - use cancel confirmation endpoint
    """
    permission_classes = [IsAuthenticated]
    serializer_class = LedgerEntryDetailSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'entry_id'
    
    def get_queryset(self):
        """Get queryset filtered by current user"""
        return model_service.ledger_entry_model.objects.filter(
            user=self.request.user
        ).select_related('category', 'receipt')
    
    def get_serializer_class(self):
        """Use different serializer for update"""
        if self.request.method in ['PUT', 'PATCH']:
            return LedgerEntryUpdateSerializer
        return LedgerEntryDetailSerializer
    
    def update(self, request, *args, **kwargs):
        """
        Override update to add business rules and proper exception handling
        """
        try:
            # ✅ FIX: Use select_for_update and transaction.atomic
            with transaction.atomic():
                # Get the instance with row-level lock
                instance = model_service.ledger_entry_model.objects.select_for_update().get(
                    id=kwargs['entry_id'],
                    user=request.user
                )
                
                # Business rule: Check 30-day update window
                entry_age = timezone.now() - instance.created_at
                if entry_age.days > 30:
                    raise BusinessLogicException(
                        detail="Ledger entry cannot be updated after 30 days",
                        context={
                            'created_at': instance.created_at.isoformat(),
                            'days_old': entry_age.days,
                            'max_days': 30
                        }
                    )
                
                # Get update serializer
                serializer = self.get_serializer(
                    instance,
                    data=request.data,
                    partial=kwargs.get('partial', False)
                )
                
                # Validate
                try:
                    serializer.is_valid(raise_exception=True)
                except DRFValidationError as e:
                    raise ValidationException(
                        detail="Invalid update data",
                        context={'validation_errors': e.detail}
                    )
                
                # Perform update
                serializer.save()
                
                # Log success
                logger.info(
                    f"Ledger entry {instance.id} updated by user {request.user.id}: "
                    f"fields={list(serializer.validated_data.keys())}"
                )
                
                # Return detailed response
                detail_serializer = LedgerEntryDetailSerializer(instance)
                return success_response(
                    message="Ledger entry updated successfully",
                    data={
                        'entry': detail_serializer.data,
                        'updated_fields': list(serializer.validated_data.keys()),
                        'restrictions': {
                            'immutable_fields': ['amount', 'date', 'currency', 'receipt'],
                            'reason': 'Financial and audit integrity'
                        }
                    }
                )
                
        except model_service.ledger_entry_model.DoesNotExist:
            raise LedgerEntryNotFoundException(
                detail="Ledger entry not found",
                context={'entry_id': kwargs.get('entry_id')}
            )
        except (ValidationException, BusinessLogicException, LedgerEntryNotFoundException):
            # Re-raise known exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error updating ledger entry: {str(e)}", exc_info=True)
            raise LedgerEntryUpdateException(
                detail="Failed to update ledger entry",
                context={'error': str(e)}
            )

class LedgerSummaryView(APIView):
    """Get spending summary for different time periods"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get spending summary"""
        try:
            period = request.GET.get('period', 'monthly')
            
            if period not in ['monthly', 'yearly', 'weekly']:
                raise ValidationException(
                    detail="Invalid period. Valid options: monthly, yearly, weekly",
                    context={'provided_period': period, 'valid_periods': ['monthly', 'yearly', 'weekly']}
                )
            
            ledger_service = service_import.ledger_service
            summary = ledger_service.get_spending_summary(request.user, period=period)
            
            # Use serializer for consistent formatting
            serializer = LedgerSummarySerializer(summary)
            
            return success_response(
                message=f"Spending summary for {period} period retrieved successfully",
                data=serializer.data
            )
            
        except ValidationException as e:
            raise e
        except DatabaseOperationException as e:
            raise e
        except Exception as e:
            logger.error(f"Unexpected error getting spending summary: {str(e)}")
            raise DatabaseOperationException(
                detail="Failed to calculate spending summary"
            )


class LedgerExportView(APIView):
    """
    Export ledger entries using same filters as list view
    Handles sync/async routing based on data size
    """
    permission_classes = [IsAuthenticated]
    
    SYNC_EXPORT_THRESHOLD = 5000
    MAX_EXPORT_RECORDS = 100000
    
    def get(self, request):
        """
        Export ledger entries with query parameters
        No request body needed - uses GET query params
        """
        try:
            # Step 1: Parse and validate filters
            try:
                filters = self._parse_and_validate_filters(request.query_params)
            except ValidationException:
                raise  # Re-raise custom exceptions
            except Exception as e:
                logger.error(f"Filter parsing failed: {str(e)}", exc_info=True)
                raise ValidationException(
                    detail="Invalid filter parameters",
                    context={'error': str(e)}
                )
            
            # Step 2: Validate format
            format_type = request.query_params.get('format', 'csv').lower()
            if format_type not in ['csv', 'json']:
                raise ValidationException(
                    detail="Invalid format type",
                    context={
                        'provided': format_type,
                        'valid_formats': ['csv', 'json']
                    }
                )
            
            # Step 3: Build queryset with error handling
            try:
                queryset = self._build_queryset(request.user, filters)
            except Exception as e:
                logger.error(f"Queryset build failed: {str(e)}", exc_info=True)
                raise DatabaseOperationException(
                    detail="Failed to query ledger entries",
                    context={'error': str(e)}
                )
            
            # Step 4: Get count with error handling
            try:
                total_count = queryset.count()
            except Exception as e:
                logger.error(f"Count query failed: {str(e)}", exc_info=True)
                raise DatabaseOperationException(
                    detail="Failed to count ledger entries",
                    context={'error': str(e)}
                )
            
            # Step 5: Handle empty result
            if total_count == 0:
                return success_response(
                    message="No entries found matching filters",
                    data={
                        'total_entries': 0,
                        'filters_applied': filters,
                        'suggestion': 'Try adjusting your filters'
                    }
                )
            
            # Step 6: Check maximum limit
            if total_count > self.MAX_EXPORT_RECORDS:
                raise BusinessLogicException(
                    detail="Export size exceeds maximum limit",
                    context={
                        'found_records': total_count,
                        'max_allowed': self.MAX_EXPORT_RECORDS,
                        'suggestion': 'Use more restrictive date range filters'
                    }
                )
            
            # Step 7: Route based on size
            try:
                if total_count <= self.SYNC_EXPORT_THRESHOLD:
                    logger.info(
                        f"Sync export: {total_count} records for user {request.user.id}"
                    )
                    return self._export_sync(queryset, format_type, filters)
                else:
                    logger.info(
                        f"Async export: {total_count} records for user {request.user.id}"
                    )
                    return self._export_async(
                        queryset, format_type, filters, request.user, total_count
                    )
            except (ValidationException, BusinessLogicException, DatabaseOperationException):
                raise  # Re-raise known exceptions
            except Exception as e:
                logger.error(f"Export routing failed: {str(e)}", exc_info=True)
                raise DatabaseOperationException(
                    detail="Export processing failed",
                    context={'error': str(e)}
                )
        
        # Catch-all for unexpected errors
        except (ValidationException, BusinessLogicException, DatabaseOperationException):
            raise  # Re-raise custom exceptions properly
        except Exception as e:
            logger.error(f"Unexpected export error: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Export service temporarily unavailable",
                context={
                    'error': str(e),
                    'suggestion': 'Please try again or contact support'
                }
            )
    
    def _parse_and_validate_filters(self, query_params):
        """Parse and validate filters with comprehensive error handling"""
        from datetime import datetime
        import uuid
        
        filters = {}
        
        # Date filters with validation
        if query_params.get('start_date'):
            try:
                filters['start_date'] = datetime.fromisoformat(
                    query_params['start_date']
                ).date()
            except ValueError as e:
                raise ValidationException(
                    detail="Invalid start_date format",
                    context={
                        'provided': query_params['start_date'],
                        'expected_format': 'YYYY-MM-DD',
                        'example': '2025-01-01'
                    }
                )
        
        if query_params.get('end_date'):
            try:
                filters['end_date'] = datetime.fromisoformat(
                    query_params['end_date']
                ).date()
            except ValueError:
                raise ValidationException(
                    detail="Invalid end_date format",
                    context={
                        'provided': query_params['end_date'],
                        'expected_format': 'YYYY-MM-DD'
                    }
                )
        
        # Amount filters with validation
        if query_params.get('min_amount'):
            try:
                min_amt = float(query_params['min_amount'])
                if min_amt < 0:
                    raise ValidationException(
                        detail="Minimum amount cannot be negative",
                        context={'provided': min_amt}
                    )
                filters['min_amount'] = min_amt
            except (ValueError, TypeError) as e:
                raise ValidationException(
                    detail="Invalid min_amount format",
                    context={
                        'provided': query_params['min_amount'],
                        'expected': 'Positive decimal number'
                    }
                )
        
        if query_params.get('max_amount'):
            try:
                max_amt = float(query_params['max_amount'])
                if max_amt < 0:
                    raise ValidationException(
                        detail="Maximum amount cannot be negative"
                    )
                filters['max_amount'] = max_amt
            except (ValueError, TypeError):
                raise ValidationException(
                    detail="Invalid max_amount format",
                    context={
                        'provided': query_params['max_amount'],
                        'expected': 'Positive decimal number'
                    }
                )
        
        # Category filter with validation
        if query_params.get('category_id'):
            try:
                category_id = uuid.UUID(query_params['category_id'])
                filters['category_id'] = str(category_id)
            except (ValueError, TypeError):
                raise ValidationException(
                    detail="Invalid category ID format",
                    context={
                        'provided': query_params['category_id'],
                        'expected': 'Valid UUID'
                    }
                )
        
        # Vendor search with validation
        if query_params.get('vendor_search'):
            vendor = query_params['vendor_search'].strip()
            if len(vendor) < 2:
                raise ValidationException(
                    detail="Vendor search term too short",
                    context={
                        'provided_length': len(vendor),
                        'minimum_length': 2
                    }
                )
            filters['vendor_search'] = vendor
        
        # Boolean filters
        if query_params.get('is_business_expense') is not None:
            filters['is_business_expense'] = (
                query_params['is_business_expense'].lower() == 'true'
            )
        
        if query_params.get('is_reimbursable') is not None:
            filters['is_reimbursable'] = (
                query_params['is_reimbursable'].lower() == 'true'
            )
        
        # Currency filter with validation
        if query_params.get('currency'):
            from ....utils.currency_utils import currency_manager
            currency = query_params['currency'].upper()
            
            if not currency_manager.is_valid_currency(currency):
                raise ValidationException(
                    detail="Invalid currency code",
                    context={
                        'provided': currency,
                        'valid_currencies': currency_manager.get_currency_codes()[:10]  # Show sample
                    }
                )
            filters['currency'] = currency
        
        # Cross-field validation
        if filters.get('start_date') and filters.get('end_date'):
            if filters['start_date'] > filters['end_date']:
                raise ValidationException(
                    detail="Start date must be before end date",
                    context={
                        'start_date': filters['start_date'].isoformat(),
                        'end_date': filters['end_date'].isoformat()
                    }
                )
        
        if filters.get('min_amount') and filters.get('max_amount'):
            if filters['min_amount'] > filters['max_amount']:
                raise ValidationException(
                    detail="Minimum amount must be less than maximum amount",
                    context={
                        'min_amount': filters['min_amount'],
                        'max_amount': filters['max_amount']
                    }
                )
        
        return filters
    
    def _build_queryset(self, user, filters):
        """Build queryset with filters - raises exceptions on failure"""
        try:
            queryset = model_service.ledger_entry_model.objects.filter(
                user=user
            ).select_related('category', 'receipt').order_by('-date', '-created_at')
            
            # Apply filters
            if filters.get('start_date'):
                queryset = queryset.filter(date__gte=filters['start_date'])
            
            if filters.get('end_date'):
                queryset = queryset.filter(date__lte=filters['end_date'])
            
            if filters.get('min_amount'):
                queryset = queryset.filter(amount__gte=filters['min_amount'])
            
            if filters.get('max_amount'):
                queryset = queryset.filter(amount__lte=filters['max_amount'])
            
            if filters.get('category_id'):
                queryset = queryset.filter(category_id=filters['category_id'])
            
            if filters.get('vendor_search'):
                queryset = queryset.filter(vendor__icontains=filters['vendor_search'])
            
            if 'is_business_expense' in filters:
                queryset = queryset.filter(
                    is_business_expense=filters['is_business_expense']
                )
            
            if 'is_reimbursable' in filters:
                queryset = queryset.filter(is_reimbursable=filters['is_reimbursable'])
            
            if filters.get('currency'):
                queryset = queryset.filter(currency=filters['currency'])
            
            return queryset
            
        except Exception as e:
            logger.error(f"Queryset build error: {str(e)}", exc_info=True)
            raise
    
    def _export_sync(self, queryset, format_type, filters):
        """Synchronous export with error handling"""
        try:
            if format_type == 'csv':
                return self._export_csv_sync(queryset)
            else:
                return self._export_json_sync(queryset)
        except MemoryError:
            logger.error("Out of memory during export")
            raise DatabaseOperationException(
                detail="Export too large for synchronous processing",
                context={
                    'suggestion': 'Try reducing the date range or number of records'
                }
            )
        except IOError as e:
            logger.error(f"IO error during export: {str(e)}")
            raise DatabaseOperationException(
                detail="File system error during export",
                context={'error': str(e)}
            )
        except Exception as e:
            logger.error(f"Sync export failed: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Export generation failed",
                context={'error': str(e)}
            )
    
    def _export_csv_sync(self, queryset):
        """Export as CSV with error handling"""
        import csv
        from io import StringIO
        
        try:
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'Date', 'Vendor', 'Amount', 'Currency', 'Category',
                'Description', 'Business Expense', 'Reimbursable', 
                'Tags', 'Created At'
            ])
            
            # Write data with error handling for each row
            row_count = 0
            for entry in queryset:
                try:
                    writer.writerow([
                        entry.date.isoformat(),
                        entry.vendor or '',
                        str(entry.amount),
                        entry.currency,
                        entry.category.name if entry.category else '',
                        entry.description or '',
                        'Yes' if entry.is_business_expense else 'No',
                        'Yes' if entry.is_reimbursable else 'No',
                        ', '.join(entry.tags) if entry.tags else '',
                        entry.created_at.isoformat()
                    ])
                    row_count += 1
                except Exception as row_error:
                    logger.warning(
                        f"Failed to export entry {entry.id}: {str(row_error)}"
                    )
                    # Continue with other rows
                    continue
            
            output.seek(0)
            response = HttpResponse(output.getvalue(), content_type='text/csv')
            response['Content-Disposition'] = (
                f'attachment; filename="ledger_export_'
                f'{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
            )
            
            logger.info(f"CSV export successful: {row_count} rows")
            return response
            
        except Exception as e:
            logger.error(f"CSV generation failed: {str(e)}", exc_info=True)
            raise
    
    def _export_json_sync(self, queryset):
        """Export as JSON with error handling"""
        import json
        
        try:
            entries = []
            skipped_count = 0
            
            for entry in queryset:
                try:
                    entries.append({
                        'id': str(entry.id),
                        'date': entry.date.isoformat(),
                        'vendor': entry.vendor,
                        'amount': float(entry.amount),
                        'currency': entry.currency,
                        'category': {
                            'id': str(entry.category.id),
                            'name': entry.category.name
                        } if entry.category else None,
                        'description': entry.description,
                        'is_business_expense': entry.is_business_expense,
                        'is_reimbursable': entry.is_reimbursable,
                        'tags': entry.tags,
                        'created_at': entry.created_at.isoformat()
                    })
                except Exception as row_error:
                    logger.warning(
                        f"Failed to serialize entry {entry.id}: {str(row_error)}"
                    )
                    skipped_count += 1
                    continue
            
            data = {
                'export_date': timezone.now().isoformat(),
                'total_entries': len(entries),
                'skipped_entries': skipped_count,
                'entries': entries
            }
            
            response = HttpResponse(
                json.dumps(data, indent=2),
                content_type='application/json'
            )
            response['Content-Disposition'] = (
                f'attachment; filename="ledger_export_'
                f'{timezone.now().strftime("%Y%m%d_%H%M%S")}.json"'
            )
            
            logger.info(
                f"JSON export successful: {len(entries)} entries, "
                f"{skipped_count} skipped"
            )
            return response
            
        except Exception as e:
            logger.error(f"JSON generation failed: {str(e)}", exc_info=True)
            raise
    
    def _export_async(self, queryset, format_type, filters, user, total_count):
        """Async export with comprehensive error handling"""
        import uuid
        from django.core.cache import cache
        
        try:
            task_id = str(uuid.uuid4())
            
            # Store task metadata with error handling
            try:
                cache.set(f"export_task:{task_id}", {
                    'id': task_id,
                    'user_id': str(user.id),
                    'user_email': user.email,
                    'format': format_type,
                    'filters': filters,
                    'total_records': total_count,
                    'status': 'queued',
                    'created_at': timezone.now().isoformat()
                }, timeout=86400)  # 24 hours
            except Exception as cache_error:
                logger.error(f"Cache storage failed: {str(cache_error)}")
                raise DatabaseOperationException(
                    detail="Failed to create export task",
                    context={'error': 'Cache storage failed'}
                )
            
            # Trigger async task with error handling
            try:
                from receipt_service.tasks.file_tasks import export_ledger_async_task
                export_ledger_async_task.delay(
                    task_id, filters, format_type, str(user.id)
                )
            except Exception as celery_error:
                logger.error(f"Celery task creation failed: {str(celery_error)}")
                # Clean up cache
                cache.delete(f"export_task:{task_id}")
                raise DatabaseOperationException(
                    detail="Failed to queue export task",
                    context={'error': 'Task queue unavailable'}
                )
            
            logger.info(f"Async export queued: task_id={task_id}, records={total_count}")
            
            return Response({
                'message': 'Large export queued for processing',
                'data': {
                    'task_id': task_id,
                    'status': 'queued',
                    'estimated_records': total_count,
                    'estimated_completion': self._estimate_completion(total_count),
                    'status_url': f'/ledger/v1//exports/{task_id}/status/',
                    'download_url': f'/ledger/v1//exports/{task_id}/download/'
                }
            }, status=status.HTTP_202_ACCEPTED)
            
        except DatabaseOperationException:
            raise
        except Exception as e:
            logger.error(f"Async export setup failed: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Failed to create async export",
                context={'error': str(e)}
            )
    
    def _estimate_completion(self, record_count):
        """Estimate completion time"""
        seconds = max(30, record_count // 500)
        
        if seconds < 60:
            return f"~{seconds} seconds"
        elif seconds < 3600:
            return f"~{seconds // 60} minutes"
        else:
            return f"~{seconds // 3600} hours"


class LedgerExportStatusView(APIView):
    """Check status of async export with proper error handling"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, task_id):
        """Get export task status"""
        from django.core.cache import cache
        
        try:
            # Convert UUID object to string (DRF already validated it)
            task_id_str = str(task_id)
            
            # Get task data with error handling
            try:
                task_data = cache.get(f"export_task:{task_id_str}")
            except Exception as cache_error:
                logger.error(f"Cache retrieval failed: {str(cache_error)}")
                raise DatabaseOperationException(
                    detail="Failed to retrieve task status",
                    context={'error': 'Cache unavailable'}
                )
            
            if not task_data:
                raise ValidationException(
                    detail="Export task not found",
                    context={
                        'task_id': task_id_str,
                        'reason': 'Task not found or has expired (tasks expire after 24 hours)'
                    }
                )
            
            # Verify ownership
            if task_data.get('user_id') != str(request.user.id):
                raise ValidationException(
                    detail="Access denied to this export task",
                    context={'task_id': task_id_str}
                )
            
            # Get status
            status_val = cache.get(f"export_task:{task_id_str}:status", 'queued')
            progress = cache.get(f"export_task:{task_id_str}:progress", 0)
            
            if status_val == 'completed':
                return success_response(
                    message="Export completed successfully",
                    data={
                        'task_id': task_id_str,
                        'status': 'completed',
                        'progress': 100,
                        'download_url': f'/ledger/v1//exports/{task_id_str}/download/'
                    }
                )
            elif status_val == 'failed':
                error = cache.get(f"export_task:{task_id_str}:error", 'Unknown error')
                raise DatabaseOperationException(
                    detail="Export task failed",
                    context={
                        'task_id': task_id_str,
                        'error': error,
                        'suggestion': 'Try creating a new export with adjusted filters'
                    }
                )
            else:
                return Response({
                    'message': 'Export still processing',
                    'data': {
                        'task_id': task_id_str,
                        'status': status_val,
                        'progress': progress,
                        'estimated_records': task_data.get('total_records', 0),
                        'check_again_in_seconds': 5
                    }
                }, status=status.HTTP_202_ACCEPTED)
        
        except (ValidationException, DatabaseOperationException):
            raise
        except Exception as e:
            logger.error(f"Status check failed: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Failed to check export status",
                context={'error': str(e)}
            )


class LedgerExportDownloadView(APIView):
    """Download completed export with proper error handling"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, task_id):
        """Download export file"""
        from django.core.cache import cache
        
        try:
            # Convert UUID object to string (DRF already validated it)
            task_id_str = str(task_id)
            
            # Get task data
            try:
                task_data = cache.get(f"export_task:{task_id_str}")
            except Exception as cache_error:
                logger.error(f"Cache error: {str(cache_error)}")
                raise DatabaseOperationException(
                    detail="Failed to retrieve task information"
                )
            
            if not task_data:
                raise ValidationException(
                    detail="Export task not found or expired",
                    context={
                        'task_id': task_id_str,
                        'reason': 'Task not found or expired after 24 hours'
                    }
                )
            
            # Verify ownership
            if task_data.get('user_id') != str(request.user.id):
                raise ValidationException(
                    detail="Access denied to this export"
                )
            
            # Check status
            status_val = cache.get(f"export_task:{task_id_str}:status")
            
            if status_val != 'completed':
                return Response({
                    'message': 'Export not ready for download',
                    'data': {
                        'status': status_val or 'queued',
                        'status_url': f'/ledger/v1//exports/{task_id_str}/status/'
                    }
                }, status=status.HTTP_202_ACCEPTED)
            
            # Get file path
            file_path = cache.get(f"export_task:{task_id_str}:file_path")
            
            if not file_path:
                raise DatabaseOperationException(
                    detail="Export file path not found",
                    context={
                        'suggestion': 'File may have expired. Create a new export.'
                    }
                )
            
            if not os.path.exists(file_path):
                raise DatabaseOperationException(
                    detail="Export file not found on disk",
                    context={
                        'suggestion': 'File has been cleaned up. Create a new export.'
                    }
                )
            
            # Serve file
            try:
                format_type = task_data.get('format', 'csv')
                filename = f"ledger_export_{task_id_str}.{format_type}"
                
                response = FileResponse(
                    open(file_path, 'rb'),
                    as_attachment=True,
                    filename=filename
                )
                response['Content-Type'] = (
                    'text/csv' if format_type == 'csv' else 'application/json'
                )
                
                logger.info(
                    f"Export downloaded: task_id={task_id_str}, "
                    f"user={request.user.id}"
                )
                return response
                
            except IOError as io_error:
                logger.error(f"File read error: {str(io_error)}")
                raise DatabaseOperationException(
                    detail="Failed to read export file",
                    context={'error': str(io_error)}
                )
        
        except (ValidationException, DatabaseOperationException):
            raise
        except Exception as e:
            logger.error(f"Download failed: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Export download failed",
                context={'error': str(e)}
            )