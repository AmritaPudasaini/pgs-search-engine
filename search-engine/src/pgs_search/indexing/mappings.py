INDEX_MAPPING: dict = {
    "settings": {
        "analysis": {
            "analyzer": {
                "pgs_text_analyzer": {
                    "type": "standard",
                    "stopwords": "_none_",
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "document_id": {
                "type": "keyword",
            },
            "title": {
                "type": "text",
                "analyzer": "pgs_text_analyzer",
            },
            "description": {
                "type": "text",
                "analyzer": "pgs_text_analyzer",
            },
            "searchable_text": {
                "type": "text",
                "analyzer": "pgs_text_analyzer",
            },
            "source_url": {
                "type": "keyword",
                "index": False,
            },
            "domain": {
                "type": "keyword",
            },
            "language": {
                "type": "keyword",
            },
            "content_type": {
                "type": "keyword",
            },
            "published_at": {
                "type": "date",
            },
            "keywords": {
                "type": "keyword",
            },
            "geo": {
                "properties": {
                    "province_code": {
                        "type": "keyword",
                    },
                    "province_name_en": {
                        "type": "text",
                    },
                    "province_name_ne": {
                        "type": "text",
                    },
                    "district_code": {
                        "type": "keyword",
                    },
                    "district_name_en": {
                        "type": "text",
                    },
                    "district_name_ne": {
                        "type": "text",
                    },
                    "municipality_id": {
                        "type": "keyword",
                    },
                    "municipality_name_en": {
                        "type": "text",
                    },
                    "municipality_name_ne": {
                        "type": "text",
                    },
                    "ward_number": {
                        "type": "integer",
                    },
                }
            },
        }
    },
}