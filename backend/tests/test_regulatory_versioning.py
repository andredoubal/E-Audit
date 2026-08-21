"""Version resolution — pure logic over hand-built LegalUnit rows, no ingestion needed."""
from __future__ import annotations

from datetime import date

from app.models.regulatory import STATUS_ACTIVE, STATUS_SUPERSEDED, LegalUnit
from app.regulatory.versioning import resolve_version


def _unit(unit_id, version_group, effective_from, effective_to, status):
    return LegalUnit(
        unit_id=unit_id, version_group=version_group, regulation_code="TEST-IR",
        level="article", content_type="IMPLEMENTING_REGULATION",
        citation_label=unit_id, text="text",
        effective_from=effective_from, effective_to=effective_to, status=status,
    )


def _seed_two_versions(db):
    # merge, not add: this helper runs once per test against a session-scoped database, so a
    # second call must update the existing rows rather than collide on the primary key.
    # commit, not just flush: `seeded` is shared for the whole test session (SQLite, one
    # writer at a time) — an uncommitted write held open here would lock out every later
    # test's own writes (including other test files' TestClient requests) for the rest of
    # the run.
    db.merge(_unit("TEST-IR-A53-v1", "TEST-IR-A53", date(2018, 1, 1), date(2021, 12, 3),
                   STATUS_SUPERSEDED))
    db.merge(_unit("TEST-IR-A53-v2", "TEST-IR-A53", date(2021, 12, 4), None, STATUS_ACTIVE))
    db.commit()


def test_resolves_the_version_covering_an_earlier_period(seeded):
    _seed_two_versions(seeded)
    u = resolve_version(seeded, "TEST-IR-A53", date(2020, 6, 1))
    assert u.unit_id == "TEST-IR-A53-v1"


def test_resolves_the_version_covering_a_later_period(seeded):
    _seed_two_versions(seeded)
    u = resolve_version(seeded, "TEST-IR-A53", date(2023, 1, 1))
    assert u.unit_id == "TEST-IR-A53-v2"


def test_boundary_date_belongs_to_the_new_version(seeded):
    _seed_two_versions(seeded)
    u = resolve_version(seeded, "TEST-IR-A53", date(2021, 12, 4))
    assert u.unit_id == "TEST-IR-A53-v2"


def test_a_period_covered_by_neither_version_returns_none(seeded):
    """This is the NEEDS_LEGAL_VALIDATION path — a gap in the version history must never be
    silently papered over by picking the nearest version."""
    db_units_only = _unit("TEST-IR-A99", "TEST-IR-A99", date(2022, 1, 1), date(2022, 12, 31),
                          STATUS_SUPERSEDED)
    seeded.merge(db_units_only)
    seeded.commit()
    assert resolve_version(seeded, "TEST-IR-A99", date(2019, 1, 1)) is None


def test_as_of_none_prefers_the_active_version(seeded):
    _seed_two_versions(seeded)
    u = resolve_version(seeded, "TEST-IR-A53", None)
    assert u.unit_id == "TEST-IR-A53-v2"


def test_unknown_version_group_returns_none(seeded):
    assert resolve_version(seeded, "NO-SUCH-GROUP", date(2024, 1, 1)) is None
