# # ai_service/services/ocr_service.py

# import pytesseract
# from pytesseract import TesseractError, TesseractNotFoundError
# import time
# import logging
# from typing import Dict, Any
# from PIL import Image
# import io

# from ..utils.image_preprocessing import image_preprocessor
# from ..utils.exceptions import (
#     OCRException,
#     OCRExtractionException,
#     OCRServiceUnavailableException,
#     ImagePreprocessingException,
#     ImageCorruptedException,
#     InvalidImageFormatException,
# )

# logger = logging.getLogger(__name__)


# class OCRService:
#     """Enhanced OCR service with preprocessing for receipts"""
    
#     def __init__(self):
#         # Optimal Tesseract config for receipts
#         # PSM 4 = Single column of variable-sized text (perfect for receipts)
#         # OEM 1 = Neural nets LSTM engine only
#         self.tesseract_config = r'--oem 1 --psm 4 -c preserve_interword_spaces=1'
#         self.min_confidence_threshold = 0.3
        
#         # Verify Tesseract is installed
#         self._verify_tesseract()
    
#     def _verify_tesseract(self) -> None:
#         """Verify Tesseract OCR is installed and accessible"""
#         try:
#             pytesseract.get_tesseract_version()
#             logger.info(f"Tesseract OCR found: {pytesseract.get_tesseract_version()}")
#         except TesseractNotFoundError:
#             logger.error("Tesseract OCR not found! Please install Tesseract.")
#             # Don't raise here - let it fail on first use with proper error
#         except Exception as e:
#             logger.warning(f"Could not verify Tesseract: {str(e)}")
    
#     def extract_text_from_image(
#         self, 
#         image_data: bytes, 
#         receipt_id: str
#     ) -> Dict[str, Any]:
#         """
#         Extract text from receipt image with preprocessing
        
#         Args:
#             image_data: Raw image bytes
#             receipt_id: Receipt identifier for logging
            
#         Returns:
#             Dict with extracted_text and confidence_score (NO preprocessing_steps)
            
#         Raises:
#             ImageCorruptedException: If image cannot be decoded
#             InvalidImageFormatException: If image format is not supported
#             ImagePreprocessingException: If preprocessing fails
#             OCRExtractionException: If OCR extraction fails
#             OCRServiceUnavailableException: If Tesseract is not installed
#         """
#         start_time = time.time()
        
#         try:
#             # Validate image data
#             if not image_data or len(image_data) == 0:
#                 raise InvalidImageFormatException(
#                     detail="Empty image data",
#                     context={'receipt_id': receipt_id}
#                 )
            
#             # Step 1: Preprocess image
#             logger.info(f"Preprocessing image for receipt {receipt_id}")
            
#             try:
#                 preprocessed_image, preprocessing_steps = image_preprocessor.preprocess_for_ocr(
#                     image_data
#                 )
#                 # Log preprocessing steps but don't store them
#                 logger.debug(f"Preprocessing steps applied: {preprocessing_steps}")
#             except (ImagePreprocessingException, ImageCorruptedException, InvalidImageFormatException):
#                 raise
#             except Exception as prep_error:
#                 logger.error(f"Preprocessing failed: {str(prep_error)}", exc_info=True)
#                 raise ImagePreprocessingException(
#                     detail="Image preprocessing failed",
#                     context={'receipt_id': receipt_id, 'error': str(prep_error)}
#                 )
            
#             # Step 2: Convert to PIL Image
#             try:
#                 image = Image.open(io.BytesIO(preprocessed_image))
#             except Exception as img_error:
#                 logger.error(f"Failed to open image: {str(img_error)}")
#                 raise ImageCorruptedException(
#                     detail="Failed to decode preprocessed image",
#                     context={'receipt_id': receipt_id, 'error': str(img_error)}
#                 )
            
#             # Step 3: Perform OCR
#             logger.info(f"Performing OCR for receipt {receipt_id}")
            
#             try:
#                 extracted_text = pytesseract.image_to_string(
#                     image,
#                     config=self.tesseract_config
#                 )
#             except TesseractNotFoundError:
#                 logger.error("Tesseract not found on system")
#                 raise OCRServiceUnavailableException(
#                     detail="Tesseract OCR is not installed or not in PATH",
#                     context={'receipt_id': receipt_id}
#                 )
#             except TesseractError as tess_error:
#                 logger.error(f"Tesseract error: {str(tess_error)}")
#                 raise OCRExtractionException(
#                     detail="OCR text extraction failed",
#                     context={'receipt_id': receipt_id, 'error': str(tess_error)}
#                 )
#             except Exception as ocr_error:
#                 logger.error(f"OCR failed: {str(ocr_error)}", exc_info=True)
#                 raise OCRExtractionException(
#                     detail="Unexpected OCR error",
#                     context={'receipt_id': receipt_id, 'error': str(ocr_error)}
#                 )
            
#             # Step 4: Get confidence score
#             confidence_score = self._calculate_confidence(image, extracted_text)
            
#             # Step 5: Clean extracted text
#             cleaned_text = self._clean_ocr_text(extracted_text)
            
#             # Check if we got meaningful text
#             if not cleaned_text or len(cleaned_text) < 10:
#                 logger.warning(
#                     f"Very short OCR output for receipt {receipt_id}: {len(cleaned_text)} chars"
#                 )
            
#             processing_time = time.time() - start_time
            
#             # Return ONLY fields that exist in OCRResult model!
#             result = {
#                 'extracted_text': cleaned_text,
#                 'confidence_score': round(confidence_score, 2),
#                 # DO NOT include: preprocessing_steps, character_count, word_count
#             }
            
#             logger.info(
#                 f"OCR completed for receipt {receipt_id} in {processing_time:.2f}s "
#                 f"with confidence {confidence_score:.2f} ({len(cleaned_text)} chars)"
#             )
            
#             return result
            
#         except (ImageCorruptedException, InvalidImageFormatException, 
#                 ImagePreprocessingException, OCRExtractionException, 
#                 OCRServiceUnavailableException):
#             raise
            
#         except Exception as e:
#             logger.error(
#                 f"OCR processing failed for receipt {receipt_id}: {str(e)}", 
#                 exc_info=True
#             )
#             raise OCRException(
#                 detail="OCR processing failed unexpectedly",
#                 context={'receipt_id': receipt_id, 'error': str(e)}
#             )
    
#     def _calculate_confidence(self, image: Image, extracted_text: str) -> float:
#         """Calculate OCR confidence score"""
#         try:
#             # Get word-level confidence from Tesseract
#             ocr_data = pytesseract.image_to_data(
#                 image,
#                 output_type=pytesseract.Output.DICT,
#                 config=self.tesseract_config
#             )
            
#             # Calculate average confidence from word-level confidence scores
#             confidences = [
#                 int(conf) for conf in ocr_data['conf'] 
#                 if conf != '-1' and int(conf) > 0
#             ]
            
#             if confidences:
#                 avg_confidence = sum(confidences) / len(confidences)
#                 confidence = avg_confidence / 100.0
                
#                 logger.debug(
#                     f"OCR confidence: {confidence:.2f} "
#                     f"({len(confidences)} words with confidence)"
#                 )
                
#                 return confidence
            
#             # Fallback: estimate based on text characteristics
#             return self._estimate_confidence_from_text(extracted_text)
                
#         except Exception as e:
#             logger.warning(f"Failed to calculate confidence: {str(e)}")
#             # Return conservative estimate
#             return self._estimate_confidence_from_text(extracted_text)
    
#     def _estimate_confidence_from_text(self, text: str) -> float:
#         """
#         Estimate confidence based on text characteristics
#         Used as fallback when word-level confidence is unavailable
#         """
#         if not text or len(text) < 5:
#             return 0.1
        
#         # Calculate metrics
#         alphanumeric_count = sum(c.isalnum() for c in text)
#         total_chars = len(text)
#         alphanumeric_ratio = alphanumeric_count / total_chars if total_chars > 0 else 0
        
#         # Words vs total characters (spacing indicator)
#         words = text.split()
#         word_count = len(words)
#         avg_word_length = alphanumeric_count / word_count if word_count > 0 else 0
        
#         # Base confidence on multiple factors
#         confidence = 0.3  # Base confidence
        
#         # Add confidence based on alphanumeric ratio (should be high for receipts)
#         confidence += alphanumeric_ratio * 0.3
        
#         # Add confidence based on length (more text = more confidence)
#         if total_chars > 200:
#             confidence += 0.2
#         elif total_chars > 100:
#             confidence += 0.15
#         elif total_chars > 50:
#             confidence += 0.1
        
#         # Add confidence based on reasonable word length
#         if 3 <= avg_word_length <= 10:
#             confidence += 0.1
        
#         return min(confidence, 0.95)  # Cap at 0.95 for estimates
    
#     def _clean_ocr_text(self, text: str) -> str:
#         """
#         Clean OCR text by removing excessive whitespace and artifacts
#         Keep structure for better Gemini parsing
#         """
#         if not text:
#             return ""
        
#         # Split into lines
#         lines = text.split('\n')
        
#         # Clean each line
#         cleaned_lines = []
#         for line in lines:
#             line = line.strip()
            
#             # Skip lines with only special characters or very short
#             if len(line) < 2:
#                 continue
            
#             # Skip lines that are just symbols/noise
#             if all(not c.isalnum() for c in line):
#                 continue
            
#             cleaned_lines.append(line)
        
#         # Join with single newlines
#         cleaned = '\n'.join(cleaned_lines)
        
#         return cleaned


# # Global instance
# ocr_service = OCRService()

"""
OCR Service with pluggable engine support (Tesseract/PaddleOCR)
Enterprise-ready implementation with Strategy Pattern
"""

import time
import logging
from typing import Dict, Any, Protocol
from abc import ABC, abstractmethod
from PIL import Image
import io
from django.conf import settings

from ..utils.image_preprocessing import image_preprocessor
from ..utils.exceptions import (
    OCRException,
    OCRExtractionException,
    OCRServiceUnavailableException,
    ImagePreprocessingException,
    ImageCorruptedException,
    InvalidImageFormatException,
)

logger = logging.getLogger(__name__)


# ============================================================================
# OCR Engine Interface (Strategy Pattern)
# ============================================================================

class OCREngine(ABC):
    """Abstract base class for OCR engines"""
    
    @abstractmethod
    def extract_text(self, image: Image.Image) -> Dict[str, Any]:
        """
        Extract text from image
        
        Returns:
            Dict with 'text' and 'confidence' keys
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if OCR engine is available"""
        pass
    
    @abstractmethod
    def get_engine_name(self) -> str:
        """Get engine name for logging"""
        pass


# ============================================================================
# Tesseract OCR Engine Implementation
# ============================================================================

# class TesseractOCREngine(OCREngine):
#     """Tesseract OCR implementation"""
    
#     def __init__(self):
#         import pytesseract
#         from pytesseract import TesseractError, TesseractNotFoundError
        
#         self.pytesseract = pytesseract
#         self.TesseractError = TesseractError
#         self.TesseractNotFoundError = TesseractNotFoundError
        
#         # Optimal config for receipts
#         # PSM 4 = Single column of variable-sized text
#         # OEM 1 = Neural nets LSTM engine
#         self.config = r'--oem 1 --psm 4 -c preserve_interword_spaces=1'
        
#         self._verify_installation()
    
#     def _verify_installation(self) -> None:
#         """Verify Tesseract is installed"""
#         try:
#             version = self.pytesseract.get_tesseract_version()
#             logger.info(f"Tesseract OCR initialized: v{version}")
#         except self.TesseractNotFoundError:
#             logger.error("Tesseract OCR not found! Please install Tesseract.")
#         except Exception as e:
#             logger.warning(f"Could not verify Tesseract: {str(e)}")
    
#     def is_available(self) -> bool:
#         """Check if Tesseract is available"""
#         try:
#             self.pytesseract.get_tesseract_version()
#             return True
#         except:
#             return False
    
#     def get_engine_name(self) -> str:
#         return "tesseract"
    
#     def extract_text(self, image: Image.Image) -> Dict[str, Any]:
#         """Extract text using Tesseract"""
#         try:
#             # Extract text
#             extracted_text = self.pytesseract.image_to_string(
#                 image,
#                 config=self.config
#             )
            
#             # Calculate confidence
#             confidence = self._calculate_confidence(image)
            
#             return {
#                 'text': extracted_text,
#                 'confidence': confidence
#             }
            
#         except self.TesseractNotFoundError:
#             raise OCRServiceUnavailableException(
#                 detail="Tesseract OCR is not installed or not in PATH"
#             )
#         except self.TesseractError as e:
#             raise OCRExtractionException(
#                 detail="Tesseract OCR extraction failed",
#                 context={'error': str(e)}
#             )
#         except Exception as e:
#             raise OCRExtractionException(
#                 detail="Unexpected Tesseract error",
#                 context={'error': str(e)}
#             )
    
#     def _calculate_confidence(self, image: Image.Image) -> float:
#         """Calculate confidence from Tesseract word-level data"""
#         try:
#             ocr_data = self.pytesseract.image_to_data(
#                 image,
#                 output_type=self.pytesseract.Output.DICT,
#                 config=self.config
#             )
            
#             # Get word-level confidences
#             confidences = [
#                 int(conf) for conf in ocr_data['conf']
#                 if conf != '-1' and int(conf) > 0
#             ]
            
#             if confidences:
#                 avg_confidence = sum(confidences) / len(confidences)
#                 return avg_confidence / 100.0
            
#             return 0.5
            
#         except Exception as e:
#             logger.warning(f"Failed to calculate Tesseract confidence: {str(e)}")
#             return 0.5


# ============================================================================
# PaddleOCR Engine Implementation
# ============================================================================

class PaddleOCREngine(OCREngine):
    """PaddleOCR implementation - PaddleOCR 3.x API"""
    
    def __init__(self):
        try:
            from paddleocr import PaddleOCR
            
            # PaddleOCR 3.x simplified initialization
            self.ocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False
            )
            
            self._available = True
            logger.info("PaddleOCR engine initialized successfully")
            
        except ImportError:
            logger.error("PaddleOCR not installed. Install with: pip install paddleocr")
            self._available = False
            self.ocr = None
            
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR: {str(e)}")
            self._available = False
            self.ocr = None
    
    def is_available(self) -> bool:
        return self._available and self.ocr is not None
    
    def get_engine_name(self) -> str:
        return "paddleocr"
    
    def extract_text(self, image: Image.Image) -> Dict[str, Any]:
        if not self.is_available():
            raise OCRServiceUnavailableException(
                detail="PaddleOCR is not available. Install with: pip install paddleocr"
            )
        
        try:
            import numpy as np
            image_np = np.array(image)
            
            # PaddleOCR 3.x returns a different structure
            result = self.ocr.predict(input=image_np)
            
            # Extract text from new result format
            if not result or len(result) == 0:
                return {'text': '', 'confidence': 0.0}
            
            # Parse the result based on PaddleOCR 3.x output format
            extracted_text = ""
            confidences = []
            
            for res in result:
                if hasattr(res, 'boxes'):
                    for box in res.boxes:
                        extracted_text += box.text + '\n'
                        confidences.append(box.score)
            
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            return {
                'text': extracted_text.strip(),
                'confidence': float(avg_confidence)
            }
            
        except Exception as e:
            logger.error(f"PaddleOCR extraction failed: {str(e)}", exc_info=True)
            raise OCRExtractionException(
                detail="PaddleOCR extraction failed",
                context={'error': str(e)}
            )

# ============================================================================
# OCR Service with Engine Selection
# ============================================================================

class OCRService:
    """
    Enhanced OCR service with pluggable engine support

    Supports:
    - Tesseract OCR (default, free, local)
    - PaddleOCR (better accuracy, free, local)

    Configure via settings.OCR_ENGINE ('tesseract' or 'paddleocr')
    """

    def __init__(self):
        self.min_confidence_threshold = 0.3
        self.engine = self._initialize_engine()
        if self.engine is None:
            raise OCRServiceUnavailableException("No OCR engine available.")
        logger.info(f"OCR Service initialized with engine: {self.engine.get_engine_name()}")

    def _initialize_engine(self) -> OCREngine:
        engine_name = getattr(settings, 'OCR_ENGINE', 'paddleocr').lower()

        if engine_name == 'paddleocr':
            engine = PaddleOCREngine()
            if engine.is_available():
                return engine
            else:
                logger.error("PaddleOCR not available or failed to initialize.")
                raise OCRServiceUnavailableException("PaddleOCR not available or failed to initialize.")

        else:
            logger.error(f"Unknown OCR engine configured: '{engine_name}'")
            raise OCRServiceUnavailableException(f"Unknown OCR engine configured: '{engine_name}'")
    
    def extract_text_from_image(
        self,
        image_data: bytes,
        receipt_id: str
    ) -> Dict[str, Any]:
        """
        Extract text from receipt image with preprocessing
        
        Args:
            image_data: Raw image bytes
            receipt_id: Receipt identifier for logging
        
        Returns:
            Dict with extracted_text and confidence_score
        
        Raises:
            ImageCorruptedException: If image cannot be decoded
            InvalidImageFormatException: If image format is not supported
            ImagePreprocessingException: If preprocessing fails
            OCRExtractionException: If OCR extraction fails
            OCRServiceUnavailableException: If OCR engine is not available
        """
        start_time = time.time()
        
        try:
            # Validate image data
            if not image_data or len(image_data) == 0:
                raise InvalidImageFormatException(
                    detail="Empty image data",
                    context={'receipt_id': receipt_id}
                )
            
            # Step 1: Preprocess image
            logger.info(
                f"Preprocessing image for receipt {receipt_id} "
                f"(engine: {self.engine.get_engine_name()})"
            )
            
            try:
                preprocessed_image, preprocessing_steps = \
                    image_preprocessor.preprocess_for_ocr(image_data)
                
                logger.debug(f"Preprocessing steps: {preprocessing_steps}")
                
            except (ImagePreprocessingException, ImageCorruptedException,
                    InvalidImageFormatException):
                raise
            except Exception as prep_error:
                logger.error(
                    f"Preprocessing failed: {str(prep_error)}",
                    exc_info=True
                )
                raise ImagePreprocessingException(
                    detail="Image preprocessing failed",
                    context={'receipt_id': receipt_id, 'error': str(prep_error)}
                )
            
            # Step 2: Convert to PIL Image
            try:
                image = Image.open(io.BytesIO(preprocessed_image))
            except Exception as img_error:
                logger.error(f"Failed to open image: {str(img_error)}")
                raise ImageCorruptedException(
                    detail="Failed to decode preprocessed image",
                    context={'receipt_id': receipt_id, 'error': str(img_error)}
                )
            
            # Step 3: Extract text using selected engine
            logger.info(
                f"Performing OCR for receipt {receipt_id} "
                f"using {self.engine.get_engine_name()}"
            )
            
            try:
                ocr_result = self.engine.extract_text(image)
                extracted_text = ocr_result['text']
                confidence_score = ocr_result['confidence']
                
            except (OCRServiceUnavailableException, OCRExtractionException):
                raise
            except Exception as ocr_error:
                logger.error(
                    f"OCR failed: {str(ocr_error)}",
                    exc_info=True
                )
                raise OCRExtractionException(
                    detail="Unexpected OCR error",
                    context={'receipt_id': receipt_id, 'error': str(ocr_error)}
                )
            
            # Step 4: Clean extracted text
            cleaned_text = self._clean_ocr_text(extracted_text)
            
            # Check if we got meaningful text
            if not cleaned_text or len(cleaned_text) < 10:
                logger.warning(
                    f"Very short OCR output for receipt {receipt_id}: "
                    f"{len(cleaned_text)} chars"
                )
            
            processing_time = time.time() - start_time
            
            # Return result matching OCRResult model
            result = {
                'extracted_text': cleaned_text,
                'confidence_score': round(confidence_score, 2),
            }
            
            logger.info(
                f"OCR completed for receipt {receipt_id} in {processing_time:.2f}s "
                f"using {self.engine.get_engine_name()} "
                f"with confidence {confidence_score:.2f} ({len(cleaned_text)} chars)"
            )
            
            return result
            
        except (ImageCorruptedException, InvalidImageFormatException,
                ImagePreprocessingException, OCRExtractionException,
                OCRServiceUnavailableException):
            raise
        except Exception as e:
            logger.error(
                f"OCR processing failed for receipt {receipt_id}: {str(e)}",
                exc_info=True
            )
            raise OCRException(
                detail="OCR processing failed unexpectedly",
                context={'receipt_id': receipt_id, 'error': str(e)}
            )
    
    def _clean_ocr_text(self, text: str) -> str:
        """
        Clean OCR text by removing excessive whitespace and artifacts
        Keep structure for better Gemini parsing
        """
        if not text:
            return ""
        
        # Split into lines
        lines = text.split('\n')
        
        # Clean each line
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            
            # Skip very short lines
            if len(line) < 2:
                continue
            
            # Skip lines with only special characters
            if all(not c.isalnum() for c in line):
                continue
            
            cleaned_lines.append(line)
        
        # Join with single newlines
        cleaned = '\n'.join(cleaned_lines)
        
        return cleaned
    
    def get_engine_info(self) -> Dict[str, Any]:
        """Get information about current OCR engine"""
        return {
            'engine': self.engine.get_engine_name(),
            'available': self.engine.is_available(),
            'min_confidence_threshold': self.min_confidence_threshold
        }


# Global instance
import threading

_ocr_instance = None
_lock = threading.Lock()

def get_ocr_service():
    global _ocr_instance
    if _ocr_instance is None:
        with _lock:
            if _ocr_instance is None:
                # Only init OCRService if paddleOCR is needed
                from django.conf import settings
                if not getattr(settings, "USE_GEMINI_ONLY_IMAGE_INPUT", False):
                    _ocr_instance = OCRService()
                else:
                    _ocr_instance = None
    return _ocr_instance

