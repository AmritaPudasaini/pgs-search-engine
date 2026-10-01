from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="dummy_test_dag",
    description="Phase 1 dummy DAG - verifies Airflow Docker setup works",
    start_date=datetime(2025, 1, 1),
    schedule=None,
    catchup=False,
    tags=["phase1", "dummy", "etl-setup"],
) as dag:

    say_hello = BashOperator(
        task_id="say_hello",
        bash_command="echo 'Hello from Airflow - setup is working.'",
    )
    say_goodbye = BashOperator(
        task_id="say_goodbye",
        bash_command="echo 'Task 2 complete - dummy DAG finished successfully.'",
    )
    say_hello >> say_goodbye