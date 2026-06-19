"""
DAG PartIntel — Pipeline complet de veille aftermarket automobile.

Flux :
  collect_kaggle ─┐
  collect_rss    ─┤─▶ transform ─▶ run_ml ─▶ notify
  collect_sdes   ─┘
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator

DEFAULT_ARGS = {
    "owner": "partintel",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}

def task_collect_kaggle(**context):
    import sys
    sys.path.insert(0, "/opt/airflow")
    from collectors.kaggle_collector import run_collection
    report = run_collection()
    context["ti"].xcom_push(key="kaggle_report", value=report)
    return report

def task_collect_rss(**context):
    import sys
    sys.path.insert(0, "/opt/airflow")
    from collectors.rss_collector import run_collection
    report = run_collection()
    context["ti"].xcom_push(key="rss_report", value=report)
    return report

def task_collect_sdes(**context):
    import sys
    sys.path.insert(0, "/opt/airflow")
    from collectors.opendata_collector import run_collection
    report = run_collection()
    context["ti"].xcom_push(key="sdes_report", value=report)
    return report

def task_transform(**context):
    import sys
    sys.path.insert(0, "/opt/airflow")
    from scripts.transform_pipeline import run_transformation
    result = run_transformation()
    context["ti"].xcom_push(key="transform_result", value=result)
    return result

def task_run_ml(**context):
    """
    En production : relance l'embedding ML sur les nouveaux documents.
    En demo : on log simplement les metriques existantes.
    """
    ti = context["ti"]
    kaggle = ti.xcom_pull(task_ids="collect.collect_kaggle", key="kaggle_report") or {}
    rss = ti.xcom_pull(task_ids="collect.collect_rss", key="rss_report") or {}
    sdes = ti.xcom_pull(task_ids="collect.collect_sdes", key="sdes_report") or {}
    transform = ti.xcom_pull(task_ids="transform", key="transform_result") or {}

    summary = {
        "kaggle_indexed": kaggle.get("total_indexed", 0),
        "rss_indexed": rss.get("total_indexed", 0),
        "sdes_indexed": sdes.get("total_indexed", 0),
        "clean_items": transform.get("total_clean", 0),
    }
    print(f"\n{'='*50}")
    print("PartIntel Pipeline — Résumé")
    for k, v in summary.items():
        print(f"  {k:<20} : {v}")
    print(f"{'='*50}\n")
    return summary

def task_notify(**context):
    ti = context["ti"]
    summary = ti.xcom_pull(task_ids="run_ml") or {}
    print(f"Pipeline terminé avec succès : {summary}")

with DAG(
    dag_id="partintel_pipeline",
    description="Pipeline ELT complet PartIntel — collecte, transformation, ML",
    schedule_interval="0 */6 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["partintel", "pipeline"],
) as dag:

    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")

    from airflow.utils.task_group import TaskGroup

    with TaskGroup("collect", tooltip="Collecte parallèle des 3 sources") as collect_group:
        collect_kaggle = PythonOperator(
            task_id="collect_kaggle",
            python_callable=task_collect_kaggle,
        )
        collect_rss = PythonOperator(
            task_id="collect_rss",
            python_callable=task_collect_rss,
        )
        collect_sdes = PythonOperator(
            task_id="collect_sdes",
            python_callable=task_collect_sdes,
        )

    transform = PythonOperator(
        task_id="transform",
        python_callable=task_transform,
    )

    run_ml = PythonOperator(
        task_id="run_ml",
        python_callable=task_run_ml,
    )

    notify = PythonOperator(
        task_id="notify",
        python_callable=task_notify,
    )

    start >> collect_group >> transform >> run_ml >> notify >> end
