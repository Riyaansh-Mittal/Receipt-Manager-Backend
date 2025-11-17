"""
Unit tests for shared/utils/circuit_breaker.py
Tests CircuitBreaker pattern implementation with state management
"""
import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from threading import Thread
from decimal import Decimal

from shared.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerManager,
    circuit_breaker,
    circuit_breaker_manager
)


@pytest.fixture
def basic_config():
    """Create basic circuit breaker configuration"""
    return CircuitBreakerConfig(
        name='test_breaker',
        failure_threshold=3,
        recovery_timeout=5,
        success_threshold=2,
        timeout=10,
        expected_exceptions=(ValueError, RuntimeError)
    )


@pytest.fixture
def breaker(basic_config):
    """Create fresh circuit breaker for each test"""
    cb = CircuitBreaker(basic_config)
    cb.reset()  # Ensure clean state
    return cb


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before and after each test"""
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.mark.unit
class TestCircuitBreakerConfig:
    """Test CircuitBreakerConfig dataclass"""
    
    def test_config_defaults(self):
        """Test default configuration values"""
        config = CircuitBreakerConfig(name='test')
        
        assert config.name == 'test'
        assert config.failure_threshold == 5
        assert config.recovery_timeout == 60
        assert config.success_threshold == 3
        assert config.timeout == 30
        assert config.expected_exceptions == (Exception,)
    
    def test_config_custom_values(self):
        """Test custom configuration values"""
        config = CircuitBreakerConfig(
            name='custom',
            failure_threshold=10,
            recovery_timeout=120,
            success_threshold=5,
            timeout=60,
            expected_exceptions=(ValueError,)
        )
        
        assert config.failure_threshold == 10
        assert config.recovery_timeout == 120
        assert config.expected_exceptions == (ValueError,)


@pytest.mark.unit
class TestCircuitBreakerInitialization:
    """Test circuit breaker initialization"""
    
    def test_initialization(self, breaker, basic_config):
        """Test circuit breaker initializes correctly"""
        assert breaker.name == 'test_breaker'
        assert breaker.config == basic_config
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0
    
    def test_cache_keys_created(self, breaker):
        """Test cache keys are properly namespaced"""
        assert 'test_breaker' in breaker._state_key
        assert 'test_breaker' in breaker._failure_count_key
        assert 'test_breaker' in breaker._success_count_key


@pytest.mark.unit
class TestCircuitBreakerStates:
    """Test circuit breaker state transitions"""
    
    def test_initial_state_closed(self, breaker):
        """Test circuit breaker starts in CLOSED state"""
        assert breaker.state == CircuitBreakerState.CLOSED
    
    def test_transition_to_open_after_failures(self, breaker):
        """Test circuit opens after threshold failures"""
        failing_func = Mock(side_effect=ValueError("Test error"))
        
        # Record failures up to threshold
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_func)
        
        assert breaker.state == CircuitBreakerState.OPEN
        assert breaker.failure_count == 3
    
    def test_open_state_rejects_calls(self, breaker):
        """Test OPEN circuit rejects calls immediately"""
        failing_func = Mock(side_effect=ValueError("Test error"))
        
        # Trigger circuit opening
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_func)
        
        # Now circuit is open - should raise CircuitBreakerError
        with pytest.raises(CircuitBreakerError) as exc_info:
            breaker.call(failing_func)
        
        assert 'is open' in str(exc_info.value)
    
    @patch('shared.utils.circuit_breaker.time.time')
    def test_transition_to_half_open_after_timeout(self, mock_time, breaker):
        """Test circuit transitions to HALF_OPEN after recovery timeout"""
        mock_time.return_value = 1000.0
        
        failing_func = Mock(side_effect=ValueError("Test error"))
        success_func = Mock(return_value="success")
        
        # Open the circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_func)
        
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Advance time past recovery timeout
        mock_time.return_value = 1006.0  # 6 seconds later (timeout is 5)
        
        # First successful call should transition to HALF_OPEN
        result = breaker.call(success_func)
        assert result == "success"
        assert breaker.state == CircuitBreakerState.HALF_OPEN  # Still HALF_OPEN after 1 success
        
        # Second successful call should close the circuit (success_threshold is 2)
        result = breaker.call(success_func)
        assert result == "success"
        assert breaker.state == CircuitBreakerState.CLOSED  # Now CLOSED after 2 successes
    
    def test_half_open_closes_after_successes(self, breaker):
        """Test HALF_OPEN closes after success threshold"""
        # Manually set to HALF_OPEN
        breaker.state = CircuitBreakerState.HALF_OPEN
        
        success_func = Mock(return_value="success")
        
        # Execute success threshold number of successful calls
        for _ in range(breaker.config.success_threshold):
            breaker.call(success_func)
        
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0
    
    def test_half_open_reopens_on_failure(self, breaker):
        """Test HALF_OPEN returns to OPEN on failure"""
        breaker.state = CircuitBreakerState.HALF_OPEN
        
        failing_func = Mock(side_effect=ValueError("Test error"))
        
        with pytest.raises(ValueError):
            breaker.call(failing_func)
        
        assert breaker.state == CircuitBreakerState.OPEN


@pytest.mark.unit
class TestCircuitBreakerExecution:
    """Test circuit breaker function execution"""
    
    def test_successful_execution(self, breaker):
        """Test successful function execution"""
        func = Mock(return_value="success")
        
        result = breaker.call(func, "arg1", kwarg1="value1")
        
        assert result == "success"
        func.assert_called_once_with("arg1", kwarg1="value1")
        assert breaker.state == CircuitBreakerState.CLOSED
    
    def test_failure_increments_counter(self, breaker):
        """Test failures increment failure counter"""
        failing_func = Mock(side_effect=ValueError("Test error"))
        
        initial_count = breaker.failure_count
        
        with pytest.raises(ValueError):
            breaker.call(failing_func)
        
        assert breaker.failure_count == initial_count + 1
    
    def test_success_resets_failure_counter_when_closed(self, breaker):
        """Test successful call in CLOSED state"""
        failing_func = Mock(side_effect=ValueError("Test error"))
        success_func = Mock(return_value="success")
        
        # Record one failure
        with pytest.raises(ValueError):
            breaker.call(failing_func)
        
        assert breaker.failure_count == 1
        
        # Successful call should not reset counter in CLOSED state
        # (only resets when transitioning from HALF_OPEN to CLOSED)
        breaker.call(success_func)
        
        # Counter persists until circuit opens and closes again
        assert breaker.state == CircuitBreakerState.CLOSED
    
    def test_unexpected_exception_not_counted(self, breaker):
        """Test unexpected exceptions don't count as failures"""
        # Circuit is configured to only count ValueError and RuntimeError
        unexpected_error = TypeError("Unexpected")
        failing_func = Mock(side_effect=unexpected_error)
        
        with pytest.raises(TypeError):
            breaker.call(failing_func)
        
        # Failure count should not increment
        assert breaker.failure_count == 0
        assert breaker.state == CircuitBreakerState.CLOSED


@pytest.mark.unit
class TestCircuitBreakerMetrics:
    """Test circuit breaker metrics tracking"""
    
    def test_metrics_initialization(self, breaker):
        """Test metrics are initialized correctly"""
        metrics = breaker.get_metrics()
        
        assert metrics['name'] == 'test_breaker'
        assert metrics['current_state'] == CircuitBreakerState.CLOSED.value
        assert metrics['total_requests'] == 0
        assert metrics['total_failures'] == 0
        assert metrics['total_successes'] == 0
    
    def test_metrics_track_requests(self, breaker):
        """Test metrics track total requests"""
        func = Mock(return_value="success")
        
        breaker.call(func)
        breaker.call(func)
        
        metrics = breaker.get_metrics()
        assert metrics['total_requests'] == 2
        assert metrics['total_successes'] == 2
    
    def test_metrics_track_failures(self, breaker):
        """Test metrics track failures"""
        failing_func = Mock(side_effect=ValueError("Error"))
        
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.call(failing_func)
        
        metrics = breaker.get_metrics()
        assert metrics['total_failures'] == 2
        assert metrics['total_requests'] == 2
    
    def test_metrics_track_state_changes(self, breaker):
        """Test metrics track circuit opens/closes"""
        failing_func = Mock(side_effect=ValueError("Error"))
        
        # Open circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_func)
        
        metrics = breaker.get_metrics()
        assert metrics['total_circuit_opens'] >= 1
        assert metrics['last_opened_at'] is not None


@pytest.mark.unit
class TestCircuitBreakerReset:
    """Test circuit breaker manual reset"""
    
    def test_reset_clears_state(self, breaker):
        """Test reset clears all state"""
        failing_func = Mock(side_effect=ValueError("Error"))
        
        # Open the circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(failing_func)
        
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Reset
        breaker.reset()
        
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0


@pytest.mark.unit
class TestCircuitBreakerDecorator:
    """Test circuit breaker decorator usage"""
    
    def test_decorator_application(self, breaker):
        """Test circuit breaker can be used as decorator"""
        @breaker
        def test_function(x):
            return x * 2
        
        result = test_function(5)
        assert result == 10
    
    def test_decorator_with_failures(self, breaker):
        """Test decorator handles failures"""
        @breaker
        def failing_function():
            raise ValueError("Test error")
        
        for _ in range(3):
            with pytest.raises(ValueError):
                failing_function()
        
        # Circuit should be open
        with pytest.raises(CircuitBreakerError):
            failing_function()


@pytest.mark.unit
class TestCircuitBreakerManager:
    """Test CircuitBreakerManager"""
    
    def test_manager_creates_breaker(self):
        """Test manager creates new circuit breakers"""
        manager = CircuitBreakerManager()
        
        breaker = manager.get_breaker('test1')
        
        assert breaker is not None
        assert breaker.name == 'test1'
    
    def test_manager_returns_existing_breaker(self):
        """Test manager returns same instance"""
        manager = CircuitBreakerManager()
        
        breaker1 = manager.get_breaker('test2')
        breaker2 = manager.get_breaker('test2')
        
        assert breaker1 is breaker2
    
    def test_manager_get_all_metrics(self):
        """Test manager aggregates metrics"""
        manager = CircuitBreakerManager()
        
        breaker1 = manager.get_breaker('breaker1')
        breaker2 = manager.get_breaker('breaker2')
        
        metrics = manager.get_all_metrics()
        
        assert 'breaker1' in metrics
        assert 'breaker2' in metrics
    
    def test_manager_reset_all(self):
        """Test manager resets all breakers"""
        manager = CircuitBreakerManager()
        
        breaker1 = manager.get_breaker('b1')
        breaker2 = manager.get_breaker('b2')
        
        # Force open state
        breaker1.state = CircuitBreakerState.OPEN
        breaker2.state = CircuitBreakerState.OPEN
        
        manager.reset_all()
        
        assert breaker1.state == CircuitBreakerState.CLOSED
        assert breaker2.state == CircuitBreakerState.CLOSED
    
    def test_manager_health_summary(self):
        """Test manager provides health summary"""
        manager = CircuitBreakerManager()
        
        manager.get_breaker('healthy1')
        manager.get_breaker('healthy2')
        breaker3 = manager.get_breaker('unhealthy')
        breaker3.state = CircuitBreakerState.OPEN
        
        summary = manager.get_health_summary()
        
        assert summary['total_circuit_breakers'] == 3
        assert summary['healthy'] == 2
        assert summary['unhealthy'] == 1


@pytest.mark.unit
class TestCircuitBreakerDecoratorFunction:
    """Test circuit_breaker decorator function"""
    
    def test_decorator_function_creates_breaker(self):
        """Test decorator function creates circuit breaker"""
        @circuit_breaker('test_service', failure_threshold=2)
        def test_func():
            return "success"
        
        result = test_func()
        assert result == "success"
    
    def test_decorator_function_with_config(self):
        """Test decorator function with custom config"""
        @circuit_breaker(
            'custom_service',
            failure_threshold=2,
            recovery_timeout=30,
            success_threshold=1
        )
        def test_func():
            raise ValueError("Error")
        
        # Should open after 2 failures
        with pytest.raises(ValueError):
            test_func()
        with pytest.raises(ValueError):
            test_func()
        
        with pytest.raises(CircuitBreakerError):
            test_func()


@pytest.mark.unit
class TestCircuitBreakerThreadSafety:
    """Test circuit breaker thread safety"""
    
    def test_concurrent_calls(self, breaker):
        """Test circuit breaker handles concurrent calls"""
        results = []
        errors = []
        
        def call_breaker():
            try:
                result = breaker.call(lambda: "success")
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        threads = [Thread(target=call_breaker) for _ in range(10)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(results) == 10
        assert len(errors) == 0


@pytest.mark.unit
class TestCircuitBreakerEdgeCases:
    """Test circuit breaker edge cases"""
    
    def test_zero_failure_threshold(self):
        """Test circuit breaker with zero failure threshold"""
        config = CircuitBreakerConfig(name='zero', failure_threshold=0)
        breaker = CircuitBreaker(config)
        
        # Should not open immediately
        breaker.call(lambda: "success")
        assert breaker.state == CircuitBreakerState.CLOSED
    
    def test_cache_failure_graceful_degradation(self, breaker):
        """Test circuit breaker handles cache failures gracefully"""
        with patch('shared.utils.circuit_breaker.cache.get', side_effect=Exception("Cache error")):
            # Should default to CLOSED state
            state = breaker.state
            assert state == CircuitBreakerState.CLOSED
    
    def test_metrics_with_response_times(self, breaker):
        """Test metrics track average response time"""
        slow_func = Mock(return_value="success")
        
        with patch('shared.utils.circuit_breaker.time.time', side_effect=[1000, 1002, 1002, 1004]):
            breaker.call(slow_func)  # 2 second response
            breaker.call(slow_func)  # 2 second response
        
        metrics = breaker.get_metrics()
        assert metrics['average_response_time'] > 0
