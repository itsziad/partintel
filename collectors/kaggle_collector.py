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

CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "raw", "vehicle_repairs.csv",
)
INDEX_NAME = "raw_kaggle_repairs"

COLUMN_ALIASES = {
    "common_problem": ["COMMON PROBLEM", "Common Problem", "common problem"],
    "solution_used": ["SOLUTION USED", "Solution Used", "solution used"],
    "vehicle_company": ["VEHICAL COMPANY", "VEHICLE COMPANY", "Vehicle Company"],
    "service_history": ["SERVICE HISTORY", "Service History", "service history"],
}

def normalize_columns(df):
    col_map = {}
    for internal_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in df.columns:
                col_map[alias] = internal_name
                break
    return df.rename(columns=col_map)

def load_csv():
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f"Fichier introuvable : {CSV_PATH}")
    df = pd.read_csv(CSV_PATH)
    logger.info(f"CSV chargé : {len(df)} lignes, colonnes : {list(df.columns)}")
    return df

def build_record_id(row, index):
    content = f"{row.get('common_problem','')}{row.get('solution_used','')}{index}"
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]

def clean_solution(solution):
    # Supprime la marque de véhicule collée après la virgule dans SOLUTION USED
    if "," in str(solution):
        solution = solution.split(",")[0].strip()
    return solution.strip()

def generate_actions(df):
    skipped = 0
    for idx, row in df.iterrows():
        problem = str(row.get("common_problem", "")).strip()
        solution = clean_solution(str(row.get("solution_used", "")))
        if not problem or problem.lower() == "nan":
            skipped += 1
            continue
        if not solution or solution.lower() == "nan":
            skipped += 1
            continue
        record_id = build_record_id(row, idx)
        yield {
            "_index": INDEX_NAME,
            "_id": record_id,
            "_source": {
                "record_id": record_id,
                "common_problem": problem,
                "solution_used": solution,
                "vehicle_company": str(row.get("vehicle_company", "")).strip(),
                "service_history": str(row.get("service_history", "")).strip(),
                "source": "kaggle_vehicle_repairs",
                "collected_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    if skipped:
        logger.warning(f"{skipped} lignes ignorées")

def run_collection():
    es = get_es_client()
    df = load_csv()
    df = normalize_columns(df)
    actions = list(generate_actions(df))
    logger.info(f"{len(actions)} documents prêts à indexer")
    success, errors = helpers.bulk(es, actions, raise_on_error=False)
    report = {
        "total_rows": len(df),
        "total_indexed": success,
        "total_errors": len(errors) if errors else 0,
    }
    logger.info(f"Collecte terminée : {report}")
    return report

if __name__ == "__main__":
    run_collection()
