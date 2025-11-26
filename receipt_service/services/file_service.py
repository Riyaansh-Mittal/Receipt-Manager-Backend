# receipt_service/services/file_service.py

import logging
from typing import Dict, Any, Optional
from io import BytesIO
from django.utils import timezone
from pathlib import Path
from uuid import uuid4
from django.db import transaction
from PIL import Image

from .receipt_model_service import model_service
from ..utils.file_validators import ReceiptFileValidator
from ..utils.storage_backends import receipt_storage
from ..utils.exceptions import (
    FileUploadException,
    FileStorageException,
    FileRetrievalException,
    FileDeletionException,
    DuplicateReceiptException,
)
from shared.utils.exceptions import DatabaseOperationException

logger = logging.getLogger(__name__)


class FileService:
    """
    File handling service for receipt uploads
    Handles upload, validation, storage, and retrieval using Django's FileField
    """
    
    def __init__(self):
        self.validator = ReceiptFileValidator()
    
    def store_receipt_file(
        self, 
        user, 
        uploaded_file, 
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Store receipt file with validation
        
        Args:
            user: User instance
            uploaded_file: Uploaded file object
            metadata: Optional metadata dict with ip_address, etc.
            
        Returns:
            Dict with receipt_id, storage_path, file_info, and receipt instance
            
        Raises:
            DuplicateReceiptException: If file hash already exists for user
            FileStorageException: If file storage fails
            DatabaseOperationException: If database operation fails
        """
        try:
            # Validate file (fail-fast)
            file_info = self.validator.validate_file(uploaded_file)
            
            # Check for duplicates (returns existing receipt_id if retry needed)
            existing_receipt_id = self.validator.check_duplicate_receipt(
                user, 
                file_info['file_hash']
            )

            # If existing failed receipt found, return it for retry
            if existing_receipt_id:
                logger.info(f"Reusing failed receipt {existing_receipt_id} for retry")
                
                # Get the existing receipt
                receipt = model_service.receipt_model.objects.get(id=existing_receipt_id)
                
                # Reset status to queued for retry
                receipt.status = 'queued'
                receipt.processing_started_at = None
                receipt.processing_completed_at = None
                receipt.save(update_fields=[
                    'status', 
                    'processing_started_at', 
                    'processing_completed_at'
                ])
                
                return {
                    'receipt_id': str(receipt.id),
                    'storage_path': receipt.file_path,
                    'file_info': file_info,
                    'is_retry': True,
                    'receipt': receipt
                }
            
            with transaction.atomic():
                # Extract metadata
                additional_metadata = metadata or {}
                
                # Create receipt record
                # Only set: user, file info, status (simplified Receipt model!)
                try:

                    # ✅ STEP 1: Save file using receipt_storage BEFORE creating Receipt
                    # Generate a unique path (same as Django's FileField upload_to)
                    storage_path = receipt_storage.save(
                        f"{user.id}/{timezone.now().year}/{timezone.now().month:02d}/{timezone.now().day:02d}/{uuid4()}{Path(uploaded_file.name).suffix}",
                        uploaded_file
                    )

                    # ✅ STEP 2: Create Receipt with the path from receipt_storage
                    receipt = model_service.receipt_model.objects.create(
                        user=user,
                        original_filename=file_info['filename'],
                        file_path=storage_path,  # ✅ Use path from receipt_storage
                        file_size=file_info['size'],
                        mime_type=file_info['mime_type'],
                        file_hash=file_info['file_hash'],
                        status='uploaded',
                        upload_ip_address=additional_metadata.get('ip_address'),
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to create receipt record for user {user.id}: {str(e)}",
                        exc_info=True
                    )
                    raise DatabaseOperationException(
                        detail="Failed to create receipt record",
                        context={
                            'user_id': str(user.id), 
                            'filename': file_info['filename'],
                            'error': str(e)
                        }
                    )
                
                logger.info(
                    f"Receipt file stored: {receipt.id} for user {user.id} at {storage_path}"
                )
                
                return {
                    'receipt_id': receipt.id,
                    'storage_path': storage_path,
                    'file_info': file_info,
                    'is_retry': False,
                    'receipt': receipt
                }
                
        except (DuplicateReceiptException, FileUploadException, DatabaseOperationException):
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error storing receipt for user {user.id}: {str(e)}", 
                exc_info=True
            )
            raise FileStorageException(
                detail="Unexpected error storing receipt file",
                context={'user_id': str(user.id), 'error': str(e)}
            )
    
    def get_secure_file_url(self, receipt, expires_in: int = 3600) -> Optional[str]:
        """
        Get secure URL for receipt file
        
        Args:
            receipt: Receipt model instance
            expires_in: URL expiration time in seconds (default: 1 hour)
            
        Returns:
            Signed URL string
            
        Raises:
            FileRetrievalException: If URL generation fails
        """
        try:
            # Validate receipt has file
            if not receipt.file_path:
                raise FileRetrievalException(
                    detail="Receipt file not found",
                    context={'receipt_id': str(receipt.id)}
                )
            
            # Check file exists in storage (use receipt_storage wrapper)
            if not receipt_storage.exists(receipt.file_path):
                raise FileRetrievalException(
                    detail="File does not exist in storage",
                    context={
                        'receipt_id': str(receipt.id),
                        'storage_path': receipt.file_path
                    }
                )
            
            # Generate signed URL (pass string path directly)
            url = receipt_storage.generate_signed_url(
                receipt.file_path,  # ✅ Just the string path
                expires_in=expires_in
            )
            
            return url
            
        except FileRetrievalException:
            raise
        except Exception as e:
            logger.error(
                f"Failed to generate URL for receipt {receipt.id}: {str(e)}",
                exc_info=True
            )
            raise FileRetrievalException(
                detail="Failed to generate secure file URL",
                context={'receipt_id': str(receipt.id), 'error': str(e)}
            )
    
    def get_file_content(self, receipt) -> bytes:
        """
        Get file content from storage
        
        Args:
            receipt: Receipt model instance
            
        Returns:
            File content as bytes
            
        Raises:
            FileRetrievalException: If file cannot be retrieved
        """
        try:
            if not hasattr(receipt, 'file_path') or not receipt.file_path:
                raise FileRetrievalException(
                    detail="Receipt has no file",
                    context={'receipt_id': str(receipt.id)}
                )
            
            # Check file exists
            if not receipt.file_path.storage.exists(receipt.file_path):
                raise FileRetrievalException(
                    detail="File does not exist in storage",
                    context={
                        'receipt_id': str(receipt.id),
                        'storage_path': receipt.file_path
                    }
                )
            
            # Read file
            with receipt.file_path.open('rb') as f:
                content = f.read()
            
            logger.debug(f"Retrieved {len(content)} bytes for receipt {receipt.id}")
            return content
            
        except FileRetrievalException:
            raise
        except Exception as e:
            logger.error(
                f"Failed to retrieve file for receipt {receipt.id}: {str(e)}",
                exc_info=True
            )
            raise FileRetrievalException(
                detail="Failed to retrieve file content",
                context={'receipt_id': str(receipt.id)}
            )
    
    def delete_receipt_file(self, receipt) -> bool:
        """
        Delete receipt file from storage
        
        Args:
            receipt: Receipt model instance
            
        Returns:
            True if deletion successful
            
        Raises:
            FileDeletionException: If deletion fails
        """
        try:
            if not hasattr(receipt, 'file_path') or not receipt.file_path:
                logger.warning(f"Receipt {receipt.id} has no file to delete")
                return True
            
            storage_path = receipt.file_path
            
            # Delete using FileField's delete method
            receipt.file_path.delete(save=False)
            
            logger.info(f"Receipt file deleted: {receipt.id} (path: {storage_path})")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting file for receipt {receipt.id}: {str(e)}", exc_info=True)
            raise FileDeletionException(
                detail="Failed to delete receipt file",
                context={'receipt_id': str(receipt.id), 'error': str(e)}
            )
    
    def file_exists(self, receipt) -> bool:
        """Check if receipt file exists in storage"""
        try:
            if not hasattr(receipt, 'file_path') or not receipt.file_path:
                return False
            
            exists = receipt.file_path.storage.exists(receipt.file_path)
            
            if not exists:
                logger.warning(f"File missing for receipt {receipt.id}")
            
            return exists
            
        except Exception as e:
            logger.error(f"Failed to check file existence: {str(e)}")
            return False
    
    def get_file_metadata(self, receipt) -> Dict[str, Any]:
        """Get file metadata without downloading content"""
        try:
            if not hasattr(receipt, 'file_path') or not receipt.file_path:
                return {
                    'exists': False,
                    'size': 0,
                    'mime_type': None
                }
            
            return {
                'exists': self.file_exists(receipt),
                'storage_path': receipt.file_path,
                'size': receipt.file_size,
                'mime_type': receipt.mime_type,
                'original_filename': receipt.original_filename
            }
            
        except Exception as e:
            logger.error(f"Failed to get metadata: {str(e)}")
            return {'exists': False, 'error': str(e)}
    
    def generate_thumbnail(self, receipt, size: tuple = (200, 200)) -> Optional[BytesIO]:
        """
        Generate thumbnail for image receipts (in-memory, not saved)
        
        Args:
            receipt: Receipt model instance
            size: Thumbnail size (width, height)
            
        Returns:
            BytesIO with thumbnail image or None
        """
        if not receipt.mime_type or not receipt.mime_type.startswith('image/'):
            return None
        
        try:
            # Get file content
            file_content = self.get_file_content(receipt)
            
            # Create thumbnail
            with Image.open(BytesIO(file_content)) as img:
                img.thumbnail(size, Image.Resampling.LANCZOS)
                
                # Convert to bytes
                thumb_io = BytesIO()
                img.save(thumb_io, format='JPEG', quality=85)
                thumb_io.seek(0)
                
                return thumb_io
                    
        except Exception as e:
            logger.warning(f"Failed to generate thumbnail: {str(e)}")
            return None
