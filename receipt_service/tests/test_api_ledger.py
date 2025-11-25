import pytest
from rest_framework import status

@pytest.mark.django_db
class TestLedgerAPI:
    base_url = '/receipt/v1/ledgerentries/'

    def test_list_requires_auth(self, api_client):
        resp = api_client.get(self.base_url)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_ledgers(self, auth_api_client):
        resp = auth_api_client.get(self.base_url)
        assert resp.status_code == status.HTTP_200_OK

    def test_create_ledger(self, auth_api_client):
        data = {'name': 'Test Ledger'}
        resp = auth_api_client.post(self.base_url, data, format='json')
        assert resp.status_code == status.HTTP_201_CREATED

    def test_update_ledger(self, auth_api_client, create_ledger):
        ledger = create_ledger()
        url = f'{self.base_url}{ledger.id}/'
        resp = auth_api_client.put(url, {'name': 'Updated Ledger'}, format='json')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['name'] == 'Updated Ledger'

    def test_delete_ledger(self, auth_api_client, create_ledger):
        ledger = create_ledger()
        url = f'{self.base_url}{ledger.id}/'
        resp = auth_api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT
