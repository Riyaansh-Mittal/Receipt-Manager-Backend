import pytest
from rest_framework import status

@pytest.mark.django_db
class TestCategoryAPI:
    base_url = '/receipt/v1/categories/'

    def test_list_categories(self, api_client):
        resp = api_client.get(self.base_url)
        assert resp.status_code == status.HTTP_200_OK

    def test_create_requires_auth(self, api_client):
        resp = api_client.post(self.base_url, {'name': 'New Cat'}, format='json')
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_category(self, auth_api_client):
        resp = auth_api_client.post(self.base_url, {'name': 'New Cat'}, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data['name'] == 'New Cat'

    def test_update_category(self, auth_api_client, create_category):
        category = create_category()
        url = f'{self.base_url}{category.id}/'
        resp = auth_api_client.put(url, {'name': 'Updated Cat'}, format='json')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['name'] == 'Updated Cat'

    def test_delete_category(self, auth_api_client, create_category):
        category = create_category()
        url = f'{self.base_url}{category.id}/'
        resp = auth_api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT
