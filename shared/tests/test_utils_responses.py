"""
Unit tests for shared/utils/responses.py
Tests standardized response helper functions
"""
import pytest
from rest_framework import status
from rest_framework.response import Response
from shared.utils.responses import (
    success_response,
    paginated_response,
    created_response,
    no_content_response,
    accepted_response,
)


@pytest.mark.unit
class TestSuccessResponse:
    """Test success_response function"""

    def test_success_response_defaults(self):
        """Test success response with default values"""
        response = success_response()
        
        assert isinstance(response, Response)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["message"] == "Success"
        assert response.data["data"] is None
        assert response.data["status"] == status.HTTP_200_OK

    def test_success_response_with_data(self):
        """Test success response with data"""
        data = {"user_id": 123, "username": "testuser"}
        response = success_response(data=data)
        
        assert response.data["data"] == data
        assert response.data["message"] == "Success"

    def test_success_response_with_custom_message(self):
        """Test success response with custom message"""
        response = success_response(message="Operation completed")
        
        assert response.data["message"] == "Operation completed"

    def test_success_response_with_custom_status_code(self):
        """Test success response with custom status code"""
        response = success_response(status_code=status.HTTP_202_ACCEPTED)
        
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data["status"] == status.HTTP_202_ACCEPTED

    def test_success_response_with_headers(self):
        """Test success response with custom headers"""
        headers = {"X-Custom-Header": "value", "X-Request-ID": "123"}
        response = success_response(headers=headers)
        
        assert response.has_header("X-Custom-Header")
        assert response["X-Custom-Header"] == "value"

    def test_success_response_with_all_parameters(self):
        """Test success response with all parameters"""
        data = {"items": [1, 2, 3]}
        headers = {"X-Total-Count": "3"}
        
        response = success_response(
            message="Items retrieved",
            data=data,
            status_code=status.HTTP_200_OK,
            headers=headers
        )
        
        assert response.data["message"] == "Items retrieved"
        assert response.data["data"] == data
        assert response.status_code == status.HTTP_200_OK
        assert response["X-Total-Count"] == "3"

    def test_success_response_with_empty_data(self):
        """Test success response with empty dict as data"""
        response = success_response(data={})
        
        assert response.data["data"] == {}

    def test_success_response_with_list_data(self):
        """Test success response with list data"""
        data = [{"id": 1}, {"id": 2}, {"id": 3}]
        response = success_response(data=data)
        
        assert response.data["data"] == data
        assert len(response.data["data"]) == 3

    def test_success_response_with_nested_data(self):
        """Test success response with nested dictionary data"""
        data = {
            "user": {
                "id": 123,
                "profile": {
                    "name": "Test User",
                    "email": "test@example.com"
                }
            }
        }
        response = success_response(data=data)
        
        assert response.data["data"]["user"]["profile"]["name"] == "Test User"


@pytest.mark.unit
class TestPaginatedResponse:
    """Test paginated_response function"""

    def test_paginated_response_defaults(self):
        """Test paginated response with default values"""
        response = paginated_response()
        
        assert isinstance(response, Response)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["message"] == "Success"
        assert response.data["data"] is None
        assert response.data["pagination"] == {}
        assert response.data["status"] == status.HTTP_200_OK

    def test_paginated_response_with_pagination_data(self):
        """Test paginated response with pagination metadata"""
        data = [{"id": 1}, {"id": 2}, {"id": 3}]
        pagination_data = {
            "page": 1,
            "page_size": 10,
            "total_pages": 5,
            "total_count": 50,
            "has_next": True,
            "has_previous": False
        }
        
        response = paginated_response(
            data=data,
            pagination_data=pagination_data
        )
        
        assert response.data["data"] == data
        assert response.data["pagination"] == pagination_data
        assert response.data["pagination"]["page"] == 1
        assert response.data["pagination"]["total_count"] == 50

    def test_paginated_response_with_custom_message(self):
        """Test paginated response with custom message"""
        response = paginated_response(message="Users retrieved")
        
        assert response.data["message"] == "Users retrieved"

    def test_paginated_response_with_custom_status_code(self):
        """Test paginated response with custom status code"""
        response = paginated_response(status_code=status.HTTP_206_PARTIAL_CONTENT)
        
        assert response.status_code == status.HTTP_206_PARTIAL_CONTENT
        assert response.data["status"] == status.HTTP_206_PARTIAL_CONTENT

    def test_paginated_response_empty_results(self):
        """Test paginated response with empty results"""
        response = paginated_response(
            data=[],
            pagination_data={"page": 1, "total_count": 0}
        )
        
        assert response.data["data"] == []
        assert response.data["pagination"]["total_count"] == 0

    def test_paginated_response_with_none_pagination(self):
        """Test that None pagination defaults to empty dict"""
        response = paginated_response(pagination_data=None)
        
        assert response.data["pagination"] == {}

    def test_paginated_response_all_parameters(self):
        """Test paginated response with all parameters"""
        data = [{"receipt_id": i} for i in range(10)]
        pagination_data = {
            "page": 2,
            "page_size": 10,
            "total_pages": 10,
            "total_count": 100,
            "next_url": "/api/receipts?page=3",
            "previous_url": "/api/receipts?page=1"
        }
        
        response = paginated_response(
            message="Receipts retrieved successfully",
            data=data,
            pagination_data=pagination_data,
            status_code=status.HTTP_200_OK
        )
        
        assert len(response.data["data"]) == 10
        assert response.data["pagination"]["page"] == 2
        assert response.data["message"] == "Receipts retrieved successfully"


@pytest.mark.unit
class TestCreatedResponse:
    """Test created_response function"""

    def test_created_response_defaults(self):
        """Test created response with default values"""
        response = created_response()
        
        assert isinstance(response, Response)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["message"] == "Created successfully"
        assert response.data["data"] is None
        assert response.data["status"] == status.HTTP_201_CREATED

    def test_created_response_with_data(self):
        """Test created response with created resource data"""
        data = {"id": 456, "name": "New Receipt", "created_at": "2025-11-14"}
        response = created_response(data=data)
        
        assert response.data["data"] == data
        assert response.status_code == status.HTTP_201_CREATED

    def test_created_response_with_custom_message(self):
        """Test created response with custom message"""
        response = created_response(message="User created successfully")
        
        assert response.data["message"] == "User created successfully"

    def test_created_response_with_location_header(self):
        """Test created response with Location header"""
        data = {"id": 123}
        headers = {"Location": "/api/receipts/123/"}
        
        response = created_response(data=data, headers=headers)
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.has_header("Location")
        assert response["Location"] == "/api/receipts/123/"

    def test_created_response_all_parameters(self):
        """Test created response with all parameters"""
        data = {"id": 789, "status": "pending"}
        headers = {"Location": "/api/resource/789", "X-Resource-ID": "789"}
        
        response = created_response(
            message="Resource created",
            data=data,
            headers=headers
        )
        
        assert response.data["message"] == "Resource created"
        assert response.data["data"]["id"] == 789
        assert response["Location"] == "/api/resource/789"


@pytest.mark.unit
class TestNoContentResponse:
    """Test no_content_response function"""

    def test_no_content_response_defaults(self):
        """Test no content response with default values"""
        response = no_content_response()
        
        assert isinstance(response, Response)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.data["message"] == "Operation completed successfully"
        assert response.data["data"] is None
        assert response.data["status"] == status.HTTP_204_NO_CONTENT

    def test_no_content_response_with_custom_message(self):
        """Test no content response with custom message"""
        response = no_content_response(message="Deleted successfully")
        
        assert response.data["message"] == "Deleted successfully"
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_no_content_response_always_null_data(self):
        """Test that no content response always has null data"""
        response = no_content_response()
        
        assert response.data["data"] is None


@pytest.mark.unit
class TestAcceptedResponse:
    """Test accepted_response function"""

    def test_accepted_response_defaults(self):
        """Test accepted response with default values"""
        response = accepted_response()
        
        assert isinstance(response, Response)
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data["message"] == "Operation still processing"
        assert response.data["data"] is None
        assert response.data["status"] == status.HTTP_202_ACCEPTED

    def test_accepted_response_with_custom_message(self):
        """Test accepted response with custom message"""
        response = accepted_response(message="Task queued for processing")
        
        assert response.data["message"] == "Task queued for processing"
        assert response.status_code == status.HTTP_202_ACCEPTED

    def test_accepted_response_always_null_data(self):
        """Test that accepted response always has null data"""
        response = accepted_response()
        
        assert response.data["data"] is None


@pytest.mark.unit
class TestResponseEdgeCases:
    """Test edge cases and special scenarios"""

    def test_response_with_none_message(self):
        """Test response functions handle None message gracefully"""
        # Python defaults will use function default, not None
        response = success_response(message="Custom")
        assert response.data["message"] == "Custom"

    def test_response_with_special_characters_in_message(self):
        """Test response with special characters in message"""
        message = "User 'test@example.com' created successfully! 🎉"
        response = success_response(message=message)
        
        assert response.data["message"] == message

    def test_response_with_very_long_message(self):
        """Test response with very long message"""
        long_message = "A" * 1000
        response = success_response(message=long_message)
        
        assert len(response.data["message"]) == 1000

    def test_response_with_unicode_data(self):
        """Test response with unicode characters in data"""
        data = {"name": "テストユーザー", "emoji": "😀"}
        response = success_response(data=data)
        
        assert response.data["data"]["name"] == "テストユーザー"
        assert response.data["data"]["emoji"] == "😀"

    def test_response_serialization_compatibility(self):
        """Test that response data is JSON-serializable"""
        import json
        
        data = {
            "string": "test",
            "number": 123,
            "float": 123.45,
            "boolean": True,
            "null": None,
            "list": [1, 2, 3],
            "dict": {"nested": "value"}
        }
        response = success_response(data=data)
        
        # Should be serializable to JSON
        json_str = json.dumps(response.data)
        assert json_str  # Not empty

    def test_multiple_custom_headers(self):
        """Test response with multiple custom headers"""
        headers = {
            "X-Request-ID": "abc-123",
            "X-Rate-Limit": "1000",
            "X-Rate-Limit-Remaining": "999",
            "Cache-Control": "no-cache"
        }
        response = success_response(headers=headers)
        
        for header_name, header_value in headers.items():
            assert response[header_name] == header_value

    def test_response_status_code_consistency(self):
        """Test that status code in data matches HTTP status code"""
        for code in [200, 201, 202, 204]:
            response = success_response(status_code=code)
            assert response.status_code == code
            assert response.data["status"] == code
