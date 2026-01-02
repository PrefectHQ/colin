"""Tests for staleness detection in the compile engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from colin.api.project import ProjectConfig
from colin.compiler import CompileEngine
from colin.models import DocumentMeta, Manifest
from colin.providers.storage.file import FileStorage


class TestStalenessDetection:
    """Tests for _is_document_stale() and staleness-based compilation skipping."""

    @pytest.fixture
    def engine_setup(
        self, tmp_path: Path, mock_agent: MagicMock
    ) -> tuple[CompileEngine, Path, Path]:
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "target" / "compiled"
        output_dir.mkdir(parents=True)

        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=source_dir,
            target_path=tmp_path / "target",
            manifest_path=tmp_path / "target" / "manifest.json",
        )
        artifact_storage = FileStorage(base_path=output_dir)

        engine = CompileEngine(
            config=config,
            artifact_storage=artifact_storage,
        )
        return engine, source_dir, output_dir

    async def test_stale_when_never_compiled(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Document is stale if never compiled before."""
        engine, source_dir, _ = engine_setup

        (source_dir / "new.md").write_text("---\nname: New\n---\nContent")

        result = await engine.compile_all()

        assert len(result) == 1
        assert result[0].uri == "project://new.md"

    async def test_stale_when_source_changed(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Document is stale if source content changed."""
        engine, source_dir, output_dir = engine_setup

        (source_dir / "test.md").write_text("---\nname: Test\n---\nOriginal content")
        await engine.compile_all()

        # Modify source
        (source_dir / "test.md").write_text("---\nname: Test\n---\nModified content")

        # Create new engine with existing manifest
        engine.manifest = Manifest.model_validate_json(
            (engine.config.manifest_path.parent / "manifest.json").read_text()
            if (engine.config.manifest_path).exists()
            else "{}"
        )
        engine._project_provider.manifest = engine.manifest

        result = await engine.compile_all()

        assert len(result) == 1
        assert "Modified content" in result[0].output

    async def test_fresh_when_source_unchanged(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Document is fresh if source unchanged and no refs changed."""
        engine, source_dir, output_dir = engine_setup

        (source_dir / "test.md").write_text("---\nname: Test\n---\nContent")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 1

        # Second compile - should skip
        result2 = await engine.compile_all()
        assert len(result2) == 0  # Skipped because fresh

    async def test_stale_when_ref_updated(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Document is stale if a referenced document was updated."""
        engine, source_dir, output_dir = engine_setup

        # Create base and derived documents
        (source_dir / "base.md").write_text("---\nname: Base\n---\nBase content")
        (source_dir / "derived.md").write_text("---\nname: Derived\n---\n{{ ref('base').content }}")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 2

        # Update base document
        (source_dir / "base.md").write_text("---\nname: Base\n---\nUpdated base content")

        # Second compile - both should be recompiled
        result2 = await engine.compile_all()
        assert len(result2) == 2  # base changed, derived depends on base

        # Verify derived has updated content
        derived = next(doc for doc in result2 if doc.uri == "project://derived.md")
        assert "Updated base content" in derived.output

    async def test_fresh_when_refs_unchanged(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Document is fresh if all refs are unchanged."""
        engine, source_dir, output_dir = engine_setup

        # Create base and derived documents
        (source_dir / "base.md").write_text("---\nname: Base\n---\nBase content")
        (source_dir / "derived.md").write_text("---\nname: Derived\n---\n{{ ref('base').content }}")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 2

        # Second compile - both should be skipped
        result2 = await engine.compile_all()
        assert len(result2) == 0  # Both fresh

    async def test_upstream_recompiled_triggers_downstream(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """If upstream recompiles this run, downstream must also recompile."""
        engine, source_dir, output_dir = engine_setup

        # Create chain: a -> b -> c
        (source_dir / "a.md").write_text("---\nname: A\n---\nA content")
        (source_dir / "b.md").write_text("---\nname: B\n---\n{{ ref('a').content }}")
        (source_dir / "c.md").write_text("---\nname: C\n---\n{{ ref('b').content }}")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 3

        # Update root document
        (source_dir / "a.md").write_text("---\nname: A\n---\nNew A content")

        # Second compile - all three should recompile
        result2 = await engine.compile_all()
        assert len(result2) == 3

        # Verify content propagated
        c_doc = next(doc for doc in result2 if doc.uri == "project://c.md")
        assert "New A content" in c_doc.output


class TestFileStorageGetLastUpdated:
    """Tests for FileStorage.get_last_updated()."""

    async def test_returns_mtime_for_existing_file(self, tmp_path: Path) -> None:
        """get_last_updated() returns file mtime."""
        storage = FileStorage(base_path=tmp_path)
        (tmp_path / "test.txt").write_text("content")

        result = await storage.get_last_updated("test.txt")

        assert result is not None
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    async def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        """get_last_updated() returns None for missing files."""
        storage = FileStorage(base_path=tmp_path)

        result = await storage.get_last_updated("nonexistent.txt")

        assert result is None


class TestCachePolicies:
    """Tests for cache policy handling."""

    @pytest.fixture
    def engine_setup(
        self, tmp_path: Path, mock_agent: MagicMock
    ) -> tuple[CompileEngine, Path, Path]:
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "target" / "compiled"
        output_dir.mkdir(parents=True)

        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=source_dir,
            target_path=tmp_path / "target",
            manifest_path=tmp_path / "target" / "manifest.json",
        )
        artifact_storage = FileStorage(base_path=output_dir)

        engine = CompileEngine(
            config=config,
            artifact_storage=artifact_storage,
        )
        return engine, source_dir, output_dir

    async def test_cache_never_always_rebuilds(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Documents with cache=never are always recompiled."""
        engine, source_dir, _ = engine_setup

        (source_dir / "test.md").write_text("""\
---
colin:
  cache:
    policy: never
---

Content
""")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 1

        # Second compile - should still compile even though nothing changed
        result2 = await engine.compile_all()
        assert len(result2) == 1

    async def test_cache_always_uses_cache(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Documents with cache=always only compile once."""
        engine, source_dir, _ = engine_setup

        (source_dir / "test.md").write_text("""\
---
colin:
  cache:
    policy: always
---

Content
""")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 1

        # Second compile - should skip because cached
        result2 = await engine.compile_all()
        assert len(result2) == 0

    async def test_cache_always_ignores_source_changes(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Documents with cache=always don't recompile even if source changes."""
        engine, source_dir, _ = engine_setup

        (source_dir / "test.md").write_text("""\
---
colin:
  cache:
    policy: always
---

Original content
""")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 1
        assert "Original content" in result1[0].output

        # Modify source
        (source_dir / "test.md").write_text("""\
---
colin:
  cache:
    policy: always
---

Modified content
""")

        # Second compile - should skip even though source changed
        result2 = await engine.compile_all()
        assert len(result2) == 0

    async def test_cache_auto_checks_staleness(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Documents with cache=auto check staleness conditions."""
        engine, source_dir, _ = engine_setup

        (source_dir / "test.md").write_text("""\
---
colin:
  cache:
    policy: auto
---

Content
""")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 1

        # Second compile - should skip (nothing changed)
        result2 = await engine.compile_all()
        assert len(result2) == 0

        # Modify source
        (source_dir / "test.md").write_text("""\
---
colin:
  cache:
    policy: auto
---

Modified content
""")

        # Third compile - should recompile (source changed)
        result3 = await engine.compile_all()
        assert len(result3) == 1
        assert "Modified content" in result3[0].output

    async def test_cache_always_rebuilds_with_force(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Documents with cache=always rebuild when force=True (--no-cache)."""
        engine, source_dir, _ = engine_setup

        (source_dir / "test.md").write_text("""\
---
colin:
  cache: always
---

Content
""")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 1

        # Second compile without force - should skip (same engine, manifest in memory)
        result2 = await engine.compile_all()
        assert len(result2) == 0

        # Third compile with force=True - create new engine with force
        forced_engine = CompileEngine(
            config=engine.config,
            artifact_storage=engine.artifact_storage,
            force=True,
        )
        result3 = await forced_engine.compile_all()
        assert len(result3) == 1

    async def test_cache_always_respects_expiration(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Documents with cache=always still expire based on time threshold."""
        engine, source_dir, _ = engine_setup

        (source_dir / "test.md").write_text("""\
---
colin:
  cache:
    policy: always
    expires: 1h
---

Content
""")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 1

        # Second compile - should skip (within expiration)
        result2 = await engine.compile_all()
        assert len(result2) == 0

        # Backdate compiled_at to simulate expiration
        doc_meta = engine.manifest.get_document("project://test.md")
        assert doc_meta is not None
        doc_meta.compiled_at = datetime.now(timezone.utc) - timedelta(hours=2)

        # Third compile - should rebuild because expired
        result3 = await engine.compile_all()
        assert len(result3) == 1

    async def test_cache_shorthand_syntax_in_document(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Shorthand 'cache: never' works in actual document compilation."""
        engine, source_dir, _ = engine_setup

        (source_dir / "test.md").write_text("""\
---
colin:
  cache: never
---

Content
""")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 1

        # Second compile - should rebuild (cache: never)
        result2 = await engine.compile_all()
        assert len(result2) == 1


class TestProjectProviderGetRefVersion:
    """Tests for ProjectProvider.get_ref_version()."""

    async def test_returns_output_hash_from_manifest(self, tmp_path: Path) -> None:
        """get_ref_version() returns output_hash from manifest."""
        from colin.models import Ref
        from colin.providers.project import ProjectProvider

        manifest = Manifest()
        manifest.set_document(
            "project://test.md",
            DocumentMeta(
                uri="project://test.md",
                source_hash="abc123",
                output_hash="def456",
            ),
        )

        provider = ProjectProvider(base_path=tmp_path, manifest=manifest)
        ref = Ref(provider="project", connection="", method="get", args={"path": "test.md"})

        result = await provider.get_ref_version(ref)

        assert result == "def456"

    async def test_falls_back_to_content_hash_when_not_in_manifest(self, tmp_path: Path) -> None:
        """get_ref_version() falls back to content hash if not in manifest."""
        from colin.models import Ref
        from colin.providers.project import ProjectProvider

        manifest = Manifest()
        (tmp_path / "unknown.md").write_text("Some content")

        provider = ProjectProvider(base_path=tmp_path, manifest=manifest)
        ref = Ref(provider="project", connection="", method="get", args={"path": "unknown.md"})

        result = await provider.get_ref_version(ref)

        # Should be a 16-char hash
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    async def test_falls_back_to_content_hash_without_manifest(self, tmp_path: Path) -> None:
        """get_ref_version() falls back to content hash if no manifest."""
        from colin.models import Ref
        from colin.providers.project import ProjectProvider

        (tmp_path / "test.md").write_text("Test content")
        provider = ProjectProvider(base_path=tmp_path)  # No manifest

        ref = Ref(provider="project", connection="", method="get", args={"path": "test.md"})
        result = await provider.get_ref_version(ref)

        # Should be a 16-char hash
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)


class TestParseDuration:
    """Tests for parse_duration() function."""

    def test_parse_hours(self) -> None:
        """Parse hour durations."""
        from colin.models import parse_duration

        assert parse_duration("1h") == timedelta(hours=1)
        assert parse_duration("24h") == timedelta(hours=24)
        assert parse_duration("168h") == timedelta(hours=168)

    def test_parse_days(self) -> None:
        """Parse day durations."""
        from colin.models import parse_duration

        assert parse_duration("1d") == timedelta(days=1)
        assert parse_duration("7d") == timedelta(days=7)
        assert parse_duration("30d") == timedelta(days=30)

    def test_parse_weeks(self) -> None:
        """Parse week durations."""
        from colin.models import parse_duration

        assert parse_duration("1w") == timedelta(weeks=1)
        assert parse_duration("2w") == timedelta(weeks=2)
        assert parse_duration("4w") == timedelta(weeks=4)

    def test_parse_months(self) -> None:
        """Parse month durations using relativedelta."""
        from dateutil.relativedelta import relativedelta

        from colin.models import parse_duration

        assert parse_duration("1M") == relativedelta(months=1)
        assert parse_duration("3M") == relativedelta(months=3)
        assert parse_duration("12M") == relativedelta(months=12)

    def test_parse_quarters(self) -> None:
        """Parse quarter durations using relativedelta (3 months each)."""
        from dateutil.relativedelta import relativedelta

        from colin.models import parse_duration

        assert parse_duration("1Q") == relativedelta(months=3)
        assert parse_duration("2Q") == relativedelta(months=6)
        assert parse_duration("4Q") == relativedelta(months=12)

    def test_invalid_format_raises(self) -> None:
        """Invalid duration formats raise ValueError."""
        from colin.models import parse_duration

        with pytest.raises(ValueError, match="Invalid duration format"):
            parse_duration("invalid")

        with pytest.raises(ValueError, match="Invalid duration format"):
            parse_duration("1x")

        with pytest.raises(ValueError, match="Invalid duration format"):
            parse_duration("h1")

        with pytest.raises(ValueError, match="Invalid duration format"):
            parse_duration("")

    def test_parse_calendar_aligned(self) -> None:
        """Parse calendar-aligned durations with 'c' prefix."""
        from colin.models import CalendarDuration, parse_duration

        assert parse_duration("1cd") == CalendarDuration(value=1, unit="d")
        assert parse_duration("1cw") == CalendarDuration(value=1, unit="w")
        assert parse_duration("1cM") == CalendarDuration(value=1, unit="M")
        assert parse_duration("1cQ") == CalendarDuration(value=1, unit="Q")
        assert parse_duration("3cM") == CalendarDuration(value=3, unit="M")

    def test_parse_minutes(self) -> None:
        """Parse minute durations."""
        from colin.models import parse_duration

        assert parse_duration("1m") == timedelta(minutes=1)
        assert parse_duration("30m") == timedelta(minutes=30)
        assert parse_duration("45m") == timedelta(minutes=45)

    def test_parse_calendar_minutes(self) -> None:
        """Parse calendar-aligned minute durations."""
        from colin.models import CalendarDuration, parse_duration

        assert parse_duration("15cm") == CalendarDuration(value=15, unit="m")
        assert parse_duration("30cm") == CalendarDuration(value=30, unit="m")

    def test_parse_calendar_hours(self) -> None:
        """Parse calendar-aligned hour durations."""
        from colin.models import CalendarDuration, parse_duration

        assert parse_duration("1ch") == CalendarDuration(value=1, unit="h")
        assert parse_duration("6ch") == CalendarDuration(value=6, unit="h")
        assert parse_duration("12ch") == CalendarDuration(value=12, unit="h")

    def test_calendar_minutes_must_divide_60(self) -> None:
        """Calendar-aligned minutes must divide evenly into 60."""
        from colin.models import parse_duration

        with pytest.raises(ValueError, match="divide evenly into 60"):
            parse_duration("7cm")

        with pytest.raises(ValueError, match="divide evenly into 60"):
            parse_duration("45cm")

    def test_calendar_hours_must_divide_24(self) -> None:
        """Calendar-aligned hours must divide evenly into 24."""
        from colin.models import parse_duration

        with pytest.raises(ValueError, match="divide evenly into 24"):
            parse_duration("5ch")

        with pytest.raises(ValueError, match="divide evenly into 24"):
            parse_duration("23ch")

    def test_calendar_days_only_value_1(self) -> None:
        """Calendar-aligned days only supports value 1."""
        from colin.models import parse_duration

        # Valid
        parse_duration("1cd")

        # Invalid
        with pytest.raises(ValueError, match="only supports value 1"):
            parse_duration("3cd")

    def test_calendar_weeks_only_value_1(self) -> None:
        """Calendar-aligned weeks only supports value 1."""
        from colin.models import parse_duration

        # Valid
        parse_duration("1cw")

        # Invalid
        with pytest.raises(ValueError, match="only supports value 1"):
            parse_duration("2cw")

    def test_calendar_months_must_divide_12(self) -> None:
        """Calendar-aligned months must divide evenly into 12."""
        from colin.models import CalendarDuration, parse_duration

        # Valid values: 1, 2, 3, 4, 6, 12
        assert parse_duration("2cM") == CalendarDuration(value=2, unit="M")
        assert parse_duration("3cM") == CalendarDuration(value=3, unit="M")
        assert parse_duration("6cM") == CalendarDuration(value=6, unit="M")

        # Invalid
        with pytest.raises(ValueError, match="divide evenly into 12"):
            parse_duration("5cM")

    def test_calendar_quarters_must_divide_4(self) -> None:
        """Calendar-aligned quarters must divide evenly into 4."""
        from colin.models import CalendarDuration, parse_duration

        # Valid values: 1, 2, 4
        assert parse_duration("2cQ") == CalendarDuration(value=2, unit="Q")
        assert parse_duration("4cQ") == CalendarDuration(value=4, unit="Q")

        # Invalid
        with pytest.raises(ValueError, match="divide evenly into 4"):
            parse_duration("3cQ")


class TestCalendarDuration:
    """Tests for CalendarDuration.is_stale() method."""

    def test_calendar_minute_stale(self) -> None:
        """Stale after calendar minute boundary (30cm = :00 and :30)."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=30, unit="m")
        # 10:15 -> 10:30 crosses the :30 boundary
        at_1015 = datetime(2024, 1, 1, 10, 15, tzinfo=timezone.utc)
        at_1030 = datetime(2024, 1, 1, 10, 30, tzinfo=timezone.utc)

        assert cd.is_stale(at_1015, at_1030) is True

    def test_calendar_minute_fresh(self) -> None:
        """Fresh within same calendar minute period."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=30, unit="m")
        # 10:05 -> 10:25 stays within the :00-:30 period
        at_1005 = datetime(2024, 1, 1, 10, 5, tzinfo=timezone.utc)
        at_1025 = datetime(2024, 1, 1, 10, 25, tzinfo=timezone.utc)

        assert cd.is_stale(at_1005, at_1025) is False

    def test_calendar_minute_15(self) -> None:
        """15cm has boundaries at :00, :15, :30, :45."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=15, unit="m")
        at_1002 = datetime(2024, 1, 1, 10, 2, tzinfo=timezone.utc)
        at_1014 = datetime(2024, 1, 1, 10, 14, tzinfo=timezone.utc)
        at_1015 = datetime(2024, 1, 1, 10, 15, tzinfo=timezone.utc)

        assert cd.is_stale(at_1002, at_1014) is False
        assert cd.is_stale(at_1002, at_1015) is True

    def test_calendar_hour_stale(self) -> None:
        """Stale after calendar hour boundary (6ch = every 6 hours)."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=6, unit="h")
        # 02:00 -> 06:00 crosses the 6-hour boundary
        at_0200 = datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc)
        at_0600 = datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc)

        assert cd.is_stale(at_0200, at_0600) is True

    def test_calendar_hour_fresh(self) -> None:
        """Fresh within same calendar hour period."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=6, unit="h")
        # 01:00 -> 05:59 stays within the 00:00-06:00 period
        at_0100 = datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc)
        at_0559 = datetime(2024, 1, 1, 5, 59, tzinfo=timezone.utc)

        assert cd.is_stale(at_0100, at_0559) is False

    def test_calendar_day_stale(self) -> None:
        """Stale after calendar day boundary."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=1, unit="d")
        jan1 = datetime(2024, 1, 1, 23, 59, tzinfo=timezone.utc)
        jan2 = datetime(2024, 1, 2, 0, 1, tzinfo=timezone.utc)

        assert cd.is_stale(jan1, jan2) is True

    def test_calendar_day_fresh(self) -> None:
        """Fresh within same calendar day."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=1, unit="d")
        morning = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
        evening = datetime(2024, 1, 1, 23, 59, tzinfo=timezone.utc)

        assert cd.is_stale(morning, evening) is False

    def test_calendar_month_stale(self) -> None:
        """Stale after calendar month boundary."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=1, unit="M")
        jan = datetime(2024, 1, 31, tzinfo=timezone.utc)
        feb = datetime(2024, 2, 1, tzinfo=timezone.utc)

        assert cd.is_stale(jan, feb) is True

    def test_calendar_month_fresh(self) -> None:
        """Fresh within same calendar month."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=1, unit="M")
        jan1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        jan31 = datetime(2024, 1, 31, tzinfo=timezone.utc)

        assert cd.is_stale(jan1, jan31) is False

    def test_calendar_quarter_stale(self) -> None:
        """Stale after calendar quarter boundary."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=1, unit="Q")
        q1 = datetime(2024, 3, 31, tzinfo=timezone.utc)
        q2 = datetime(2024, 4, 1, tzinfo=timezone.utc)

        assert cd.is_stale(q1, q2) is True

    def test_calendar_quarter_fresh(self) -> None:
        """Fresh within same calendar quarter."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=1, unit="Q")
        jan = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mar = datetime(2024, 3, 31, tzinfo=timezone.utc)

        assert cd.is_stale(jan, mar) is False

    def test_multiple_calendar_months(self) -> None:
        """3cM divides year into 4 periods: Jan-Mar, Apr-Jun, Jul-Sep, Oct-Dec."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=3, unit="M")
        jan = datetime(2024, 1, 15, tzinfo=timezone.utc)
        mar = datetime(2024, 3, 31, tzinfo=timezone.utc)
        apr = datetime(2024, 4, 1, tzinfo=timezone.utc)

        # Jan to Mar = same period (Jan-Mar), not stale
        assert cd.is_stale(jan, mar) is False
        # Jan to Apr = crossed into Apr-Jun period, stale
        assert cd.is_stale(jan, apr) is True

    def test_bimonthly_periods(self) -> None:
        """2cM divides year into 6 periods: Jan-Feb, Mar-Apr, etc."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=2, unit="M")
        jan = datetime(2024, 1, 15, tzinfo=timezone.utc)
        feb = datetime(2024, 2, 28, tzinfo=timezone.utc)
        mar = datetime(2024, 3, 1, tzinfo=timezone.utc)

        # Jan to Feb = same period (Jan-Feb), not stale
        assert cd.is_stale(jan, feb) is False
        # Jan to Mar = crossed into Mar-Apr period, stale
        assert cd.is_stale(jan, mar) is True

    def test_semiannual_quarters(self) -> None:
        """2cQ divides year into 2 periods: Q1-Q2 (Jan-Jun), Q3-Q4 (Jul-Dec)."""
        from colin.models import CalendarDuration

        cd = CalendarDuration(value=2, unit="Q")
        jan = datetime(2024, 1, 15, tzinfo=timezone.utc)
        jun = datetime(2024, 6, 30, tzinfo=timezone.utc)
        jul = datetime(2024, 7, 1, tzinfo=timezone.utc)

        # Jan to Jun = same period (Q1-Q2), not stale
        assert cd.is_stale(jan, jun) is False
        # Jan to Jul = crossed into Q3-Q4 period, stale
        assert cd.is_stale(jan, jul) is True


class TestTimeBasedExpiration:
    """Tests for time-based expiration using expires field."""

    @pytest.fixture
    def engine_setup(
        self, tmp_path: Path, mock_agent: MagicMock
    ) -> tuple[CompileEngine, Path, Path]:
        source_dir = tmp_path / "models"
        source_dir.mkdir()
        output_dir = tmp_path / "target" / "compiled"
        output_dir.mkdir(parents=True)

        config = ProjectConfig(
            name="test-project",
            project_root=tmp_path,
            model_path=source_dir,
            target_path=tmp_path / "target",
            manifest_path=tmp_path / "target" / "manifest.json",
        )
        artifact_storage = FileStorage(base_path=output_dir)

        engine = CompileEngine(
            config=config,
            artifact_storage=artifact_storage,
        )
        return engine, source_dir, output_dir

    async def test_expired_after_time_threshold(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Document is stale when time threshold is exceeded."""
        engine, source_dir, _ = engine_setup

        (source_dir / "test.md").write_text("""\
---
colin:
  cache:
    expires: 1h
---

Content
""")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 1

        # Manually backdate the compiled_at time to simulate expiration
        doc_meta = engine.manifest.get_document("project://test.md")
        assert doc_meta is not None
        doc_meta.compiled_at = datetime.now(timezone.utc) - timedelta(hours=2)

        # Second compile - should recompile because stale threshold exceeded
        result2 = await engine.compile_all()
        assert len(result2) == 1

    async def test_fresh_before_time_threshold(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Document is fresh when within time threshold."""
        engine, source_dir, _ = engine_setup

        (source_dir / "test.md").write_text("""\
---
colin:
  cache:
    expires: 1d
---

Content
""")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 1

        # Second compile - should skip because within threshold
        result2 = await engine.compile_all()
        assert len(result2) == 0

    async def test_expiration_overrides_ref_freshness(
        self, engine_setup: tuple[CompileEngine, Path, Path]
    ) -> None:
        """Time-based expiration triggers rebuild even if refs unchanged."""
        engine, source_dir, _ = engine_setup

        # Create a document with short expiration threshold
        (source_dir / "test.md").write_text("""\
---
colin:
  cache:
    expires: 1h
---

Content
""")

        # First compile
        result1 = await engine.compile_all()
        assert len(result1) == 1

        # Backdate compilation
        doc_meta = engine.manifest.get_document("project://test.md")
        assert doc_meta is not None
        doc_meta.compiled_at = datetime.now(timezone.utc) - timedelta(hours=2)

        # Second compile - should recompile due to time, not refs
        result2 = await engine.compile_all()
        assert len(result2) == 1
