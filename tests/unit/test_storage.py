"""SQLite 异步存储单元测试。

使用临时数据库文件，测试完成后清理。
覆盖：init_db、schema 迁移、record_application、has_applied、
count_applications、upsert_job、is_job_seen、save_state、load_latest_state。
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

import src.storage.state_db as state_db_module


@pytest.fixture
def temp_db():
    """使用临时数据库文件，测试后清理。"""
    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "test_agent_state.db")
    original_path = state_db_module._DB_PATH
    state_db_module._DB_PATH = db_path
    state_db_module._initialized = False

    yield db_path

    # 清理
    state_db_module._DB_PATH = original_path
    state_db_module._initialized = False
    if os.path.exists(db_path):
        os.remove(db_path)
    os.rmdir(tmpdir)


class TestInitDB:
    @pytest.mark.asyncio
    async def test_init_creates_tables(self, temp_db):
        await state_db_module.init_db()
        # 验证表存在
        import aiosqlite
        async with aiosqlite.connect(temp_db) as db:
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in await cursor.fetchall()}
        assert "applications" in tables
        assert "agent_state" in tables
        assert "jobs" in tables
        assert "schema_version" in tables

    @pytest.mark.asyncio
    async def test_schema_version_recorded(self, temp_db):
        await state_db_module.init_db()
        import aiosqlite
        async with aiosqlite.connect(temp_db) as db:
            cursor = await db.execute("SELECT MAX(version) FROM schema_version")
            row = await cursor.fetchone()
        assert row[0] == 2

    @pytest.mark.asyncio
    async def test_init_idempotent(self, temp_db):
        """多次调用 init_db 不应报错。"""
        await state_db_module.init_db()
        await state_db_module.init_db()
        await state_db_module.init_db()


class TestApplications:
    @pytest.mark.asyncio
    async def test_record_application(self, temp_db):
        await state_db_module.init_db()
        rid = await state_db_module.record_application(
            job_url="https://test.com/job/1",
            job_title="测试工程师",
            company="测试公司",
            site_name="test",
            success=True,
            failed_fields=0,
            status="page_verified",
        )
        assert rid > 0

    @pytest.mark.asyncio
    async def test_has_applied_true(self, temp_db):
        await state_db_module.init_db()
        await state_db_module.record_application(
            job_url="https://test.com/job/1", site_name="test", success=True
        )
        assert await state_db_module.has_applied("https://test.com/job/1", "test") is True

    @pytest.mark.asyncio
    async def test_has_applied_false(self, temp_db):
        await state_db_module.init_db()
        assert await state_db_module.has_applied("https://test.com/job/999", "test") is False

    @pytest.mark.asyncio
    async def test_count_applications(self, temp_db):
        await state_db_module.init_db()
        for i in range(3):
            await state_db_module.record_application(
                job_url=f"https://test.com/job/{i}", site_name="test", success=True
            )
        assert await state_db_module.count_applications("test") == 3

    @pytest.mark.asyncio
    async def test_count_applications_empty_site(self, temp_db):
        await state_db_module.init_db()
        assert await state_db_module.count_applications("nonexistent") == 0

    @pytest.mark.asyncio
    async def test_application_history(self, temp_db):
        await state_db_module.init_db()
        for i in range(5):
            await state_db_module.record_application(
                job_url=f"https://test.com/job/{i}", job_title=f"岗位{i}", site_name="test"
            )
        history = await state_db_module.get_application_history(limit=3)
        assert len(history) == 3
        assert history[0]["job_title"] == "岗位4"  # 最新的在前


class TestJobsDedup:
    @pytest.mark.asyncio
    async def test_upsert_job_inserts(self, temp_db):
        await state_db_module.init_db()
        await state_db_module.upsert_job(
            job_url="https://test.com/job/1",
            job_title="测试工程师",
            company="测试公司",
            site_name="test",
        )
        assert await state_db_module.is_job_seen("https://test.com/job/1") is True

    @pytest.mark.asyncio
    async def test_upsert_job_updates(self, temp_db):
        """重复插入应更新而非报错。"""
        await state_db_module.init_db()
        await state_db_module.upsert_job(
            job_url="https://test.com/job/1", job_title="旧标题", company="旧公司", site_name="test"
        )
        await state_db_module.upsert_job(
            job_url="https://test.com/job/1", job_title="新标题", company="新公司", site_name="test"
        )
        # 验证只有一条记录
        import aiosqlite
        async with aiosqlite.connect(temp_db) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM jobs WHERE job_url = ?", ("https://test.com/job/1",))
            row = await cursor.fetchone()
        assert row[0] == 1

    @pytest.mark.asyncio
    async def test_is_job_seen_false(self, temp_db):
        await state_db_module.init_db()
        assert await state_db_module.is_job_seen("https://test.com/job/999") is False


class TestStatePersistence:
    @pytest.mark.asyncio
    async def test_save_and_load_state(self, temp_db):
        await state_db_module.init_db()
        test_state = {"key": "value", "number": 42, "nested": {"a": 1}}
        await state_db_module.save_state("session_123", test_state)
        loaded = await state_db_module.load_latest_state("session_123")
        assert loaded is not None
        assert loaded["key"] == "value"
        assert loaded["number"] == 42
        assert loaded["nested"]["a"] == 1

    @pytest.mark.asyncio
    async def test_load_latest_returns_none_for_unknown(self, temp_db):
        await state_db_module.init_db()
        loaded = await state_db_module.load_latest_state("nonexistent_session")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_latest_returns_most_recent(self, temp_db):
        await state_db_module.init_db()
        await state_db_module.save_state("session_1", {"version": 1})
        await state_db_module.save_state("session_1", {"version": 2})
        await state_db_module.save_state("session_1", {"version": 3})
        loaded = await state_db_module.load_latest_state("session_1")
        assert loaded["version"] == 3
