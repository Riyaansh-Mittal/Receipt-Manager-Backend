# receipt_service/utils/storage_backends.py

import os
from django.core.files.storage import FileSystemStorage
from django.conf import settings
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ReceiptFileStorage:
    """
    File storage handler for receipts
    
    Files are stored directly in MEDIA_ROOT with paths from FileField's upload_to
    NO additional 'receipts/' prefix is added here
    """
    
    def __init__(self):
        self.use_s3 = getattr(settings, 'USE_S3_STORAGE', False)
        
        if self.use_s3:
            # S3 Storage for production
            try:
                from storages.backends.s3boto3 import S3Boto3Storage
                
                self.storage = S3Boto3Storage(
                    bucket_name=getattr(settings, 'AWS_STORAGE_BUCKET_NAME'),
                    location='',  # No prefix - path comes from FileField
                    file_overwrite=False,
                    default_acl='private',
                )
                logger.info("Using S3 storage for receipts")
            except ImportError:
                logger.warning("S3 storage not available, falling back to local storage")
                self.use_s3 = False
                self.storage = self._get_local_storage()
        
        else:
            # Local filesystem storage for dev
            self.storage = self._get_local_storage()
    
    def _get_local_storage(self) -> FileSystemStorage:
        """Get local filesystem storage"""
        media_root = settings.MEDIA_ROOT
        media_url = settings.MEDIA_URL
        
        # Ensure MEDIA_ROOT exists
        os.makedirs(media_root, exist_ok=True)
        
        logger.info(f"Using local storage for receipts at: {media_root}")
        
        return FileSystemStorage(
            location=media_root,
            base_url=media_url
        )
    
    def save(self, name: str, content, max_length: Optional[int] = None) -> str:
        """
        Save file and return the saved path
        
        Args:
            name: Relative path from MEDIA_ROOT (e.g., 'user_id/2025/10/04/uuid.png')
            content: File content
            max_length: Maximum length for the filename
            
        Returns:
            Saved file path relative to MEDIA_ROOT
        """
        saved_path = self.storage.save(name, content, max_length)
        logger.debug(f"File saved to: {saved_path}")
        return saved_path
    
    def delete(self, name: str) -> bool:
        """
        Delete file from storage
        
        Args:
            name: File path relative to MEDIA_ROOT
            
        Returns:
            True if successful
        """
        try:
            if self.exists(name):
                self.storage.delete(name)
                logger.info(f"File deleted: {name}")
                return True
            else:
                logger.warning(f"File not found for deletion: {name}")
                return False
        except Exception as e:
            logger.error(f"Failed to delete file {name}: {str(e)}")
            return False
    
    def exists(self, name: str) -> bool:
        """
        Check if file exists in storage
        
        Args:
            name: File path relative to MEDIA_ROOT
            
        Returns:
            True if file exists
        """
        try:
            return self.storage.exists(name)
        except Exception as e:
            logger.error(f"Error checking file existence {name}: {str(e)}")
            return False
    
    def url(self, name: str) -> str:
        """
        Get file URL
        
        Args:
            name: File path relative to MEDIA_ROOT
            
        Returns:
            Accessible URL for the file
        """
        try:
            return self.storage.url(name)
        except Exception as e:
            logger.error(f"Error generating URL for {name}: {str(e)}")
            return None
    
    def size(self, name: str) -> int:
        """Get file size in bytes"""
        try:
            return self.storage.size(name)
        except Exception as e:
            logger.error(f"Error getting size for {name}: {str(e)}")
            return 0
    
    def get_modified_time(self, name: str):
        """Get file modification time"""
        try:
            return self.storage.get_modified_time(name)
        except Exception as e:
            logger.error(f"Error getting modified time for {name}: {str(e)}")
            return None
    
    def get_absolute_path(self, name: str) -> str:
        """
        Get absolute filesystem path (local storage only)
        
        Args:
            name: File path relative to MEDIA_ROOT
            
        Returns:
            Absolute filesystem path
        """
        if not self.use_s3:
            return os.path.join(settings.MEDIA_ROOT, name)
        return None
    
    def generate_signed_url(self, name: str, expires_in: int = 3600) -> str:
        """
        Generate signed URL for secure access
        
        Args:
            name: File path relative to MEDIA_ROOT
            expires_in: URL expiration time in seconds
            
        Returns:
            Signed URL (for S3) or regular URL (for local storage)
        """
        if self.use_s3:
            try:
                # Generate presigned URL for S3
                return self.storage.connection.meta.client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': self.storage.bucket_name, 
                        'Key': name
                    },
                    ExpiresIn=expires_in
                )
            except Exception as e:
                logger.error(f"Failed to generate signed URL for {name}: {str(e)}")
                return self.url(name)
        else:
            # For local storage, return regular URL
            return self.url(name)


# Global storage instance
receipt_storage = ReceiptFileStorage()
