"""
Unit tests for ai_service/utils/rate_limiter.py
Tests rate limiting for external API calls (Gemini API)
"""
import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from freezegun import freeze_time

from ai_service.utils.rate_limiter import RateLimiter, rate_limiter


@pytest.fixture
def limiter():
    """Create fresh rate limiter for each test"""
    return RateLimiter()


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before and after each test"""
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.mark.unit
class TestRateLimiterInitialization:
    """Test rate limiter initialization"""
    
    def test_initialization(self, limiter):
        """Test rate limiter initializes with correct limits"""
        assert 'gemini_api' in limiter.limits
        assert 'tesseract' in limiter.limits
        
        gemini_limits = limiter.limits['gemini_api']
        assert gemini_limits['enabled'] is True
        assert gemini_limits['requests_per_minute'] > 0
        assert gemini_limits['requests_per_day'] > 0
    
    def test_tesseract_disabled(self, limiter):
        """Test Tesseract rate limiting is disabled"""
        tesseract_limits = limiter.limits['tesseract']
        assert tesseract_limits['enabled'] is False


@pytest.mark.unit
class TestRateLimitChecks:
    """Test rate limit checking"""
    
    @freeze_time("2024-01-01 12:00:00")
    def test_check_rate_limit_allows_first_request(self, limiter):
        """Test first request is allowed"""
        result = limiter.check_rate_limit('gemini_api')
        
        assert result['allowed'] is True
        assert result['service'] == 'gemini_api'
    
    @freeze_time("2024-01-01 12:00:00")
    def test_check_rate_limit_disabled_service(self, limiter):
        """Test disabled service always allows requests"""
        result = limiter.check_rate_limit('tesseract')
        
        assert result['allowed'] is True
        assert result['reason'] == 'rate_limiting_disabled'
    
    @freeze_time("2024-01-01 12:00:00")
    def test_check_rate_limit_unconfigured_service(self, limiter):
        """Test unconfigured service allows requests"""
        result = limiter.check_rate_limit('unknown_service')
        
        assert result['allowed'] is True
        assert result['reason'] == 'no_limits_configured'


@pytest.mark.unit
class TestMinuteRateLimit:
    """Test per-minute rate limiting"""
    
    @freeze_time("2024-01-01 12:00:00")
    def test_minute_limit_enforcement(self, limiter):
        """Test requests are limited per minute"""
        # Set low limit for testing
        limiter.limits['gemini_api']['requests_per_minute'] = 3
        
        # First 3 requests should succeed
        for _ in range(3):
            result = limiter.check_rate_limit('gemini_api')
            assert result['allowed'] is True
        
        # 4th request should be denied
        result = limiter.check_rate_limit('gemini_api')
        
        assert result['allowed'] is False
        assert result['reason'] == 'minute_limit_exceeded'
        assert result['window'] == 'minute'
        assert result['limit'] == 3
    
    @freeze_time("2024-01-01 12:00:00")
    def test_minute_limit_resets(self, limiter):
        """Test minute limit resets after 60 seconds"""
        limiter.limits['gemini_api']['requests_per_minute'] = 2
        
        # Use up limit
        limiter.check_rate_limit('gemini_api')
        limiter.check_rate_limit('gemini_api')
        
        # Should be blocked
        result = limiter.check_rate_limit('gemini_api')
        assert result['allowed'] is False
        
        # Advance time by 61 seconds (new minute)
        with freeze_time("2024-01-01 12:01:01"):
            result = limiter.check_rate_limit('gemini_api')
            assert result['allowed'] is True


@pytest.mark.unit
class TestDailyRateLimit:
    """Test per-day rate limiting"""
    
    @freeze_time("2024-01-01 00:00:00")
    def test_daily_limit_enforcement(self, limiter):
        """Test requests are limited per day"""
        limiter.limits['gemini_api']['requests_per_day'] = 5
        limiter.limits['gemini_api']['requests_per_minute'] = 100  # High to not interfere
        
        # First 5 requests should succeed
        for _ in range(5):
            result = limiter.check_rate_limit('gemini_api')
            assert result['allowed'] is True
        
        # 6th request should be denied
        result = limiter.check_rate_limit('gemini_api')
        
        assert result['allowed'] is False
        assert result['reason'] == 'daily_limit_exceeded'
        assert result['window'] == 'daily'
    
    @freeze_time("2024-01-01 00:00:00")
    def test_daily_limit_resets(self, limiter):
        """Test daily limit resets after 24 hours"""
        limiter.limits['gemini_api']['requests_per_day'] = 2
        limiter.limits['gemini_api']['requests_per_minute'] = 100
        
        # Use up daily limit
        limiter.check_rate_limit('gemini_api')
        limiter.check_rate_limit('gemini_api')
        
        result = limiter.check_rate_limit('gemini_api')
        assert result['allowed'] is False
        
        # Advance to next day
        with freeze_time("2024-01-02 00:00:01"):
            result = limiter.check_rate_limit('gemini_api')
            assert result['allowed'] is True


@pytest.mark.unit
class TestBurstRateLimit:
    """Test burst rate limiting"""
    
    @freeze_time("2024-01-01 12:00:00")
    def test_burst_limit_enforcement(self, limiter):
        """Test burst limit prevents rapid requests"""
        limiter.limits['gemini_api']['burst_limit'] = 3
        limiter.limits['gemini_api']['requests_per_minute'] = 100
        
        # First 3 rapid requests should succeed
        for _ in range(3):
            result = limiter.check_rate_limit('gemini_api')
            assert result['allowed'] is True
        
        # 4th rapid request should be denied
        result = limiter.check_rate_limit('gemini_api')
        
        assert result['allowed'] is False
        assert result['reason'] == 'burst_limit_exceeded'
        assert result['window'] == 'burst'
    
    @freeze_time("2024-01-01 12:00:00")
    def test_burst_limit_per_user(self, limiter):
        """Test burst limit is per-user"""
        limiter.limits['gemini_api']['burst_limit'] = 2
        limiter.limits['gemini_api']['requests_per_minute'] = 100
        
        # User 1 uses up burst
        limiter.check_rate_limit('gemini_api', user_id='user1')
        limiter.check_rate_limit('gemini_api', user_id='user1')
        
        # User 1 should be blocked
        result = limiter.check_rate_limit('gemini_api', user_id='user1')
        assert result['allowed'] is False
        
        # User 2 should still be allowed
        result = limiter.check_rate_limit('gemini_api', user_id='user2')
        assert result['allowed'] is True


@pytest.mark.unit
class TestUsageStats:
    """Test usage statistics"""
    
    @freeze_time("2024-01-01 12:00:00")
    def test_get_usage_stats(self, limiter):
        """Test getting usage statistics"""
        limiter.limits['gemini_api']['requests_per_minute'] = 10
        limiter.limits['gemini_api']['requests_per_day'] = 100
        
        # Make some requests
        limiter.check_rate_limit('gemini_api')
        limiter.check_rate_limit('gemini_api')
        limiter.check_rate_limit('gemini_api')
        
        stats = limiter.get_usage_stats('gemini_api')
        
        assert stats['service'] == 'gemini_api'
        assert stats['enabled'] is True
        assert stats['current_minute'] == 3
        assert stats['remaining_minute'] == 7
        assert stats['current_daily'] == 3
        assert stats['remaining_daily'] == 97
    
    def test_get_usage_stats_disabled_service(self, limiter):
        """Test stats for disabled service"""
        stats = limiter.get_usage_stats('tesseract')
        
        assert stats['enabled'] is False
        assert stats['limit_minute'] == 0


@pytest.mark.unit
class TestRateLimiterMethods:
    """Test rate limiter utility methods"""
    
    def test_is_rate_limiting_enabled(self, limiter):
        """Test checking if rate limiting is enabled"""
        assert limiter.is_rate_limiting_enabled('gemini_api') is True
        assert limiter.is_rate_limiting_enabled('tesseract') is False
        assert limiter.is_rate_limiting_enabled('unknown') is False
    
    def test_get_service_limits(self, limiter):
        """Test getting service limit configuration"""
        limits = limiter.get_service_limits('gemini_api')
        
        assert 'enabled' in limits
        assert 'requests_per_minute' in limits
        assert 'requests_per_day' in limits
    
    @freeze_time("2024-01-01 12:00:00")
    def test_reset_limits(self, limiter):
        """Test resetting rate limits"""
        # Make some requests
        limiter.check_rate_limit('gemini_api')
        limiter.check_rate_limit('gemini_api')
        
        stats_before = limiter.get_usage_stats('gemini_api')
        assert stats_before['current_minute'] == 2
        
        # Reset
        limiter.reset_limits('gemini_api')
        
        stats_after = limiter.get_usage_stats('gemini_api')
        assert stats_after['current_minute'] == 0


@pytest.mark.unit
class TestRateLimiterErrorHandling:
    """Test rate limiter error handling"""
    
    def test_check_rate_limit_cache_failure(self, limiter):
        """Test rate limiter fails open on cache errors"""
        with patch('ai_service.utils.rate_limiter.cache.get', side_effect=Exception("Cache error")):
            result = limiter.check_rate_limit('gemini_api')
            
            # Should fail open (allow request)
            assert result['allowed'] is True
            assert 'error' in result
            assert result['failsafe'] is True
    
    def test_get_usage_stats_error(self, limiter):
        """Test usage stats returns error dict on failure"""
        with patch('ai_service.utils.rate_limiter.cache.get', side_effect=Exception("Error")):
            stats = limiter.get_usage_stats('gemini_api')
            
            assert 'error' in stats


@pytest.mark.unit
class TestRateLimiterIntegration:
    """Test rate limiter integration scenarios"""
    
    @freeze_time("2024-01-01 12:00:00")
    def test_multiple_limit_types_enforced(self, limiter):
        """Test all limit types work together"""
        limiter.limits['gemini_api']['requests_per_minute'] = 10
        limiter.limits['gemini_api']['requests_per_day'] = 20
        limiter.limits['gemini_api']['burst_limit'] = 3
        
        # Burst limit kicks in first
        for i in range(3):
            result = limiter.check_rate_limit('gemini_api')
            assert result['allowed'] is True, f"Request {i+1} failed"
        
        # 4th rapid request blocked by burst
        result = limiter.check_rate_limit('gemini_api')
        assert result['allowed'] is False
        assert result['reason'] == 'burst_limit_exceeded'
    
    @freeze_time("2024-01-01 12:00:00")
    def test_remaining_requests_calculated(self, limiter):
        """Test remaining requests are calculated correctly"""
        limiter.limits['gemini_api']['requests_per_minute'] = 5
        limiter.limits['gemini_api']['requests_per_day'] = 100
        
        # Make 2 requests
        result1 = limiter.check_rate_limit('gemini_api')
        result2 = limiter.check_rate_limit('gemini_api')
        
        assert result2['remaining_minute'] == 3
        assert result2['remaining_daily'] == 98


@pytest.mark.unit
class TestGlobalRateLimiter:
    """Test global rate limiter instance"""
    
    def test_global_instance_exists(self):
        """Test global rate_limiter instance is available"""
        from ai_service.utils.rate_limiter import rate_limiter as global_limiter
        
        assert global_limiter is not None
        assert isinstance(global_limiter, RateLimiter)
    
    @freeze_time("2024-01-01 12:00:00")
    def test_global_instance_functional(self):
        """Test global instance works correctly"""
        result = rate_limiter.check_rate_limit('gemini_api')
        
        assert 'allowed' in result
