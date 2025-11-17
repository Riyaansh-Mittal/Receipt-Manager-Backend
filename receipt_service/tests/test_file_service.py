"""
Unit tests for receipt_service/services/file_service.py
Tests file upload, storage, retrieval, and deletion
IMPORTANT: Mock database and storage operations - these are unit tests
"""
import pytest
import uuid
from unittest.mock import Mock, patch, MagicMock, mock_open
from io import BytesIO
from PIL import Image

from receipt_service.services.file_service import FileService
from receipt_service.utils.exceptions import (
    FileUploadException,
    FileStorageException,
    FileRetrievalException,
    FileDeletionException,
    DuplicateReceiptException,
)
from shared.utils.exceptions import DatabaseOperationException


@pytest.fixture
def mock_user():
    """Create mock user object"""
    user = Mock()
    user.id = uuid.uuid4()
    user.email = 'test@example.com'
    return user


@pytest.fixture
def mock_receipt():
    """Create mock receipt object"""
    receipt = Mock()
    receipt.id = uuid.uuid4()
    receipt.user_id = uuid.uuid4()
    receipt.original_filename = 'test_receipt.jpg'
    receipt.file_size = 1024 * 100  # 100KB
    receipt.mime_type = 'image/jpeg'
    receipt.file_hash = 'abc123def456'
    receipt.status = 'uploaded'
    
    # Mock file_path FileField
    receipt.file_path = Mock()
    receipt.file_path.name = 'receipts/2024/test_receipt.jpg'
    receipt.file_path.storage = Mock()
    receipt.file_path.storage.exists = Mock(return_value=True)
    receipt.file_path.open = Mock()
    receipt.file_path.delete = Mock()
    
    return receipt


@pytest.fixture
def mock_uploaded_file():
    """Create mock uploaded file"""
    # Create actual image bytes
    img = Image.new('RGB', (500, 500), color='white')
    img_bytes = BytesIO()
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)
    
    uploaded_file = Mock()
    uploaded_file.name = 'test.jpg'
    uploaded_file.size = img_bytes.getbuffer().nbytes
    uploaded_file.content_type = 'image/jpeg'
    uploaded_file.read = Mock(side_effect=[img_bytes.getvalue(), b''])
    uploaded_file.seek = Mock()
    
    return uploaded_file


@pytest.fixture
def file_service():
    """Create file service instance"""
    return FileService()


@pytest.mark.unit
class TestFileServiceInitialization:
    """Test file service initialization"""
    
    def test_initialization(self, file_service):
        """Test service initializes correctly"""
        assert file_service.validator is not None
        from receipt_service.utils.file_validators import ReceiptFileValidator
        assert isinstance(file_service.validator, ReceiptFileValidator)


@pytest.mark.unit
class TestStoreReceiptFile:
    """Test receipt file storage"""
    
    @patch('receipt_service.services.file_service.transaction')
    @patch('receipt_service.services.file_service.model_service')
    def test_store_receipt_success(self, mock_model_service, mock_transaction, file_service, mock_user, mock_uploaded_file, mock_receipt):
        """Test successful file storage"""
        # Mock transaction.atomic
        mock_transaction.atomic.return_value.__enter__ = Mock(return_value=None)
        mock_transaction.atomic.return_value.__exit__ = Mock(return_value=False)
        
        # Mock validator
        file_info = {
            'filename': 'test.jpg',
            'size': 1024,
            'mime_type': 'image/jpeg',
            'file_hash': 'abc123',
            'width': 500,
            'height': 500
        }
        
        with patch.object(file_service.validator, 'validate_file', return_value=file_info):
            with patch.object(file_service.validator, 'check_duplicate_receipt', return_value=None):
                # Mock receipt creation
                mock_model_service.receipt_model.objects.create = Mock(return_value=mock_receipt)
                
                result = file_service.store_receipt_file(mock_user, mock_uploaded_file)
        
        assert 'receipt_id' in result
        assert 'storage_path' in result
        assert 'file_info' in result
        assert result['is_retry'] is False
        assert 'receipt' in result
    
    @patch('receipt_service.services.file_service.model_service')
    def test_store_receipt_duplicate_retry(self, mock_model_service, file_service, mock_user, mock_uploaded_file, mock_receipt):
        """Test handling duplicate for retry"""
        file_info = {
            'filename': 'test.jpg',
            'size': 1024,
            'mime_type': 'image/jpeg',
            'file_hash': 'abc123'
        }
        
        # Mock duplicate found
        existing_id = uuid.uuid4()
        
        with patch.object(file_service.validator, 'validate_file', return_value=file_info):
            with patch.object(file_service.validator, 'check_duplicate_receipt', return_value=existing_id):
                # Mock receipt retrieval
                mock_receipt.status = 'failed'
                mock_model_service.receipt_model.objects.get = Mock(return_value=mock_receipt)
                
                result = file_service.store_receipt_file(mock_user, mock_uploaded_file)
        
        assert result['is_retry'] is True
        assert result['receipt_id'] == str(mock_receipt.id)
        assert mock_receipt.status == 'queued'
    
    def test_store_receipt_validation_failure(self, file_service, mock_user, mock_uploaded_file):
        """Test storage fails on validation error"""
        from receipt_service.utils.exceptions import InvalidFileFormatException
        
        with patch.object(file_service.validator, 'validate_file', side_effect=InvalidFileFormatException('Invalid file')):
            with pytest.raises(InvalidFileFormatException):
                file_service.store_receipt_file(mock_user, mock_uploaded_file)
    
    @patch('receipt_service.services.file_service.transaction')
    @patch('receipt_service.services.file_service.model_service')
    def test_store_receipt_database_failure(self, mock_model_service, mock_transaction, file_service, mock_user, mock_uploaded_file):
        """Test storage fails on database error"""
        mock_transaction.atomic.return_value.__enter__ = Mock(return_value=None)
        mock_transaction.atomic.return_value.__exit__ = Mock(return_value=False)
        
        file_info = {
            'filename': 'test.jpg',
            'size': 1024,
            'mime_type': 'image/jpeg',
            'file_hash': 'abc123'
        }
        
        with patch.object(file_service.validator, 'validate_file', return_value=file_info):
            with patch.object(file_service.validator, 'check_duplicate_receipt', return_value=None):
                # Mock database error
                mock_model_service.receipt_model.objects.create = Mock(
                    side_effect=Exception('DB error')
                )
                
                with pytest.raises(DatabaseOperationException):
                    file_service.store_receipt_file(mock_user, mock_uploaded_file)
    
    @patch('receipt_service.services.file_service.model_service')
    def test_store_receipt_with_metadata(self, mock_model_service, file_service, mock_user, mock_uploaded_file, mock_receipt):
        """Test storage with metadata"""
        metadata = {
            'ip_address': '192.168.1.1'
        }
        
        file_info = {
            'filename': 'test.jpg',
            'size': 1024,
            'mime_type': 'image/jpeg',
            'file_hash': 'abc123'
        }
        
        with patch.object(file_service.validator, 'validate_file', return_value=file_info):
            with patch.object(file_service.validator, 'check_duplicate_receipt', return_value=None):
                with patch('receipt_service.services.file_service.transaction'):
                    mock_model_service.receipt_model.objects.create = Mock(return_value=mock_receipt)
                    
                    result = file_service.store_receipt_file(
                        mock_user,
                        mock_uploaded_file,
                        metadata=metadata
                    )
        
        assert result is not None


@pytest.mark.unit
class TestGetSecureFileUrl:
    """Test secure URL generation"""
    
    @patch('receipt_service.services.file_service.receipt_storage')
    def test_get_secure_url_success(self, mock_storage, file_service, mock_receipt):
        """Test successful URL generation"""
        expected_url = 'https://storage.example.com/signed-url'
        mock_storage.generate_signed_url = Mock(return_value=expected_url)
        
        url = file_service.get_secure_file_url(mock_receipt)
        
        assert url == expected_url
        mock_storage.generate_signed_url.assert_called_once()
    
    @patch('receipt_service.services.file_service.receipt_storage')
    def test_get_secure_url_custom_expiry(self, mock_storage, file_service, mock_receipt):
        """Test URL generation with custom expiry"""
        expected_url = 'https://storage.example.com/signed-url'
        mock_storage.generate_signed_url = Mock(return_value=expected_url)
        
        url = file_service.get_secure_file_url(mock_receipt, expires_in=7200)
        
        assert url == expected_url
        mock_storage.generate_signed_url.assert_called_with(
            mock_receipt.file_path.name,
            expires_in=7200
        )
    
    def test_get_secure_url_no_file(self, file_service):
        """Test URL generation fails when receipt has no file"""
        receipt = Mock()
        receipt.id = uuid.uuid4()
        receipt.file_path = None
        
        with pytest.raises(FileRetrievalException) as exc_info:
            file_service.get_secure_file_url(receipt)
        
        assert 'not found' in str(exc_info.value)
    
    def test_get_secure_url_file_not_exists(self, file_service, mock_receipt):
        """Test URL generation fails when file doesn't exist"""
        mock_receipt.file_path.storage.exists = Mock(return_value=False)
        
        with pytest.raises(FileRetrievalException) as exc_info:
            file_service.get_secure_file_url(mock_receipt)
        
        assert 'does not exist' in str(exc_info.value)
    
    @patch('receipt_service.services.file_service.receipt_storage')
    def test_get_secure_url_generation_error(self, mock_storage, file_service, mock_receipt):
        """Test URL generation handles storage errors"""
        mock_storage.generate_signed_url = Mock(side_effect=Exception('Storage error'))
        
        with pytest.raises(FileRetrievalException):
            file_service.get_secure_file_url(mock_receipt)


@pytest.mark.unit
class TestGetFileContent:
    """Test file content retrieval"""
    
    def test_get_file_content_success(self, file_service, mock_receipt):
        """Test successful file content retrieval"""
        expected_content = b"fake file content"
        
        mock_file = Mock()
        mock_file.read = Mock(return_value=expected_content)
        mock_file.__enter__ = Mock(return_value=mock_file)
        mock_file.__exit__ = Mock(return_value=False)
        
        mock_receipt.file_path.open = Mock(return_value=mock_file)
        
        content = file_service.get_file_content(mock_receipt)
        
        assert content == expected_content
    
    def test_get_file_content_no_file(self, file_service):
        """Test content retrieval fails when no file"""
        receipt = Mock()
        receipt.id = uuid.uuid4()
        receipt.file_path = None
        
        with pytest.raises(FileRetrievalException):
            file_service.get_file_content(receipt)
    
    def test_get_file_content_file_not_exists(self, file_service, mock_receipt):
        """Test content retrieval fails when file doesn't exist"""
        mock_receipt.file_path.storage.exists = Mock(return_value=False)
        
        with pytest.raises(FileRetrievalException):
            file_service.get_file_content(mock_receipt)
    
    def test_get_file_content_read_error(self, file_service, mock_receipt):
        """Test content retrieval handles read errors"""
        mock_receipt.file_path.open = Mock(side_effect=IOError('Read error'))
        
        with pytest.raises(FileRetrievalException):
            file_service.get_file_content(mock_receipt)


@pytest.mark.unit
class TestDeleteReceiptFile:
    """Test file deletion"""
    
    def test_delete_file_success(self, file_service, mock_receipt):
        """Test successful file deletion"""
        result = file_service.delete_receipt_file(mock_receipt)
        
        assert result is True
        mock_receipt.file_path.delete.assert_called_once_with(save=False)
    
    def test_delete_file_no_file(self, file_service):
        """Test deletion succeeds when no file exists"""
        receipt = Mock()
        receipt.id = uuid.uuid4()
        receipt.file_path = None
        
        result = file_service.delete_receipt_file(receipt)
        
        assert result is True
    
    def test_delete_file_error(self, file_service, mock_receipt):
        """Test deletion handles errors"""
        mock_receipt.file_path.delete = Mock(side_effect=Exception('Delete error'))
        
        with pytest.raises(FileDeletionException):
            file_service.delete_receipt_file(mock_receipt)


@pytest.mark.unit
class TestFileExists:
    """Test file existence check"""
    
    def test_file_exists_true(self, file_service, mock_receipt):
        """Test file exists check returns True"""
        mock_receipt.file_path.storage.exists = Mock(return_value=True)
        
        result = file_service.file_exists(mock_receipt)
        
        assert result is True
    
    def test_file_exists_false(self, file_service, mock_receipt):
        """Test file exists check returns False"""
        mock_receipt.file_path.storage.exists = Mock(return_value=False)
        
        result = file_service.file_exists(mock_receipt)
        
        assert result is False
    
    def test_file_exists_no_path(self, file_service):
        """Test file exists returns False when no path"""
        receipt = Mock()
        receipt.file_path = None
        
        result = file_service.file_exists(receipt)
        
        assert result is False
    
    def test_file_exists_error(self, file_service, mock_receipt):
        """Test file exists handles errors gracefully"""
        mock_receipt.file_path.storage.exists = Mock(side_effect=Exception('Storage error'))
        
        result = file_service.file_exists(mock_receipt)
        
        assert result is False


@pytest.mark.unit
class TestGetFileMetadata:
    """Test file metadata retrieval"""
    
    def test_get_metadata_success(self, file_service, mock_receipt):
        """Test successful metadata retrieval"""
        metadata = file_service.get_file_metadata(mock_receipt)
        
        assert metadata['exists'] is True
        assert metadata['storage_path'] == mock_receipt.file_path.name
        assert metadata['size'] == mock_receipt.file_size
        assert metadata['mime_type'] == mock_receipt.mime_type
        assert metadata['original_filename'] == mock_receipt.original_filename
    
    def test_get_metadata_no_file(self, file_service):
        """Test metadata when no file"""
        receipt = Mock()
        receipt.file_path = None
        
        metadata = file_service.get_file_metadata(receipt)
        
        assert metadata['exists'] is False
        assert metadata['size'] == 0
    
    def test_get_metadata_error(self, file_service, mock_receipt):
        """Test metadata handles errors"""
        # Force an error by making file_exists raise
        with patch.object(file_service, 'file_exists', side_effect=Exception('Error')):
            metadata = file_service.get_file_metadata(mock_receipt)
            
            assert metadata['exists'] is False
            assert 'error' in metadata


@pytest.mark.unit
class TestGenerateThumbnail:
    """Test thumbnail generation"""
    
    def test_generate_thumbnail_success(self, file_service, mock_receipt):
        """Test successful thumbnail generation"""
        # Create actual image content
        img = Image.new('RGB', (1000, 1000), color='blue')
        img_bytes = BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        
        with patch.object(file_service, 'get_file_content', return_value=img_bytes.getvalue()):
            thumbnail = file_service.generate_thumbnail(mock_receipt)
        
        assert thumbnail is not None
        assert isinstance(thumbnail, BytesIO)
        
        # Verify it's a valid image
        thumbnail.seek(0)
        thumb_img = Image.open(thumbnail)
        assert thumb_img.size[0] <= 200
        assert thumb_img.size[1] <= 200
    
    def test_generate_thumbnail_custom_size(self, file_service, mock_receipt):
        """Test thumbnail with custom size"""
        img = Image.new('RGB', (1000, 1000), color='green')
        img_bytes = BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        
        with patch.object(file_service, 'get_file_content', return_value=img_bytes.getvalue()):
            thumbnail = file_service.generate_thumbnail(mock_receipt, size=(100, 100))
        
        assert thumbnail is not None
        thumbnail.seek(0)
        thumb_img = Image.open(thumbnail)
        assert thumb_img.size[0] <= 100
        assert thumb_img.size[1] <= 100
    
    def test_generate_thumbnail_pdf(self, file_service, mock_receipt):
        """Test thumbnail returns None for PDF"""
        mock_receipt.mime_type = 'application/pdf'
        
        thumbnail = file_service.generate_thumbnail(mock_receipt)
        
        assert thumbnail is None
    
    def test_generate_thumbnail_no_mime_type(self, file_service, mock_receipt):
        """Test thumbnail returns None when no MIME type"""
        mock_receipt.mime_type = None
        
        thumbnail = file_service.generate_thumbnail(mock_receipt)
        
        assert thumbnail is None
    
    def test_generate_thumbnail_error(self, file_service, mock_receipt):
        """Test thumbnail handles errors gracefully"""
        with patch.object(file_service, 'get_file_content', side_effect=Exception('Error')):
            thumbnail = file_service.generate_thumbnail(mock_receipt)
        
        assert thumbnail is None
