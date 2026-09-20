"""
Human-in-the-loop 阻断处理器（HITL）

满足两条硬要求：
1. 遇到「需要登录」「验证码/人机验证」或「AI 无法继续操作」的网站时，
   不要静默跳过、不要瞎点，而是**停下来把问题清楚地汇报给用户**。
2. 用户在弹出的可见浏览器里手动处理完（登录 / 过验证 / 手动点过去）后，
   回到终端按回车，Agent 从断点继续运行；用户也可以输入 skip 跳过该站。

设计：
- interactive=True 且浏览器非无头（headless=False）时，才真正阻塞等待——
  因为只有可见窗口里用户才有可能手动操作。
- 无头 / 非交互场景（定时任务、无人值守、离线测试）不阻塞，直接返回 False
  表示「跳过这里」，绝不卡死在 input() 上。
- on_pause 回调可注入（测试 / 自有 UI），默认走终端 input()。

暂停期间浏览器必须「静止」：
- `handle()` 等待用户输入时会清掉内部 resume 事件，所有并发的浏览器操作
  通过 `await wait_until_resumed()` 停下来，不再抢标签页、不再重载页面
  （否则用户正在登录时窗口会不停闪烁）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from loguru import logger


@dataclass
class BlockInfo:
    """一次阻断事件的描述，方便上层记录 / 展示"""

    kind: str          # login / captcha / blocked / unknown
    url: str
    detail: str = ""

    @property
    def label(self) -> str:
        return {
            "login": "需要登录",
            "captcha": "出现验证码/人机验证",
            "blocked": "被网站拦截",
            "unknown": "Agent 无法继续操作",
        }.get(self.kind, "Agent 无法继续操作")


# on_pause(info) -> "continue" | "skip"；默认走终端输入
PauseCallback = Callable[[BlockInfo], Awaitable[str]]


class BlockHandler:
    """统一的「停下 → 汇报 → 等人 → 继续」处理器"""

    def __init__(
        self,
        interactive: bool = True,
        headless: bool = True,
        on_pause: Optional[PauseCallback] = None,
    ):
        self.interactive = interactive
        self.headless = headless
        self._on_pause = on_pause
        # 同一站点只暂停一次，避免并发抓 JD 时反复打断用户
        self._seen_domains: set[str] = set()
        # 暂停闸门：等待用户处理期间清掉，浏览器侧所有操作都要先等它
        self._resume = asyncio.Event()
        self._resume.set()
        self._paused = False

    # ------------------------------------------------------------------ #
    @property
    def is_paused(self) -> bool:
        """当前是否正在等用户手动处理（此时绝不能再去动浏览器）"""
        return self._paused

    async def wait_until_resumed(self) -> None:
        """
        等「用户处理完」再继续。

        并发抓 JD 时，某个页面撞上登录墙会触发暂停；其余页面/新标签页必须先
        停在这里，否则会在用户登录过程中不断开新页、重载页面（页面疯狂闪烁）。
        未暂停时是一次立即返回的空操作。
        """
        if self._resume.is_set():
            return
        logger.info("等待用户在浏览器里完成处理（Agent 暂停所有页面操作）...")
        await self._resume.wait()

    # ------------------------------------------------------------------ #
    def _domain(self, url: str) -> str:
        try:
            from urllib.parse import urlparse
            return (urlparse(url).netloc or url).lower()
        except Exception:
            return (url or "").lower()

    @property
    def can_pause(self) -> bool:
        """只有「交互模式 + 可见浏览器」才真正需要人工介入"""
        return self.interactive and not self.headless

    # ------------------------------------------------------------------ #
    async def handle(self, kind: str, url: str, detail: str = "") -> bool:
        """
        处理一次阻断。

        Returns:
            True  -> 用户已处理完，从断点继续（重试 / 继续抓下一页）
            False -> 跳过这里（无头 / 非交互 / 用户选择 skip）
        """
        info = BlockInfo(kind=kind, url=url, detail=detail)
        domain = self._domain(url)

        if not self.can_pause:
            logger.warning(
                f"[{info.label}] {url}（无头/非交互，自动跳过；"
                f"如需人工处理请以可见浏览器、交互模式启动）"
            )
            return False

        # 同域只打断一次：用户登录一次通常整站通行。
        # 注意：这只在「同一个浏览器实例」内成立——浏览器被重建（用户关掉窗口、
        # 页面崩溃后自动重建）时登录态已经丢了，调用方必须调 reset() 让这里重新询问。
        if domain in self._seen_domains:
            logger.info(f"[{info.label}] {url}（该站此前已人工处理，按已通行继续）")
            return True
        self._seen_domains.add(domain)

        self._paused = True
        self._resume.clear()
        try:
            choice = await self._ask_user(info)
        finally:
            self._paused = False
            self._resume.set()
        if choice == "skip":
            logger.warning(f"用户选择跳过：{info.label} {url}")
            return False
        logger.info(f"用户已处理，继续运行：{info.label} {url}")
        return True

    # ------------------------------------------------------------------ #
    async def _ask_user(self, info: BlockInfo) -> str:
        """向用户清楚地汇报问题，并等待其处理结果。返回 'continue' / 'skip'。"""
        banner = "=" * 60
        print(f"\n{banner}")
        print(f"⛔ Agent 在这里停住了，需要你手动处理：")
        print(f"   问题：{info.label}")
        print(f"   页面：{info.url}")
        if info.detail:
            print(f"   说明：{info.detail}")
        print(f"   请在弹出的浏览器窗口里完成登录 / 验证 / 必要操作；")
        print(f"   完成后回到这里按【回车】继续；输入 skip 可跳过这个网站。")
        print(banner)

        if self._on_pause is not None:
            try:
                return (await self._on_pause(info)).strip().lower()
            except Exception as e:
                logger.warning(f"自定义暂停回调失败，回退终端输入: {e}")

        # 用线程跑 input()，避免阻塞事件循环
        try:
            raw = await asyncio.to_thread(
                input, "处理完成后按回车继续（输入 skip 跳过）> "
            )
            return (raw or "").strip().lower()
        except (EOFError, KeyboardInterrupt):
            # 没有终端（管道 / 后台）时不要炸，视为跳过
            return "skip"

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """
        清空「已人工处理站点」记录。

        两个调用时机：
        1. 新一轮搜索开始前；
        2. **浏览器被重建时**（用户关掉窗口 / 崩溃后自动重建）——
           新浏览器没有旧登录态，必须重新询问，不能按「已通行」放行。
        """
        self._seen_domains.clear()
        self._paused = False
        self._resume.set()

