"""通用网页表单填写 Agent。

循环：看页面(accessibility snapshot) → LLM 决策动作 → 经 MCP 执行 → 再看，
直到表单填完。任何网站用同一套逻辑，不写站点 selector。
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from pydantic import AliasChoices, BaseModel, Field

from src.llm.client import chat_structured
from src.browser_agent.mcp_client import MCPBrowser

# ============================================================
# 动作模型
# ============================================================

ALLOWED_ACTIONS = {
    "click", "type", "select_option", "upload", "evaluate",
    "wait", "press_key", "ask", "finished",
}


class AgentAction(BaseModel):
    action: str = Field(
        validation_alias=AliasChoices("action", "type"),
        description="动作类型（字段名必须用 action）: click/type/select_option/upload/evaluate/wait/press_key/ask/finished")
    target: str = Field(default="", description="目标元素的 ref，如 e98")
    text: str = Field(default="", description="type 动作要输入的文本；ask 动作要问用户的问题")
    code: str = Field(default="", description="evaluate 动作要执行的 JS 函数，如 () => {...}")
    values: list[str] = Field(default_factory=list, description="select_option 动作的选项值")
    reason: str = Field(default="", description="为什么做这个动作")


class ActionPlan(BaseModel):
    thought: str = Field(default="", description="当前页面状态与下一步思路")
    actions: list[AgentAction] = Field(default_factory=list)
    finished: bool = Field(default=False, description="表单是否已完整填写（不要点提交）")


# ============================================================
# 系统提示
# ============================================================

SYSTEM_PROMPT = """你是一个网页申请表单填写 Agent。目标：把当前招聘申请表单**完整、准确**地填好。

## 你会看到什么
每轮你会收到当前页面的 accessibility snapshot（可访问性快照），形如：
- text: 姓名 *
- textbox [ref=e42]
- combobox [ref=e55]
- button "添加" [ref=e70]
每个可交互元素都有一个 `[ref=eN]`。**动作里的 target 就填这个 ref**（如 "e42"）。

## 识别折叠模块的"添加"按钮（重要）
项目经历、实习经历、工作经历、作品、竞赛、证书、语言能力、自我评价、社交账号等模块默认折叠。它们的"添加"按钮往往是一个**紧跟在模块标题（paragraph 文字，如"项目经历"）后面、本身没有文字的图标按钮（+ 号）**，在快照里形如：
```
- generic [ref=e412]:
  - paragraph [ref=e415]: 项目经历
  - button [ref=e421] [cursor=pointer]
```
这个无文字的 `button [cursor=pointer]` 就是该模块的"添加"按钮。**逐个点击这些按钮展开模块**，点击后重新快照确认字段出现，再填写。判断方法：按钮的上一个兄弟节点是该模块的标题文字。
注意：实习经历若默认勾选了"没有实习经历"而你有实习，先取消该勾选再添加。

## 你可以做的动作
- click：点击按钮/链接/复选框/单选框/combobox。遇到"添加"按钮先点击展开模块；遇到 combobox 先点击展开选项。
- type：在文本框输入内容，需提供 target 和 text。
- select_option：在已展开的下拉/单选组里选选项，需提供 target 和 values。
- upload：上传简历。target 填"选择文件"按钮的 ref（如 e140）；系统会自动先点该按钮弹出文件框、再上传，你只需给这一个动作，不要在 upload 前再单独点它。
- press_key：按键，如 "Enter"、"Escape"。
- wait：等待页面加载（一般不需要，工具会自动等待）。
- ask：当某字段需要的信息在"用户资料"里找不到、或遇到登录/验证码/扫码时，用 ask 提出，用户会手动处理或提供答案。
- finished：表单已完整填好时返回，**绝不要点击最终提交按钮**。

## 规则
1. 先规划：对照快照里的字段名，逐项从"用户资料"里找对应值，不要错位（"导师"框只填导师，"项目经历"要先点"添加"展开项目模块再填）。
2. 必填项（标 *）必须填；选填项若资料里没有就留空，不要编造。
3. 项目/实习/工作/竞赛等模块默认折叠，需要点对应"添加"按钮展开后再填写。
4. 遇到登录墙、扫码、短信验证码、人机验证 → 用 ask 让用户在浏览器里手动完成，不要猜不要跳。
5. **展开类动作（下拉 combobox、折叠模块、弹窗）必须独占一轮**：这一轮的动作里只能有一个"展开"动作，**绝不能同时操作其他字段**（否则下拉会收起、弹窗会关闭，选项就点不中）。展开后重新快照，下一轮再点选项或填内容。
6. 当所有必填字段都已填好、简历已上传、隐私政策已勾选 → 返回 finished，不要点提交。
7. 资料里没有的开放式问题（如"举一个你用 Agent 技术解决问题的案例"），用 ask 让用户提供，或基于用户资料中的项目如实组织，不要虚构。
8. 下拉选择（combobox）的标准两步：
   第1轮：只 click combobox 展开（动作里只有这一个，见规则5）。
   第2轮：重新快照，在 listbox 里找到目标 option 后只 click 该 option。**注意：listbox 可能被渲染在 ARIA 树的页面底部（和 combobox 分开），要往下找，不要因为 combobox 附近没看到选项就以为没有。**
   只有当展开后没有 option、只有一个搜索框时，才需要在搜索框输入关键词；若 type 后仍无 option，用 evaluate 执行下面这段（把 INPUT_SELECTOR、KEYWORD 替换），再重新快照点 option：
   () => { const i = document.querySelector('INPUT_SELECTOR'); i.focus(); const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set; s.call(i,'KEYWORD'); i.dispatchEvent(new Event('input',{bubbles:true})); }
9. 若没有出现你想要的选项（如该岗位只列出北京、深圳、没有上海），说明该岗位不开放该选项：**直接选择实际列出的选项，或用 ask 让用户确认**，不要反复操作同一个下拉。
10. 简历上传：先 click"选择文件/上传简历"按钮（触发文件选择框），再用 upload；不要在没有文件选择框时直接 upload。

## 输出
每轮输出 ActionPlan：thought（简述）、actions（动作列表）、finished（是否完成）。
"""


# ============================================================
# Agent 主循环
# ============================================================

async def _ask_user(question: str) -> str:
    """在屏幕弹窗向用户提问并返回答案（不依赖终端 stdin，后台运行也能回答）。"""
    import tkinter
    from tkinter import ttk

    def _ask() -> str:
        root = tkinter.Tk()
        root.title("Agent 需要你处理")
        root.attributes("-topmost", True)
        w, h = 520, 260
        root.geometry(f"{w}x{h}+{root.winfo_screenwidth()//2-w//2}+{root.winfo_screenheight()//2-h//2}")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        box = tkinter.Text(root, wrap="word", height=8, relief="flat",
                           background="#f5f5f5", padx=10, pady=10)
        box.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        box.insert("1.0", question)
        box.configure(state="disabled")

        var = tkinter.StringVar()
        entry = ttk.Entry(root, textvariable=var)
        entry.grid(row=1, column=0, sticky="ew", padx=12)
        entry.focus_set()

        result = {"value": ""}

        def ok(*_):
            result["value"] = var.get()
            root.destroy()

        def skip(*_):
            result["value"] = ""
            root.destroy()

        bar = ttk.Frame(root)
        bar.grid(row=2, column=0, sticky="e", padx=12, pady=10)
        ttk.Button(bar, text="直接回车（已在浏览器处理）", command=skip).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="提交答案", command=ok).pack(side="right")
        root.bind("<Return>", ok)
        root.protocol("WM_DELETE_WINDOW", skip)
        root.mainloop()
        return result["value"]

    return (await asyncio.to_thread(_ask)).strip()


def _err_msg(e: BaseException) -> str:
    """把异常（含 ExceptionGroup）转成简短文本。"""
    if isinstance(e, BaseExceptionGroup):
        sub = e.exceptions[0] if e.exceptions else e
        return f"{type(sub).__name__}: {sub}"
    return f"{type(e).__name__}: {e}"


async def _execute_action(browser: MCPBrowser, act: AgentAction) -> str:
    """执行单个动作，返回工具输出（通常含新快照）。"""
    a = act.action
    if a == "click":
        return await browser.click(act.target)
    if a == "type":
        return await browser.type(act.target, act.text)
    if a == "select_option":
        return await browser.select_option(act.target, act.values)
    if a == "upload":
        # 简历路径由调用方通过环境变量 RESUME_PATH 提供。
        # 必须先点"选择文件"按钮弹出 file chooser，再上传。
        import os
        resume = os.getenv("RESUME_PATH", "data/resume.pdf")
        if act.target:
            await browser.click(act.target)
        return await browser.upload([resume])
    if a == "press_key":
        return await browser.press_key(act.text or "Enter")
    if a == "evaluate":
        return await browser.evaluate(act.code or "() => null")
    if a == "wait":
        return await browser.wait_for(time=1)
    raise ValueError(f"未知动作: {a}")


async def run_form_agent(
    browser: MCPBrowser,
    url: str,
    user_context: str,
    max_steps: int = 40,
    run_id: str = "",
) -> dict:
    """打开 url 并驱动表单填写。返回结果摘要。"""
    from loguru import logger

    # 1. 打开页面，等待异步表单加载完成
    await browser.navigate(url)
    await browser.wait_for(time=3)
    snapshot = await browser.snapshot()

    # 2. 固定基础消息（不随轮次增长）
    base_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"【用户资料】\n{user_context}"},
    ]
    done_log: list[str] = []   # 紧凑动作历史
    feedback = ""              # 失败/用户处理反馈，仅带入下一轮
    recent_sigs: list[str] = []  # 最近动作签名，用于检测死循环
    recent_targets: list[list[str]] = []  # 每轮动作 target，用于检测"同一控件反复打转"

    result = {"finished": False, "steps": 0, "asks": []}
    decision_errors = 0

    # 3. 决策循环
    for step in range(1, max_steps + 1):
        result["steps"] = step
        # 快照可能很长，截断保护
        snap_for_llm = snapshot if len(snapshot) < 12000 else snapshot[:12000] + "\n...(快照已截断)"

        # 每轮重建消息：固定基础 + 紧凑历史 + 反馈 + 最新快照（大小恒定，不累积）
        messages = list(base_messages)
        if done_log:
            messages.append({"role": "system",
                             "content": "【已执行动作（避免重复）】\n" + "\n".join(done_log[-25:])})
        if feedback:
            messages.append({"role": "user", "content": feedback})
            feedback = ""
        messages.append({"role": "user", "content": f"【当前页面快照 第{step}轮】\n{snap_for_llm}"})

        try:
            plan = await chat_structured(messages, ActionPlan, temperature=0.1, run_id=run_id)
        except BaseException as e:
            msg = _err_msg(e)
            logger.warning("form-agent decision failed: %s", msg)
            decision_errors += 1
            if decision_errors >= 3:
                raise
            feedback = (f"上一次输出无法解析（{msg[:150]}）。请严格按 ActionPlan 重新输出："
                        f"每个动作的字段名必须是 \"action\"（不要写成 type），并带 target/text。")
            await asyncio.sleep(1)
            continue
        decision_errors = 0
        logger.info(
            f"form-agent step{step}: actions={[(a.action, a.target or '-') for a in plan.actions]} "
            f"finished={plan.finished} snap_len={len(snapshot)}"
        )

        if plan.finished:
            result["finished"] = True
            break

        # 卡死检测：
        #  (a) 连续 3 轮动作完全相同；
        #  (b) 最近 6 轮里某个 target 被反复操作 ≥4 次（同一控件打转、每轮略不同）
        sig = "|".join(f"{a.action}:{a.target}:{a.text[:10]}" for a in plan.actions)
        recent_sigs.append(sig)
        tgts = [a.target for a in plan.actions if a.target]
        recent_targets.append(tgts)
        if len(recent_targets) > 6:
            recent_targets = recent_targets[-6:]
        flat = [t for tl in recent_targets for t in tl]
        repeated = any(flat.count(t) >= 4 for t in set(flat))
        same3 = len(recent_sigs) >= 3 and len(set(recent_sigs[-3:])) == 1
        has_ask = any(a.action == "ask" for a in plan.actions)
        stuck = (same3 or (len(recent_targets) >= 5 and repeated)) and not has_ask
        if stuck:
            q = "我连续几次操作都没有进展（可能该选项不存在、岗位不开放该城市、或控件无响应）。请在浏览器中手动完成这一步，或告诉我该选什么。"
            answer = await _ask_user(q)
            result["asks"].append(q)
            feedback = f"用户处理结果：{answer or '已在浏览器完成'}"
            recent_sigs.clear()
            recent_targets.clear()
            try:
                snapshot = await browser.snapshot()
            except BaseException:
                pass
            continue

        # 执行动作（动作输出不直接当快照）
        for act in plan.actions:
            done_log.append(
                f"{act.action} {act.target or '-'} {act.text[:40]}".strip()
            )
            if act.action == "ask":
                answer = await _ask_user(act.text or "请处理当前页面问题")
                result["asks"].append(act.text)
                feedback = f"用户处理结果：{answer or '已在浏览器完成'}"
                continue
            try:
                await _execute_action(browser, act)
                await browser.wait_for(time=1)  # 给页面反应时间
            except BaseException as e:
                # 捕获所有异常（含 ExceptionGroup），反馈给 LLM 换方式，不崩溃
                msg = _err_msg(e)
                logger.warning(f"action {act.action}({act.target}) failed: {msg}")
                feedback = f"动作 {act.action}({act.target}) 失败：{msg}，请换一种方式。"

        # 动作全部执行完后，重新拿干净、完整的快照
        try:
            snapshot = await browser.snapshot()
        except BaseException as e:
            logger.warning(f"snapshot failed: {_err_msg(e)}")
            feedback = (feedback + " " if feedback else "") + "页面快照获取失败，请确认页面状态后换一种操作。"

    return result
