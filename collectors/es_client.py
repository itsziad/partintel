import os
import sys
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

def get_es_client():
    host = os.getenv("ES_HOST", "localhost")
    port = os.getenv("ES_PORT", "9200")
    user = os.getenv("ES_USER", "elastic")
    password = os.getenv("ES_PASSWORD", "changeme123")
    return Elasticsearch(
        f"http://{host}:{port}",
        basic_auth=(user, password),
        retry_on_timeout=True,
        max_retries=3,
        request_timeout=30,
    )

def check_connection():
    es = get_es_client()
    try:
        info = es.info()
        print(f"✓ Connecté à Elasticsearch {info['version']['number']}")
        health = es.cluster.health()
        print(f"✓ Statut du cluster : {health['status']}")
        return True
    except Exception as exc:
        print(f"✗ Impossible de se connecter : {exc}")
        return False

if __name__ == "__main__":
    ok = check_connection()
    sys.exit(0 if ok else 1)
