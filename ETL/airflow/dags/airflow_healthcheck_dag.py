from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="airflow_healthcheck",
    description="Verifies Airflow scheduling and worker execution",
    start_date=datetime(2025, 1, 1),
    schedule=None,
    catchup=False,
    tags=["etl", "healthcheck"],
) as dag:

    say_hello = BashOperator(
        task_id="say_hello",
        bash_command="echo 'Hello from Airflow - setup is working.'",
    )
    say_goodbye = BashOperator(
        task_id="say_goodbye",
        bash_command="echo 'Task 2 complete - Airflow healthcheck finished successfully.'",
    )
    say_hello >> say_goodbye
