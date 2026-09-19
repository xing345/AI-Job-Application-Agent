"""
固定招聘站点清单

不再用 Tavily 自动「搜索有哪些招聘网站」。改为：
- 内置固定门户：Boss直聘 / 猎聘 / 前程无忧 —— 每次必找；
- 用户自定义文件（data/job_sites.json）：你自己往里加别的招聘站/公司官网，
  这些站会在内置三站之外额外加入找岗。
"""

import json
import os
from typing import Dict, List

# 每次必找的固定门户（职位列表/搜索页入口）
BUILTIN_JOB_SITES = [
    {"name": "Boss直聘", "url": "https://www.zhipin.com/web/geek/job", "kind": "portal"},
    {"name": "猎聘", "url": "https://www.liepin.com/zhaopin/", "kind": "portal"},
    {"name": "前程无忧", "url": "https://we.51job.com/pc/search", "kind": "portal"},
]

DEFAULT_SITES_FILE = os.path.join("data", "job_sites.json")


def _project_root() -> str:
    # src/search/site_registry.py -> 上三级即项目根
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_extra_sites(path: str = None) -> List[Dict]:
    """读取用户自定义站点文件，只保留合法 http(s) 链接。"""
    path = path or os.path.join(_project_root(), DEFAULT_SITES_FILE)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # 文件坏了不要崩，视为没有额外站点
        from loguru import logger
        logger.warning(f"读取自定义站点文件失败 {path}: {e}")
        return []

    out: List[Dict] = []
    for s in (data.get("sites") or []):
        if not isinstance(s, dict):
            continue
        url = (s.get("url") or "").strip()
        name = (s.get("name") or url).strip()
        if url.startswith("http"):
            out.append({"name": name, "url": url, "kind": s.get("kind", "portal")})
    return out


def resolve_sites(path: str = None) -> List[Dict]:
    """
    最终找站点列表：内置三站 + 用户文件里的站（保序、按 host 去重）。
    """
    merged: List[Dict] = []
    seen = set()
    for s in BUILTIN_JOB_SITES + load_extra_sites(path):
        key = s["url"].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(s)
    return merged
