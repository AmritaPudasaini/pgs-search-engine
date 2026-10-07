import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pgs_db.enums import LocalBodyType
from pgs_db.models import District, Domain, LocalBody, Province

# Codes deliberately outside every seeded range (P1-P7, D01-D77, MUN001-MUN753) so the
# schema tests stay hermetic whether or not scripts/seed_geography.py has been run.
TEST_PROVINCE = "PT"
TEST_DISTRICT = "DT"
TEST_LOCAL_BODY = "LBT"


def test_geography_chain(session: Session) -> None:
    p = Province(code=TEST_PROVINCE, name_en="Testland", name_ne="परीक्षण")
    d = District(code=TEST_DISTRICT, name_en="Testville", name_ne="परीक्षणपुर", province=p)
    lb = LocalBody(
        code=TEST_LOCAL_BODY,
        name_en="Testpur",
        name_ne="परीक्षणपुरी",
        type=LocalBodyType.METROPOLITAN_CITY,
        district=d,
    )
    session.add(lb)
    session.flush()
    assert lb.district.province.name_en == "Testland"

    site = Domain(domain="testpurmun.gov.np", local_body_id=lb.id)
    session.add(site)
    session.flush()
    assert site.status.value == "PENDING"


def test_district_needs_existing_province(session: Session) -> None:
    session.add(District(code="D99", name_en="X", name_ne="X", province_code="P9"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_local_body_code_is_unique(session: Session) -> None:
    p = Province(code=TEST_PROVINCE, name_en="Testland", name_ne="परीक्षण")
    d = District(code=TEST_DISTRICT, name_en="Testville", name_ne="परीक्षणपुर", province=p)
    for _ in range(2):
        session.add(
            LocalBody(
                code=TEST_LOCAL_BODY,
                name_en="Testpur",
                name_ne="परीक्षणपुरी",
                type=LocalBodyType.MUNICIPALITY,
                district=d,
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()


class TestSeededGazetteer:
    """Guards the reference data loaded by scripts/seed_geography.py.

    Skipped when the seed has not been run, so a bare `alembic upgrade head`
    database still passes the rest of the suite.
    """

    @pytest.fixture(autouse=True)
    def _require_seed(self, session: Session) -> None:
        if not session.scalar(select(func.count()).select_from(District)):
            pytest.skip("geography not seeded; run scripts/seed_geography.py")

    def test_official_counts(self, session: Session) -> None:
        assert session.scalar(select(func.count()).select_from(Province)) == 7
        assert session.scalar(select(func.count()).select_from(District)) == 77
        assert session.scalar(select(func.count()).select_from(LocalBody)) == 753

    def test_local_body_type_breakdown(self, session: Session) -> None:
        rows = session.execute(
            select(LocalBody.type, func.count()).group_by(LocalBody.type)
        ).all()
        got = {row[0]: row[1] for row in rows}
        assert got == {
            LocalBodyType.METROPOLITAN_CITY: 6,
            LocalBodyType.SUB_METROPOLITAN_CITY: 11,
            LocalBodyType.MUNICIPALITY: 276,
            LocalBodyType.RURAL_MUNICIPALITY: 460,
        }

    def test_pokhara_resolves_to_gandaki(self, session: Session) -> None:
        lb = session.scalars(select(LocalBody).where(LocalBody.name_en == "Pokhara")).one()
        assert lb.type == LocalBodyType.METROPOLITAN_CITY
        assert lb.district.name_en == "Kaski"
        assert lb.district.province.name_en == "Gandaki"
        assert lb.name_ne == "पोखरा"

    def test_every_local_body_has_a_nepali_name(self, session: Session) -> None:
        missing = session.scalars(
            select(LocalBody.code).where((LocalBody.name_ne == "") | (LocalBody.name_ne.is_(None)))
        ).all()
        assert not missing
