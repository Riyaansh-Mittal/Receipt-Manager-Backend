from typing import TYPE_CHECKING
import logging
from importlib import import_module
from typing import Any


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from receipt_service.services.receipt_service import ReceiptService
    from receipt_service.services.file_service import FileService
    from receipt_service.services.category_service import CategoryService
    from .ocr_service import OCRService
    from .processing_pipeline import ProcessingPipelineService


class ServiceImportService:
    """
    Centralized service imports for AI service
    Provides lazy loading of services to avoid circular imports
    """
    
    def __init__(self):
        self._receipt_service = None
        self._file_service = None
        self._category_service = None
        self._cache_service = None
        self._ocr_service = None
        self._processing_pipeline_service = None
    
    @property
    def receipt_service(self) -> 'ReceiptService':
        """Get receipt service instance"""
        if self._receipt_service is None:
            try:
                from receipt_service.services.receipt_import_service import service_import
                self._receipt_service = service_import.receipt_service
            except ImportError as e:
                logger.error(f"Failed to import receipt service: {e}")
                raise ImportError("Could not import receipt service") from e
        return self._receipt_service
    
    @property
    def file_service(self) -> 'FileService':
        """Get file service instance"""
        if self._file_service is None:
            try:
                from receipt_service.services.receipt_import_service import service_import
                self._file_service = service_import.file_service
            except ImportError as e:
                logger.error(f"Failed to import file service: {e}")
                raise ImportError("Could not import file service") from e
        return self._file_service
    
    @property
    def category_service(self) -> 'CategoryService':
        """Get category service instance"""
        if self._category_service is None:
            try:
                from receipt_service.services.receipt_import_service import service_import
                self._category_service = service_import.category_service
            except ImportError as e:
                logger.error(f"Failed to import category service: {e}")
                raise ImportError("Could not import category service") from e
        return self._category_service
    
    @property
    def cache_service(self):
        """Get Django cache service instance"""
        if self._cache_service is None:
            try:
                module = import_module('django.core.cache')
                self._cache_service = module.cache
            except ImportError as e:
                logger.error(f"Failed to import Django cache service: {e}")
                raise ImportError("Could not import Django cache service") from e
        return self._cache_service
    
    @property
    def ocr_service(self) -> 'OCRService':
        """Get OCR service instance"""
        if self._ocr_service is None:
            from .ocr_service import OCRService
            self._ocr_service = OCRService()
        return self._ocr_service
    
    @property
    def processing_pipeline_service(self) -> 'ProcessingPipelineService':
        """Get processing pipeline service instance"""
        if self._processing_pipeline_service is None:
            from .processing_pipeline import ProcessingPipelineService
            self._processing_pipeline_service = ProcessingPipelineService()
        return self._processing_pipeline_service
    
    def get_service(self, module_path: str, class_name: str) -> Any:
        """Dynamic service import"""
        try:
            module = import_module(module_path)
            return getattr(module, class_name)()
        except (ImportError, AttributeError) as e:
            logger.error(f"Failed to import {class_name} from {module_path}: {e}")
            raise ImportError(f"Failed to import {class_name} from {module_path}: {str(e)}")


# Global service import instance
service_import = ServiceImportService()