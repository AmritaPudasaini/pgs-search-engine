from pyspark.sql import SparkSession

from transform import analyze_text

spark = (
    SparkSession.builder
    .appName("TestSetup")
    .master("local[*]")
    .getOrCreate()
)

sample_text = "This is a dummy notice used to test text extraction in Airflow."
result = analyze_text(spark, sample_text)
result.show(truncate=80)

spark.stop()