import pytest
from rest_framework import status
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

User = get_user_model()

@pytest.fixture
def create_user(db):
    def _create_user(email='user@example.com'):
        return User.objects.create_user(email=email, password='password')
    return _create_user

@pytest.fixture
def auth_api_client(api_client, create_user):
    user = create_user()
    api_client.force_authenticate(user=user)
    return api_client

@pytest.fixture
def create_category(db):
    from receipt_service.models.category import Category
    def _create_category(name="Test Category"):
        return Category.objects.create(name=name)
    return _create_category

@pytest.fixture
def create_receipt(db, create_user, create_category):
    from receipt_service.models.receipt import Receipt
    def _create_receipt(user=None, category=None):
        if user is None:
            user = create_user()
        if category is None:
            category = create_category()
        return Receipt.objects.create(
            title="Test Receipt", amount=100.0, user=user, category=category
        )
    return _create_receipt

@pytest.mark.django_db
class TestReceiptCRUD:
    base_url = '/receipt/v1/receipts/'

    def test_list_requires_auth(self, api_client):
        resp = api_client.get(self.base_url)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_receipt(self, auth_api_client, create_category):
        cat = create_category()
        data = {'title': 'Receipt title', 'amount': '10.50', 'category': cat.id}
        resp = auth_api_client.post(self.base_url, data, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data['title'] == 'Receipt title'

    def test_get_receipt_detail(self, auth_api_client, create_receipt):
        receipt = create_receipt(user=auth_api_client.handler._force_user)
        url = f'{self.base_url}{receipt.id}/'
        resp = auth_api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['id'] == str(receipt.id)

    def test_update_receipt(self, auth_api_client, create_receipt):
        receipt = create_receipt(user=auth_api_client.handler._force_user)
        url = f'{self.base_url}{receipt.id}/'
        resp = auth_api_client.put(url, {'title': 'Updated Receipt'}, format='json')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['title'] == 'Updated Receipt'

    def test_delete_receipt(self, auth_api_client, create_receipt):
        receipt = create_receipt(user=auth_api_client.handler._force_user)
        url = f'{self.base_url}{receipt.id}/'
        resp = auth_api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT

@pytest.mark.django_db
class TestReceiptFileUpload:
    upload_url = '/receipt/v1/receipts/upload/'

    @patch('receipt_service.api.v1.views.receipt_views.process_receipt_file.delay')
    def test_upload_receipt_file(self, mock_task, auth_api_client):
        mock_task.return_value = None
        file_content = b'%PDF-1.4 fake pdf data'
        file = SimpleUploadedFile('receipt.pdf', file_content, content_type='application/pdf')
        resp = auth_api_client.post(self.upload_url, {'file': file}, format='multipart')
        assert resp.status_code == status.HTTP_200_OK
        mock_task.assert_called_once()

@pytest.mark.django_db
class TestReceiptFiltering:
    base_url = '/receipt/v1/receipts/'

    def test_filter_by_category(self, auth_api_client, create_receipt, create_category):
        cat = create_category()
        receipt_in_cat = create_receipt(user=auth_api_client.handler._force_user, category=cat)
        receipt_other = create_receipt(user=auth_api_client.handler._force_user)
        resp = auth_api_client.get(self.base_url, {'category': cat.id})
        assert resp.status_code == status.HTTP_200_OK
        ids = [r['id'] for r in resp.data['results']]
        assert str(receipt_in_cat.id) in ids
        assert str(receipt_other.id) not in ids
