"""SQLite 存储：投递记录、断点续跑、历史去重。"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_PATH = str(Path(__file__).resolve().parent.parent.parent / "data" / "agent_state.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化数据库表。"""
    conn = _get_conn()
    try:
        conn.executescript("""
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
        conn.commit()
    finally:
        conn.close()


async def record_application(
    job_url: str,
    job_title: str = "",
    company: str = "",
    site_name: str = "",
    success: bool = False,
    failed_fields: int = 0,
) -> int:
    """记录一条投递结果。"""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            """INSERT INTO applications (job_url, job_title, company, site_name, success, failed_fields, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (job_url, job_title, company, site_name, int(success), failed_fields, datetime.now().isoformat()),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def has_applied(job_url: str, site_name: str = "", cycle_days: int = 30) -> bool:
    """检查某岗位是否在配额周期内已投递过。"""
    conn = _get_conn()
    try:
        since = (datetime.now() - timedelta(days=cycle_days)).isoformat()
        if site_name:
            row = conn.execute(
                "SELECT 1 FROM applications WHERE job_url = ? AND site_name = ? AND created_at >= ? LIMIT 1",
                (job_url, site_name, since),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM applications WHERE job_url = ? AND created_at >= ? LIMIT 1",
                (job_url, since),
            ).fetchone()
        return row is not None
    finally:
        conn.close()


def count_applications(site_name: str, cycle_days: int = 30) -> int:
    """统计某站点在配额周期内的投递数量。"""
    conn = _get_conn()
    try:
        since = (datetime.now() - timedelta(days=cycle_days)).isoformat()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM applications WHERE site_name = ? AND created_at >= ?",
            (site_name, since),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def get_application_history(limit: int = 50) -> List[Dict[str, Any]]:
    """获取最近的投递历史。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM applications ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_state(session_id: str, state_dict: Dict[str, Any]) -> None:
    """保存 AgentState 用于断点续跑。"""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO agent_state (session_id, state_json, created_at) VALUES (?, ?, ?)",
            (session_id, json.dumps(state_dict, ensure_ascii=False, default=str), datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def load_latest_state(session_id: str) -> Optional[Dict[str, Any]]:
    """加载最近一次保存的 AgentState。"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT state_json FROM agent_state WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row:
            return json.loads(row["state_json"])
        return None
    finally:
        conn.close()


# 初始化
init_db()
