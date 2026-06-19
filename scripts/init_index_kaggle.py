import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors.es_client import get_es_client

INDEX_NAME = "raw_kaggle_repairs"
MAPPING = {
    "mappings": {
        "properties": {
            "record_id": {"type": "keyword"},
            "common_problem": {"type": "text", "analyzer": "english"},
            "solution_used": {"type": "text", "analyzer": "english"},
            "vehicle_company": {"type": "keyword"},
            "service_history": {"type": "text"},
            "source": {"type": "keyword"},
            "collected_at": {"type": "date"},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

def create_index(recreate=False):
    es = get_es_client()
    exists = es.indices.exists(index=INDEX_NAME)
    if exists and recreate:
        es.indices.delete(index=INDEX_NAME)
        exists = False
    if not exists:
        es.indices.create(index=INDEX_NAME, body=MAPPING)
        print(f"✓ Index créé : {INDEX_NAME}")
    else:
        print(f"→ Index déjà existant : {INDEX_NAME}")

if __name__ == "__main__":
    create_index()
