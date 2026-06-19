import os
import sys
import hashlib
import logging
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors.es_client import get_es_client
from elasticsearch import helpers

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

INDEX_NAME = "raw_opendata_parc_auto"

CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "raw", "parc_vehicules_sdes.csv",
)

def load_csv():
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f"Fichier introuvable : {CSV_PATH}")
    df = pd.read_csv(CSV_PATH, sep=";", header=1, quotechar='"', encoding="utf-8")
    logger.info(f"CSV charge : {len(df)} lignes, colonnes : {list(df.columns)}")
    return df

def build_doc_id(row, idx):
    content = f"{row.get('COMMUNE_CODE','')}{row.get('CARBURANT','')}{row.get('CATEGORIE','')}{idx}"
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]

def generate_actions(df):
    for idx, row in df.iterrows():
        commune = str(row.get("COMMUNE_CODE", "")).strip()
        if not commune or commune.lower() == "nan":
            continue
        doc_id = build_doc_id(row, idx)
        parc_2023 = int(row["PARC_2023"]) if pd.notna(row.get("PARC_2023")) else 0
        parc_2024 = int(row["PARC_2024"]) if pd.notna(row.get("PARC_2024")) else 0
        parc_2025 = int(row["PARC_2025"]) if pd.notna(row.get("PARC_2025")) else 0
        yield {
            "_index": INDEX_NAME,
            "_id": doc_id,
            "_source": {
                "doc_id": doc_id,
                "commune_code": commune,
                "commune_nom": str(row.get("COMMUNE_NOM", "")).strip(),
                "carburant": str(row.get("CARBURANT", "")).strip(),
                "crit_air": str(row.get("CRIT_AIR", "")).strip(),
                "statut_utilisateur": str(row.get("STATUT_UTILISATEUR", "")).strip(),
                "groupe": str(row.get("GROUPE", "")).strip(),
                "categorie": str(row.get("CATEGORIE", "")).strip(),
                "parc_2023": parc_2023,
                "parc_2024": parc_2024,
                "parc_2025": parc_2025,
                "source": "opendata_sdes",
                "collected_at": datetime.now(timezone.utc).isoformat(),
            },
        }

def run_collection():
    es = get_es_client()
    df = load_csv()
    actions = list(generate_actions(df))
    logger.info(f"{len(actions)} documents prets a indexer")
    success, errors = helpers.bulk(es, actions, raise_on_error=False)
    report = {
        "total_rows": len(df),
        "total_indexed": success,
        "total_errors": len(errors) if errors else 0,
    }
    logger.info(f"Collecte Open Data terminee : {report}")
    return report

if __name__ == "__main__":
    run_collection()
