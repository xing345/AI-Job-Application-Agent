"""SQLite 存储：投递记录、断点续跑、岗位去重、历史记录。

使用 aiosqlite 异步化，避免阻塞事件循环。
包含 schema_version 表和迁移逻辑，支持平滑升级。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)

_DB_PATH = str(Path(__file__).resolve().parent.parent.parent / "data" / "agent_state.db")
_SCHEMA_VERSION = 2

_initialized = False


def _get_db_path() -> str:
    return _DB_PATH


async def init_db() -> None:
    """初始化数据库表和 schema 版本。

    包含迁移逻辑：根据当前 schema_version 执行升级。
    """
    global _initialized
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)

    async with aiosqlite.connect(_DB_PATH) as db:
        # 创建 schema_version 表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
        """)

        # 获取当前版本
        cursor = await db.execute("SELECT MAX(version) FROM schema_version")
        row = await cursor.fetchone()
        current_version = row[0] if row and row[0] else 0

        # 迁移到 v1：applications + agent_state 表
        if current_version < 1:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_url TEXT NOT NULL,
                    job_title TEXT,
                    company TEXT,
                    site_name TEXT,
                    success INTEGER DEFAULT 0,
                    failed_fields INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_applications_url ON applications(job_url);
                CREATE INDEX IF NOT EXISTS idx_applications_site ON applications(site_name);

                CREATE TABLE IF NOT EXISTS agent_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            await db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (1, ?)",
                (datetime.now().isoformat(),),
            )
            logger.info("DB migrated to v1")

        # 迁移到 v2：添加 status 列 + jobs 去重表
        if current_version < 2:
            # 检查 applications 表是否已有 status 列（兼容旧库）
            cursor = await db.execute("PRAGMA table_info(applications)")
            columns = {row[1] for row in await cursor.fetchall()}
            if "status" not in columns:
                await db.execute("ALTER TABLE applications ADD COLUMN status TEXT DEFAULT 'pending'")

            # 岗位去重表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_url TEXT NOT NULL UNIQUE,
                    job_title TEXT,
                    company TEXT,
                    site_name TEXT,
                    location TEXT,
                    category_path TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_site ON jobs(site_name)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)")

            await db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (2, ?)",
                (datetime.now().isoformat(),),
            )
            logger.info("DB migrated to v2")

        await db.commit()

    _initialized = True
    logger.info("DB initialized: version=%d path=%s", _SCHEMA_VERSION, _DB_PATH)


async def _ensure_init() -> None:
    """确保数据库已初始化。"""
    if not _initialized:
        await init_db()


# ============================================================
# 投递记录
# ============================================================

async def record_application(
    job_url: str,
    job_title: str = "",
    company: str = "",
    site_name: str = "",
    success: bool = False,
    failed_fields: int = 0,
    status: str = "pending",
) -> int:
    """记录一条投递结果。"""
    await _ensure_init()
    async with aiosqlite.connect(_DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO applications (job_url, job_title, company, site_name, success, failed_fields, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_url, job_title, company, site_name, int(success), failed_fields, status, datetime.now().isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def has_applied(job_url: str, site_name: str = "", cycle_days: int = 30) -> bool:
    """检查某岗位是否在配额周期内已投递过。"""
    await _ensure_init()
    since = (datetime.now() - timedelta(days=cycle_days)).isoformat()
    async with aiosqlite.connect(_DB_PATH) as db:
        if site_name:
            cursor = await db.execute(
                "SELECT 1 FROM applications WHERE job_url = ? AND site_name = ? AND created_at >= ? LIMIT 1",
                (job_url, site_name, since),
            )
        else:
            cursor = await db.execute(
                "SELECT 1 FROM applications WHERE job_url = ? AND created_at >= ? LIMIT 1",
                (job_url, since),
            )
        row = await cursor.fetchone()
        return row is not None


async def count_applications(site_name: str, cycle_days: int = 30) -> int:
    """统计某站点在配额周期内的投递数量。"""
    await _ensure_init()
    since = (datetime.now() - timedelta(days=cycle_days)).isoformat()
    async with aiosqlite.connect(_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM applications WHERE site_name = ? AND created_at >= ?",
            (site_name, since),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_application_history(limit: int = 50) -> List[Dict[str, Any]]:
    """获取最近的投递历史。"""
    await _ensure_init()
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM applications ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ============================================================
# 岗位去重
# ============================================================

async def upsert_job(
    job_url: str,
    job_title: str = "",
    company: str = "",
    site_name: str = "",
    location: str = "",
    category_path: str = "",
) -> None:
    """插入或更新岗位记录（用于去重）。"""
    await _ensure_init()
    now = datetime.now().isoformat()
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """INSERT INTO jobs (job_url, job_title, company, site_name, location, category_path, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(job_url) DO UPDATE SET
                   job_title=excluded.job_title,
                   company=excluded.company,
                   location=excluded.location,
                   category_path=excluded.category_path,
                   last_seen_at=excluded.last_seen_at""",
            (job_url, job_title, company, site_name, location, category_path, now, now),
        )
        await db.commit()


async def is_job_seen(job_url: str) -> bool:
    """检查岗位是否已被发现过。"""
    await _ensure_init()
    async with aiosqlite.connect(_DB_PATH) as db:
        cursor = await db.execute("SELECT 1 FROM jobs WHERE job_url = ? LIMIT 1", (job_url,))
        row = await cursor.fetchone()
        return row is not None


# ============================================================
# 断点续跑
# ============================================================

async def save_state(session_id: str, state_dict: Dict[str, Any]) -> None:
    """保存 AgentState 用于断点续跑。"""
    await _ensure_init()
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "INSERT INTO agent_state (session_id, state_json, created_at) VALUES (?, ?, ?)",
            (session_id, json.dumps(state_dict, ensure_ascii=False, default=str), datetime.now().isoformat()),
        )
        await db.commit()


async def load_latest_state(session_id: str) -> Optional[Dict[str, Any]]:
    """加载最近一次保存的 AgentState。"""
    await _ensure_init()
    async with aiosqlite.connect(_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT state_json FROM agent_state WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None
