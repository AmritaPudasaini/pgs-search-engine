"""Document extraction validation DAG.

Reads local HTML/TXT fixtures, strips markup, and reports word counts so the
Airflow worker path can be checked independently of Kafka.
"""

from datetime import datetime
from html.parser import HTMLParser

from airflow import DAG
from airflow.operators.python import PythonOperator


class TextExtractor(HTMLParser):
    """Minimal HTML tag stripper using only Python's built-in library."""

    def __init__(self):
        super().__init__()
        self.text_parts = []

    def handle_data(self, data):
        self.text_parts.append(data)

    def get_text(self):
        return " ".join(part.strip() for part in self.text_parts if part.strip())


def parse_html_file():
    with open("/opt/airflow/data/sample.html", "r", encoding="utf-8") as f:
        raw_html = f.read()

    extractor = TextExtractor()
    extractor.feed(raw_html)
    clean_text = extractor.get_text()

    print("Extracted text from sample.html:")
    print(clean_text)
    print(f"Word count: {len(clean_text.split())}")


def parse_txt_file():
    with open("/opt/airflow/data/sample.txt", "r", encoding="utf-8") as f:
        raw_text = f.read()

    print("Contents of sample.txt:")
    print(raw_text)
    print(f"Word count: {len(raw_text.split())}")


with DAG(
    dag_id="document_extraction_check",
    description="Validates local HTML/TXT extraction through Airflow workers",
    start_date=datetime(2025, 1, 1),
    schedule=None,
    catchup=False,
    tags=["etl", "validation", "extraction", "celery"],
) as dag:

    extract_html = PythonOperator(
        task_id="extract_html",
        python_callable=parse_html_file,
    )

    extract_txt = PythonOperator(
        task_id="extract_txt",
        python_callable=parse_txt_file,
    )

    extract_html >> extract_txt
