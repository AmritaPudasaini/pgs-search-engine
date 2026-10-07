from transform import analyze_text


def main():
    try:
        from pyspark.sql import SparkSession
    except ImportError:
        print("PySpark is not installed locally. Run this through the Spark Docker image.")
        return

    spark = (
        SparkSession.builder
        .appName("SparkTransformSmoke")
        .master("local[*]")
        .getOrCreate()
    )

    sample_text = "Kathmandu Metropolitan City notice used to test Spark ETL."
    result = analyze_text(spark, sample_text)
    result.show(truncate=80)

    spark.stop()


if __name__ == "__main__":
    main()
