# syntax=docker/dockerfile:1
#
# ETL image: Airflow (orchestration) + the transform/scan/embedding code in spark/
# + the Kafka consumer (kafka/) + the OpenSearch indexer (OpenSearch/).
# Build context: the repository root (needs ETL/ and the shared database/ package).
#
# One image runs every ETL role in the root docker-compose.yml: airflow-init,
# airflow-webserver, airflow-scheduler, airflow-worker, etl-consumer, and the tools
# etl-spark-test, ingestion-signal-publisher and opensearch-indexer. It replaces the
# former ETL/airflow/Dockerfile, ETL/spark/Dockerfile and ETL/OpenSearch/Dockerfile:
# the Airflow image already had what the Spark image had (Python 3.11, a JDK, PySpark),
# so their packages are merged into one environment here.

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
# SQLAlchemy < 2.0, so the two cannot share one environment. pgs-db gets its own
# virtualenv, with the Kafka client and the OpenSearch client: the Kafka consumer and
# the OpenSearch indexer run with /opt/etl-venv/bin/python, and an Airflow task can
# via @task.external_python(python="/opt/etl-venv/bin/python").
COPY database/constraints.txt database/pyproject.toml database/README.md /tmp/pgs-db/
COPY database/src /tmp/pgs-db/src
COPY ETL/OpenSearch/requirements.txt /tmp/etl-opensearch-requirements.txt
COPY --chown=airflow:0 ETL/kafka/requirements.txt /tmp/etl-kafka-requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/etl-venv \
    && /opt/etl-venv/bin/pip install --disable-pip-version-check \
        --requirement /tmp/etl-kafka-requirements.txt \
        --requirement /tmp/etl-opensearch-requirements.txt \
        --constraint /tmp/pgs-db/constraints.txt \
        "/tmp/pgs-db[postgres]" \
    && rm -rf /tmp/pgs-db /tmp/etl-opensearch-requirements.txt

# Writable state, group 0 like the rest of the Airflow image so any AIRFLOW_UID works:
# the Kafka consumer's SQLite receipts (ETL_DATABASE=/data/etl.sqlite3) and the
# Hugging Face cache for the LaBSE embedding model (HF_HOME, a volume in compose).
ENV HF_HOME=/home/airflow/.cache/huggingface
RUN mkdir -p /data "${HF_HOME}" \
    && chown airflow:0 /data "${HF_HOME}" \
    && chmod 2775 /data "${HF_HOME}"

USER 50000
# Airflow's own environment, where the DAG tasks run: PySpark, the Kafka client, and
# what spark/transform.py and spark/security_scanner.py import (pypdf for PDFs,
# sentence-transformers for LaBSE embeddings, clamd for ClamAV). PyTorch is the
# CPU-only build: nothing runs on a GPU, and the default wheel adds several GB of CUDA.
# apache-airflow is named in the same command so pip can never up- or downgrade it.
ARG TORCH_VERSION=2.14.1
RUN pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        "apache-airflow==${AIRFLOW_VERSION}" \
        "torch==${TORCH_VERSION}+cpu" \
        pyspark==3.5.3 \
        pypdf==5.1.0 \
        sentence-transformers==3.3.1 \
        clamd==1.0.2 \
        --requirement /tmp/etl-kafka-requirements.txt \
    && rm /tmp/etl-kafka-requirements.txt

# ETL code, at the paths the DAGs use (/opt/airflow/spark_lib, /opt/airflow/data).
# docker-compose.yml bind-mounts the same directories over these for live editing; the
# copies make the image runnable on its own.
COPY ETL/airflow/dags /opt/airflow/dags
COPY ETL/airflow/plugins /opt/airflow/plugins
COPY ETL/airflow/config /opt/airflow/config
COPY ETL/airflow/data /opt/airflow/data
COPY ETL/spark /opt/airflow/spark_lib
COPY ETL/kafka /opt/etl/kafka
COPY ETL/OpenSearch /opt/etl/OpenSearch
