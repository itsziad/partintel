import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors.es_client import get_es_client

INDEX_NAME = "raw_opendata_parc_auto"
MAPPING = {
    "mappings": {
        "properties": {
            "doc_id": {"type": "keyword"},
            "annee": {"type": "integer"},
            "region": {"type": "keyword"},
            "departement": {"type": "keyword"},
            "commune": {"type": "keyword"},
            "motorisation": {"type": "keyword"},
            "nb_vp": {"type": "integer"},
            "source": {"type": "keyword"},
            "collected_at": {"type": "date"},
            "raw_record": {"type": "object", "dynamic": True},
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
