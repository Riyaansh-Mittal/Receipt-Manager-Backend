import time
import logging
from django.core.cache import cache
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings

logger = logging.getLogger(__name__)

class SecurityMiddleware(MiddlewareMixin):
    """
    Enhanced security middleware for authentication endpoints
    """
    
    def __init__(self, get_response):
        super().__init__(get_response)
        self.max_requests_per_ip = getattr(settings, 'MAX_REQUESTS_PER_IP_PER_MINUTE', 60)
        self.max_auth_requests_per_ip = getattr(settings, 'MAX_AUTH_REQUESTS_PER_IP_PER_MINUTE', 10)
        
    def process_request(self, request):
        """Process incoming request for security checks"""
        
        # Get client IP
        ip_address = self._get_client_ip(request)
        
        # Apply rate limiting
        if self._is_rate_limited(request, ip_address):
            return JsonResponse({
                'error': {
                    'code': 'rate_limit_exceeded',
                    'message': 'Too many requests. Please try again later.',
                    'status_code': 429
                }
            }, status=429)
        
        # Add security headers
        request.client_ip = ip_address
        
        return None
    
    def process_response(self, request, response):
        """Add security headers to response"""
        
        # Security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Content-Security-Policy'] = "default-src 'self'"
        
        # CORS headers for API
        if request.path.startswith('/api/'):
            allowed_origins = getattr(settings, 'ALLOWED_CORS_ORIGINS', ['https://857fff45a9c4.ngrok-free.app'])
            origin = request.META.get('HTTP_ORIGIN')
            
            if origin in allowed_origins:
                response['Access-Control-Allow-Origin'] = origin
                response['Access-Control-Allow-Credentials'] = 'true'
                response['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
                response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        
        return response
    
    def _get_client_ip(self, request) -> str:
        """Extract client IP from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR', '0.0.0.0')
        return ip
    
    def _is_rate_limited(self, request, ip_address: str) -> bool:
        """Check if request should be rate limited"""
        
        # Different limits for different endpoints
        if request.path.startswith('/auth/'):
            max_requests = int(self.max_auth_requests_per_ip)
            window_key = f"rate_limit_auth:{ip_address}"
        else:
            max_requests = int(self.max_requests_per_ip)
            window_key = f"rate_limit_general:{ip_address}"
        
        # Sliding window rate limiting
        current_time = int(time.time())
        window_start = current_time - 60  # 1 minute window
        
        # Get current requests in window
        requests_in_window = cache.get(window_key, [])
        
        # Filter to current window
        requests_in_window = [req_time for req_time in requests_in_window if req_time > window_start]
        
        # Check limit
        if len(requests_in_window) >= max_requests:
            logger.warning(f"Rate limit exceeded for IP: {ip_address} on path: {request.path}")
            return True
        
        # Add current request
        requests_in_window.append(current_time)
        cache.set(window_key, requests_in_window, timeout=120)  # Cache for 2 minutes
        
        return False
    
    # In middleware/security_middleware.py - add this method

    def _check_user_authorization(self, request):
        """Check user authorization for protected resources"""
        if hasattr(request, 'user') and request.user.is_authenticated:
            
            # Check if user is deactivated
            if not request.user.is_active:
                return JsonResponse({
                    'error': {
                        'code': 'account_deactivated',
                        'message': 'Account has been deactivated',
                        'status_code': 403
                    }
                }, status=403)
        
        return None


class IPWhitelistMiddleware(MiddlewareMixin):
    """
    Middleware to whitelist specific IPs for admin access
    """
    
    def __init__(self, get_response):
        super().__init__(get_response)
        self.whitelisted_ips = getattr(settings, 'ADMIN_WHITELISTED_IPS', [])
    
    def process_request(self, request):
        """Check IP whitelist for admin paths"""
        
        if not self.whitelisted_ips:
            return None
            
        if request.path.startswith('/admin/') or request.path.startswith('/api/admin/'):
            client_ip = self._get_client_ip(request)
            
            if client_ip not in self.whitelisted_ips:
                logger.warning(f"Blocked admin access from non-whitelisted IP: {client_ip}")
                return JsonResponse({
                    'error': {
                        'code': 'access_denied',
                        'message': 'Access denied from this IP address',
                        'status_code': 403
                    }
                }, status=403)
        
        return None
    
    def _get_client_ip(self, request) -> str:
        """Extract client IP from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR', '0.0.0.0')
        return ip
