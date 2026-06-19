import os
import sys
import hashlib
import logging
from datetime import datetime, timezone

import feedparser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors.es_client import get_es_client
from elasticsearch import helpers

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

INDEX_NAME = "raw_rss_automotive"

RSS_FEEDS = {
    "usine_auto": "https://www.usinenouvelle.com/rss/auto.xml",
    "motor1_fr": "https://fr.motor1.com/rss/news/all/",
    "caradisiac": "https://www.caradisiac.com/rss/actualite.xml",
}

def build_doc_id(entry):
    content = f"{entry.get('link','')}{entry.get('title','')}"
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]

def parse_feed(source_name, url):
    logger.info(f"Parsing flux : {source_name} ({url})")
    try:
        feed = feedparser.parse(url)
        if feed.bozo:
            logger.warning(f"Flux malformé {source_name} : {feed.bozo_exception}")
        logger.info(f"{source_name} : {len(feed.entries)} entrées trouvées")
        return feed.entries
    except Exception as exc:
        logger.error(f"Erreur flux {source_name} : {exc}")
        return []

def generate_actions(source_name, entries):
    for entry in entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        summary = entry.get("summary", "").strip()
        published = entry.get("published", "")

        if not title or not link:
            continue

        doc_id = build_doc_id(entry)

        yield {
            "_index": INDEX_NAME,
            "_id": doc_id,
            "_source": {
                "doc_id": doc_id,
                "title": title,
                "link": link,
                "summary": summary[:500],
                "published_raw": published,
                "source_name": source_name,
                "source": "rss_automotive",
                "collected_at": datetime.now(timezone.utc).isoformat(),
            },
        }

def run_collection():
    es = get_es_client()
    total_indexed = 0
    total_errors = 0

    for source_name, url in RSS_FEEDS.items():
        entries = parse_feed(source_name, url)
        if not entries:
            continue

        actions = list(generate_actions(source_name, entries))
        if not actions:
            continue

        success, errors = helpers.bulk(es, actions, raise_on_error=False)
        total_indexed += success
        total_errors += len(errors) if errors else 0
        logger.info(f"{source_name} : {success} articles indexés")

    report = {
        "total_indexed": total_indexed,
        "total_errors": total_errors,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"Collecte RSS terminée : {report}")
    return report

if __name__ == "__main__":
    run_collection()
