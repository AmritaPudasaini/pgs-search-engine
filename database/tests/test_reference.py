import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pgs_db.enums import LocalBodyType
from pgs_db.models import District, Domain, LocalBody, Province


def test_geography_chain(session: Session) -> None:
    # Reuse P4 if the seed script already loaded it.
    p = session.scalars(select(Province).where(Province.code == "P4")).one_or_none()
    if p is None:
        p = Province(code="P4", name_en="Gandaki", name_ne="गण्डकी")

    d = District(code="D39", name_en="Kaski", name_ne="कास्की", province=p)
    lb = LocalBody(
        code="MUN75340",
        name_en="Pokhara",
        name_ne="पोखरा",
        type=LocalBodyType.METROPOLITAN_CITY,
        district=d,
    )
    session.add(lb)
    session.flush()
    assert lb.district.province.name_en == "Gandaki"

    site = Domain(domain="pokharamun.gov.np", local_body_id=lb.id)
    session.add(site)
    session.flush()
    assert site.status.value == "PENDING"


def test_district_needs_existing_province(session: Session) -> None:
    session.add(District(code="D99", name_en="X", name_ne="X", province_code="P9"))
    with pytest.raises(IntegrityError):
        session.flush()