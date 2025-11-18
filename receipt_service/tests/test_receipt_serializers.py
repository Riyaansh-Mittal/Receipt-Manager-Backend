"""
Unit tests for receipt_service/api/v1/serializers/receipt_serializers.py
Tests ACTUAL serializers that exist in the codebase
"""
import pytest
import uuid
from decimal import Decimal
from datetime import date, timedelta
from io import BytesIO
from PIL import Image
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

User = get_user_model()


@pytest.fixture
def sample_user(db):
    """Create sample user"""
    user = User.objects.create_user(
        username='testuser',
        email='user@example.com',
        first_name='Test',
        last_name='User'
    )
    yield user
    # Explicit cleanup not needed - Django handles it

@pytest.fixture
def sample_category(db):
    """Create sample category"""
    from receipt_service.models.category import Category
    category = Category.objects.create(
        name='Food & Dining',
        slug='food-dining',
        icon='🍔',
        color='#FF5722',
        is_active=True
    )
    yield category


@pytest.fixture
def sample_receipt(db, sample_user, sample_category):
    """Create sample receipt with proper foreign key"""
    from receipt_service.models.receipt import Receipt
    
    # Import the CORRECT User model from auth_service
    from auth_service.models import User
    
    # Create user using auth_service User model
    auth_user = User.objects.create_user(
        username='receiptuser',
        email='receipt@example.com'
    )
    
    receipt = Receipt.objects.create(
        user=auth_user,  # Use auth_service User
        original_filename='test_receipt.jpg',
        file_size=1024 * 100,
        mime_type='image/jpeg',
        file_hash='abc123def456',
        status='processed'
    )
    return receipt

@pytest.fixture
def sample_image_file():
    """Create sample image file"""
    img = Image.new('RGB', (500, 500), color='white')
    img_bytes = BytesIO()
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)
    
    return SimpleUploadedFile(
        name='test_receipt.jpg',
        content=img_bytes.getvalue(),
        content_type='image/jpeg'
    )


@pytest.mark.django_db
class TestReceiptUploadSerializer:
    """Test receipt upload serializer"""
    
    def test_valid_image_upload(self, sample_image_file):
        """Test valid image upload"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptUploadSerializer
        
        data = {'file': sample_image_file}
        serializer = ReceiptUploadSerializer(data=data)
        
        assert serializer.is_valid()
    
    def test_missing_file(self):
        """Test missing file fails"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptUploadSerializer
        
        data = {}
        serializer = ReceiptUploadSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'file' in serializer.errors
    
    def test_file_too_large(self):
        """Test file exceeding 10MB fails"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptUploadSerializer
        
        # Create 11MB file
        large_content = b'x' * (11 * 1024 * 1024)
        large_file = SimpleUploadedFile(
            name='large.jpg',
            content=large_content,
            content_type='image/jpeg'
        )
        
        data = {'file': large_file}
        serializer = ReceiptUploadSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'file' in serializer.errors
        assert '10MB' in str(serializer.errors['file'])
    
    def test_invalid_file_extension(self):
        """Test invalid file extension fails"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptUploadSerializer
        
        invalid_file = SimpleUploadedFile(
            name='document.txt',
            content=b'fake content',
            content_type='text/plain'
        )
        
        data = {'file': invalid_file}
        serializer = ReceiptUploadSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'file' in serializer.errors
    
    def test_pdf_file_upload(self):
        """Test PDF file upload is valid"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptUploadSerializer
        
        pdf_file = SimpleUploadedFile(
            name='receipt.pdf',
            content=b'%PDF-1.4 fake pdf content',
            content_type='application/pdf'
        )
        
        data = {'file': pdf_file}
        serializer = ReceiptUploadSerializer(data=data)
        
        assert serializer.is_valid()


@pytest.mark.django_db
class TestReceiptListSerializer:
    """Test receipt list serializer"""
    
    def test_serialize_receipt_list(self, sample_receipt):
        """Test serializing receipt for list view"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptListSerializer
        
        serializer = ReceiptListSerializer(sample_receipt)
        
        data = serializer.data
        assert 'id' in data
        assert 'original_filename' in data
        assert 'status' in data
        assert 'upload_date' in data
        assert 'file_size_mb' in data
        assert 'processing_progress' in data
    
    def test_file_size_mb_calculation(self, sample_receipt):
        """Test file size MB calculation"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptListSerializer
        
        serializer = ReceiptListSerializer(sample_receipt)
        
        # 102400 bytes = 0.1 MB
        assert serializer.data['file_size_mb'] == 0.1
    
    def test_processing_progress_mapping(self, sample_receipt):
        """Test processing progress percentage"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptListSerializer
        
        sample_receipt.status = 'processed'
        sample_receipt.save()
        
        serializer = ReceiptListSerializer(sample_receipt)
        
        assert serializer.data['processing_progress'] == 90
    
    def test_serialize_multiple_receipts(self, sample_user, sample_category, db):
        """Test serializing multiple receipts"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptListSerializer
        from receipt_service.models.receipt import Receipt
        
        receipts = [
            Receipt.objects.create(
                user=sample_user,
                original_filename=f'receipt_{i}.jpg',
                file_size=1024,
                mime_type='image/jpeg',
                file_hash=f'hash{i}',
                status='processed'
            )
            for i in range(3)
        ]
        
        serializer = ReceiptListSerializer(receipts, many=True)
        
        assert len(serializer.data) == 3


@pytest.mark.django_db
class TestReceiptDetailSerializer:
    """Test receipt detail serializer (read-only)"""
    
    def test_serialize_receipt_detail(self, sample_receipt):
        """Test serializing receipt detail"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptDetailSerializer
        
        detail_data = {
            'id': sample_receipt.id,
            'original_filename': sample_receipt.original_filename,
            'status': sample_receipt.status,
            'file_size': sample_receipt.file_size,
            'file_size_mb': round(sample_receipt.file_size / (1024 * 1024), 2),
            'mime_type': sample_receipt.mime_type,
            'upload_date': sample_receipt.created_at.isoformat(),
            'processing_started_at': None,
            'processing_completed_at': None,
            'file_url': None,
            'can_be_confirmed': False,
            'ocr_data': None,
            'extracted_data': None,
            'ai_suggestion': None
        }
        
        serializer = ReceiptDetailSerializer(detail_data)
        
        data = serializer.data
        assert str(data['id']) == str(sample_receipt.id)
        assert data['original_filename'] == 'test_receipt.jpg'
        assert data['status'] == 'processed'
        assert data['file_size'] == 102400
    
    def test_processing_duration_calculation(self):
        """Test processing duration calculation"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptDetailSerializer
        
        started = timezone.now()
        completed = started + timedelta(seconds=30)
        
        detail_data = {
            'id': uuid.uuid4(),
            'status': 'processed',
            'processing_started_at': started,
            'processing_completed_at': completed,
            'file_size': 1024,
            'file_size_mb': 0.001
        }
        
        serializer = ReceiptDetailSerializer(detail_data)
        
        duration = serializer.data['processing_duration_seconds']
        assert duration == 30
    
    def test_next_actions_for_processed_receipt(self):
        """Test next actions for processed receipt"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptDetailSerializer
        
        receipt_id = uuid.uuid4()
        detail_data = {
            'id': receipt_id,
            'status': 'processed',
            'can_be_confirmed': True,
            'file_size': 1024,
            'file_size_mb': 0.001
        }
        
        serializer = ReceiptDetailSerializer(detail_data)
        
        actions = serializer.data['next_actions']
        assert len(actions) >= 1
        assert any(a['action'] == 'confirm' for a in actions)


@pytest.mark.django_db
class TestReceiptConfirmSerializer:
    """Test receipt confirmation serializer"""
    
    def test_valid_confirmation_data(self, sample_category):
        """Test valid confirmation data"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptConfirmSerializer
        
        data = {
            'date': date.today().isoformat(),
            'amount': '99.99',
            'currency': 'USD',
            'category_id': str(sample_category.id),
            'vendor': 'Test Vendor'
        }
        
        serializer = ReceiptConfirmSerializer(data=data)
        
        assert serializer.is_valid()
    
    def test_future_date_fails(self, sample_category):
        """Test future date fails validation"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptConfirmSerializer
        
        future_date = (date.today() + timedelta(days=1)).isoformat()
        
        data = {
            'date': future_date,
            'amount': '99.99',
            'currency': 'USD',
            'category_id': str(sample_category.id)
        }
        
        serializer = ReceiptConfirmSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'date' in serializer.errors
    
    def test_negative_amount_fails(self, sample_category):
        """Test negative amount fails"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptConfirmSerializer
        
        data = {
            'date': date.today().isoformat(),
            'amount': '-50.00',
            'currency': 'USD',
            'category_id': str(sample_category.id)
        }
        
        serializer = ReceiptConfirmSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'amount' in serializer.errors
    
    def test_invalid_currency_fails(self, sample_category):
        """Test invalid currency code fails"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptConfirmSerializer
        
        data = {
            'date': date.today().isoformat(),
            'amount': '99.99',
            'currency': 'INVALID',
            'category_id': str(sample_category.id)
        }
        
        serializer = ReceiptConfirmSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'currency' in serializer.errors
    
    def test_inactive_category_fails(self, db):
        """Test inactive category fails validation"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptConfirmSerializer
        from receipt_service.models.category import Category
        
        inactive_cat = Category.objects.create(
            name='Inactive',
            slug='inactive',
            icon='❌',
            color='#000000',
            is_active=False
        )
        
        data = {
            'date': date.today().isoformat(),
            'amount': '99.99',
            'currency': 'USD',
            'category_id': str(inactive_cat.id)
        }
        
        serializer = ReceiptConfirmSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'category_id' in serializer.errors
    
    def test_vendor_with_invalid_chars_fails(self, sample_category):
        """Test vendor name with invalid characters fails"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptConfirmSerializer
        
        data = {
            'date': date.today().isoformat(),
            'amount': '99.99',
            'currency': 'USD',
            'category_id': str(sample_category.id),
            'vendor': 'Test<script>alert("xss")</script>'
        }
        
        serializer = ReceiptConfirmSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'vendor' in serializer.errors
    
    def test_too_many_tags_fails(self, sample_category):
        """Test more than 10 tags fails"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptConfirmSerializer
        
        data = {
            'date': date.today().isoformat(),
            'amount': '99.99',
            'currency': 'USD',
            'category_id': str(sample_category.id),
            'tags': [f'tag{i}' for i in range(11)]
        }
        
        serializer = ReceiptConfirmSerializer(data=data)
        
        assert not serializer.is_valid()
        assert 'tags' in serializer.errors


@pytest.mark.django_db
class TestReceiptStatusSerializer:
    """Test receipt status serializer (read-only)"""
    
    def test_serialize_status(self):
        """Test serializing receipt status"""
        from receipt_service.api.v1.serializers.receipt_serializers import ReceiptStatusSerializer
        
        status_data = {
            'receipt_id': str(uuid.uuid4()),
            'status': 'processing',
            'current_stage': 'ocr',
            'progress_percentage': 50,
            'started_at': timezone.now().isoformat(),
            'completed_at': None,
            'error_message': None,
            'message': 'Processing receipt'
        }
        
        serializer = ReceiptStatusSerializer(status_data)
        
        data = serializer.data
        assert data['status'] == 'processing'
        assert data['current_stage'] == 'ocr'
        assert data['progress_percentage'] == 50


@pytest.mark.django_db
class TestUploadHistorySerializer:
    """Test upload history serializer (read-only)"""
    
    def test_serialize_history(self):
        """Test serializing upload history"""
        from receipt_service.api.v1.serializers.receipt_serializers import UploadHistorySerializer
        
        history_data = {
            'month': '2024-01',
            'month_name': 'January',
            'upload_count': 10,
            'confirmed_count': 8,
            'failed_count': 1,
            'processing_count': 1,
            'total_amount': Decimal('500.00'),
            'formatted_total': 'USD 500.00'
        }
        
        serializer = UploadHistorySerializer(history_data)
        
        data = serializer.data
        assert data['month'] == '2024-01'
        assert data['upload_count'] == 10
        assert data['confirmed_count'] == 8
        assert Decimal(data['total_amount']) == Decimal('500.00')
