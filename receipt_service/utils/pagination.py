# receipt_service/utils/pagination.py
from shared.utils.pagination import LargeResultSetPagination, CachedPagination

class LargeResultSetPagination(LargeResultSetPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 500

class CachedPagination(CachedPagination):
    """Custom cached pagination for admin platform settings"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    cache_timeout = 300  # 5 minutes cache for admin data