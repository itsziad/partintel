import os
import sys
import json
import logging
import numpy as np
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors.es_client import get_es_client
from elasticsearch import helpers

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
TEST_QUERIES_PATH = os.path.join(DATA_PATH, "test_queries.json")


# ─── Chargement du corpus ────────────────────────────────────────────────────

def load_corpus():
    """Charge les paires panne/solution depuis Elasticsearch."""
    es = get_es_client()
    corpus = []
    for hit in helpers.scan(es, index="raw_kaggle_repairs",
                             query={"query": {"match_all": {}}}, scroll="2m"):
        src = hit["_source"]
        problem = src.get("common_problem", "").strip()
        solution = src.get("solution_used", "").strip()
        if problem and solution:
            corpus.append({"problem": problem, "solution": solution,
                           "id": src.get("record_id", hit["_id"])})
    logger.info(f"Corpus charge : {len(corpus)} paires panne/solution")
    return corpus


def load_test_queries():
    with open(TEST_QUERIES_PATH, "r") as f:
        return json.load(f)


# ─── Métriques d'évaluation ──────────────────────────────────────────────────

def precision_at_k(retrieved, relevant, k):
    top_k = retrieved[:k]
    hits = sum(1 for r in top_k if r in relevant)
    return hits / k if k > 0 else 0.0

def recall_at_k(retrieved, relevant, k):
    if not relevant:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for r in top_k if r in relevant)
    return hits / len(relevant)

def average_precision_at_k(retrieved, relevant, k):
    if not relevant:
        return 0.0
    hits, score = 0, 0.0
    for i, r in enumerate(retrieved[:k], 1):
        if r in relevant:
            hits += 1
            score += hits / i
    return score / min(len(relevant), k)

def reciprocal_rank(retrieved, relevant):
    for i, r in enumerate(retrieved, 1):
        if r in relevant:
            return 1.0 / i
    return 0.0

def ndcg_at_k(retrieved, relevant, k):
    import math
    dcg = sum(1.0 / math.log2(i + 1) for i, r in enumerate(retrieved[:k], 1) if r in relevant)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / idcg if idcg > 0 else 0.0

def evaluate_model(model_name, search_fn, corpus, test_queries, k=5):
    logger.info(f"Evaluation du modele : {model_name}")
    p_scores, r_scores, ap_scores, rr_scores, ndcg_scores = [], [], [], [], []

    for item in test_queries:
        query = item["query"]
        relevant = set(item["relevant_solutions"])
        retrieved = search_fn(query, corpus, k=k*2)
        retrieved_solutions = [r["solution"] for r in retrieved[:k]]

        p_scores.append(precision_at_k(retrieved_solutions, relevant, k))
        r_scores.append(recall_at_k(retrieved_solutions, relevant, k))
        ap_scores.append(average_precision_at_k(retrieved_solutions, relevant, k))
        rr_scores.append(reciprocal_rank(retrieved_solutions, relevant))
        ndcg_scores.append(ndcg_at_k(retrieved_solutions, relevant, k))

    results = {
        "model": model_name,
        f"precision@{k}": round(np.mean(p_scores), 4),
        f"recall@{k}": round(np.mean(r_scores), 4),
        f"map@{k}": round(np.mean(ap_scores), 4),
        "mrr": round(np.mean(rr_scores), 4),
        f"ndcg@{k}": round(np.mean(ndcg_scores), 4),
    }
    logger.info(f"  P@{k}={results[f'precision@{k}']} MAP={results[f'map@{k}']} "
                f"MRR={results['mrr']} NDCG@{k}={results[f'ndcg@{k}']}")
    return results


# ─── Modèle 1 : TF-IDF ───────────────────────────────────────────────────────

def build_tfidf(corpus):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    texts = [c["problem"] for c in corpus]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=5000)
    matrix = vectorizer.fit_transform(texts)
    return vectorizer, matrix

def search_tfidf(query, corpus, vectorizer, matrix, k=10):
    from sklearn.metrics.pairwise import cosine_similarity
    vec = vectorizer.transform([query])
    scores = cosine_similarity(vec, matrix)[0]
    top_indices = scores.argsort()[::-1][:k]
    return [{"problem": corpus[i]["problem"], "solution": corpus[i]["solution"],
             "score": float(scores[i])} for i in top_indices]


# ─── Modèle 2 : Word2Vec ─────────────────────────────────────────────────────

def build_word2vec(corpus):
    from gensim.models import Word2Vec
    sentences = [c["problem"].lower().split() for c in corpus]
    model = Word2Vec(sentences, vector_size=100, window=5, min_count=1, workers=4, epochs=50)
    return model

def text_to_vec_w2v(text, model):
    words = text.lower().split()
    vecs = [model.wv[w] for w in words if w in model.wv]
    return np.mean(vecs, axis=0) if vecs else np.zeros(model.vector_size)

def search_word2vec(query, corpus, model, k=10):
    query_vec = text_to_vec_w2v(query, model)
    scores = []
    for item in corpus:
        doc_vec = text_to_vec_w2v(item["problem"], model)
        norm = np.linalg.norm(query_vec) * np.linalg.norm(doc_vec)
        sim = float(np.dot(query_vec, doc_vec) / norm) if norm > 0 else 0.0
        scores.append((sim, item))
    scores.sort(key=lambda x: x[0], reverse=True)
    return [{"problem": s[1]["problem"], "solution": s[1]["solution"],
             "score": s[0]} for s in scores[:k]]


# ─── Modèle 3 : Sentence Transformers (MiniLM) ───────────────────────────────

def build_sentence_transformer(corpus):
    from sentence_transformers import SentenceTransformer
    logger.info("Chargement MiniLM-L6-v2 (premier chargement : telechargement possible)...")
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    texts = [c["problem"] for c in corpus]
    embeddings = model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    logger.info("Embeddings MiniLM calcules.")
    return model, embeddings

def search_sentence_transformer(query, corpus, model, embeddings, k=10):
    query_vec = model.encode([query], normalize_embeddings=True)[0]
    scores = embeddings @ query_vec
    top_indices = scores.argsort()[::-1][:k]
    return [{"problem": corpus[i]["problem"], "solution": corpus[i]["solution"],
             "score": float(scores[i])} for i in top_indices]


# ─── Modèle 4 : LLM local via Ollama ─────────────────────────────────────────

def build_ollama_embeddings(corpus):
    import requests as req
    logger.info("Generation des embeddings Ollama (nomic-embed-text)...")
    embeddings = []
    for item in corpus:
        try:
            r = req.post("http://localhost:11434/api/embeddings",
                        json={"model": "nomic-embed-text", "prompt": item["problem"]},
                        timeout=30)
            emb = r.json().get("embedding", [])
            embeddings.append(np.array(emb) if emb else np.zeros(768))
        except Exception:
            embeddings.append(np.zeros(768))
    embeddings = np.array(embeddings)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.where(norms > 0, norms, 1)
    logger.info(f"Embeddings Ollama calcules : {len(embeddings)} vecteurs")
    return embeddings

def search_ollama(query, corpus, embeddings, k=10):
    import requests as req
    try:
        r = req.post("http://localhost:11434/api/embeddings",
                    json={"model": "nomic-embed-text", "prompt": query}, timeout=30)
        query_vec = np.array(r.json().get("embedding", np.zeros(768)))
        norm = np.linalg.norm(query_vec)
        if norm > 0:
            query_vec = query_vec / norm
        scores = embeddings @ query_vec
        top_indices = scores.argsort()[::-1][:k]
        return [{"problem": corpus[i]["problem"], "solution": corpus[i]["solution"],
                 "score": float(scores[i])} for i in top_indices]
    except Exception as exc:
        logger.error(f"Ollama indisponible : {exc}")
        return []


# ─── Pipeline principal ───────────────────────────────────────────────────────

def run_all_models():
    corpus = load_corpus()
    test_queries = load_test_queries()
    all_results = []

    # Modèle 1 — TF-IDF
    logger.info("=== Modele 1 : TF-IDF ===")
    vectorizer, matrix = build_tfidf(corpus)
    results_tfidf = evaluate_model(
        "TF-IDF",
        lambda q, c, k: search_tfidf(q, c, vectorizer, matrix, k),
        corpus, test_queries
    )
    all_results.append(results_tfidf)

    # Modèle 2 — Word2Vec
    logger.info("=== Modele 2 : Word2Vec ===")
    w2v_model = build_word2vec(corpus)
    results_w2v = evaluate_model(
        "Word2Vec",
        lambda q, c, k: search_word2vec(q, c, w2v_model, k),
        corpus, test_queries
    )
    all_results.append(results_w2v)

    # Modèle 3 — Sentence Transformers
    logger.info("=== Modele 3 : Sentence Transformers (MiniLM) ===")
    st_model, st_embeddings = build_sentence_transformer(corpus)
    results_st = evaluate_model(
        "MiniLM-L6-v2",
        lambda q, c, k: search_sentence_transformer(q, c, st_model, st_embeddings, k),
        corpus, test_queries
    )
    all_results.append(results_st)

    # Modèle 4 — Ollama (optionnel)
    logger.info("=== Modele 4 : LLM Ollama ===")
    try:
        ollama_embeddings = build_ollama_embeddings(corpus)
        results_ollama = evaluate_model(
            "LLM-Ollama",
            lambda q, c, k: search_ollama(q, c, ollama_embeddings, k),
            corpus, test_queries
        )
        all_results.append(results_ollama)
    except Exception as exc:
        logger.warning(f"Ollama ignore : {exc}")

    # Tableau comparatif
    print("\n" + "="*75)
    print(f"{'Modele':<20} {'P@5':<8} {'R@5':<8} {'MAP@5':<8} {'MRR':<8} {'NDCG@5'}")
    print("-"*75)
    for r in all_results:
        print(f"{r['model']:<20} {r['precision@5']:<8} {r['recall@5']:<8} "
              f"{r['map@5']:<8} {r['mrr']:<8} {r['ndcg@5']}")
    print("="*75)

    best = max(all_results, key=lambda x: x["ndcg@5"])
    print(f"\nModele retenu : {best['model']} (meilleur NDCG@5 = {best['ndcg@5']})")

    return all_results

if __name__ == "__main__":
    run_all_models()
