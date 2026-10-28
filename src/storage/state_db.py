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
_SCHEMA_VERSION = 5

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

        # 迁移到 v3：jobs 表增加 JD 全文与匹配结果缓存字段（分阶段缓存，避免重跑重复抓取/匹配）
        if current_version < 3:
            cursor = await db.execute("PRAGMA table_info(jobs)")
            existing_cols = {row[1] for row in await cursor.fetchall()}
            v3_columns = [
                ("full_jd", "TEXT"),
                ("responsibilities", "TEXT"),
                ("requirements", "TEXT"),
                ("jd_hash", "TEXT"),
                ("jd_fetched_at", "TEXT"),
                ("match_json", "TEXT"),
                ("matched_at", "TEXT"),
            ]
            for col_name, col_type in v3_columns:
                if col_name not in existing_cols:
                    await db.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")

            await db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (3, ?)",
                (datetime.now().isoformat(),),
            )
            logger.info("DB migrated to v3")

        # 迁移到 v4：jobs 表增加初筛标记（-1 未筛 / 0 筛了未过 / 1 筛了通过），用于复用初筛结果
        if current_version < 4:
            cursor = await db.execute("PRAGMA table_info(jobs)")
            existing_cols = {row[1] for row in await cursor.fetchall()}
            if "passed_screen" not in existing_cols:
                await db.execute(
                    "ALTER TABLE jobs ADD COLUMN passed_screen INTEGER DEFAULT -1")
            await db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (4, ?)",
                (datetime.now().isoformat(),),
            )
            logger.info("DB migrated to v4")

        # 迁移到 v5：known_fields 跨站记忆库（用户补充过一次的字段，按语义复用）
        if current_version < 5:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS known_fields (
                    field_key TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used TEXT NOT NULL
                )
            """)
            await db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (5, ?)",
                (datetime.now().isoformat(),),
            )
            logger.info("DB migrated to v5")

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


# ============================================================
# 分阶段缓存：JD 全文 + 匹配结果（避免重跑重复抓取/匹配）
# ============================================================

def _compute_jd_hash(full_jd: str) -> str:
    """计算 JD 全文的 hash，用于判断 JD 是否变化（匹配缓存是否仍有效）。"""
    import hashlib
    return hashlib.md5((full_jd or "").encode("utf-8")).hexdigest()


async def save_jd_detail(
    job_url: str,
    full_jd: str,
    responsibilities: str = "",
    requirements: str = "",
) -> None:
    """缓存某岗位抓取到的 JD 全文。"""
    await _ensure_init()
    now = datetime.now().isoformat()
    jd_hash = _compute_jd_hash(full_jd)
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """UPDATE jobs
               SET full_jd=?, responsibilities=?, requirements=?, jd_hash=?, jd_fetched_at=?
               WHERE job_url=?""",
            (full_jd, responsibilities, requirements, jd_hash, now, job_url),
        )
        await db.commit()


async def get_cached_jd(job_url: str) -> Optional[Dict[str, Any]]:
    """获取缓存的 JD；无有效缓存返回 None。"""
    await _ensure_init()
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT job_url, job_title, company, site_name, location, category_path,
                      full_jd, responsibilities, requirements, jd_hash, jd_fetched_at
               FROM jobs WHERE job_url=?""",
            (job_url,),
        )
        row = await cursor.fetchone()
        if row and row["full_jd"]:
            return dict(row)
        return None


async def save_match(job_url: str, match: Dict[str, Any], jd_hash: str) -> None:
    """缓存某岗位的 LLM 匹配结果，关联当前 JD hash。"""
    await _ensure_init()
    now = datetime.now().isoformat()
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE jobs SET match_json=?, matched_at=?, jd_hash=? WHERE job_url=?",
            (json.dumps(match, ensure_ascii=False), now, jd_hash, job_url),
        )
        await db.commit()


async def get_cached_match(job_url: str, jd_hash: str) -> Optional[Dict[str, Any]]:
    """获取缓存的匹配结果；JD hash 不一致（JD 已变）或无缓存返回 None。"""
    await _ensure_init()
    async with aiosqlite.connect(_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT match_json, jd_hash FROM jobs WHERE job_url=?",
            (job_url,),
        )
        row = await cursor.fetchone()
        if row and row[0] and row[1] == jd_hash:
            return json.loads(row[0])
        return None


async def get_site_job_postings(site_name: str) -> List[Dict[str, Any]]:
    """从库中加载某站点所有已发现岗位（用于跳过岗位发现，直接复用）。"""
    await _ensure_init()
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT job_url, job_title, company, site_name, location, category_path
               FROM jobs WHERE site_name=? ORDER BY id""",
            (site_name,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ============================================================
# 初筛结果缓存
# ============================================================

async def reset_screen_flags(site_name: str) -> None:
    """把某站点所有岗位的初筛标记重置为 -1（未筛），用于重新发现后强制重筛。"""
    await _ensure_init()
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE jobs SET passed_screen=-1 WHERE site_name=?", (site_name,))
        await db.commit()


async def mark_screen_results(
    site_name: str, all_urls: List[str], passed_urls: List[str]
) -> None:
    """初筛完成后记录每个岗位是否通过（1 通过 / 0 未过）。"""
    await _ensure_init()
    passed = set(passed_urls)
    async with aiosqlite.connect(_DB_PATH) as db:
        for url in all_urls:
            await db.execute(
                "UPDATE jobs SET passed_screen=? WHERE job_url=?",
                (1 if url in passed else 0, url),
            )
        await db.commit()


async def get_cached_screened(site_name: str) -> Optional[List[Dict[str, Any]]]:
    """获取已缓存的初筛通过岗位。

    若该站点还有岗位未筛（passed_screen=-1），返回 None 表示需重新初筛；
    否则返回通过初筛（passed_screen=1）的岗位列表。
    """
    await _ensure_init()
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE site_name=? AND passed_screen=-1",
            (site_name,),
        )
        unscreened = (await cursor.fetchone())["c"]
        if unscreened > 0:
            return None
        cursor = await db.execute(
            """SELECT job_url, job_title, company, site_name, location, category_path
               FROM jobs WHERE site_name=? AND passed_screen=1 ORDER BY id""",
            (site_name,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ============================================================
# 跨站记忆库 known_fields（用户补充过一次的字段，按语义复用）
# ============================================================

def _norm_field_text(t: str) -> str:
    """规范化字段标签用于模糊匹配：小写、去空白与常见 UI 助词。"""
    import re
    t = (t or "").lower()
    t = re.sub(r"[\s\*:：（）()、,，。.]", "", t)
    for filler in ("请输入", "请选择", "您的", "你的", "请填写", "请"):
        t = t.replace(filler, "")
    return t


async def upsert_known_field(field_key: str, label: str, value: str) -> None:
    """保存/更新一个记忆字段（按 field_key 语义主键）。"""
    await _ensure_init()
    now = datetime.now().isoformat()
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """INSERT INTO known_fields (field_key, label, value, created_at, last_used)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(field_key) DO UPDATE SET
                   label=excluded.label, value=excluded.value, last_used=excluded.last_used""",
            (field_key, label, value, now, now),
        )
        await db.commit()


async def list_known_fields() -> List[Dict[str, Any]]:
    """列出全部记忆字段。"""
    await _ensure_init()
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT field_key, label, value, created_at, last_used FROM known_fields ORDER BY last_used DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]


async def find_known_field(label: str = "", semantic_type: str = "") -> Optional[Dict[str, Any]]:
    """按语义类型精确 + 标签模糊查找记忆字段，命中返回 {field_key,label,value}。

    匹配顺序：1) semantic_type 精确命中 field_key；2) label 规范化后互相包含。
    命中后更新 last_used。
    """
    await _ensure_init()
    rows = await list_known_fields()
    if not rows:
        return None

    # 1) 语义精确
    if semantic_type:
        key = _norm_field_text(semantic_type)
        for r in rows:
            if _norm_field_text(r["field_key"]) == key:
                return r

    # 2) 标签模糊
    nl = _norm_field_text(label)
    if len(nl) >= 2:
        best = None
        best_score = 0.0
        for r in rows:
            nr = _norm_field_text(r["label"])
            if not nr:
                continue
            if nl == nr:
                best, best_score = r, 1.0
                break
            if nl in nr or nr in nl:
                score = min(len(nl), len(nr)) / max(len(nl), len(nr))
                if score > best_score:
                    best, best_score = r, score
        if best is not None and best_score >= 0.5:
            async with aiosqlite.connect(_DB_PATH) as db:
                await db.execute(
                    "UPDATE known_fields SET last_used=? WHERE field_key=?",
                    (datetime.now().isoformat(), best["field_key"]),
                )
                await db.commit()
            return best
    return None
