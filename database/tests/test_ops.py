"""admin_users and error_logs: the API's login store and the shared error log."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pgs_db import BronzeRepository, OpsRepository
from pgs_db.enums import AdminRole, LogSeverity, ServiceName
from pgs_db.models import AdminUser, CrawledDocument, ErrorLog
from pgs_db.schemas import AdminUserCreate, AdminUserRead, ErrorLogRead

HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"
HOST = "failedsite.com.np"
_ANCIENT = datetime(1975, 1, 1, tzinfo=UTC)


@pytest.fixture()
def ops(session: Session) -> OpsRepository:
    return OpsRepository(session)


def admin(ops: OpsRepository, name: str, role: AdminRole = AdminRole.SUPER_ADMIN) -> AdminUser:
    return ops.create_admin(name, password_hash=HASH, role=role)


class TestAdminUsers:
    def test_usernames_are_stored_lowercase_and_found_case_insensitively(
        self, ops: OpsRepository
    ) -> None:
        user = ops.create_admin(
            "  Admin_Operator ", password_hash=HASH, role=AdminRole.SYSTEM_OPERATOR,
            email="Ops@PGS.gov.np",
        )
        assert (user.username, user.email) == ("admin_operator", "ops@pgs.gov.np")
        assert user.is_active
        assert ops.get_admin("ADMIN_OPERATOR") is user

    def test_login_works_by_email_as_the_ui_sends_it(self, ops: OpsRepository) -> None:
        user = ops.create_admin(
            "ui_admin", password_hash=HASH, role=AdminRole.SUPER_ADMIN, email="admin@pgs.local"
        )
        assert ops.get_admin(" Admin@PGS.local ") is user
        assert ops.get_admin("ui_admin") is user
        assert ops.get_admin("nobody@pgs.local") is None

    def test_deactivated_accounts_cannot_log_in_by_email(self, ops: OpsRepository) -> None:
        admin(ops, "keeper")
        user = ops.create_admin(
            "gone_ui", password_hash=HASH, role=AdminRole.AUDITOR, email="gone@pgs.local"
        )
        ops.set_active(user.id, False)
        assert ops.get_admin("gone@pgs.local") is None
        assert ops.get_admin("gone@pgs.local", active_only=False) is user

    def test_usernames_cannot_look_like_emails(self, ops: OpsRepository) -> None:
        with pytest.raises(ValueError, match="'@'"):
            ops.create_admin("a@b", password_hash=HASH, role=AdminRole.AUDITOR)
        ops.session.add(AdminUser(username="x@y", password_hash=HASH, role=AdminRole.AUDITOR))
        with pytest.raises(IntegrityError, match="ck_admin_users_username_no_at"):
            ops.session.flush()

    def test_database_rejects_mixed_case_email(self, ops: OpsRepository) -> None:
        ops.session.add(
            AdminUser(
                username="caps", email="Caps@PGS.local", password_hash=HASH, role=AdminRole.AUDITOR
            )
        )
        with pytest.raises(IntegrityError, match="ck_admin_users_email_lowercase"):
            ops.session.flush()

    def test_read_schema_never_exposes_the_hash(self, ops: OpsRepository) -> None:
        read = AdminUserRead.model_validate(admin(ops, "reader"))
        assert "password_hash" not in read.model_dump()
        assert read.role == AdminRole.SUPER_ADMIN

    def test_duplicate_username_is_rejected(self, ops: OpsRepository) -> None:
        admin(ops, "dup")
        with pytest.raises(IntegrityError, match="uq_admin_users_username"):
            admin(ops, "DUP")

    def test_database_rejects_mixed_case_and_empty_hash(self, ops: OpsRepository) -> None:
        ops.session.add(AdminUser(username="Mixed", password_hash=HASH, role=AdminRole.AUDITOR))
        with pytest.raises(IntegrityError, match="ck_admin_users_username_lowercase"):
            ops.session.flush()

    @pytest.mark.parametrize("name, hash_", [(" ", HASH), ("someone", "")])
    def test_bad_calls_are_rejected(self, ops: OpsRepository, name: str, hash_: str) -> None:
        with pytest.raises(ValueError):
            ops.create_admin(name, password_hash=hash_, role=AdminRole.AUDITOR)

    def test_deactivated_accounts_cannot_log_in_but_still_exist(self, ops: OpsRepository) -> None:
        admin(ops, "boss")
        gone = admin(ops, "leaver", AdminRole.AUDITOR)
        ops.set_active(gone.id, False)
        assert ops.get_admin("leaver") is None
        assert ops.get_admin("leaver", active_only=False) is gone
        assert "leaver" not in [u.username for u in ops.list_admins()]
        assert "leaver" in [u.username for u in ops.list_admins(include_inactive=True)]

    def test_record_login_stamps_the_time(self, ops: OpsRepository) -> None:
        user = admin(ops, "stamp")
        when = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
        ops.record_login(user.id, when=when)
        assert user.last_login_at == when

    def test_the_last_super_admin_cannot_be_demoted_or_deactivated(
        self, ops: OpsRepository
    ) -> None:
        # Other super admins may already exist in the dev database; deactivate them here.
        for other in ops.list_admins():
            other.is_active = False
        root = admin(ops, "root")
        with pytest.raises(ValueError, match="last active SUPER_ADMIN"):
            ops.set_role(root.id, AdminRole.AUDITOR)
        with pytest.raises(ValueError, match="last active SUPER_ADMIN"):
            ops.set_active(root.id, False)

        second = admin(ops, "second")
        ops.set_role(root.id, AdminRole.AUDITOR)
        assert root.role == AdminRole.AUDITOR
        with pytest.raises(ValueError):
            ops.set_active(second.id, False)

    def test_unknown_admin_raises_lookup_error(self, ops: OpsRepository) -> None:
        with pytest.raises(LookupError):
            ops.record_login(9_999_999)

    def test_create_schema_normalizes_and_validates(self) -> None:
        body = AdminUserCreate(username=" New.Admin ", password_hash=HASH, role="AUDITOR")
        assert body.username == "new.admin"
        with pytest.raises(ValidationError):
            AdminUserCreate(username="a b", password_hash=HASH, role="AUDITOR")


class TestErrorLogs:
    def test_an_entry_resolves_its_domain_from_the_url(self, ops: OpsRepository) -> None:
        domain_id = BronzeRepository(ops.session).ensure_domain(HOST)
        entry = ops.log_error(
            ServiceName.SCRAPER,
            LogSeverity.ERROR,
            "HTTP 503 Service Unavailable",
            instance="Scraper-Go-Worker-12",
            error_type="HTTP_503",
            url=f"https://www.{HOST}/data",
            context={"attempt": 3},
        )
        assert entry.domain_id == domain_id
        assert entry.occurred_at is not None
        read = ErrorLogRead.model_validate(entry)
        assert (read.service, read.context) == (ServiceName.SCRAPER, {"attempt": 3})

    def test_unknown_hosts_leave_domain_empty(self, ops: OpsRepository) -> None:
        entry = ops.log_error(
            ServiceName.ETL, LogSeverity.WARN, "odd page", url="https://nowhere.invalid/x"
        )
        assert entry.domain_id is None

    def test_empty_message_is_rejected(self, ops: OpsRepository) -> None:
        with pytest.raises(ValueError):
            ops.log_error(ServiceName.API, LogSeverity.ERROR, "  ")

    def test_list_filters_and_orders_newest_first(self, ops: OpsRepository) -> None:
        # Far-past timestamps keep this test's rows apart from anything already logged.
        since = _ANCIENT
        for minutes, service, severity in [
            (1, ServiceName.SCRAPER, LogSeverity.ERROR),
            (2, ServiceName.SCRAPER, LogSeverity.WARN),
            (3, ServiceName.SECURITY, LogSeverity.WARN),
            (4, ServiceName.SCRAPER, LogSeverity.ERROR),
        ]:
            ops.log_error(
                service, severity, f"m{minutes}", occurred_at=since + timedelta(minutes=minutes)
            )
        until = since + timedelta(days=1)

        rows, total = ops.list_errors(service=ServiceName.SCRAPER, since=since)
        ours = [r.message for r in rows if r.occurred_at < until]
        assert ours == ["m4", "m2", "m1"]

        rows, _ = ops.list_errors(
            service=ServiceName.SCRAPER, severity=LogSeverity.ERROR, since=since
        )
        assert [r.message for r in rows if r.occurred_at < until] == ["m4", "m1"]

        page, total = ops.list_errors(service=ServiceName.SECURITY, since=since, limit=1)
        assert len(page) == 1 and total >= 1

    def test_counts_and_purge(self, ops: OpsRepository) -> None:
        old = _ANCIENT - timedelta(days=400)
        ops.log_error(ServiceName.ETL, LogSeverity.FATAL, "ancient", occurred_at=old)
        counts = ops.count_errors_since(old)
        assert set(counts) == {"WARN", "ERROR", "FATAL"}
        assert counts["FATAL"] >= 1

        assert ops.purge_errors(old + timedelta(seconds=1)) >= 1
        rows, _ = ops.list_errors(since=old - timedelta(days=1))
        assert "ancient" not in [r.message for r in rows]

    def test_the_log_outlives_the_bronze_row(self, ops: OpsRepository) -> None:
        bronze = BronzeRepository(ops.session)
        url = f"https://{HOST}/gone"
        doc_id = bronze.save_document(
            {
                "url": url,
                "normalized_url": url,
                "host": HOST,
                "content_hash": "e" * 64,
                "fetched_at": _ANCIENT.isoformat(),
            }
        ).id
        entry = ops.log_error(
            ServiceName.ETL, LogSeverity.ERROR, "parse failed", crawled_document_id=doc_id
        )
        ops.session.execute(delete(CrawledDocument).where(CrawledDocument.id == doc_id))
        ops.session.refresh(entry)
        assert entry.crawled_document_id is None
        assert ops.session.get(ErrorLog, entry.id) is not None
