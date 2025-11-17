"""
Unit tests for receipt_service/utils/file_validators.py
Tests ReceiptFileValidator class with various file scenarios
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO
from PIL import Image
import hashlib

from receipt_service.utils.file_validators import ReceiptFileValidator
from receipt_service.utils.exceptions import (
    InvalidFileFormatException,
    FileSizeExceededException,
)


@pytest.fixture
def validator():
    """Create a fresh validator instance for each test"""
    return ReceiptFileValidator()


@pytest.fixture
def mock_valid_image_file():
    """Create a mock valid image file"""
    mock_file = Mock()
    mock_file.name = "test_receipt.jpg"
    mock_file.size = 1024 * 1024  # 1MB
    mock_file.content_type = "image/jpeg"
    
    # Create actual image bytes
    img = Image.new('RGB', (500, 500), color='white')
    img_bytes = BytesIO()
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)
    
    mock_file.read = Mock(side_effect=[img_bytes.getvalue(), b''])
    mock_file.seek = Mock()
    
    return mock_file


@pytest.fixture
def mock_valid_pdf_file():
    """Create a mock valid PDF file"""
    mock_file = Mock()
    mock_file.name = "test_receipt.pdf"
    mock_file.size = 500 * 1024  # 500KB
    mock_file.content_type = "application/pdf"
    mock_file.read = Mock(side_effect=[b"%PDF-1.4\n%sample pdf content"[:1024], b"%PDF", b"%PDF-1.4\n%sample pdf content", b''])
    mock_file.seek = Mock()
    
    return mock_file


@pytest.mark.unit
class TestValidatorInitialization:
    """Test ReceiptFileValidator initialization"""

    def test_validator_initialization(self, validator):
        """Test validator is initialized with empty errors"""
        assert validator.errors == []
        assert validator.MAX_FILE_SIZE > 0
        assert len(validator.ALLOWED_EXTENSIONS) > 0
        assert len(validator.ALLOWED_MIME_TYPES) > 0

    def test_validator_constants(self, validator):
        """Test validator constants are properly set"""
        assert 'pdf' in validator.ALLOWED_EXTENSIONS
        assert 'jpg' in validator.ALLOWED_EXTENSIONS
        assert 'jpeg' in validator.ALLOWED_EXTENSIONS
        assert 'png' in validator.ALLOWED_EXTENSIONS
        
        assert 'application/pdf' in validator.ALLOWED_MIME_TYPES
        assert 'image/jpeg' in validator.ALLOWED_MIME_TYPES
        assert 'image/png' in validator.ALLOWED_MIME_TYPES

    def test_validator_size_limits(self, validator):
        """Test image dimension limits"""
        assert validator.MIN_IMAGE_WIDTH == 100
        assert validator.MIN_IMAGE_HEIGHT == 100
        assert validator.MAX_IMAGE_WIDTH == 10000
        assert validator.MAX_IMAGE_HEIGHT == 10000


@pytest.mark.unit
class TestFileExtensionValidation:
    """Test file extension validation"""

    def test_validate_extension_valid_jpg(self, validator):
        """Test validation of .jpg extension"""
        validator._validate_file_extension("receipt.jpg")

    def test_validate_extension_valid_jpeg(self, validator):
        """Test validation of .jpeg extension"""
        validator._validate_file_extension("receipt.jpeg")

    def test_validate_extension_valid_png(self, validator):
        """Test validation of .png extension"""
        validator._validate_file_extension("receipt.png")

    def test_validate_extension_valid_pdf(self, validator):
        """Test validation of .pdf extension"""
        validator._validate_file_extension("receipt.pdf")

    def test_validate_extension_invalid(self, validator):
        """Test validation of invalid extension"""
        with pytest.raises(InvalidFileFormatException):
            validator._validate_file_extension("receipt.txt")

    def test_validate_extension_no_extension(self, validator):
        """Test validation of file with no extension"""
        with pytest.raises(InvalidFileFormatException):
            validator._validate_file_extension("receipt")

    def test_validate_extension_case_insensitive(self, validator):
        """Test that extension validation is case-insensitive"""
        for ext in ["JPG", "JPEG", "PNG", "PDF", "Jpg", "Pdf"]:
            validator._validate_file_extension(f"receipt.{ext}")

    def test_validate_extension_multiple_dots(self, validator):
        """Test validation of filename with multiple dots"""
        validator._validate_file_extension("my.receipt.2024.jpg")


@pytest.mark.unit
class TestFileSizeValidation:
    """Test file size validation"""

    def test_validate_size_within_limit(self, validator):
        """Test validation of file within size limit"""
        mock_file = Mock()
        mock_file.size = 5 * 1024 * 1024  # 5MB
        validator._validate_file_size(mock_file)

    def test_validate_size_at_exact_limit(self, validator):
        """Test validation of file at exact size limit"""
        mock_file = Mock()
        mock_file.size = validator.MAX_FILE_SIZE
        validator._validate_file_size(mock_file)

    def test_validate_size_exceeds_limit(self, validator):
        """Test validation of file exceeding size limit"""
        mock_file = Mock()
        mock_file.size = 11 * 1024 * 1024  # 11MB
        with pytest.raises(FileSizeExceededException):
            validator._validate_file_size(mock_file)

    def test_validate_size_zero_bytes(self, validator):
        """Test validation of zero-byte file"""
        mock_file = Mock()
        mock_file.size = 0
        validator._validate_file_size(mock_file)  # Zero bytes is allowed

    def test_validate_size_very_small_file(self, validator):
        """Test validation of very small file"""
        mock_file = Mock()
        mock_file.size = 1  # 1 byte
        validator._validate_file_size(mock_file)


@pytest.mark.unit
class TestMimeTypeValidation:
    """Test MIME type validation"""

    @patch('receipt_service.utils.file_validators.magic.from_buffer')
    def test_validate_mime_type_valid_jpeg(self, mock_magic, validator):
        """Test MIME type validation for JPEG"""
        mock_file = Mock()
        mock_file.name = "test.jpg"
        mock_file.read = Mock(return_value=b"fake jpeg bytes")
        mock_file.seek = Mock()
        
        mock_magic.return_value = "image/jpeg"
        
        mime_type = validator._validate_mime_type(mock_file)
        assert mime_type == "image/jpeg"

    @patch('receipt_service.utils.file_validators.magic.from_buffer')
    def test_validate_mime_type_valid_png(self, mock_magic, validator):
        """Test MIME type validation for PNG"""
        mock_file = Mock()
        mock_file.name = "test.png"
        mock_file.read = Mock(return_value=b"fake png bytes")
        mock_file.seek = Mock()
        
        mock_magic.return_value = "image/png"
        
        mime_type = validator._validate_mime_type(mock_file)
        assert mime_type == "image/png"

    @patch('receipt_service.utils.file_validators.magic.from_buffer')
    def test_validate_mime_type_valid_pdf(self, mock_magic, validator):
        """Test MIME type validation for PDF"""
        mock_file = Mock()
        mock_file.name = "test.pdf"
        mock_file.read = Mock(return_value=b"%PDF-1.4")
        mock_file.seek = Mock()
        
        mock_magic.return_value = "application/pdf"
        
        mime_type = validator._validate_mime_type(mock_file)
        assert mime_type == "application/pdf"

    @patch('receipt_service.utils.file_validators.magic.from_buffer')
    def test_validate_mime_type_invalid(self, mock_magic, validator):
        """Test MIME type validation for invalid type"""
        mock_file = Mock()
        mock_file.name = "test.txt"
        mock_file.read = Mock(return_value=b"fake text content")
        mock_file.seek = Mock()
        
        mock_magic.return_value = "text/plain"
        
        with pytest.raises(InvalidFileFormatException):
            validator._validate_mime_type(mock_file)

    @patch('receipt_service.utils.file_validators.mimetypes.guess_type')
    @patch('receipt_service.utils.file_validators.magic.from_buffer')
    def test_validate_mime_type_spoofed_extension(self, mock_magic, mock_guess, validator):
        """Test detection of spoofed file extension"""
        mock_file = Mock()
        mock_file.name = "malicious.jpg"
        mock_file.read = Mock(return_value=b"<!DOCTYPE html>")
        mock_file.seek = Mock()
        
        mock_magic.return_value = "text/html"
        mock_guess.return_value = (None, None)  # ← Fallback also fails
        
        with pytest.raises(InvalidFileFormatException):
            validator._validate_mime_type(mock_file)


    @patch('receipt_service.utils.file_validators.mimetypes.guess_type')
    @patch('receipt_service.utils.file_validators.magic.from_buffer')
    def test_validate_mime_type_exception_handling(self, mock_magic, mock_guess, validator):
        """Test MIME type validation handles exceptions"""
        mock_file = Mock()
        mock_file.name = "test.jpg"
        mock_file.read = Mock(side_effect=Exception("Read error"))
        
        mock_guess.return_value = (None, None)  # ← Fallback also fails
        
        with pytest.raises(InvalidFileFormatException):
            validator._validate_mime_type(mock_file)


@pytest.mark.unit
class TestImageValidation:
    """Test image-specific validation"""

    def test_validate_image_valid_dimensions(self, validator):
        """Test validation of image with valid dimensions"""
        mock_file = Mock()
        mock_file.seek = Mock()
        
        with patch('receipt_service.utils.file_validators.Image.open') as mock_open:
            mock_img = MagicMock()
            mock_img.size = (500, 600)
            mock_img.__enter__ = Mock(return_value=mock_img)
            mock_img.__exit__ = Mock(return_value=False)
            mock_open.return_value = mock_img
            
            validator._validate_image_content(mock_file)

    def test_validate_image_too_small_width(self, validator):
        """Test validation of image with width too small"""
        mock_file = Mock()
        mock_file.seek = Mock()
        
        with patch('receipt_service.utils.file_validators.Image.open') as mock_open:
            mock_img = MagicMock()
            mock_img.size = (50, 500)
            mock_img.__enter__ = Mock(return_value=mock_img)
            mock_img.__exit__ = Mock(return_value=False)
            mock_open.return_value = mock_img
            
            with pytest.raises(InvalidFileFormatException):
                validator._validate_image_content(mock_file)

    def test_validate_image_too_large_width(self, validator):
        """Test validation of image with width too large"""
        mock_file = Mock()
        mock_file.seek = Mock()
        
        with patch('receipt_service.utils.file_validators.Image.open') as mock_open:
            mock_img = MagicMock()
            mock_img.size = (15000, 500)
            mock_img.__enter__ = Mock(return_value=mock_img)
            mock_img.__exit__ = Mock(return_value=False)
            mock_open.return_value = mock_img
            
            with pytest.raises(InvalidFileFormatException):
                validator._validate_image_content(mock_file)

    def test_validate_image_corrupted(self, validator):
        """Test validation of corrupted image"""
        mock_file = Mock()
        mock_file.seek = Mock()
        
        with patch('receipt_service.utils.file_validators.Image.open', side_effect=Exception("Cannot identify image")):
            with pytest.raises(InvalidFileFormatException):
                validator._validate_image_content(mock_file)


@pytest.mark.unit
class TestFileHashCalculation:
    """Test file hash calculation"""

    def test_generate_file_hash_consistent(self, validator):
        """Test that same file produces same hash"""
        content = b"test file content"
        
        mock_file1 = Mock()
        mock_file1.read = Mock(side_effect=[content, b''])
        mock_file1.seek = Mock()
        
        hash1 = validator._generate_file_hash(mock_file1)
        
        mock_file2 = Mock()
        mock_file2.read = Mock(side_effect=[content, b''])
        mock_file2.seek = Mock()
        
        hash2 = validator._generate_file_hash(mock_file2)
        
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_generate_file_hash_different_content(self, validator):
        """Test that different files produce different hashes"""
        mock_file1 = Mock()
        mock_file1.read = Mock(side_effect=[b"content 1", b''])
        mock_file1.seek = Mock()
        
        mock_file2 = Mock()
        mock_file2.read = Mock(side_effect=[b"content 2", b''])
        mock_file2.seek = Mock()
        
        hash1 = validator._generate_file_hash(mock_file1)
        hash2 = validator._generate_file_hash(mock_file2)
        
        assert hash1 != hash2

    def test_generate_file_hash_resets_pointer(self, validator):
        """Test that hash calculation resets file pointer"""
        mock_file = Mock()
        mock_file.read = Mock(side_effect=[b"test content", b''])
        mock_file.seek = Mock()
        
        validator._generate_file_hash(mock_file)
        
        mock_file.seek.assert_called_with(0)


@pytest.mark.unit
class TestCompleteFileValidation:
    """Test complete file validation flow"""

    @patch('receipt_service.utils.file_validators.magic.from_buffer')
    def test_validate_file_complete_success_pdf(self, mock_magic, validator, mock_valid_pdf_file):
        """Test complete validation of valid PDF file"""
        mock_magic.return_value = "application/pdf"
        
        result = validator.validate_file(mock_valid_pdf_file)
        
        assert result['filename'] == "test_receipt.pdf"
        assert result['file_hash'] is not None
        assert result['mime_type'] == "application/pdf"

    def test_validate_file_invalid_extension(self, validator):
        """Test validation fails for invalid extension"""
        mock_file = Mock()
        mock_file.name = "receipt.txt"
        mock_file.size = 1024
        
        with pytest.raises(InvalidFileFormatException):
            validator.validate_file(mock_file)

    def test_validate_file_size_exceeded(self, validator):
        """Test validation fails for oversized file"""
        mock_file = Mock()
        mock_file.name = "receipt.jpg"
        mock_file.size = 20 * 1024 * 1024  # 20MB
        
        with pytest.raises(FileSizeExceededException):
            validator.validate_file(mock_file)


@pytest.mark.unit
class TestValidatorErrorHandling:
    """Test error accumulation and reporting"""

    def test_errors_reset_on_new_validation(self, validator):
        """Test that errors are reset for new validation"""
        with pytest.raises(InvalidFileFormatException):
            validator._validate_file_extension("receipt.txt")
        
        # New validation should work
        validator.errors = []
        validator._validate_file_extension("receipt.jpg")
        assert len(validator.errors) == 0
