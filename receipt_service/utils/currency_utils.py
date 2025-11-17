import requests
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional
from django.core.cache import cache
from django.conf import settings
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import logging
from datetime import datetime
import json
from shared.utils.circuit_breaker import circuit_breaker_manager, CircuitBreakerConfig, CircuitBreakerError


logger = logging.getLogger(__name__)


class ExchangeRateAPIClient:
    """
    Production-ready client for ExchangeRate-API with circuit breaker protection
    """
    
    def __init__(self):
        # Store as private attributes, load lazily via properties
        self._api_key = None
        self._timeout = None
        self._max_retries = None
        self._circuit_breaker_config = None
        self._circuit_breaker = None
        
        self.base_url = 'https://v6.exchangerate-api.com/v6'
        
        # Rate limiting
        self.last_request_time = None
        self.min_request_interval = 1.0  # 1 second between requests
        
        # Session will be created on first use
        self._session = None
    
    @property
    def api_key(self):
        """Lazy load API key from settings"""
        if self._api_key is None:
            self._api_key = getattr(settings, 'EXCHANGE_RATE_API_KEY', None)
        return self._api_key
    
    @property
    def timeout(self):
        """Lazy load timeout from settings"""
        if self._timeout is None:
            self._timeout = getattr(settings, 'EXCHANGE_RATE_API_TIMEOUT', 10)
        return self._timeout
    
    @property
    def max_retries(self):
        """Lazy load max retries from settings"""
        if self._max_retries is None:
            self._max_retries = getattr(settings, 'EXCHANGE_RATE_MAX_RETRIES', 3)
        return self._max_retries
    
    @property
    def session(self):
        """Lazy create session on first access"""
        if self._session is None:
            self._session = self._create_session()
        return self._session
    
    @property
    def circuit_breaker_config(self):
        """Lazy load circuit breaker config from settings"""
        if self._circuit_breaker_config is None:
            self._circuit_breaker_config = CircuitBreakerConfig(
                name='exchange_rate_api',
                failure_threshold=getattr(settings, 'EXCHANGE_RATE_FAILURE_THRESHOLD', 3),
                recovery_timeout=getattr(settings, 'EXCHANGE_RATE_RECOVERY_TIMEOUT', 300),  # 5 minutes
                success_threshold=getattr(settings, 'EXCHANGE_RATE_SUCCESS_THRESHOLD', 2),
                timeout=self.timeout,
                expected_exceptions=(
                    requests.exceptions.RequestException,
                    requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.HTTPError,
                    json.JSONDecodeError,
                    ValueError,
                    KeyError
                )
            )
        return self._circuit_breaker_config
    
    @property
    def circuit_breaker(self):
        """Lazy get circuit breaker from manager"""
        if self._circuit_breaker is None:
            self._circuit_breaker = circuit_breaker_manager.get_breaker(
                'exchange_rate_api', 
                self.circuit_breaker_config
            )
        return self._circuit_breaker
    
    def _create_session(self) -> requests.Session:
        """Create HTTP session with retry strategy and timeouts"""
        session = requests.Session()
        
        # Retry strategy
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Set headers
        session.headers.update({
            'User-Agent': 'Receipt-Manager/1.0',
            'Accept': 'application/json',
            'Connection': 'keep-alive'
        })
        
        return session
    
    def _rate_limit(self):
        """Implement rate limiting between requests"""
        if self.last_request_time:
            time_since_last = time.time() - self.last_request_time
            if time_since_last < self.min_request_interval:
                sleep_time = self.min_request_interval - time_since_last
                time.sleep(sleep_time)
        self.last_request_time = time.time()
    
    def _fetch_rates_from_api(self, base_currency: str = 'USD') -> Dict[str, Decimal]:
        """Internal method to fetch rates from API"""
        self._rate_limit()
        
        url = f"{self.base_url}/{self.api_key}/latest/{base_currency}"
        logger.info(f"Fetching exchange rates from: {url}")
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('result') == 'success':
                # Validate and parse rates
                if 'conversion_rates' not in data:
                    raise KeyError("Missing 'conversion_rates' in API response")
                
                rates = {}
                conversion_rates = data['conversion_rates']
                
                if not conversion_rates:
                    raise ValueError("Empty conversion rates received from API")
                
                for currency, rate in conversion_rates.items():
                    try:
                        decimal_rate = Decimal(str(rate))
                        if decimal_rate <= 0:
                            logger.warning(f"Invalid rate for {currency}: {rate}")
                            continue
                        rates[currency] = decimal_rate
                    except (ValueError, TypeError, InvalidOperation) as e:
                        logger.warning(f"Invalid rate for {currency}: {rate}, error: {e}")
                        continue
                
                if not rates:
                    raise ValueError("No valid exchange rates parsed")
                
                logger.info(f"Successfully fetched {len(rates)} exchange rates")
                return rates
            else:
                error_type = data.get('error-type', 'unknown')
                raise ValueError(f"API error: {error_type}")
        
        except requests.exceptions.Timeout as e:
            raise requests.exceptions.Timeout(f"API timed out after {self.timeout}s") from e
        
        except requests.exceptions.ConnectionError as e:
            raise requests.exceptions.ConnectionError("Failed to connect to API") from e
        
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise
    
    def get_latest_rates(self, base_currency: str = 'USD') -> Optional[Dict[str, Decimal]]:
        """
        Fetch latest exchange rates with circuit breaker protection
        Returns None if circuit breaker is open or API fails
        """
        try:
            # Validate input
            if not base_currency or len(base_currency) != 3:
                logger.error(f"Invalid base currency: {base_currency}")
                return None
            
            base_currency = base_currency.upper()
            
            # This call is protected by the circuit breaker
            rates = self.circuit_breaker.call(self._fetch_rates_from_api, base_currency)
            
            # Validate response
            if not rates:
                logger.warning("Empty rates returned from API")
                return None
            
            return rates
            
        except CircuitBreakerError as e:
            logger.warning(f"Exchange rate API circuit breaker is open: {e}")
            return None
        
        except Exception as e:
            logger.error(f"Unexpected error in get_latest_rates: {str(e)}")
            return None
    
    def get_health_status(self) -> Dict[str, any]:
        """Get comprehensive health status including circuit breaker metrics"""
        try:
            circuit_metrics = self.circuit_breaker.get_metrics()
            
            # Add additional API client specific health info
            health_info = {
                'api_client_config': {
                    'base_url': self.base_url,
                    'timeout': self.timeout,
                    'max_retries': self.max_retries,
                    'min_request_interval': self.min_request_interval
                },
                'circuit_breaker': circuit_metrics,
                'last_request_time': self.last_request_time,
                'api_key_configured': bool(self.api_key and len(self.api_key) > 10)
            }
            
            return health_info
            
        except Exception as e:
            logger.error(f"Error getting health status: {str(e)}")
            return {
                'error': str(e),
                'circuit_breaker': {'error': 'Unable to get circuit breaker status'}
            }
    
    def reset_circuit_breaker(self):
        """Manually reset the circuit breaker"""
        try:
            self.circuit_breaker.reset()
            logger.info("Exchange rate API circuit breaker manually reset")
        except Exception as e:
            logger.error(f"Error resetting circuit breaker: {str(e)}")

class CurrencyManager:
    """
    Enhanced currency manager with external API integration and fallback mechanisms
    """
    
    # Extended supported currencies based on API response
    SUPPORTED_CURRENCIES = {
        'USD': {'name': 'US Dollar', 'symbol': '$', 'decimal_places': 2},
        'EUR': {'name': 'Euro', 'symbol': '€', 'decimal_places': 2},
        'GBP': {'name': 'British Pound', 'symbol': '£', 'decimal_places': 2},
        'INR': {'name': 'Indian Rupee', 'symbol': '₹', 'decimal_places': 2},
        'CAD': {'name': 'Canadian Dollar', 'symbol': 'C$', 'decimal_places': 2},
        'AUD': {'name': 'Australian Dollar', 'symbol': 'A$', 'decimal_places': 2},
        'JPY': {'name': 'Japanese Yen', 'symbol': '¥', 'decimal_places': 0},
        'CNY': {'name': 'Chinese Yuan', 'symbol': '¥', 'decimal_places': 2},
        'CHF': {'name': 'Swiss Franc', 'symbol': 'CHF', 'decimal_places': 2},
        'SGD': {'name': 'Singapore Dollar', 'symbol': 'S$', 'decimal_places': 2},
        'AED': {'name': 'UAE Dirham', 'symbol': 'د.إ', 'decimal_places': 2},
        'BRL': {'name': 'Brazilian Real', 'symbol': 'R$', 'decimal_places': 2},
        'KRW': {'name': 'South Korean Won', 'symbol': '₩', 'decimal_places': 0},
        'MXN': {'name': 'Mexican Peso', 'symbol': '$', 'decimal_places': 2},
        'NOK': {'name': 'Norwegian Krone', 'symbol': 'kr', 'decimal_places': 2},
        'SEK': {'name': 'Swedish Krona', 'symbol': 'kr', 'decimal_places': 2},
        'DKK': {'name': 'Danish Krone', 'symbol': 'kr.', 'decimal_places': 2},
        'PLN': {'name': 'Polish Zloty', 'symbol': 'zł', 'decimal_places': 2},
        'CZK': {'name': 'Czech Koruna', 'symbol': 'Kč', 'decimal_places': 2},
        'HUF': {'name': 'Hungarian Forint', 'symbol': 'Ft', 'decimal_places': 0},
        'THB': {'name': 'Thai Baht', 'symbol': '฿', 'decimal_places': 2},
        'MYR': {'name': 'Malaysian Ringgit', 'symbol': 'RM', 'decimal_places': 2},
        'PHP': {'name': 'Philippine Peso', 'symbol': '₱', 'decimal_places': 2},
        'IDR': {'name': 'Indonesian Rupiah', 'symbol': 'Rp', 'decimal_places': 0},
        'ILS': {'name': 'Israeli Shekel', 'symbol': '₪', 'decimal_places': 2},
        'ZAR': {'name': 'South African Rand', 'symbol': 'R', 'decimal_places': 2},
    }
    
    def __init__(self):
        self.api_client = ExchangeRateAPIClient()
        self._initialize_fallback_rates()
        # Lazy load settings
        self._default_currency = None
        self._base_currency = None
        self._exchange_rate_cache_timeout = None
        self._fallback_cache_timeout = None

    @property
    def DEFAULT_CURRENCY(self):
        """Lazy load DEFAULT_CURRENCY from settings"""
        if self._default_currency is None:
            self._default_currency = getattr(settings, 'DEFAULT_CURRENCY', 'USD')
        return self._default_currency
    
    @property
    def BASE_CURRENCY(self):
        """Lazy load BASE_CURRENCY from settings"""
        if self._base_currency is None:
            self._base_currency = getattr(settings, 'BASE_CURRENCY', 'USD')
        return self._base_currency
    
    @property
    def EXCHANGE_RATE_CACHE_TIMEOUT(self):
        """Lazy load EXCHANGE_RATE_CACHE_TIMEOUT from settings"""
        if self._exchange_rate_cache_timeout is None:
            self._exchange_rate_cache_timeout = getattr(settings, 'EXCHANGE_RATE_CACHE_TIMEOUT', 3600)
        return self._exchange_rate_cache_timeout
    
    @property
    def FALLBACK_CACHE_TIMEOUT(self):
        """Lazy load FALLBACK_CACHE_TIMEOUT from settings"""
        if self._fallback_cache_timeout is None:
            self._fallback_cache_timeout = getattr(settings, 'FALLBACK_CACHE_TIMEOUT', 86400)
        return self._fallback_cache_timeout
    
    def _initialize_fallback_rates(self):
        """Initialize fallback exchange rates for offline scenarios"""
        self.fallback_rates = {
            'USD': Decimal('1.0'),
            'EUR': Decimal('0.8521'),
            'GBP': Decimal('0.7419'),
            'INR': Decimal('88.7311'),
            'CAD': Decimal('1.3931'),
            'AUD': Decimal('1.5124'),
            'JPY': Decimal('147.0930'),
            'CNY': Decimal('7.1226'),
            'CHF': Decimal('0.7972'),
            'SGD': Decimal('1.2882'),
            'AED': Decimal('3.6725'),
            'BRL': Decimal('5.3186'),
            'KRW': Decimal('1402.7125'),
            'MXN': Decimal('18.3534'),
            'NOK': Decimal('9.9223'),
            'SEK': Decimal('9.3790'),
            'DKK': Decimal('6.3583'),
            'PLN': Decimal('3.6303'),
            'CZK': Decimal('20.6862'),
            'HUF': Decimal('331.4635'),
            'THB': Decimal('32.3986'),
            'MYR': Decimal('4.2080'),
            'PHP': Decimal('58.1842'),
            'IDR': Decimal('16627.5585'),
            'ILS': Decimal('3.3171'),
            'ZAR': Decimal('17.2075'),
        }
    
    @classmethod
    def get_supported_currencies(cls) -> Dict[str, Dict[str, str]]:
        """Get all supported currencies with their metadata"""
        return cls.SUPPORTED_CURRENCIES.copy()
    
    @classmethod
    def get_currency_choices(cls) -> List[tuple]:
        """Get currency choices for Django model/serializer fields"""
        return [(code, f"{code} - {info['name']}") for code, info in cls.SUPPORTED_CURRENCIES.items()]
    
    @classmethod
    def get_currency_codes(cls) -> List[str]:
        """Get list of supported currency codes"""
        return list(cls.SUPPORTED_CURRENCIES.keys())
    
    @classmethod
    def is_valid_currency(cls, currency_code: str) -> bool:
        """Check if currency code is supported"""
        return currency_code.upper() in cls.SUPPORTED_CURRENCIES
    
    @classmethod
    def get_currency_info(cls, currency_code: str) -> Optional[Dict[str, str]]:
        """Get currency information by code"""
        return cls.SUPPORTED_CURRENCIES.get(currency_code.upper())
    
    @classmethod
    def format_amount(cls, amount: Decimal, currency_code: str) -> str:
        """Format amount with currency symbol"""
        currency_info = cls.get_currency_info(currency_code)
        if not currency_info:
            return f"{amount} {currency_code}"
        
        symbol = currency_info['symbol']
        decimal_places = currency_info['decimal_places']
        
        # Format based on decimal places
        if decimal_places == 0:
            formatted_amount = f"{int(amount):,}"
        else:
            formatted_amount = f"{amount:,.{decimal_places}f}"
        
        return f"{symbol}{formatted_amount}"
    
    def get_exchange_rate(self, from_currency: str, to_currency: str) -> Optional[Decimal]:
        """
        Get exchange rate with multi-tier caching and fallback strategy
        
        Tier 1: Fresh cache (1 hour)
        Tier 2: Stale cache with API refresh attempt
        Tier 3: Long-term fallback cache (1 week)
        Tier 4: Hardcoded fallback rates
        """
        if from_currency == to_currency:
            return Decimal('1.0')
        
        # Normalize currency codes
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        
        # Validate currencies
        if not (self.is_valid_currency(from_currency) and self.is_valid_currency(to_currency)):
            logger.error(f"Invalid currency pair: {from_currency}/{to_currency}")
            return None
        
        # Try fresh cache first (Tier 1)
        fresh_cache_key = f"exchange_rate_fresh_{from_currency}_{to_currency}"
        rate = cache.get(fresh_cache_key)
        if rate is not None:
            logger.debug(f"Using fresh cached rate for {from_currency}/{to_currency}: {rate}")
            return rate
        
        # Try to fetch new rates from API
        rates = self._get_latest_rates_with_caching()
        
        if rates:
            # Calculate rate from fetched data
            rate = self._calculate_rate(from_currency, to_currency, rates)
            if rate is not None:
                # Cache with reasonable timeout
                try:
                    cache.set(fresh_cache_key, rate, self.EXCHANGE_RATE_CACHE_TIMEOUT)
                except Exception as cache_error:
                    logger.warning(f"Failed to cache rate: {str(cache_error)}")
                return rate
        
        # Tier 2: Try stale cache (6 hours)
        stale_cache_key = f"exchange_rate_stale_{from_currency}_{to_currency}"
        rate = cache.get(stale_cache_key)
        if rate is not None:
            logger.warning(f"Using stale cached rate for {from_currency}/{to_currency}: {rate}")
            return rate
        
        # Tier 3: Use hardcoded fallback rates
        rate = self._get_fallback_rate(from_currency, to_currency)
        if rate is not None:
            logger.warning(f"Using hardcoded fallback rate for {from_currency}/{to_currency}")
            # Cache fallback with reasonable timeout
            try:
                cache.set(
                    f"exchange_rate_fallback_{from_currency}_{to_currency}", 
                    rate, 
                    self.FALLBACK_CACHE_TIMEOUT  # 1 day instead of 1 week
                )
            except Exception as cache_error:
                logger.warning(f"Failed to cache fallback rate: {str(cache_error)}")
            return rate
        
        logger.error(f"No exchange rate available for {from_currency}/{to_currency}")
        return None
    
    def _get_latest_rates_with_caching(self) -> Optional[Dict[str, Decimal]]:
        """Get latest rates with multiple cache layers"""
        # Check if we have fresh rates cached
        rates_cache_key = "exchange_rates_usd_base"
        rates = cache.get(rates_cache_key)
        
        if rates is None:
            # Fetch from API using circuit breaker
            rates = self.api_client.get_latest_rates('USD')
            
            if rates:
                # Cache rates at multiple levels
                try:
                    cache.set(rates_cache_key, rates, self.EXCHANGE_RATE_CACHE_TIMEOUT)
                    cache.set(f"{rates_cache_key}_stale", rates, self.EXCHANGE_RATE_CACHE_TIMEOUT * 6)  # 6 hours stale
                    cache.set(f"{rates_cache_key}_fallback", rates, self.FALLBACK_CACHE_TIMEOUT)
                    
                    logger.info(f"Fetched and cached {len(rates)} exchange rates")
                except Exception as e:
                    logger.error(f"Error caching exchange rates: {str(e)}")
            else:
                logger.warning("Failed to fetch exchange rates from API")
        
        return rates
    
    def _calculate_rate(self, from_currency: str, to_currency: str, rates: Dict[str, Decimal]) -> Optional[Decimal]:
        """Calculate exchange rate from USD-based rates"""
        try:
            if from_currency == 'USD':
                return rates.get(to_currency)
            elif to_currency == 'USD':
                from_rate = rates.get(from_currency)
                return Decimal('1') / from_rate if from_rate and from_rate > 0 else None
            else:
                # Cross-currency calculation via USD
                from_rate = rates.get(from_currency)
                to_rate = rates.get(to_currency)
                
                if from_rate and to_rate and from_rate > 0:
                    return to_rate / from_rate
        except Exception as e:
            logger.error(f"Error calculating exchange rate: {e}")
        
        return None
    
    def _get_fallback_rate(self, from_currency: str, to_currency: str) -> Optional[Decimal]:
        """Get rate from hardcoded fallback rates"""
        try:
            if from_currency == 'USD':
                return self.fallback_rates.get(to_currency)
            elif to_currency == 'USD':
                from_rate = self.fallback_rates.get(from_currency)
                return Decimal('1') / from_rate if from_rate and from_rate > 0 else None
            else:
                # Cross-currency via USD
                from_rate = self.fallback_rates.get(from_currency)
                to_rate = self.fallback_rates.get(to_currency)
                
                if from_rate and to_rate and from_rate > 0:
                    return to_rate / from_rate
        except Exception as e:
            logger.error(f"Error with fallback rate calculation: {e}")
        
        return None
    
    def convert_amount(self, amount: Decimal, from_currency: str, to_currency: str) -> Optional[Decimal]:
        """Convert amount from one currency to another with proper rounding"""

        rate = self.get_exchange_rate(from_currency, to_currency)
        if rate is None:
            return None
        
        try:
            converted = amount * rate
            
            # Round to appropriate decimal places
            to_currency_info = self.get_currency_info(to_currency)
            if to_currency_info:
                decimal_places = to_currency_info['decimal_places']
                return converted.quantize(Decimal('0.1') ** decimal_places)
            
            return converted.quantize(Decimal('0.01'))  # Default to 2 decimal places
        except Exception as e:
            logger.error(f"Error converting amount: {e}")
            return None
    
    def convert_to_base_currency(self, amount: Decimal, from_currency: str) -> Optional[Decimal]:
        """Convert amount to base currency for analytics"""
        return self.convert_amount(amount, from_currency, self.BASE_CURRENCY)
    
    def get_supported_currencies_with_rates(self) -> Dict[str, Dict]:
        """Get supported currencies with current exchange rates"""
        rates = self._get_latest_rates_with_caching() or {}
        
        result = {}
        for code, info in self.SUPPORTED_CURRENCIES.items():
            result[code] = {
                **info,
                'rate_to_usd': float(rates.get(code, self.fallback_rates.get(code, 1.0))),
                'last_updated': datetime.now().isoformat(),
                'source': 'api' if rates.get(code) else 'fallback'
            }
        
        return result
    
    def health_check(self) -> Dict[str, any]:
        """Enhanced health check with circuit breaker metrics"""
        health_status = {
            'cache_available': True,
            'fallback_available': True,
            'supported_currencies': len(self.SUPPORTED_CURRENCIES),
            'base_currency': self.BASE_CURRENCY,
            'default_currency': self.DEFAULT_CURRENCY
        }
        
        # Get API client health including circuit breaker status
        try:
            api_health = self.api_client.get_health_status()
            health_status.update({
                'api_client': api_health,
                'api_available': api_health.get('circuit_breaker', {}).get('current_state') == 'closed'
            })
        except Exception as e:
            health_status['api_client'] = {'error': str(e)}
            health_status['api_available'] = False
        
        # Test cache
        try:
            cache.set('currency_health_test', 'ok', 60)
            cache.get('currency_health_test')
        except Exception as e:
            health_status['cache_available'] = False
            health_status['cache_error'] = str(e)
        
        return health_status
    
    def reset_circuit_breaker(self):
        """Reset the exchange rate API circuit breaker"""
        self.api_client.reset_circuit_breaker()


# Global currency manager instance
currency_manager = CurrencyManager()
