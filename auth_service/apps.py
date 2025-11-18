# apps/auth_service/apps.py
from django.apps import AppConfig

class AuthServiceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'auth_service'
    label = 'auth_service'   # must match model_service references
    verbose_name = 'Authentication Service'
    
    def ready(self):
        """Initialize app when Django starts"""
        # Import signal handlers (if any)
        try:
            import auth_service.signals
        except ImportError:
            pass
        
        # Register custom authentication backend
        from django.conf import settings
        
        # Ensure our models are registered
        from . import models
