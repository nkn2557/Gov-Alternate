
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/")
    assert response.status_code == 200
    print("[PASS] Health Check:", response.json())

def test_search_municipalities():
    # Test with "mock" query to trigger the mock response in Service
    response = client.get("/v1/municipalities/search?q=mock")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert data[0]["name"] == "千代田区"
    print("[PASS] Search Municipalities:", data)

def test_recommendations():
    payload = {
        "municipality_id": "tokyo-chiyoda",
        "category": "moving",
        "profile": {
            "moving_date": "2026-02",
            "children_counts": 1
        }
    }
    response = client.post("/v1/recommendations", json=payload)
    if response.status_code != 200:
        print("[FAIL] Recommendations:", response.text)
    assert response.status_code == 200
    data = response.json()
    # Should get empty cards list if DB is empty, but structure should be valid
    assert "cards" in data
    print("[PASS] Recommendations (Count):", data["program_count"])

def test_admin_build_start():
    payload = {
        "municipality_id": "tokyo-chiyoda",
        "domain": "moving"
    }
    response = client.post("/admin/catalog/build", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "building"
    print("[PASS] Admin Build Start:", data)
    return data["catalog_id"]

def test_admin_build_status(catalog_id):
    response = client.get(f"/admin/catalog/{catalog_id}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "building"
    print("[PASS] Admin Build Status:", data)

if __name__ == "__main__":
    print("Running Tests...")
    try:
        test_health_check()
        test_search_municipalities()
        test_recommendations()
        cid = test_admin_build_start()
        test_admin_build_status(cid)
        print("\nAll Tests Passed!")
    except Exception as e:
        print(f"\nTest Failed: {e}")
        exit(1)
