import os
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

# Monkeypatch DATABASE_URL BEFORE importing main
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from main import app, get_session

# Setup test DB
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

def get_session_override():
    with Session(engine) as session:
        yield session

app.dependency_overrides[get_session] = get_session_override

@pytest.fixture(name="client")
def client_fixture():
    SQLModel.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(name="admin_token")
def admin_token_fixture(client):
    response = client.post("/auth/token", data={"username": "admin1", "role": "admin", "password": "demo123"})
    return response.json()["access_token"]

@pytest.fixture(name="hotel_token")
def hotel_token_fixture(client):
    response = client.post("/auth/token", data={"username": "hotel1", "role": "hotel", "password": "demo123"})
    return response.json()["access_token"]

def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"HotelSupply" in response.content


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200

def test_dashboard_summary_structure(client):
    response = client.get("/dashboard/summary")
    assert response.status_code == 200
    data = response.json()
    expected_keys = {"total", "open", "matched", "accepted", "fulfilled", "fulfillment_rate"}
    assert set(data.keys()) == expected_keys

def test_create_hotel_unauthenticated(client):
    response = client.post("/hotels", json={"name": "Test Hotel", "contact_email": "test@test.com"})
    assert response.status_code == 401

def test_auth_token_bad_password(client):
    response = client.post("/auth/token", data={"username": "admin1", "role": "admin", "password": "wrong"})
    assert response.status_code == 401

def test_auth_token_success(client):
    response = client.post("/auth/token", data={"username": "admin1", "role": "admin", "password": "demo123"})
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_create_hotel_as_admin(client, admin_token):
    response = client.post(
        "/hotels", 
        json={"name": "Test Hotel", "contact_email": "test@test.com"},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200

def test_create_supplier_as_admin(client, admin_token):
    response = client.post(
        "/suppliers", 
        json={"name": "Test Supplier", "contact_email": "supp@test.com", "catalog_items": "beds,towels"},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200

def test_hotel_cannot_create_supplier(client, hotel_token):
    response = client.post(
        "/suppliers", 
        json={"name": "Test Supplier", "contact_email": "supp@test.com", "catalog_items": "beds,towels"},
        headers={"Authorization": f"Bearer {hotel_token}"}
    )
    assert response.status_code == 403
