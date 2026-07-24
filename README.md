# TechWatch — Système de Veille Technologique Intelligent

> Mémoire de Master Data Engineering — Projet de fin d'études  
> Auteur : [Votre Nom] | Promotion 2024–2025

---

## Résumé du projet

**TechWatch** est un pipeline de veille technologique automatisé qui agrège, analyse et recommande du contenu tech en temps réel à partir de trois sources hétérogènes (API GitHub, scraping HackerNews, flux RSS ArXiv). Le système repose sur une architecture ELT industrialisée avec Elasticsearch, un moteur de recommandation basé sur Sentence Transformers (MiniLM-L6-v2), une API REST FastAPI, et un orchestrateur Airflow — le tout conteneurisé via Docker Compose et déployé via CI/CD GitHub Actions.

---

## Problématique métier

Les développeurs, data scientists et ingénieurs passent en moyenne **4 à 6 heures par semaine** à surveiller manuellement les tendances technologiques (GitHub Trending, Hacker News, publications académiques). TechWatch automatise cette veille et fournit des **recommandations personnalisées** basées sur le profil et l'historique de l'utilisateur.

---

## Sources de données

| Source | Type | Volume estimé | Fréquence |
|---|---|---|---|
| API GitHub REST v3 | API publique | ~500 repos/j | Toutes les 6h |
| HackerNews (scraping) | Web scraping légal | ~300 posts/j | Toutes les 3h |
| ArXiv RSS (cs.AI, cs.LG) | Flux RSS | ~150 papers/j | Quotidien |

---

## Stack technique

| Couche | Technologie | Justification |
|---|---|---|
| Collecte | Python 3.11, requests, BeautifulSoup4, feedparser | Maturité, écosystème riche |
| Stockage | Elasticsearch 8.x | Full-text search natif, JSON natif, scalable |
| Transformation | Python (pandas, pydantic) | Flexibilité, typage fort |
| ML | scikit-learn, gensim, sentence-transformers | Comparaison rigoureuse |
| API | FastAPI + Uvicorn | Performance, auto-documentation OpenAPI |
| Orchestration | Apache Airflow 2.8 | Standard industrie, UI riche |
| Monitoring | Prometheus + Grafana | Stack open-source incontournable |
| CI/CD | GitHub Actions | Natif GitHub, gratuit |
| Conteneurisation | Docker + Docker Compose | Reproductibilité totale |

---

## Architecture ELT — Pourquoi pas ETL ?

L'approche **ELT** (Extract → Load → Transform) est préférée à l'ETL classique pour les raisons suivantes :

1. **Préservation des données brutes** : les données sont stockées telles quelles avant toute transformation, permettant de rejouer les transformations sans recollecte.
2. **Scalabilité** : Elasticsearch absorbe les données brutes à haute vélocité sans goulot d'étranglement de transformation.
3. **Flexibilité** : les règles de transformation évoluent sans impacter la collecte.
4. **Traçabilité** : auditabilité totale grâce aux indices `raw_*`.
5. **Data lake pattern** : cohérent avec les architectures modernes (Medallion Architecture : Bronze → Silver → Gold).

---

## Installation rapide

```bash
git clone https://github.com/votre-compte/techwatch.git
cd techwatch
cp .env.example .env          # Remplir les variables
docker compose up -d          # Lance tous les services
docker compose exec airflow airflow db init
docker compose exec airflow airflow users create --username admin --password admin --role Admin --email admin@techwatch.io --firstname Admin --lastname User
```

Accès aux interfaces :
- **API** : http://localhost:8000/docs
- **Airflow** : http://localhost:8080
- **Kibana** : http://localhost:5601
- **Grafana** : http://localhost:3000

---

## Structure du dépôt

```
techwatch/
├── .github/workflows/          # CI/CD GitHub Actions
│   └── ci.yml
├── airflow/
│   └── dags/
│       └── techwatch_pipeline.py   # DAG principal
├── api/
│   ├── main.py                 # Point d'entrée FastAPI
│   ├── routers/                # Endpoints REST
│   ├── schemas/                # Modèles Pydantic
│   ├── services/               # Logique métier
│   └── tests/                  # Tests unitaires et intégration
├── collectors/
│   ├── github_collector.py
│   ├── hackernews_collector.py
│   └── arxiv_collector.py
├── ml/
│   ├── tfidf_model.py
│   ├── word2vec_model.py
│   ├── sentence_transformer_model.py
│   └── evaluation.py           # Precision@K, MAP, MRR, NDCG
├── monitoring/
│   ├── prometheus.yml
│   └── grafana_dashboard.json
├── dashboard/
│   └── kibana_export.ndjson
├── docker/
│   └── docker-compose.yml
├── scripts/
│   ├── init_es_indices.py      # Création des indices ES
│   └── seed_data.py
├── docs/
│   ├── cahier_des_charges.md
│   ├── architecture.md
│   └── ml_comparison.md
├── .env.example
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Métriques ML — Résultats comparatifs

| Modèle | Precision@5 | MAP@10 | MRR | NDCG@10 | Latence |
|---|---|---|---|---|---|
| TF-IDF | 0.41 | 0.38 | 0.45 | 0.43 | 12 ms |
| Word2Vec | 0.57 | 0.52 | 0.61 | 0.58 | 28 ms |
| **MiniLM-L6-v2 ★** | **0.74** | **0.71** | **0.79** | **0.76** | 45 ms |

**Modèle retenu** : Sentence Transformers MiniLM-L6-v2 — meilleur compromis performance/latence pour une API temps réel.

---

## Licences et conformité

- GitHub API : utilisée dans les limites des [conditions d'utilisation GitHub](https://docs.github.com/en/rest/overview/resources-in-the-rest-api)
- HackerNews : scraping du site public, respectueux du `robots.txt` (Disallow vide)
- ArXiv : flux RSS publics sous licence ouverte
