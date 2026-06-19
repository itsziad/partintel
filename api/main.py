import os
import sys
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import bcrypt
from jose import jwt, JWTError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors.es_client import get_es_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "partintel_secret_key_minimum_32_chars_long")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60

# Comptes de demo (bcrypt) — jamais de mots de passe en clair
DEMO_USERS = {
    "admin": bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode(),
    "demo":  bcrypt.hashpw("demo123".encode(),  bcrypt.gensalt()).decode(),
}

app = FastAPI(
    title="PartIntel API",
    description="API REST de recommandation de pièces détachées automobiles",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5601", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()


# ─── Schémas Pydantic ────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class SearchResponse(BaseModel):
    query: str
    total: int
    results: list
    took_ms: float

class RecommendResponse(BaseModel):
    query: str
    model: str
    results: list
    took_ms: float


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def create_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─── Endpoints Auth ───────────────────────────────────────────────────────────

@app.post("/auth/login", response_model=TokenResponse, tags=["Auth"])
def login(request: LoginRequest):
    """
    Authentification JWT.
    Comptes de demo : admin/admin123 ou demo/demo123
    """
    stored = DEMO_USERS.get(request.username)
    if not stored or not bcrypt.checkpw(request.password.encode(), stored.encode()):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    token = create_token(request.username)
    return TokenResponse(access_token=token, expires_in=JWT_EXPIRE_MINUTES * 60)

@app.get("/auth/me", tags=["Auth"])
def get_profile(user: str = Depends(get_current_user)):
    """Retourne le profil de l'utilisateur connecté."""
    return {"username": user, "authenticated": True}


# ─── Endpoints Système ────────────────────────────────────────────────────────

@app.get("/health", tags=["Système"])
def health():
    """Vérification de santé de l'API."""
    return {"status": "healthy", "version": "1.0.0", "timestamp": time.time()}


# ─── Endpoints CRUD ───────────────────────────────────────────────────────────

@app.get("/items/{item_id}", tags=["Items"])
def get_item(item_id: str, user: str = Depends(get_current_user)):
    """Récupère un item par son ID depuis clean_items."""
    es = get_es_client()
    try:
        result = es.get(index="clean_items", id=item_id)
        return {"item_id": item_id, "data": result["_source"]}
    except Exception:
        raise HTTPException(status_code=404, detail=f"Item {item_id} introuvable")

@app.get("/items", tags=["Items"])
def list_items(
    source: Optional[str] = Query(None, description="Filtrer par source : kaggle | rss | opendata_sdes"),
    size: int = Query(10, ge=1, le=100),
    user: str = Depends(get_current_user),
):
    """Liste les items de clean_items avec filtre optionnel par source."""
    es = get_es_client()
    query = {"query": {"match_all": {}}, "size": size}
    if source:
        query["query"] = {"term": {"source": source}}
    result = es.search(index="clean_items", body=query)
    items = [{"item_id": h["_id"], **h["_source"]} for h in result["hits"]["hits"]]
    return {"total": result["hits"]["total"]["value"], "items": items}

@app.delete("/items/{item_id}", tags=["Items"])
def delete_item(item_id: str, user: str = Depends(get_current_user)):
    """Supprime un item de clean_items."""
    es = get_es_client()
    try:
        es.delete(index="clean_items", id=item_id)
        return {"message": f"Item {item_id} supprimé"}
    except Exception:
        raise HTTPException(status_code=404, detail=f"Item {item_id} introuvable")


# ─── Endpoint Recherche ───────────────────────────────────────────────────────

@app.get("/search", response_model=SearchResponse, tags=["Recherche"])
def search(
    q: str = Query(..., description="Requête de recherche", min_length=2),
    source: Optional[str] = Query(None),
    size: int = Query(10, ge=1, le=50),
    user: str = Depends(get_current_user),
):
    """
    Recherche full-text dans clean_items.
    Utilise une requête multi-match avec boost sur le titre.
    """
    es = get_es_client()
    t0 = time.perf_counter()

    must = [{"multi_match": {
        "query": q,
        "fields": ["title^3", "description^1", "tags^2"],
        "fuzziness": "AUTO",
    }}]
    filters = []
    if source:
        filters.append({"term": {"source": source}})

    body = {
        "query": {"bool": {"must": must, "filter": filters}},
        "size": size,
    }
    result = es.search(index="clean_items", body=body)
    took_ms = (time.perf_counter() - t0) * 1000

    results = [
        {
            "item_id": h["_id"],
            "title": h["_source"].get("title", ""),
            "description": h["_source"].get("description", "")[:200],
            "source": h["_source"].get("source", ""),
            "score": h["_score"],
        }
        for h in result["hits"]["hits"]
    ]

    return SearchResponse(
        query=q,
        total=result["hits"]["total"]["value"],
        results=results,
        took_ms=round(took_ms, 1),
    )


# ─── Endpoint Recommandation ──────────────────────────────────────────────────

@app.get("/recommend", response_model=RecommendResponse, tags=["Recommandations"])
def recommend(
    q: str = Query(..., description="Description de la panne en langage naturel"),
    top_k: int = Query(5, ge=1, le=20),
    user: str = Depends(get_current_user),
):
    """
    Recommandation sémantique avec MiniLM-L6-v2.
    Encode la requête et cherche les pannes/solutions les plus similaires.
    """
    from sentence_transformers import SentenceTransformer
    from elasticsearch import helpers
    import numpy as np

    t0 = time.perf_counter()
    es = get_es_client()

    # Chargement du modèle (singleton en mémoire)
    if not hasattr(recommend, "_model"):
        recommend._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        # Préchargement du corpus
        recommend._corpus = []
        for hit in helpers.scan(es, index="raw_kaggle_repairs",
                                 query={"query": {"match_all": {}}}, scroll="2m"):
            src = hit["_source"]
            if src.get("common_problem") and src.get("solution_used"):
                recommend._corpus.append(src)
        texts = [c["common_problem"] for c in recommend._corpus]
        recommend._embeddings = recommend._model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )

    query_vec = recommend._model.encode([q], normalize_embeddings=True)[0]
    scores = recommend._embeddings @ query_vec
    top_indices = scores.argsort()[::-1][:top_k]

    results = [
        {
            "rank": int(i + 1),
            "problem": recommend._corpus[idx]["common_problem"],
            "solution": recommend._corpus[idx]["solution_used"],
            "vehicle": recommend._corpus[idx].get("vehicle_company", ""),
            "similarity": round(float(scores[idx]), 4),
        }
        for i, idx in enumerate(top_indices)
    ]

    took_ms = (time.perf_counter() - t0) * 1000
    return RecommendResponse(
        query=q,
        model="MiniLM-L6-v2",
        results=results,
        took_ms=round(took_ms, 1),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)


@app.get("/metrics", tags=["Système"], include_in_schema=False)
def metrics():
    """Exposition des métriques Prometheus."""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
