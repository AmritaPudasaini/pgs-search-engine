from typing import Any

from opensearchpy import OpenSearch

DEFAULT_DATE_FIELD = "scraped_at"

GEO_FIELD_MAP = {
    "province_code": "geo_location.province_code",
    "district_code": "geo_location.district_code",
    "municipality_id": "geo_location.municipality_id",
    "ward_number": "geo_location.ward_number",
}


class GeoFilteredSearch:
    """Region-bounded document search/browse, newest first.

    Implements Flow B from the architecture spec ("Interactive Map &
    Region-Based Filtering"): given an administrative-boundary filter
    (province/district/municipality), return matching documents with
    the most recently scraped/published ones first.

    Two modes:
      - No `query` passed: pure browse -- e.g. "show me everything
        tagged to Kaski district", sorted strictly by recency.
      - `query` passed: same geo filter, but also matched against text
        (title/description/searchable_text), ranked by relevance with
        recency as a tie-breaker.
    """

    def __init__(self, client: OpenSearch, index: str, date_field: str = DEFAULT_DATE_FIELD):
        self.client = client
        self.index = index
        self.date_field = date_field

    def browse(
        self,
        province_code: str | None = None,
        district_code: str | None = None,
        municipality_id: str | None = None,
        ward_number: str | None = None,
        query: str | None = None,
        k: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return up to `k` documents matching the given geo filters.

        At least one geo filter should normally be passed -- calling
        this with none is equivalent to "browse everything, newest
        first" and is allowed, but is rarely what you want for a
        region-bounded search.
        """
        filter_clauses = self._build_geo_filters(
            province_code=province_code,
            district_code=district_code,
            municipality_id=municipality_id,
            ward_number=ward_number,
        )

        bool_query: dict[str, Any] = {}
        if query:
            bool_query["must"] = {
                "multi_match": {
                    "query": query,
                    "fields": ["title^3", "text", "description"],
                    "type": "best_fields",
                }
            }
        else:
            bool_query["must"] = {"match_all": {}}

        if filter_clauses:
            bool_query["filter"] = filter_clauses

        sort_clauses: list[Any] = []
        if query:
            # Relevance first, recency breaks ties.
            sort_clauses.append({"_score": {"order": "desc"}})
        sort_clauses.append(
            {self.date_field: {"order": "desc", "unmapped_type": "date"}}
        )

        body = {
            "size": k,
            "from": offset,
            "query": {"bool": bool_query},
            "sort": sort_clauses,
        }

        response = self.client.search(index=self.index, body=body)

        return [
            {
                "document_id": hit["_id"],
                "score": hit.get("_score"),
                "source": hit.get("_source", {}),
            }
            for hit in response["hits"]["hits"]
        ]

    @staticmethod
    def _build_geo_filters(
        province_code: str | None,
        district_code: str | None,
        municipality_id: str | None,
        ward_number: str | None,
    ) -> list[dict[str, Any]]:
        values = {
            "province_code": province_code,
            "district_code": district_code,
            "municipality_id": municipality_id,
            "ward_number": ward_number,
        }
        return [
            {"term": {GEO_FIELD_MAP[field]: value}}
            for field, value in values.items()
            if value is not None
        ]
