import uuid
from django.db import models
from django.utils.text import slugify
from django.db.models import F
from django.db import transaction
from django.utils import timezone

class Category(models.Model):
    """Fixed expense categories for receipt classification"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    icon = models.CharField(max_length=10, help_text="Emoji icon")
    color = models.CharField(max_length=7, help_text="Hex color code")
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'receipt_categories'
        ordering = ['display_order', 'name']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active', 'display_order']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            suffix = 1
            
            # Use atomic transaction with select_for_update
            with transaction.atomic():
                while Category.objects.filter(slug=slug).exists():
                    suffix += 1
                    slug = f"{base_slug}-{suffix}"
                self.slug = slug
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.icon} {self.name}"


class UserCategoryPreference(models.Model):
    """Track user's category usage patterns for better AI suggestions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'auth_service.User', 
        on_delete=models.CASCADE, 
        related_name='category_preferences'
    )
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    usage_count = models.PositiveIntegerField(default=0)
    last_used = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'receipt_user_category_preferences'
        unique_together = ['user', 'category']
        indexes = [
            models.Index(fields=['user', '-usage_count']),
            models.Index(fields=['user', '-last_used']),
        ]
    
    def increment_usage(self):
        """Increment usage count safely with F() expression"""
        self.usage_count = F('usage_count') + 1
        self.last_used = timezone.now()
        self.save(update_fields=['usage_count', 'last_used'])
        # Refresh to get actual value
        self.refresh_from_db(fields=['usage_count'])
    
    def __str__(self):
        return f"{self.user.email} -> {self.category.name} ({self.usage_count}x)"
