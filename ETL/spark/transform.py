"""Shared Spark transformation logic. Used both standalone (test_spark.py,
run directly in the spark/ Docker image) and from Airflow's
phase1_chain_dag.py -- so both environments run the exact same logic
instead of two independent copies that could drift apart.

Real dedup/geo-tagging/embedding logic replaces analyze_text() here as
the Spark Transformation task is built out -- this is the single plug
point both callers use."""

from pyspark.sql import DataFrame, SparkSession


def analyze_text(spark: SparkSession, text: str) -> DataFrame:
    """Placeholder transformation: character/word counts. Stands in for
    real DOM/PDF parsing, dedup, and geo-tagging (Spark Transformation
    task, not yet implemented)."""
    df = spark.createDataFrame([(text,)], ["raw_text"])
    return df.selectExpr(
        "raw_text",
        "length(raw_text) as char_count",
        "size(split(raw_text, ' ')) as word_count",
    )