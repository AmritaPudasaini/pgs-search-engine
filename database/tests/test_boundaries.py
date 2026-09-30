"""Region boundaries (PostGIS): the seeded shapes, point lookup and the map's GeoJSON.

Needs `scripts/seed_boundaries.py` to have run against the test database.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pgs_db import ReferenceRepository
from pgs_db.models import District, LocalBody, Province
from pgs_db.repositories.reference import BOUNDARY_ATTRIBUTION

# Pokhara (MUN414, Kaski D38, Gandaki P4): a point by Phewa Lake.
PHEWA = (28.2096, 83.9587)
# Kathmandu Durbar Square: Kathmandu Metropolitan City, Kathmandu district, Bagmati.
DURBAR_SQUARE = (27.7043, 85.3071)


@pytest.fixture()
def ref(session: Session) -> ReferenceRepository:
    loaded = session.scalar(select(func.count()).where(LocalBody.boundary.is_not(None)))
    if not loaded:
        pytest.skip("boundaries not seeded: run scripts/seed_boundaries.py")
    return ReferenceRepository(session)


class TestSeededShapes:
    def test_every_region_has_a_valid_shape(self, ref: ReferenceRepository) -> None:
        for model in (Province, District, LocalBody):
            missing, invalid = ref.session.execute(
                select(
                    func.count().filter(model.boundary.is_(None)),
                    func.count().filter(~func.ST_IsValid(model.boundary)),
                )
            ).one()
            assert (missing, invalid) == (0, 0), model.__tablename__

    def test_every_local_body_lies_in_its_own_district(self, ref: ReferenceRepository) -> None:
        # The name mapping in build_boundaries.py, checked by geometry instead of spelling.
        misplaced = ref.session.scalar(
            select(func.count())
            .select_from(LocalBody)
            .join(District, District.code == LocalBody.district_code)
            .where(~func.ST_Within(func.ST_PointOnSurface(LocalBody.boundary), District.boundary))
        )
        assert misplaced == 0

    def test_ward_counts_are_loaded(self, ref: ReferenceRepository) -> None:
        pokhara = ref.session.scalar(select(LocalBody).where(LocalBody.code == "MUN414"))
        assert pokhara is not None and pokhara.ward_count == 33


class TestLocate:
    def test_a_point_resolves_to_all_three_levels(self, ref: ReferenceRepository) -> None:
        assert ref.locate(*PHEWA) == {
            "province_code": "P4",
            "district_code": "D38",
            "municipality_id": "MUN414",
        }
        durbar = ref.locate(*DURBAR_SQUARE)
        assert durbar is not None and durbar["province_code"] == "P3"

    def test_outside_nepal_and_bad_input(self, ref: ReferenceRepository) -> None:
        assert ref.locate(51.5, -0.12) is None  # London
        with pytest.raises(ValueError):
            ref.locate(95.0, 10.0)


class TestMapGeoJSON:
    def test_levels_and_parent_filter(self, ref: ReferenceRepository) -> None:
        provinces = ref.boundaries_geojson("province")
        assert [f["properties"]["code"] for f in provinces["features"]] == [
            f"P{i}" for i in range(1, 8)
        ]
        assert provinces["attribution"] == BOUNDARY_ATTRIBUTION
        assert len(ref.boundaries_geojson("district")["features"]) == 77

        kaski = ref.boundaries_geojson("local_body", within="D38")
        codes = {f["properties"]["code"] for f in kaski["features"]}
        assert "MUN414" in codes and all(
            f["properties"]["district_code"] == "D38" for f in kaski["features"]
        )
        feature = kaski["features"][0]
        assert feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
        assert {"code", "name_en", "name_ne", "type"} <= set(feature["properties"])

    def test_simplification_shrinks_the_payload(self, ref: ReferenceRepository) -> None:
        def points(tolerance: float) -> int:
            shape = ref.boundaries_geojson("district", within="P4", tolerance=tolerance)
            return len(str(shape["features"]))

        assert points(0.01) < points(0.0001)

    def test_bad_arguments(self, ref: ReferenceRepository) -> None:
        with pytest.raises(ValueError):
            ref.boundaries_geojson("ward")
        with pytest.raises(ValueError):
            ref.boundaries_geojson("province", within="P1")

    def test_other_queries_do_not_load_polygons(self, ref: ReferenceRepository) -> None:
        pokhara = ref.session.scalar(select(LocalBody).where(LocalBody.code == "MUN414"))
        assert pokhara is not None
        assert "boundary" not in pokhara.__dict__  # deferred until asked for
