"""
Tests unitaires et d'intégration de l'API PartIntel.
Couvre : health check, authentification, search, recommend.
"""

import pytest
from fastapi.testclient import TestClient
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("JWT_SECRET_KEY", "test_secret_key_minimum_32_characters_long")
os.environ.setdefault("ES_HOST", "localhost")
os.environ.setdefault("ES_PORT", "9200")
os.environ.setdefault("ES_PASSWORD", "Daiz@2703")

from api.main import app

client = TestClient(app)


# ─── Tests système ────────────────────────────────────────────────────────────

def test_health_check():
    """L'endpoint /health retourne 200 et status healthy."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"
    assert "timestamp" in data


def test_openapi_docs_available():
    """La documentation OpenAPI est accessible."""
    r = client.get("/docs")
    assert r.status_code == 200


def test_metrics_endpoint():
    """L'endpoint /metrics expose des métriques Prometheus."""
    r = client.get("/metrics")
    assert r.status_code == 200
    assert b"python" in r.content or b"process" in r.content


# ─── Tests authentification ───────────────────────────────────────────────────

def test_login_success():
    """Login avec identifiants corrects retourne un token JWT."""
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 3600


def test_login_wrong_password():
    """Login avec mauvais mot de passe retourne 401."""
    r = client.post("/auth/login", json={"username": "admin", "password": "wrongpassword"})
    assert r.status_code == 401


def test_login_unknown_user():
    """Login avec utilisateur inconnu retourne 401."""
    r = client.post("/auth/login", json={"username": "unknown", "password": "test"})
    assert r.status_code == 401


def get_token():
    """Helper : récupère un token valide pour les tests protégés."""
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    return r.json()["access_token"]


def test_get_profile_authenticated():
    """L'endpoint /auth/me retourne le profil si token valide."""
    token = get_token()
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "admin"


def test_get_profile_no_token():
    """L'endpoint /auth/me retourne 403 sans token."""
    r = client.get("/auth/me")
    assert r.status_code in (401, 403)


def test_get_profile_invalid_token():
    """L'endpoint /auth/me retourne 401 avec token invalide."""
    r = client.get("/auth/me", headers={"Authorization": "Bearer fake_token_invalid"})
    assert r.status_code == 401


# ─── Tests items ──────────────────────────────────────────────────────────────

def test_list_items_authenticated():
    """GET /items retourne une liste si authentifié."""
    token = get_token()
    r = client.get("/items?size=5", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data


def test_list_items_no_auth():
    """GET /items retourne 403 sans authentification."""
    r = client.get("/items")
    assert r.status_code in (401, 403)


def test_list_items_filter_by_source():
    """GET /items avec filtre source retourne uniquement cette source."""
    token = get_token()
    r = client.get("/items?source=kaggle&size=5",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    for item in data["items"]:
        assert item["source"] == "kaggle"


def test_get_item_not_found():
    """GET /items/{id} avec ID inexistant retourne 404."""
    token = get_token()
    r = client.get("/items/id_qui_nexiste_pas_du_tout",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


# ─── Tests recherche ──────────────────────────────────────────────────────────

def test_search_basic():
    """GET /search avec une requête retourne des résultats."""
    token = get_token()
    r = client.get("/search?q=brake",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert "results" in data
    assert "total" in data
    assert data["query"] == "brake"


def test_search_no_auth():
    """GET /search sans token retourne 403."""
    r = client.get("/search?q=brake")
    assert r.status_code in (401, 403)


def test_search_short_query():
    """GET /search avec requête trop courte retourne 422."""
    token = get_token()
    r = client.get("/search?q=a",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 422


def test_search_with_source_filter():
    """GET /search avec filtre source fonctionne."""
    token = get_token()
    r = client.get("/search?q=oil&source=kaggle",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_search_pagination():
    """GET /search avec paramètre size fonctionne."""
    token = get_token()
    r = client.get("/search?q=brake&size=3",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert len(data["results"]) <= 3


# ─── Tests recommandation ─────────────────────────────────────────────────────

def test_recommend_basic():
    """GET /recommend retourne des recommandations sémantiques."""
    token = get_token()
    r = client.get("/recommend?q=brake+noise+when+stopping",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert "results" in data
    assert data["model"] == "MiniLM-L6-v2"
    assert len(data["results"]) > 0


def test_recommend_similarity_range():
    """Les scores de similarité sont entre 0 et 1."""
    token = get_token()
    r = client.get("/recommend?q=engine+overheating",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    for result in r.json()["results"]:
        assert 0.0 <= result["similarity"] <= 1.0


def test_recommend_no_auth():
    """GET /recommend sans token retourne 403."""
    r = client.get("/recommend?q=brake+noise")
    assert r.status_code in (401, 403)


def test_recommend_top_k():
    """GET /recommend respecte le paramètre top_k."""
    token = get_token()
    r = client.get("/recommend?q=brake+noise&top_k=3",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert len(r.json()["results"]) <= 3
