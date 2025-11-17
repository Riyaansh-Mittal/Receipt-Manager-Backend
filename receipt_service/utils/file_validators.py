import hashlib
import mimetypes
import magic
from PIL import Image
from django.conf import settings
from typing import Dict, Any, Optional
from .exceptions import (
    InvalidFileFormatException,
    FileSizeExceededException,
    DuplicateReceiptException
)

import logging
logger = logging.getLogger(__name__)

class ReceiptFileValidator:
    """Comprehensive file validation for receipt uploads"""
    
    # Move settings access to properties/methods instead of class-level constants
    ALLOWED_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png']
    ALLOWED_MIME_TYPES = [
        'application/pdf',
        'image/jpeg',
        'image/png',
    ]
    
    # Image validation constants (these are static, no settings needed)
    MIN_IMAGE_WIDTH = 100
    MIN_IMAGE_HEIGHT = 100
    MAX_IMAGE_WIDTH = 10000
    MAX_IMAGE_HEIGHT = 10000
    
    def __init__(self):
        self.errors = []
    
    @property
    def MAX_FILE_SIZE(self):
        """Lazy load MAX_FILE_SIZE from settings"""
        return int(getattr(settings, 'RECEIPT_MAX_FILE_SIZE', 10 * 1024 * 1024))  # 10MB
    
    # Rest of your methods remain the same, just replace self.MAX_FILE_SIZE references
    def validate_file(self, uploaded_file) -> Dict[str, Any]:
        """
        Comprehensive file validation
        Returns file metadata if valid, raises exception if invalid
        """
        self.errors = []
        
        try:
            # Basic validations
            self._validate_file_size(uploaded_file)
            filename = uploaded_file.name
            self._validate_file_extension(filename)
            
            # Content validations
            mime_type = self._validate_mime_type(uploaded_file)
            
            # Additional content-specific validation
            if mime_type.startswith('image/'):
                self._validate_image_content(uploaded_file)
            elif mime_type == 'application/pdf':
                self._validate_pdf_content(uploaded_file)
            
            # Generate file hash for duplicate detection
            file_hash = self._generate_file_hash(uploaded_file)
            
            # Return validation result
            return {
                'filename': filename,
                'size': uploaded_file.size,
                'mime_type': mime_type,
                'file_hash': file_hash,
                'extension': self._get_file_extension(filename)
            }
            
        except (InvalidFileFormatException, FileSizeExceededException, DuplicateReceiptException) as e:
            logger.error(f"File validation error: {str(e)}")
            raise
        
        except Exception as e:
            logger.error(f"Unexpected validation error: {str(e)}", exc_info=True)
            raise InvalidFileFormatException(
                detail="File validation failed",
                context={'error': str(e)}
            )
    
    def _get_file_extension(self, filename: str) -> str:
        """Extract file extension from filename"""
        return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    
    def _validate_file_size(self, uploaded_file):
        """Validate file size is within acceptable limits"""
        if uploaded_file.size > self.MAX_FILE_SIZE:
            raise FileSizeExceededException(
                detail=f"File too large. Maximum size: {self.MAX_FILE_SIZE / (1024*1024):.1f}MB",
                context={
                    'max_size_mb': self.MAX_FILE_SIZE / (1024*1024),
                    'actual_size_bytes': uploaded_file.size
                }
            )
    
    def _validate_file_extension(self, filename: str):
        """Validate file extension is in allowed list"""
        extension = self._get_file_extension(filename)
        
        if extension not in self.ALLOWED_EXTENSIONS:
            raise InvalidFileFormatException(
                detail=f"Invalid file extension. Allowed: {', '.join(self.ALLOWED_EXTENSIONS)}",
                context={
                    'allowed_extensions': self.ALLOWED_EXTENSIONS,
                    'provided_extension': extension
                }
            )
    
    def _validate_mime_type(self, uploaded_file) -> str:
        """Validate MIME type using python-magic"""
        try:
            # Read first 1KB for MIME detection
            file_start = uploaded_file.read(1024)
            uploaded_file.seek(0)
            
            # Detect MIME type using magic
            mime_type = magic.from_buffer(file_start, mime=True)
            
            if mime_type not in self.ALLOWED_MIME_TYPES:
                raise InvalidFileFormatException(
                    detail=f"Invalid file type detected: {mime_type}",
                    context={
                        'detected_mime_type': mime_type,
                        'allowed_mime_types': self.ALLOWED_MIME_TYPES
                    }
                )
            
            return mime_type
            
        except Exception as e:
            # Fallback to extension-based MIME type
            logger.warning(f"Magic MIME detection failed: {e}, falling back to extension")
            mime_type, _ = mimetypes.guess_type(uploaded_file.name)
            
            if mime_type not in self.ALLOWED_MIME_TYPES:
                raise InvalidFileFormatException(
                    detail="Unable to determine valid file type",
                    context={'filename': uploaded_file.name}
                )
            
            return mime_type
    
    def _validate_image_content(self, uploaded_file):
        """Validate image file can be opened and has valid dimensions"""
        try:
            uploaded_file.seek(0)
            with Image.open(uploaded_file) as img:
                width, height = img.size
                
                if width < self.MIN_IMAGE_WIDTH or height < self.MIN_IMAGE_HEIGHT:
                    raise InvalidFileFormatException(
                        detail=f"Image too small. Minimum: {self.MIN_IMAGE_WIDTH}x{self.MIN_IMAGE_HEIGHT}px",
                        context={
                            'min_width': self.MIN_IMAGE_WIDTH,
                            'min_height': self.MIN_IMAGE_HEIGHT,
                            'actual_width': width,
                            'actual_height': height
                        }
                    )
                
                if width > self.MAX_IMAGE_WIDTH or height > self.MAX_IMAGE_HEIGHT:
                    raise InvalidFileFormatException(
                        detail=f"Image too large. Maximum: {self.MAX_IMAGE_WIDTH}x{self.MAX_IMAGE_HEIGHT}px",
                        context={
                            'max_width': self.MAX_IMAGE_WIDTH,
                            'max_height': self.MAX_IMAGE_HEIGHT,
                            'actual_width': width,
                            'actual_height': height
                        }
                    )
            
            uploaded_file.seek(0)
            
        except Exception as e:
            uploaded_file.seek(0)
            raise InvalidFileFormatException(
                detail="Invalid or corrupted image file",
                context={'error': str(e)}
            )
    
    def _validate_pdf_content(self, uploaded_file):
        """Validate PDF file signature"""
        try:
            uploaded_file.seek(0)
            header = uploaded_file.read(4)
            uploaded_file.seek(0)
            
            if not header.startswith(b'%PDF'):
                raise InvalidFileFormatException(
                    detail="Invalid PDF file format",
                    context={'header': header.hex()}
                )
                
        except Exception as e:
            uploaded_file.seek(0)
            raise InvalidFileFormatException(
                detail="Unable to validate PDF content",
                context={'error': str(e)}
            )
    
    def _generate_file_hash(self, uploaded_file) -> str:
        """Generate SHA-256 hash for duplicate detection"""
        sha256_hash = hashlib.sha256()
        
        uploaded_file.seek(0)
        for byte_block in iter(lambda: uploaded_file.read(4096), b""):
            sha256_hash.update(byte_block)
        uploaded_file.seek(0)
        
        return sha256_hash.hexdigest()
    
    def check_duplicate_receipt(self, user, file_hash: str) -> Optional[str]:
        """
        Check if receipt with same hash already exists for user
        Returns receipt_id if duplicate found (for retry), None otherwise
        Raises DuplicateReceiptException if receipt already processed
        """
        from receipt_service.services.receipt_import_service import model_service
        from ai_service.services.ai_import_service import model_service as ai_model_service
        from django.utils import timezone
        from datetime import timedelta
        
        # Check if receipt with same hash exists
        existing_receipt = model_service.receipt_model.objects.filter(
            user=user,
            file_hash=file_hash
        )
        
        if not existing_receipt.exists():
            return None
        
        receipt = existing_receipt.first()
        
        # Check processing status
        processing_job = ai_model_service.processing_job_model.objects.filter(
            receipt=receipt
        ).first()
        
        if processing_job:
            # If processing failed, allow retry
            if processing_job.status == 'failed':
                logger.info(f"Allowing retry for failed receipt: {receipt.id}")
                return str(receipt.id)
            
            # If processing stuck (> 5 minutes), allow retry
            if processing_job.status == 'processing':
                time_elapsed = timezone.now() - processing_job.created_at
                if time_elapsed > timedelta(minutes=5):
                    logger.warning(f"Processing stuck for receipt {receipt.id}, allowing retry")
                    return str(receipt.id)
            
            # If completed or pending, it's a duplicate
            if processing_job.status in ['completed', 'pending']:
                raise DuplicateReceiptException(
                    detail="This receipt has already been uploaded and processed",
                    context={
                        'receipt_id': str(receipt.id),
                        'status': processing_job.status,
                        'uploaded_at': receipt.created_at.isoformat()
                    }
                )
        
        # If no processing job but receipt exists (edge case)
        if receipt.status not in ['pending', 'processing']:
            raise DuplicateReceiptException(
                detail="This receipt has already been uploaded",
                context={
                    'receipt_id': str(receipt.id),
                    'status': receipt.status
                }
            )
        
        return str(receipt.id)
