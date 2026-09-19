"""
人工介入暂停（HITL）

遇到登录墙、验证码、或自动化无法继续操作的页面时：
停下来把原因告诉用户，等用户在浏览器里处理完后再发指令继续。

用户回复约定：
  回车 / continue / 继续 / 好了  -> 已处理，Agent 接着跑
  skip / 跳过                     -> 跳过当前站点/当前职位
  abort / 停止                    -> 中止整段流程
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Optional

from loguru import logger


class HitlDecision(str, Enum):
    CONTINUE = "continue"
    SKIP = "skip"
    ABORT = "abort"


class HitlAbort(Exception):
    """用户选择中止当前自动化流程。"""


def parse_hitl_reply(raw: Optional[str]) -> HitlDecision:
    """解析用户在终端里的回复。空输入视为已处理完毕、继续。"""
    text = (raw or "").strip().lower()
    if not text or text in {
        "c", "y", "yes", "ok", "continue", "go",
        "继续", "好了", "完成", "搞定", "已登录", "已处理",
    }:
        return HitlDecision.CONTINUE
    if text in {"s", "skip", "n", "no", "跳过", "下一个", "下一站"}:
        return HitlDecision.SKIP
    if text in {"q", "abort", "quit", "exit", "stop", "停止", "退出", "中止"}:
        return HitlDecision.ABORT
    # 未识别的话默认继续，避免用户随手打了「好」之类被卡住
    return HitlDecision.CONTINUE


async def pause_for_human(
    *,
    reason: str,
    url: str = "",
    hint: str = "",
    interactive: bool = True,
) -> HitlDecision:
    """
    在终端暂停，把问题反馈给用户，等待其处理后再继续。

    Returns:
        HitlDecision：continue / skip / abort
    """
    if not interactive:
        logger.warning(f"非交互模式遇到需人工处理的情况，跳过: {reason} {url}")
        return HitlDecision.SKIP

    print("\n" + "=" * 60)
    print("⏸️  自动化已暂停，需要你判断并处理")
    print("=" * 60)
    print(f"原因: {reason}")
    if url:
        print(f"页面: {url}")
    if hint:
        print(f"建议: {hint}")
    print()
    print("请在弹出的浏览器窗口中完成登录 / 验证码 / 点到职位列表等操作。")
    print("处理完后回到这里：")
    print("  回车 或 continue  —— 告诉我已解决，继续运行")
    print("  skip              —— 跳过当前站点/当前职位")
    print("  abort             —— 停止本次流程")
    print("=" * 60)

    try:
        reply = await asyncio.to_thread(input, "处理完成后输入指令 > ")
    except (EOFError, KeyboardInterrupt):
        logger.warning("HITL 输入被中断，按跳过处理")
        return HitlDecision.SKIP

    decision = parse_hitl_reply(reply)
    logger.info(f"HITL 用户指令: {decision.value}（原因: {reason}）")
    if decision is HitlDecision.ABORT:
        raise HitlAbort(reason)
    return decision


# 页面阻断检测：登录墙 / 验证码。在浏览器 page.evaluate 中执行。
_BLOCKER_JS = """() => {
    const lower = (s) => String(s == null ? "" : s).toLowerCase();
    const norm = (s) => lower(s).replace(/\\s+/g, "");
    const visible = (el) => {
        if (!el || el.nodeType !== 1) return false;
        try {
            const st = window.getComputedStyle(el);
            if (st.display === "none" || st.visibility === "hidden") return false;
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        } catch (err) { return false; }
    };

    const CAPTCHA_SEL = [
        ".g-recaptcha", 'iframe[src*="recaptcha" i]', 'iframe[src*="hcaptcha" i]',
        'iframe[src*="geetest" i]', 'input[name*="captcha" i]', 'input[id*="captcha" i]',
        'img[src*="captcha" i]'
    ];
    for (const sel of CAPTCHA_SEL) {
        const el = document.querySelector(sel);
        if (el && visible(el)) return {kind: "captcha", detail: sel};
    }

    const bodyText = (document.body && (document.body.innerText || "")) || "";
    const captchaHints = ["验证码", "安全验证", "滑动验证", "人机验证", "行为验证",
                          "are you a robot", "verify you are human", "unusual traffic"];
    const blob = lower(bodyText.slice(0, 4000));
    if (captchaHints.some((h) => blob.includes(h))) {
        return {kind: "captcha", detail: "page-text"};
    }

    const LOGIN_KEYS = ["login", "log in", "signin", "sign-in", "sign in", "登录", "登入"];
    const EXACT_BTN = ["登录", "登入", "立即登录", "马上登录", "安全登录",
                       "快速登录", "login", "signin", "sign in", "log in"];
    const hasLoginKey = (s) => LOGIN_KEYS.some((k) => lower(s).includes(k));
    const isExactLoginBtn = (s) => EXACT_BTN.some((k) => norm(s) === norm(k));

    const pw = Array.from(document.querySelectorAll(
        'input[type="password"], input[name="password" i], ' +
        'input[placeholder*="密码" i], input[placeholder*="password" i]'
    )).find(visible);
    const headingParts = [];
    if (document.title) headingParts.push(document.title);
    for (const el of document.querySelectorAll("h1, h2, h3, legend")) {
        if (visible(el)) headingParts.push(el.innerText || el.textContent || "");
    }
    const headingLogin = hasLoginKey(headingParts.join(" "));
    const formIsLogin = (f) => {
        const action = f.getAttribute("action") || "";
        if (hasLoginKey(action)) return true;
        return Array.from(f.querySelectorAll(
            'button, input[type="submit"], input[type="button"], a[role="button"]'
        )).some((b) => isExactLoginBtn(b.innerText || b.value || ""));
    };
    let anyFormLogin = false;
    for (const f of Array.from(document.querySelectorAll("form"))) {
        if (formIsLogin(f)) { anyFormLogin = true; break; }
    }
    if (anyFormLogin || (pw && headingLogin)) {
        return {kind: "login", detail: "login-wall"};
    }

    const short = bodyText.replace(/\\s+/g, " ").trim();
    if (short.length < 40) {
        return {kind: "unoperable", detail: "empty-page"};
    }
    return {kind: "", detail: ""};
}"""


async def detect_page_blocker(page) -> Optional[str]:
    """
    检测当前页是否阻断自动化。

    Returns:
        人类可读原因，或 None 表示页面可继续操作。
    """
    try:
        result = await page.evaluate(_BLOCKER_JS)
    except Exception as e:
        logger.debug(f"阻断检测失败，按可操作处理: {e}")
        return None
    kind = (result or {}).get("kind") or ""
    if kind == "login":
        return "需要登录后才能继续"
    if kind == "captcha":
        return "出现验证码 / 安全验证，自动化无法通过"
    if kind == "unoperable":
        return "页面几乎空白或未加载，自动化无法操作"
    return None
