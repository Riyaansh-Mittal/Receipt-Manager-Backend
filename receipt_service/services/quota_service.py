# receipt_service/services/quota_service.py

import logging
from datetime import datetime, date
from typing import Dict, Any, List

from django.utils import timezone
from django.core.cache import cache

from .receipt_model_service import model_service
from ..utils.exceptions import (
    MonthlyUploadLimitExceededException,
    QuotaCalculationException,
)
from shared.utils.exceptions import DatabaseOperationException

logger = logging.getLogger(__name__)


class QuotaService:
    """Handle user upload quotas and limits with caching"""
    
    MONTHLY_RECEIPT_LIMIT = 50
    CACHE_TIMEOUT = 300  # 5 minutes
    
    def check_upload_quota(self, user) -> Dict[str, Any]:
        """
        Check user's current upload quota status
        
        Returns:
            Dict with quota information and remaining uploads
        """
        cache_key = f"quota_status_{user.id}_{timezone.now().strftime('%Y_%m')}"
        
        try:
            # Try cache first
            quota_status = cache.get(cache_key)
            if quota_status:
                return quota_status
            
            current_month = timezone.now().date().replace(day=1)
            
            # Count receipts this month
            try:
                monthly_count = model_service.receipt_model.objects.filter(
                    user=user,
                    created_at__date__gte=current_month
                ).count()
            except Exception as e:
                logger.error(f"Failed to count receipts for user {user.id}: {str(e)}")
                raise QuotaCalculationException(
                    detail="Failed to calculate quota usage",
                    context={'user_id': str(user.id), 'error': str(e)}
                )
            
            # Update user quota if needed
            self._update_user_quota_if_needed(user, current_month, monthly_count)
            
            remaining = max(0, self.MONTHLY_RECEIPT_LIMIT - monthly_count)
            next_reset = self._get_next_month_date(current_month)
            
            quota_status = {
                'monthly_limit': self.MONTHLY_RECEIPT_LIMIT,
                'current_month_uploads': monthly_count,
                'remaining_uploads': remaining,
                'reset_date': next_reset.isoformat(),
                'quota_exceeded': monthly_count >= self.MONTHLY_RECEIPT_LIMIT,
                'utilization_percentage': round((monthly_count / self.MONTHLY_RECEIPT_LIMIT) * 100, 1)
            }
            
            # Cache result
            try:
                cache.set(cache_key, quota_status, self.CACHE_TIMEOUT)
            except Exception as e:
                logger.warning(f"Failed to cache quota status: {str(e)}")
            
            logger.info(f"Quota check for user {user.id}: {monthly_count}/{self.MONTHLY_RECEIPT_LIMIT}")
            
            return quota_status
            
        except QuotaCalculationException:
            raise
        except Exception as e:
            logger.error(f"Unexpected quota check error: {str(e)}", exc_info=True)
            raise QuotaCalculationException(
                detail="Unexpected error during quota calculation",
                context={'user_id': str(user.id)}
            )
    
    def validate_upload_allowed(self, user) -> bool:
        """
        Validate if user can upload more receipts
        
        Raises:
            MonthlyUploadLimitExceededException: If quota exceeded
        """
        try:
            quota_status = self.check_upload_quota(user)
            
            if quota_status['quota_exceeded']:
                logger.warning(f"Upload blocked for user {user.id}: quota exceeded")
                
                reset_date = datetime.fromisoformat(quota_status['reset_date']).date()
                days_until_reset = (reset_date - timezone.now().date()).days
                
                raise MonthlyUploadLimitExceededException(
                    detail=f"Monthly limit of {self.MONTHLY_RECEIPT_LIMIT} receipts reached. Resets in {days_until_reset} days.",
                    context={
                        'monthly_limit': self.MONTHLY_RECEIPT_LIMIT,
                        'current_uploads': quota_status['current_month_uploads'],
                        'reset_date': quota_status['reset_date'],
                        'days_until_reset': days_until_reset
                    }
                )
            
            return True
            
        except MonthlyUploadLimitExceededException:
            raise
        except Exception as e:
            logger.error(f"Failed to validate quota: {str(e)}")
            raise QuotaCalculationException(
                detail="Failed to validate upload quota"
            )
    
    def sync_user_quota(self, user_id: str) -> None:
        """
        Sync monthly_upload_count to actual processed/confirmed receipts.
        Updates upload_reset_date if month changed.
        """
        from django.db import transaction
        from auth_service.models import User  # Adjust if User model is elsewhere

        try:
            with transaction.atomic():
                user = User.objects.select_for_update().get(id=user_id)
                current_month = timezone.now().date().replace(day=1)

                # Reset month if needed
                if user.upload_reset_date < current_month:
                    user.upload_reset_date = current_month

                # Count actual receipts in current month
                month_start = user.upload_reset_date
                actual_count = model_service.receipt_model.objects.filter(
                    user_id=user_id,
                    created_at__gte=month_start,
                    status__in=['processed', 'confirmed']
                ).count()

                # Update to accurate count
                user.monthly_upload_count = actual_count
                user.save(update_fields=['monthly_upload_count', 'upload_reset_date'])

                # Invalidate caches
                cache_keys = [
                    f"quota_status_{user_id}_{timezone.now().strftime('%Y_%m')}",
                    f"user_stats:{user_id}"
                ]
                for key in cache_keys:
                    try:
                        cache.delete(key)
                    except Exception:
                        pass

                logger.info(
                    f"User quota synced: {user_id} = {actual_count} "
                    f"(reset_date: {user.upload_reset_date})"
                )

        except User.DoesNotExist:
            logger.error(f"User not found during quota sync: {user_id}")
        except Exception as e:
            logger.error(f"Quota sync failed for {user_id}: {str(e)}", exc_info=True)
            raise DatabaseOperationException(
                detail="Failed to sync quota",
                context={'user_id': user_id, 'error': str(e)}
            )
    
    def increment_upload_count(self, user_id: str) -> None:
        """
        Legacy increment - now just triggers sync for accuracy.
        Call this after processing/confirmation as before.
        """
        self.sync_user_quota(user_id)
    
    def get_quota_history(self, user, months: int = 12) -> Dict[str, Any]:
        """Get user's upload history with proper currency conversion"""
        from ..utils.currency_utils import currency_manager
        from decimal import Decimal
        
        try:
            from django.utils import timezone
            from dateutil.relativedelta import relativedelta
            
            # Calculate date range
            end_date = timezone.now()
            start_date = end_date - relativedelta(months=months)
            
            # Get receipts in date range
            receipts = model_service.receipt_model.objects.filter(
                user=user,
                created_at__gte=start_date
            ).select_related('ledger_entry')
            
            # Build monthly stats
            monthly_stats = []
            current_date = start_date
            
            while current_date <= end_date:
                month_start = current_date.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                month_end = (month_start + relativedelta(months=1)) - relativedelta(seconds=1)
                
                month_receipts = receipts.filter(
                    created_at__gte=month_start,
                    created_at__lte=month_end
                )
                
                # Count by status
                upload_count = month_receipts.count()
                confirmed_count = month_receipts.filter(status='confirmed').count()
                failed_count = month_receipts.filter(status='failed').count()
                processing_count = month_receipts.filter(
                    status__in=['queued', 'processing']
                ).count()
                
                # Calculate total with currency conversion
                total_amount = Decimal('0.00')
                currencies_used = {}
                
                try:
                    confirmed_receipts = month_receipts.filter(status='confirmed')
                    for receipt in confirmed_receipts:
                        if hasattr(receipt, 'ledger_entry'):
                            ledger = receipt.ledger_entry
                            
                            # Convert to base currency
                            converted = currency_manager.convert_to_base_currency(
                                ledger.amount,
                                ledger.currency
                            )
                            
                            if converted:
                                total_amount += converted
                                
                                # Track original currencies
                                if ledger.currency not in currencies_used:
                                    currencies_used[ledger.currency] = Decimal('0')
                                currencies_used[ledger.currency] += ledger.amount
                            else:
                                logger.warning(
                                    f"Failed to convert {ledger.currency} "
                                    f"for ledger entry {ledger.id}"
                                )
                except Exception as e:
                    logger.warning(f"Could not calculate total amount: {str(e)}")
                
                monthly_stats.append({
                    'month': month_start.strftime('%Y-%m'),
                    'month_name': month_start.strftime('%B %Y'),
                    'upload_count': upload_count,
                    'confirmed_count': confirmed_count,
                    'failed_count': failed_count,
                    'processing_count': processing_count,
                    'total_amount': float(total_amount),
                    'formatted_total': currency_manager.format_amount(
                        total_amount,
                        currency_manager.BASE_CURRENCY
                    ),
                    'currencies_breakdown': {
                        curr: {
                            'amount': float(amt),
                            'formatted': currency_manager.format_amount(amt, curr)
                        }
                        for curr, amt in currencies_used.items()
                    }
                })
                
                current_date += relativedelta(months=1)
            
            # Calculate summary
            total_uploads = sum(stat['upload_count'] for stat in monthly_stats)
            total_confirmed = sum(stat['confirmed_count'] for stat in monthly_stats)
            total_failed = sum(stat['failed_count'] for stat in monthly_stats)
            total_processing = sum(stat['processing_count'] for stat in monthly_stats)
            total_amount_sum = sum(Decimal(str(stat['total_amount'])) for stat in monthly_stats)
            
            summary = {
                'total_uploads': total_uploads,
                'total_confirmed': total_confirmed,
                'total_failed': total_failed,
                'total_processing': total_processing,
                'total_amount': float(total_amount_sum),
                'formatted_total_amount': currency_manager.format_amount(
                    total_amount_sum,
                    currency_manager.BASE_CURRENCY
                ),
                'average_monthly_uploads': round(
                    total_uploads / months, 1
                ) if months > 0 else 0,
                'success_rate': round(
                    (total_confirmed / total_uploads * 100), 1
                ) if total_uploads > 0 else 0,
                'base_currency': currency_manager.BASE_CURRENCY,
                'period': {
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d'),
                    'months': months
                }
            }
            
            return {
                'history': monthly_stats,
                'summary': summary
            }
            
        except Exception as e:
            logger.error(f"Failed to get quota history: {str(e)}", exc_info=True)
            raise QuotaCalculationException(
                detail="Failed to calculate upload history",
                context={'user_id': str(user.id)}
            )
    
    def _update_user_quota_if_needed(self, user, current_month: date, actual_count: int) -> None:
        """Update user quota fields if month changed"""
        try:
            if user.upload_reset_date < current_month:
                user.monthly_upload_count = actual_count
                user.upload_reset_date = current_month
                user.save(update_fields=['monthly_upload_count', 'upload_reset_date'])
        except Exception as e:
            logger.error(f"Failed to update user quota: {str(e)}")
            # Don't raise - not critical
    
    def _get_next_month_date(self, current_month: date) -> date:
        """Get first day of next month"""
        if current_month.month == 12:
            return current_month.replace(year=current_month.year + 1, month=1)
        return current_month.replace(month=current_month.month + 1)
