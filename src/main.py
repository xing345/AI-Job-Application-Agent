"""自动求职 Agent 主入口。

用法：
  python -m src.main --site bytedance --resume data/resume.pdf --profile data/user_profile.json
  python -m src.main --job-url https://jobs.bytedance.com/xxx --resume data/resume.pdf
  python -m src.main --resume-run <session_id>
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

from src.agent.graph import build_graph
from src.agent.state import AgentState
from src.browser.manager import close_browser, get_browser
from src.storage import state_db
from src.utils.logging_config import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自动求职 Agent")
    parser.add_argument("--site", type=str, default="", help="招聘站点名称（如 bytedance, bilibili, tencent）")
    parser.add_argument("--job-url", type=str, action="append", default=[], help="直接指定岗位详情页 URL（可多次指定，跳过岗位发现）")
    parser.add_argument("--apply-url", type=str, default="", help="直达填表：给定一个投递/表单链接，打开后直接填表，跳过发现/初筛/匹配")
    parser.add_argument("--resume", type=str, default="", help="简历文件路径（PDF/JSON/TXT）")
    parser.add_argument("--profile", type=str, default="", help="用户画像 JSON 路径")
    parser.add_argument("--discover-url", type=str, default="", help="直接指定任意招聘列表页 URL，自动发现岗位（无需预先注册站点）")
    parser.add_argument("--resume-run", type=str, default="", help="断点续跑：指定 session_id 恢复上次状态")
    parser.add_argument("--refresh", action="store_true", help="强制重新发现岗位（默认复用本地缓存的发现/JD/匹配结果）")
    parser.add_argument("--max-deep", type=int, default=80, help="每个站点深度抓取JD+匹配的岗位上限（按方向相关度排序，0=不限；默认80）")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    parser.add_argument("--list-sites", action="store_true", help="列出支持的招聘站点")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    session_id = args.resume_run or str(uuid.uuid4())[:8]
    if args.refresh:
        os.environ["JOB_AGENT_REFRESH"] = "1"
    os.environ["JOB_AGENT_MAX_DEEP"] = str(max(0, args.max_deep))
    setup_logging(verbose=args.verbose, run_id=session_id)
    logger = logging.getLogger(__name__)

    if args.list_sites:
        from src.search.site_registry import list_sites
        print("支持的招聘站点：")
        for s in list_sites():
            print(f"  - {s}")
        return

    logger.info("=== 自动求职 Agent 启动 | session=%s ===", session_id)
    # 处理 --discover-url：动态注册任意招聘网站
    site_name = args.site
    if args.discover_url:
        from urllib.parse import urlparse
        from src.search.site_registry import SiteConfig, register_site, get_site_config
        parsed = urlparse(args.discover_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        site_name = parsed.netloc.replace(".", "_").replace(":", "_")
        # 检查是否已注册
        if not get_site_config(site_name):
            register_site(SiteConfig(
                name=site_name,
                base_url=base_url,
                category_url=args.discover_url,
                pagination_type="scroll",
                max_pages=50,
                description=f"自定义站点: {base_url}",
            ))
            logger.info("动态注册站点: %s -> %s", site_name, args.discover_url)

    state = AgentState(
        run_id=session_id,
        site_name=site_name,
        job_urls=args.job_url,
        apply_url=args.apply_url,
        resume_path=args.resume,
        profile_path=args.profile,
    )

    if args.resume_run:
        saved = await state_db.load_latest_state(args.resume_run)
        if saved:
            state = AgentState.model_validate(saved)
            logger.info("恢复断点状态: %s", args.resume_run)
        else:
            logger.warning("未找到会话 %s 的保存状态，将从头开始", args.resume_run)

    if not state.site_name and not state.job_urls and not state.apply_url:
        print("错误：请指定 --site、--job-url 或 --apply-url")
        print("使用 --list-sites 查看支持的站点")
        sys.exit(1)

    try:
        await state_db.init_db()
        logger.info("Database ready")

        # 直达填表：走通用 MCP 浏览器 agent（不启动旧的固定 selector 流程）
        if state.apply_url:
            from src.browser_agent.apply import run_apply
            await run_apply(state.apply_url, args.profile, args.resume, run_id=session_id)
            return

        await get_browser()
        logger.info("Browser ready")

        graph = build_graph()
        result = await graph.ainvoke(state)

        # LangGraph 可能返回 dict，统一转成 AgentState
        if isinstance(result, dict):
            final_state = AgentState.model_validate(result)
        else:
            final_state = result

        await state_db.save_state(session_id, final_state.model_dump(mode="json"))

        print("\n" + "=" * 60)
        print("=== 运行结束 ===")
        print(f"会话 ID: {session_id}")
        if final_state.errors:
            print(f"错误 ({len(final_state.errors)}):")
            for e in final_state.errors[-10:]:
                print(f"  - {e}")
        if final_state.apply_queue:
            print(f"投递队列: {len(final_state.apply_queue)} 个岗位")
        if final_state.match_results:
            print(f"匹配结果: {len(final_state.match_results)} 个岗位")
            top = final_state.match_results[0]
            print(f"最高匹配: {top.job_title} ({top.score}分)")
        print("=" * 60)

    except KeyboardInterrupt:
        logger.info("用户中断")
        await state_db.save_state(session_id, state.model_dump(mode="json"))
        print(f"\n已保存状态，可用 --resume-run {session_id} 恢复")
    except Exception as e:
        logger.exception("Agent 运行失败: %s", e)
        await state_db.save_state(session_id, state.model_dump(mode="json"))
        print(f"\n运行失败: {e}")
        print(f"已保存状态，可用 --resume-run {session_id} 恢复")
    finally:
        await close_browser()
        logger.info("Browser closed")


if __name__ == "__main__":
    asyncio.run(main())
