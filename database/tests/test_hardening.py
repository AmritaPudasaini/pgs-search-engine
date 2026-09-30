"""Production guards: roles and grants, updated_at triggers, indexed FKs, health, jobs, passwords.

Role tests run the real repository calls under `SET LOCAL ROLE`, so a missing grant
fails here, not in production. The test database user must be allowed to SET ROLE
to the service roles (the dev superuser is).
"""

import argparse
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from pgs_db import (
    BronzeRepository,
    OpsRepository,
    ReferenceRepository,
    SearchLogRepository,
    SearchRepository,
    SilverRepository,
    StatsRepository,
    grants,
    health,
    jobs,
)
from pgs_db.enums import AdminRole, DomainStatus, LogSeverity, ServiceName
from pgs_db.models import AdminUser, CrawledDocument
from pgs_db.security import hash_password, needs_rehash, verify_password

HOST = "roles-test.gov.np"
_ANCIENT = datetime(1975, 1, 1, tzinfo=UTC)
DATABASE_DIR = Path(__file__).resolve().parent.parent


def bronze_doc(n: int) -> dict[str, Any]:
    url = f"https://{HOST}/{n}"
    return {
        "url": url,
        "normalized_url": url,
        "host": HOST,
        "content_hash": f"{n:064x}",
        "fetched_at": (_ANCIENT + timedelta(days=n)).isoformat(),
    }


@contextmanager
def as_role(session: Session, role: str) -> Iterator[None]:
    """Run the block as `role`, in a savepoint so the role (and any error) is undone."""
    savepoint = session.begin_nested()
    session.execute(text(f"SET LOCAL ROLE {role}"))
    try:
        yield
    finally:
        if savepoint.is_active:
            savepoint.rollback()


def refused(session: Session, role: str, action: Callable[[], object]) -> None:
    """`action` must fail as `role` with a permission error."""
    with as_role(session, role), pytest.raises(ProgrammingError, match="permission denied"):
        action()
        session.flush()


# ------------------------------------------------------------------- catalogue


class TestCatalogue:
    def test_every_table_and_view_is_in_the_grant_matrix(self, session: Session) -> None:
        objects = set(
            session.scalars(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' "
                    "AND table_name NOT IN ('alembic_version', 'spatial_ref_sys', "
                    "'geography_columns', 'geometry_columns')"
                )
            )
        )
        assert objects == set(grants.ALL_OBJECTS)

    def test_every_table_with_updated_at_has_the_trigger(self, session: Session) -> None:
        missing = session.scalars(
            text(
                """
                SELECT c.table_name FROM information_schema.columns c
                JOIN information_schema.tables t
                  ON t.table_name = c.table_name AND t.table_schema = c.table_schema
                WHERE c.table_schema = 'public' AND c.column_name = 'updated_at'
                  AND t.table_type = 'BASE TABLE'
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_trigger g
                      WHERE g.tgrelid = ('public.' || c.table_name)::regclass
                        AND g.tgname = 'trg_' || c.table_name || '_updated_at')
                """
            )
        ).all()
        assert missing == []

    def test_every_foreign_key_is_indexed(self, session: Session) -> None:
        unindexed = session.scalars(
            text(
                """
                SELECT c.conname FROM pg_constraint c
                WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_index i
                      WHERE i.indrelid = c.conrelid
                        AND (i.indkey::int2[])[0:cardinality(c.conkey) - 1] @> c.conkey
                        AND (i.indkey::int2[])[0:cardinality(c.conkey) - 1] <@ c.conkey)
                """
            )
        ).all()
        assert unindexed == []

    def test_expected_revision_is_the_alembic_head(self) -> None:
        config = Config(str(DATABASE_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(DATABASE_DIR / "migrations"))
        assert ScriptDirectory.from_config(config).get_current_head() == health.EXPECTED_REVISION


# -------------------------------------------------------------------- triggers


class TestUpdatedAtTrigger:
    def test_plain_sql_updates_bump_updated_at(self, session: Session) -> None:
        doc_id = BronzeRepository(session).save_document(bronze_doc(1)).id
        session.execute(
            text("UPDATE crawled_documents SET updated_at = :t WHERE id = :id"),
            {"t": _ANCIENT, "id": doc_id},
        )
        # An update that does not touch updated_at (the Go scraper's style) bumps it...
        session.execute(
            text("UPDATE crawled_documents SET title = 'x' WHERE id = :id"), {"id": doc_id}
        )
        bumped = session.scalar(
            text("SELECT updated_at FROM crawled_documents WHERE id = :id"), {"id": doc_id}
        )
        assert bumped > _ANCIENT
        # ...while an explicit new value (the claim queues' timestamps) is kept.
        session.execute(
            text("UPDATE crawled_documents SET updated_at = :t WHERE id = :id"),
            {"t": _ANCIENT, "id": doc_id},
        )
        kept = session.scalar(
            text("SELECT updated_at FROM crawled_documents WHERE id = :id"), {"id": doc_id}
        )
        assert kept == _ANCIENT


# ----------------------------------------------------------------------- roles


class TestRoles:
    def test_scraper_writes_bronze_only(self, session: Session) -> None:
        with as_role(session, "pgs_scraper"):
            bronze = BronzeRepository(session)
            bronze.save_document(bronze_doc(10), register_unknown_domains=True)
            bronze.ensure_domain("another.gov.np")
            OpsRepository(session).log_error(ServiceName.SCRAPER, LogSeverity.ERROR, "503")
            session.flush()
        doc_id = BronzeRepository(session).save_document(bronze_doc(11)).id
        refused(session, "pgs_scraper", lambda: SilverRepository(session).save_page(
            {"searchable_text": "x", "content_hash": "a" * 64}, crawled_document_id=doc_id))
        refused(session, "pgs_scraper", lambda: session.execute(select(AdminUser)).all())

    def test_etl_builds_silver_but_not_gold_or_admin(self, session: Session) -> None:
        doc_id = BronzeRepository(session).save_document(bronze_doc(20)).id
        session.flush()
        with as_role(session, "pgs_etl"):
            silver = SilverRepository(session)
            silver.claim_bronze(limit=1000)
            silver.save_page(
                {"searchable_text": "x", "content_hash": "b" * 64}, crawled_document_id=doc_id
            )
            silver.mark_bronze_processed([doc_id])
            session.flush()
        refused(session, "pgs_etl", lambda: StatsRepository(session).refresh_domain_stats())
        refused(session, "pgs_etl", lambda: session.add(
            AdminUser(username="etl", password_hash="h", role=AdminRole.AUDITOR)))

    def test_search_indexes_but_cannot_touch_bronze(self, session: Session) -> None:
        doc_id = BronzeRepository(session).save_document(bronze_doc(30)).id
        page_id = SilverRepository(session).save_page(
            {"searchable_text": "x", "content_hash": "c" * 64}, crawled_document_id=doc_id
        ).id
        session.flush()
        with as_role(session, "pgs_search"):
            SearchRepository(session).claim_for_indexing(limit=1000)
            SilverRepository(session).mark_processed(page_id)
            SearchRepository(session).documents([page_id])
            session.flush()
        refused(session, "pgs_search", lambda: session.execute(
            text("UPDATE crawled_documents SET title = 'x' WHERE id = :id"), {"id": doc_id}))

    def test_api_admin_and_search_log(self, session: Session) -> None:
        domain_id = BronzeRepository(session).ensure_domain("api-role.gov.np")
        doc_id = BronzeRepository(session).save_document(bronze_doc(40)).id
        page_id = SilverRepository(session).save_page(
            {"searchable_text": "x", "content_hash": "d" * 64}, crawled_document_id=doc_id
        ).id
        session.flush()
        with as_role(session, "pgs_api"):
            ops = OpsRepository(session)
            ops.create_admin("role_admin", password_hash="h", role=AdminRole.SUPER_ADMIN)
            assert ops.get_admin("role_admin") is not None
            log = SearchLogRepository(session)
            query = log.log_query("q", result_count=1)
            log.log_click(query.id, url="https://x", rank_position=1)
            log.judge("q", page_id, 2, judged_by="role_admin")
            ReferenceRepository(session).add_region_link(
                "D38", title_en="x", url="https://x.gov.np"
            )
            StatsRepository(session).set_domain_status(domain_id, DomainStatus.PAUSED)
            StatsRepository(session).dashboard_summary()
            session.flush()
        refused(session, "pgs_api", lambda: session.execute(
            text("DELETE FROM pages WHERE id = :id"), {"id": page_id}))

    def test_jobs_run_every_job(self, session: Session) -> None:
        args = argparse.Namespace(stale_minutes=30, error_days=90, search_days=365)
        with as_role(session, "pgs_jobs"):
            for name in jobs.JOBS:
                report = jobs.run_job(session, name, args)
                assert report["status"] == "ok", report
        refused(session, "pgs_jobs", lambda: session.execute(select(AdminUser)).all())

    def test_readonly_reads_everything_but_secrets(self, session: Session) -> None:
        with as_role(session, "pgs_readonly"):
            session.execute(text("SELECT count(*) FROM search_documents")).one()
            session.execute(select(CrawledDocument).limit(1)).all()
        refused(session, "pgs_readonly", lambda: session.execute(select(AdminUser)).all())
        refused(session, "pgs_readonly", lambda: OpsRepository(session).log_error(
            ServiceName.API, LogSeverity.WARN, "nope"))


# ---------------------------------------------------------------- health & jobs


class TestHealth:
    def test_a_migrated_seeded_database_is_not_failing(self, session: Session) -> None:
        report = health.check(session)
        assert report["status"] in {"ok", "degraded"}, report["problems"]
        assert report["revision"] == health.EXPECTED_REVISION
        assert report["reference_counts"] == health.EXPECTED_COUNTS

    def test_stale_gold_is_reported(self, session: Session) -> None:
        StatsRepository(session).refresh_geo_content_stats(when=_ANCIENT)
        session.execute(text("UPDATE domain_stats SET computed_at = :t"), {"t": _ANCIENT})
        session.execute(text("UPDATE page_scores SET computed_at = :t"), {"t": _ANCIENT})
        report = health.check(session)
        assert report["status"] == "degraded"
        assert any("geo_content_stats last computed" in p for p in report["problems"])


class TestJobsCli:
    def test_a_second_concurrent_run_is_skipped(self, session: Session) -> None:
        args = jobs.parse_args(["stats"])
        first = jobs.run_job(session, "stats", args)
        assert first["status"] == "ok"
        # Another connection holding the same lock makes this run skip.
        other = session.get_bind().engine.connect()  # type: ignore[union-attr]
        try:
            other.begin()
            import zlib

            other.execute(
                text("SELECT pg_advisory_xact_lock(:k)"),
                {"k": zlib.crc32(b"pgs_db.jobs.scores")},
            )
            skipped = jobs.run_job(session, "scores", args)
            assert skipped["status"] == "skipped"
        finally:
            other.rollback()
            other.close()

    def test_main_reports_json_per_job(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(session: Session, args: argparse.Namespace) -> dict[str, Any]:
            raise RuntimeError("kaput")

        monkeypatch.setattr(jobs, "JOBS", {"stats": jobs.JOBS["stats"], "purge": boom})
        exit_code = jobs.main(["all"])
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert [(r["job"], r["status"]) for r in lines] == [("stats", "ok"), ("purge", "failed")]
        assert "kaput" in lines[1]["error"] and exit_code == 1


# ------------------------------------------------------------------- passwords


class TestPasswords:
    def test_hash_verify_and_rehash(self) -> None:
        hashed = hash_password("correct horse battery")
        assert hashed.startswith("$argon2id$")
        assert verify_password(hashed, "correct horse battery")
        assert not verify_password(hashed, "wrong horse battery")
        assert not verify_password("not-a-hash", "whatever")
        assert not needs_rehash(hashed)
        with pytest.raises(ValueError, match="at least"):
            hash_password("short")

    def test_a_stored_hash_logs_in(self, session: Session) -> None:
        ops = OpsRepository(session)
        ops.create_admin(
            "hashy", password_hash=hash_password("a long enough pass"), role=AdminRole.AUDITOR
        )
        user = ops.get_admin("hashy")
        assert user is not None and verify_password(user.password_hash, "a long enough pass")
