# syntax=docker/dockerfile:1
#
# ETL image: Airflow (orchestration) + PySpark (transform.py, security_scanner.py)
# + the Kafka consumer (kafka/consumer.py).
# Build context: the repository root (needs ETL/ and the shared database/ package).
#
# One image runs every ETL role in the root docker-compose.yml: airflow-init,
# airflow-webserver, airflow-scheduler, airflow-worker, etl-consumer and the standalone
# Spark check (etl-spark-test). It replaces ETL/airflow/Dockerfile and
# ETL/spark/Dockerfile: the Airflow image already had everything the Spark image had
# (Python 3.11, a JDK, PySpark 3.5.3), so test_spark.py runs here unchanged.

FROM apache/airflow:2.10.4-python3.11

USER 0
# PySpark needs a JVM.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jdk-headless \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# The shared pgs-db package needs SQLAlchemy 2.x, while Airflow 2.10 requires
# SQLAlchemy < 2.0, so the two cannot share one environment. pgs-db (plus the Kafka
# client) gets its own virtualenv: ETL code that writes to PostgreSQL through pgs_db
# runs with /opt/etl-venv/bin/python -- the Kafka consumer does, and an Airflow task
# can via @task.external_python(python="/opt/etl-venv/bin/python").
COPY database/constraints.txt database/pyproject.toml database/README.md /tmp/pgs-db/
COPY database/src /tmp/pgs-db/src
COPY --chown=airflow:0 ETL/kafka/requirements.txt /tmp/etl-kafka-requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/etl-venv \
    && /opt/etl-venv/bin/pip install --disable-pip-version-check \
        --requirement /tmp/etl-kafka-requirements.txt \
        --constraint /tmp/pgs-db/constraints.txt \
        "/tmp/pgs-db[postgres]" \
    && rm -rf /tmp/pgs-db

# The Kafka consumer keeps its SQLite receipts here (ETL_DATABASE=/data/etl.sqlite3).
# Group 0 may write, like the rest of the Airflow image, so any AIRFLOW_UID works.
RUN mkdir -p /data && chown airflow:0 /data && chmod 2775 /data

USER 50000
# Airflow's own environment, used by the DAG tasks: PySpark and the Kafka client.
# apache-airflow is named in the same command so pip can never up- or downgrade it.
RUN pip install --no-cache-dir \
        "apache-airflow==${AIRFLOW_VERSION}" \
        pyspark==3.5.3 \
        --requirement /tmp/etl-kafka-requirements.txt \
    && rm /tmp/etl-kafka-requirements.txt

# ETL code, at the paths the DAGs use (phase1_chain_dag.py: /opt/airflow/spark_lib,
# /opt/airflow/data). docker-compose.yml bind-mounts the same directories over these
# for live editing; the copies make the image runnable on its own.
COPY ETL/airflow/dags /opt/airflow/dags
COPY ETL/airflow/plugins /opt/airflow/plugins
COPY ETL/airflow/config /opt/airflow/config
COPY ETL/airflow/data /opt/airflow/data
COPY ETL/spark /opt/airflow/spark_lib
COPY ETL/kafka /opt/etl/kafka
