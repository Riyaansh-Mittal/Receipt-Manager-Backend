"""
Unit tests for receipt_service/utils/currency_utils.py
Tests currency conversion, exchange rate API, circuit breaker integration, and caching
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
import requests
import json
from django.core.cache import cache
from django.conf import settings
from receipt_service.utils.currency_utils import (
    ExchangeRateAPIClient,
    CurrencyManager
)
from shared.utils.circuit_breaker import CircuitBreakerError


@pytest.mark.unit
class TestExchangeRateAPIClient:
    """Test ExchangeRateAPIClient class"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test"""
        # Clear cache before each test
        cache.clear()
        yield
        # Cleanup after test
        cache.clear()

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_initialization(self, mock_cb_manager):
        """Test API client initialization"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_api_key_123'):
            client = ExchangeRateAPIClient()
            
            assert client.api_key == 'test_api_key_123'
            assert client.base_url == 'https://v6.exchangerate-api.com/v6'
            assert client.timeout == 10
            assert client.max_retries == 3
            assert client.min_request_interval == 1.0
            assert client.session is not None

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_create_session(self, mock_cb_manager):
        """Test session creation with retry strategy"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            session = client._create_session()
            
            assert 'User-Agent' in session.headers
            assert session.headers['User-Agent'] == 'Receipt-Manager/1.0'
            assert session.headers['Accept'] == 'application/json'

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    @patch('receipt_service.utils.currency_utils.time.sleep')
    def test_rate_limiting(self, mock_sleep, mock_cb_manager):
        """Test rate limiting between API requests"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            
            # First request - no sleep
            client._rate_limit()
            mock_sleep.assert_not_called()
            
            # Second request immediately after - should sleep
            client._rate_limit()
            mock_sleep.assert_called_once()

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_fetch_rates_success(self, mock_cb_manager):
        """Test successful rate fetching from API"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            
            mock_response = Mock()
            mock_response.json.return_value = {
                'result': 'success',
                'conversion_rates': {
                    'USD': 1.0,
                    'EUR': 0.85,
                    'GBP': 0.73,
                    'INR': 88.50
                }
            }
            mock_response.raise_for_status = Mock()
            
            with patch.object(client.session, 'get', return_value=mock_response):
                rates = client._fetch_rates_from_api('USD')
                
                assert len(rates) == 4
                assert rates['USD'] == Decimal('1.0')
                assert rates['EUR'] == Decimal('0.85')
                assert rates['GBP'] == Decimal('0.73')

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_fetch_rates_api_error(self, mock_cb_manager):
        """Test API error response handling"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            
            mock_response = Mock()
            mock_response.json.return_value = {
                'result': 'error',
                'error-type': 'invalid-key'
            }
            mock_response.raise_for_status = Mock()
            
            with patch.object(client.session, 'get', return_value=mock_response):
                with pytest.raises(ValueError, match="API error: invalid-key"):
                    client._fetch_rates_from_api('USD')

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_fetch_rates_missing_conversion_rates(self, mock_cb_manager):
        """Test handling of missing conversion_rates in response"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            
            mock_response = Mock()
            mock_response.json.return_value = {
                'result': 'success',
                # Missing 'conversion_rates' key
            }
            mock_response.raise_for_status = Mock()
            
            with patch.object(client.session, 'get', return_value=mock_response):
                with pytest.raises(KeyError, match="Missing 'conversion_rates'"):
                    client._fetch_rates_from_api('USD')

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_fetch_rates_invalid_rate_values(self, mock_cb_manager):
        """Test handling of invalid rate values"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            
            mock_response = Mock()
            mock_response.json.return_value = {
                'result': 'success',
                'conversion_rates': {
                    'USD': 1.0,
                    'EUR': -0.85,  # Negative rate - invalid
                    'GBP': 'invalid',  # String instead of number
                    'INR': 0,  # Zero rate - invalid
                    'CAD': 1.25  # Valid
                }
            }
            mock_response.raise_for_status = Mock()
            
            with patch.object(client.session, 'get', return_value=mock_response):
                rates = client._fetch_rates_from_api('USD')
                
                # Should only include valid rates
                assert 'USD' in rates
                assert 'CAD' in rates
                assert 'EUR' not in rates  # Negative
                assert 'GBP' not in rates  # Invalid string
                assert 'INR' not in rates  # Zero

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_fetch_rates_timeout(self, mock_cb_manager):
        """Test timeout exception handling"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            
            with patch.object(client.session, 'get', side_effect=requests.exceptions.Timeout("Connection timeout")):
                with pytest.raises(requests.exceptions.Timeout, match="API timed out after"):
                    client._fetch_rates_from_api('USD')

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_fetch_rates_connection_error(self, mock_cb_manager):
        """Test connection error handling"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            
            with patch.object(client.session, 'get', side_effect=requests.exceptions.ConnectionError("No connection")):
                with pytest.raises(requests.exceptions.ConnectionError, match="Failed to connect to API"):
                    client._fetch_rates_from_api('USD')

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_get_latest_rates_success(self, mock_cb_manager):
        """Test get_latest_rates with circuit breaker"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            
            mock_rates = {'USD': Decimal('1.0'), 'EUR': Decimal('0.85')}
            mock_circuit_breaker = Mock()
            mock_circuit_breaker.call.return_value = mock_rates
            client._circuit_breaker = mock_circuit_breaker
            
            rates = client.get_latest_rates('USD')
            
            assert rates == mock_rates
            mock_circuit_breaker.call.assert_called_once()

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_get_latest_rates_invalid_currency_code(self, mock_cb_manager):
        """Test get_latest_rates with invalid currency code"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            
            # Invalid currency code (not 3 characters)
            rates = client.get_latest_rates('US')
            assert rates is None
            
            # Empty currency code
            rates = client.get_latest_rates('')
            assert rates is None

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_get_latest_rates_circuit_breaker_open(self, mock_cb_manager):
        """Test get_latest_rates when circuit breaker is open"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            
            mock_circuit_breaker = Mock()
            mock_circuit_breaker.call.side_effect = CircuitBreakerError("Circuit breaker is open")
            client._circuit_breaker = mock_circuit_breaker
            
            rates = client.get_latest_rates('USD')
            
            assert rates is None  # Should return None, not raise

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_get_health_status(self, mock_cb_manager):
        """Test health status reporting"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key_longer_than_10'):
            client = ExchangeRateAPIClient()
            
            mock_circuit_breaker = Mock()
            mock_circuit_breaker.get_metrics.return_value = {
                'current_state': 'closed',
                'failure_count': 0,
                'success_count': 10
            }
            client._circuit_breaker = mock_circuit_breaker
            
            health = client.get_health_status()
            
            assert 'api_client_config' in health
            assert 'circuit_breaker' in health
            assert health['api_key_configured'] is True
            assert health['api_client_config']['timeout'] == 10

    @patch('receipt_service.utils.currency_utils.circuit_breaker_manager')
    def test_reset_circuit_breaker(self, mock_cb_manager):
        """Test manual circuit breaker reset"""
        with patch.object(settings, 'EXCHANGE_RATE_API_KEY', 'test_key'):
            client = ExchangeRateAPIClient()
            
            mock_circuit_breaker = Mock()
            client._circuit_breaker = mock_circuit_breaker
            
            client.reset_circuit_breaker()
            
            mock_circuit_breaker.reset.assert_called_once()


@pytest.mark.unit
class TestCurrencyManager:
    """Test CurrencyManager class"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test"""
        cache.clear()
        yield
        cache.clear()

    def test_supported_currencies_structure(self):
        """Test supported currencies have correct structure"""
        currencies = CurrencyManager.get_supported_currencies()
        
        assert len(currencies) > 0
        for code, info in currencies.items():
            assert 'name' in info
            assert 'symbol' in info
            assert 'decimal_places' in info
            assert len(code) == 3
            assert isinstance(info['decimal_places'], int)

    def test_get_currency_codes(self):
        """Test getting list of currency codes"""
        codes = CurrencyManager.get_currency_codes()
        
        assert 'USD' in codes
        assert 'EUR' in codes
        assert 'GBP' in codes
        assert 'INR' in codes
        assert all(len(code) == 3 for code in codes)

    def test_is_valid_currency(self):
        """Test currency code validation"""
        assert CurrencyManager.is_valid_currency('USD') is True
        assert CurrencyManager.is_valid_currency('usd') is True  # Case insensitive
        assert CurrencyManager.is_valid_currency('EUR') is True
        assert CurrencyManager.is_valid_currency('XXX') is False
        assert CurrencyManager.is_valid_currency('') is False

    def test_get_currency_info(self):
        """Test getting currency information"""
        info = CurrencyManager.get_currency_info('USD')
        
        assert info is not None
        assert info['name'] == 'US Dollar'
        assert info['symbol'] == '$'
        assert info['decimal_places'] == 2
        
        # Test case insensitivity
        info = CurrencyManager.get_currency_info('usd')
        assert info is not None

    def test_get_currency_info_invalid(self):
        """Test getting info for invalid currency"""
        info = CurrencyManager.get_currency_info('INVALID')
        assert info is None

    def test_format_amount_standard_currency(self):
        """Test formatting amount with standard 2-decimal currency"""
        formatted = CurrencyManager.format_amount(Decimal('1234.56'), 'USD')
        assert formatted == '$1,234.56'
        
        formatted = CurrencyManager.format_amount(Decimal('999.99'), 'EUR')
        assert formatted == '€999.99'

    def test_format_amount_zero_decimal_currency(self):
        """Test formatting amount with zero-decimal currency (JPY, KRW)"""
        formatted = CurrencyManager.format_amount(Decimal('1234'), 'JPY')
        assert formatted == '¥1,234'
        
        formatted = CurrencyManager.format_amount(Decimal('50000'), 'KRW')
        assert formatted == '₩50,000'

    def test_format_amount_large_numbers(self):
        """Test formatting large amounts"""
        formatted = CurrencyManager.format_amount(Decimal('1000000.50'), 'USD')
        assert formatted == '$1,000,000.50'

    def test_format_amount_invalid_currency(self):
        """Test formatting with invalid currency code"""
        formatted = CurrencyManager.format_amount(Decimal('100'), 'INVALID')
        assert 'INVALID' in formatted
        assert '100' in formatted

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_get_exchange_rate_same_currency(self, mock_api_client):
        """Test exchange rate for same currency"""
        manager = CurrencyManager()
        rate = manager.get_exchange_rate('USD', 'USD')
        
        assert rate == Decimal('1.0')

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_get_exchange_rate_invalid_currencies(self, mock_api_client):
        """Test exchange rate with invalid currency codes"""
        manager = CurrencyManager()
        
        rate = manager.get_exchange_rate('INVALID', 'USD')
        assert rate is None
        
        rate = manager.get_exchange_rate('USD', 'INVALID')
        assert rate is None

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_get_exchange_rate_from_cache(self, mock_api_client):
        """Test getting exchange rate from cache"""
        manager = CurrencyManager()
        
        # Set up fresh cache
        cache_key = "exchange_rate_fresh_USD_EUR"
        cache.set(cache_key, Decimal('0.85'), 3600)
        
        rate = manager.get_exchange_rate('USD', 'EUR')
        
        assert rate == Decimal('0.85')
        # API should not be called
        mock_api_client.return_value.get_latest_rates.assert_not_called()

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_get_exchange_rate_from_api(self, mock_api_client):
        """Test getting exchange rate from API"""
        mock_client_instance = mock_api_client.return_value
        mock_client_instance.get_latest_rates.return_value = {
            'USD': Decimal('1.0'),
            'EUR': Decimal('0.85'),
            'GBP': Decimal('0.73')
        }
        
        manager = CurrencyManager()
        rate = manager.get_exchange_rate('USD', 'EUR')
        
        assert rate == Decimal('0.85')
        mock_client_instance.get_latest_rates.assert_called()

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_get_exchange_rate_fallback(self, mock_api_client):
        """Test falling back to hardcoded rates when API fails"""
        mock_client_instance = mock_api_client.return_value
        mock_client_instance.get_latest_rates.return_value = None  # API failed
        
        manager = CurrencyManager()
        rate = manager.get_exchange_rate('USD', 'EUR')
        
        # Should return fallback rate
        assert rate is not None
        assert isinstance(rate, Decimal)

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_calculate_rate_usd_to_other(self, mock_api_client):
        """Test calculating rate from USD to another currency"""
        manager = CurrencyManager()
        rates = {'EUR': Decimal('0.85'), 'GBP': Decimal('0.73')}
        
        rate = manager._calculate_rate('USD', 'EUR', rates)
        assert rate == Decimal('0.85')

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_calculate_rate_other_to_usd(self, mock_api_client):
        """Test calculating rate from another currency to USD"""
        manager = CurrencyManager()
        rates = {'EUR': Decimal('0.85')}
        
        rate = manager._calculate_rate('EUR', 'USD', rates)
        expected = Decimal('1') / Decimal('0.85')
        assert abs(rate - expected) < Decimal('0.0001')

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_calculate_rate_cross_currency(self, mock_api_client):
        """Test calculating cross-currency rate (EUR to GBP via USD)"""
        manager = CurrencyManager()
        rates = {'EUR': Decimal('0.85'), 'GBP': Decimal('0.73')}
        
        rate = manager._calculate_rate('EUR', 'GBP', rates)
        expected = Decimal('0.73') / Decimal('0.85')
        assert abs(rate - expected) < Decimal('0.0001')

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_convert_amount_success(self, mock_api_client):
        """Test successful amount conversion"""
        mock_client_instance = mock_api_client.return_value
        mock_client_instance.get_latest_rates.return_value = {
            'USD': Decimal('1.0'),
            'EUR': Decimal('0.85')
        }
        
        manager = CurrencyManager()
        converted = manager.convert_amount(Decimal('100'), 'USD', 'EUR')
        
        assert converted == Decimal('85.00')

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_convert_amount_with_rounding(self, mock_api_client):
        """Test amount conversion respects decimal places"""
        mock_client_instance = mock_api_client.return_value
        mock_client_instance.get_latest_rates.return_value = {
            'USD': Decimal('1.0'),
            'JPY': Decimal('147.5')
        }
        
        manager = CurrencyManager()
        converted = manager.convert_amount(Decimal('100'), 'USD', 'JPY')
        
        # JPY has 0 decimal places
        assert converted == Decimal('14750')
        assert converted % 1 == 0  # No decimal part

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_convert_amount_no_rate_available(self, mock_api_client):
        """Test amount conversion when no rate available"""
        mock_client_instance = mock_api_client.return_value
        mock_client_instance.get_latest_rates.return_value = None
        
        manager = CurrencyManager()
        # Clear cache to force API call
        cache.clear()
        
        with patch.object(manager, 'get_exchange_rate', return_value=None):
            converted = manager.convert_amount(Decimal('100'), 'USD', 'EUR')
            assert converted is None

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_convert_to_base_currency(self, mock_api_client):
        """Test converting to base currency"""
        mock_client_instance = mock_api_client.return_value
        mock_client_instance.get_latest_rates.return_value = {
            'USD': Decimal('1.0'),
            'EUR': Decimal('0.85')
        }
        
        manager = CurrencyManager()
        converted = manager.convert_to_base_currency(Decimal('85'), 'EUR')
        
        # EUR to USD
        assert converted is not None
        assert isinstance(converted, Decimal)

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_get_supported_currencies_with_rates(self, mock_api_client):
        """Test getting currencies with current rates"""
        mock_client_instance = mock_api_client.return_value
        mock_client_instance.get_latest_rates.return_value = {
            'USD': Decimal('1.0'),
            'EUR': Decimal('0.85')
        }
        
        manager = CurrencyManager()
        result = manager.get_supported_currencies_with_rates()
        
        assert 'USD' in result
        assert 'rate_to_usd' in result['USD']
        assert 'source' in result['USD']
        assert result['USD']['source'] == 'api'

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_health_check(self, mock_api_client):
        """Test currency manager health check"""
        mock_client_instance = mock_api_client.return_value
        mock_client_instance.get_health_status.return_value = {
            'circuit_breaker': {'current_state': 'closed'},
            'api_key_configured': True
        }
        
        manager = CurrencyManager()
        health = manager.health_check()
        
        assert 'cache_available' in health
        assert 'api_available' in health
        assert 'supported_currencies' in health
        assert health['supported_currencies'] > 0

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_reset_circuit_breaker(self, mock_api_client):
        """Test resetting circuit breaker through manager"""
        mock_client_instance = mock_api_client.return_value
        
        manager = CurrencyManager()
        manager.reset_circuit_breaker()
        
        mock_client_instance.reset_circuit_breaker.assert_called_once()


@pytest.mark.unit
class TestCurrencyManagerEdgeCases:
    """Test edge cases and error conditions"""

    @pytest.fixture(autouse=True)
    def setup(self):
        cache.clear()
        yield
        cache.clear()

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_cache_failure_graceful_degradation(self, mock_api_client):
        """Test graceful handling of cache failures"""
        manager = CurrencyManager()
        
        with patch('django.core.cache.cache.set', side_effect=Exception("Cache error")):
            # Should not crash, just log warning
            with patch.object(manager, '_get_latest_rates_with_caching', return_value={'EUR': Decimal('0.85')}):
                rate = manager.get_exchange_rate('USD', 'EUR')
                # Should still work despite cache failure
                assert rate is not None

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_decimal_precision_maintained(self, mock_api_client):
        """Test that decimal precision is maintained through conversions"""
        mock_client_instance = mock_api_client.return_value
        mock_client_instance.get_latest_rates.return_value = {
            'USD': Decimal('1.0'),
            'EUR': Decimal('0.852134567')
        }
        
        manager = CurrencyManager()
        amount = Decimal('100.123456')
        converted = manager.convert_amount(amount, 'USD', 'EUR')
        
        # Should have exactly 2 decimal places for EUR
        assert converted is not None
        assert converted.as_tuple().exponent == -2

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_zero_amount_conversion(self, mock_api_client):
        """Test converting zero amount"""
        manager = CurrencyManager()
        
        with patch.object(manager, 'get_exchange_rate', return_value=Decimal('0.85')):
            converted = manager.convert_amount(Decimal('0'), 'USD', 'EUR')
            assert converted == Decimal('0.00')

    @patch('receipt_service.utils.currency_utils.ExchangeRateAPIClient')
    def test_very_large_amount_conversion(self, mock_api_client):
        """Test converting very large amounts"""
        manager = CurrencyManager()
        
        with patch.object(manager, 'get_exchange_rate', return_value=Decimal('0.85')):
            large_amount = Decimal('999999999.99')
            converted = manager.convert_amount(large_amount, 'USD', 'EUR')
            assert converted is not None
            assert converted > 0
