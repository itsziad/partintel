import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors.es_client import get_es_client

INDEX_NAME = "raw_kaggle_repairs"

def check():
    es = get_es_client()
    if not es.indices.exists(index=INDEX_NAME):
        print(f"✗ Index '{INDEX_NAME}' introuvable.")
        return
    count = es.count(index=INDEX_NAME)["count"]
    print(f"✓ {count} documents dans '{INDEX_NAME}'")
    response = es.search(index=INDEX_NAME, body={"query": {"match_all": {}}, "size": 3})
    print("\nExemples :")
    print("-" * 60)
    for hit in response["hits"]["hits"]:
        src = hit["_source"]
        print(f"  Panne    : {src.get('common_problem')}")
        print(f"  Solution : {src.get('solution_used')}")
        print(f"  Véhicule : {src.get('vehicle_company')}")
        print("-" * 60)

if __name__ == "__main__":
    check()
