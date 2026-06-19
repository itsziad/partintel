import os
import sys
import re
import hashlib
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors.es_client import get_es_client
from elasticsearch import helpers

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CLEAN_INDEX = "clean_items"

CLEAN_MAPPING = {
    "mappings": {
        "properties": {
            "item_id":          {"type": "keyword"},
            "source":           {"type": "keyword"},
            "content_type":     {"type": "keyword"},
            "title":            {"type": "text", "analyzer": "english",
                                 "fields": {"keyword": {"type": "keyword"}}},
            "description":      {"type": "text", "analyzer": "english"},
            "tags":             {"type": "keyword"},
            "author":           {"type": "keyword"},
            "content_hash":     {"type": "keyword"},
            "is_duplicate":     {"type": "boolean"},
            "quality_score":    {"type": "float"},
            "collected_at":     {"type": "date"},
            "processed_at":     {"type": "date"},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

def clean_text(text, max_length=500):
    if not text or str(text).lower() == "nan":
        return ""
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]

def compute_hash(title, source_id):
    content = f"{title.lower().strip()}|{source_id}"
    return hashlib.md5(content.encode("utf-8")).hexdigest()

def quality_score(doc):
    score = 0.0
    if doc.get("title") and len(doc["title"]) > 3:
        score += 0.40
    if doc.get("description") and len(doc["description"]) > 10:
        score += 0.30
    if doc.get("tags"):
        score += 0.15
    if doc.get("author"):
        score += 0.15
    return round(score, 2)

def transform_kaggle(hit):
    src = hit["_source"]
    problem = clean_text(src.get("common_problem", ""))
    solution = clean_text(src.get("solution_used", ""))
    if not problem:
        return None
    title = problem
    description = f"Solution : {solution}" if solution else ""
    tags = []
    if src.get("vehicle_company"):
        tags.append(clean_text(src["vehicle_company"]))
    if solution:
        tags.append(solution[:50])
    doc = {
        "item_id": f"kaggle_{src.get('record_id', hit['_id'])}",
        "source": "kaggle",
        "content_type": "repair_case",
        "title": title,
        "description": description,
        "tags": [t for t in tags if t],
        "author": "",
        "content_hash": compute_hash(title, hit["_id"]),
        "is_duplicate": False,
        "collected_at": src.get("collected_at"),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    doc["quality_score"] = quality_score(doc)
    return doc

def transform_rss(hit):
    src = hit["_source"]
    title = clean_text(src.get("title", ""))
    if not title:
        return None
    description = clean_text(src.get("summary", ""), max_length=300)
    doc = {
        "item_id": f"rss_{src.get('doc_id', hit['_id'])}",
        "source": "rss",
        "content_type": "news_article",
        "title": title,
        "description": description,
        "tags": [src.get("source_name", "")] if src.get("source_name") else [],
        "author": src.get("source_name", ""),
        "content_hash": compute_hash(title, hit["_id"]),
        "is_duplicate": False,
        "collected_at": src.get("collected_at"),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    doc["quality_score"] = quality_score(doc)
    return doc

def transform_opendata(hit):
    src = hit["_source"]
    commune = clean_text(src.get("commune_nom", ""))
    carburant = clean_text(src.get("carburant", ""))
    categorie = clean_text(src.get("categorie", ""))
    if not commune or not carburant:
        return None
    title = f"{commune} - {carburant} - {categorie}"
    parc_2023 = src.get("parc_2023", 0)
    parc_2025 = src.get("parc_2025", 0)
    description = f"Parc 2023: {parc_2023} vehicules | Parc 2025: {parc_2025} vehicules"
    doc = {
        "item_id": f"sdes_{src.get('doc_id', hit['_id'])}",
        "source": "opendata_sdes",
        "content_type": "parc_automobile",
        "title": title,
        "description": description,
        "tags": [carburant, categorie, src.get("groupe", "")],
        "author": "SDES",
        "content_hash": compute_hash(title, hit["_id"]),
        "is_duplicate": False,
        "collected_at": src.get("collected_at"),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    doc["quality_score"] = quality_score(doc)
    return doc

TRANSFORMERS = {
    "raw_kaggle_repairs":   transform_kaggle,
    "raw_rss_automotive":   transform_rss,
    "raw_opendata_parc_auto": transform_opendata,
}

def deduplicate(documents):
    seen = set()
    result = []
    dupes = 0
    for doc in documents:
        h = doc.get("content_hash", "")
        if h in seen:
            doc["is_duplicate"] = True
            dupes += 1
        else:
            seen.add(h)
        result.append(doc)
    if dupes:
        logger.info(f"Doublons detectes : {dupes}")
    return result

def create_clean_index(es):
    if not es.indices.exists(index=CLEAN_INDEX):
        es.indices.create(index=CLEAN_INDEX, body=CLEAN_MAPPING)
        logger.info(f"Index cree : {CLEAN_INDEX}")
    else:
        logger.info(f"Index existant : {CLEAN_INDEX}")

def run_transformation():
    es = get_es_client()
    create_clean_index(es)

    all_docs = []
    for raw_index, transform_fn in TRANSFORMERS.items():
        if not es.indices.exists(index=raw_index):
            logger.warning(f"Index introuvable : {raw_index} — ignore")
            continue
        count = es.count(index=raw_index)["count"]
        logger.info(f"Transformation {raw_index} : {count} documents bruts")
        docs = []
        for hit in helpers.scan(es, index=raw_index, query={"query": {"match_all": {}}}, scroll="2m"):
            doc = transform_fn(hit)
            if doc:
                docs.append(doc)
        logger.info(f"  -> {len(docs)} documents transformes")
        all_docs.extend(docs)

    all_docs = deduplicate(all_docs)
    valid_docs = [d for d in all_docs if not d["is_duplicate"]]
    logger.info(f"Total apres deduplication : {len(valid_docs)} documents uniques")

    actions = [
        {"_index": CLEAN_INDEX, "_id": d["item_id"], "_source": d}
        for d in valid_docs
    ]
    if actions:
        success, errors = helpers.bulk(es, actions, raise_on_error=False)
        logger.info(f"Indexes dans clean_items : {success} | Erreurs : {len(errors) if errors else 0}")

    return {"total_clean": len(valid_docs)}

if __name__ == "__main__":
    result = run_transformation()
    print(f"\nResultat : {result}")
