"""
Dashboard 建表逻辑校验（不启动 Streamlit）

把 src/dashboard/app.py 里的 init_db() 抽出来，在临时库上跑一遍，
确认三张表的列齐全（含 Dashboard 先于 Agent 建库的情况）。

用法：python tools/check_dashboard_schema.py
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    src = (ROOT / "src" / "dashboard" / "app.py").read_text(encoding="utf-8")
    start = src.index("def init_db(")
    end = src.index("@st.cache_data", start)
    body = src[start:end]

    tmp_db = Path(tempfile.gettempdir()) / "dsh_dashboard_schema_check.db"
    if tmp_db.exists():
        tmp_db.unlink()

    marker = 'Path(__file__).parent.parent.parent / "data" / "agent_state.db"'
    if marker not in body:
        print("!! 未找到 db_path 定义，请同步更新本脚本")
        return 1
    body = body.replace(marker, f'Path(r"{tmp_db}")')

    ns = {"Path": Path, "sqlite3": sqlite3}
    exec(body, ns)          # noqa: S102 - 只用于本地校验
    ns["init_db"]()

    expected = {
        "job_applications": ["error_message", "search_source", "original_jd",
                             "user_persona_snapshot"],
        "strategy_rules": ["category", "examples_count"],
        "job_search_log": ["is_qualified", "match_score", "url", "title"],
    }
    ok = True
    conn = sqlite3.connect(str(tmp_db))
    for table, cols in expected.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        missing = [c for c in cols if c not in have]
        print(f"{'OK ' if not missing else '!! '}{table}: cols={sorted(have)}")
        if missing:
            print(f"    缺列: {missing}")
            ok = False
    conn.close()
    tmp_db.unlink(missing_ok=True)
    print("schema 校验", "通过" if ok else "失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
