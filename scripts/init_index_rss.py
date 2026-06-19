import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors.es_client import get_es_client

INDEX_NAME = "raw_rss_automotive"
MAPPING = {
    "mappings": {
        "properties": {
            "doc_id": {"type": "keyword"},
            "title": {"type": "text", "analyzer": "french"},
            "link": {"type": "keyword"},
            "summary": {"type": "text", "analyzer": "french"},
            "published_raw": {"type": "keyword"},
            "source_name": {"type": "keyword"},
            "source": {"type": "keyword"},
            "collected_at": {"type": "date"},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

def create_index():
    es = get_es_client()
    if not es.indices.exists(index=INDEX_NAME):
        es.indices.create(index=INDEX_NAME, body=MAPPING)
        print(f"✓ Index créé : {INDEX_NAME}")
    else:
        print(f"→ Index déjà existant : {INDEX_NAME}")

if __name__ == "__main__":
    create_index()
