import pytest
from fastapi.testclient import TestClient

def test_create_rule_success(client: TestClient):
    payload = {
        "keyword": "PRICE",
        "dm_message": "Here's the price list: 100$"
    }
    response = client.post("/rules", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "rule_id" in data
    assert data["keyword"] == "PRICE"
    assert data["dm_message"] == "Here's the price list: 100$"

def test_create_rule_empty_keyword(client: TestClient):
    payload = {
        "keyword": "   ",
        "dm_message": "Here's the price list"
    }
    response = client.post("/rules", json=payload)
    assert response.status_code == 422

def test_create_rule_empty_message(client: TestClient):
    payload = {
        "keyword": "PRICE",
        "dm_message": ""
    }
    response = client.post("/rules", json=payload)
    assert response.status_code == 422
