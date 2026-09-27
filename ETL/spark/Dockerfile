FROM python:3.11-slim-bookworm

# Install Java (required for Spark)
RUN apt-get update && \
    apt-get install -y --no-install-recommends default-jdk-headless && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set JAVA_HOME
ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV PATH="$JAVA_HOME/bin:$PATH"

# Set working directory
WORKDIR /app

# Install PySpark
RUN pip install pyspark==3.5.3

# Copy your ETL code into the container
COPY . .

# Default command (runs your test script)
CMD ["python", "test_spark.py"]