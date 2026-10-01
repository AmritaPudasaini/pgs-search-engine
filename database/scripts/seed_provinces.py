"""Load Nepal's 7 provinces. Safe to run more than once.

Usage:  python scripts/seed_provinces.py
"""

from sqlalchemy.dialects.postgresql import insert

from pgs_db import make_session_factory
from pgs_db.models import Province

PROVINCES = [
    ("P1", "Koshi", "कोशी"),
    ("P2", "Madhesh", "मधेश"),
    ("P3", "Bagmati", "बागमती"),
    ("P4", "Gandaki", "गण्डकी"),
    ("P5", "Lumbini", "लुम्बिनी"),
    ("P6", "Karnali", "कर्णाली"),
    ("P7", "Sudurpashchim", "सुदूरपश्चिम"),
]


def main() -> None:
    Session = make_session_factory()
    with Session.begin() as session:
        stmt = insert(Province).values(
            [{"code": c, "name_en": en, "name_ne": ne} for c, en, ne in PROVINCES]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Province.code],
            set_={"name_en": stmt.excluded.name_en, "name_ne": stmt.excluded.name_ne},
        )
        session.execute(stmt)
    print(f"Seeded {len(PROVINCES)} provinces")


if __name__ == "__main__":
    main()
