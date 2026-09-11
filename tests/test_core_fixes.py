# -*- coding: utf-8 -*-
"""
本轮修复的离线回归测试（无需真实 LLM / 浏览器 / 网络）。
默认即可运行: python -m pytest tests/test_core_fixes.py -q
"""
import os
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- #
# 1. llm_client 健壮 JSON 解析
# ---------------------------------------------------------------- #
@pytest.fixture(scope="module")
def llm_client_class():
    from src.utils.llm_client import LLMClient
    return LLMClient


def test_parse_json_content_plain(llm_client_class):
    assert llm_client_class._parse_json_content('{"a": 1}') == {"a": 1}


def test_parse_json_content_with_fences(llm_client_class):
    raw = '```json\n{"name": "张三"}\n```'
    assert llm_client_class._parse_json_content(raw) == {"name": "张三"}


def test_parse_json_content_with_surrounding_text(llm_client_class):
    raw = '好的,结果如下: {"match_score": 85, "level": "优秀"} 以上。'
    parsed = llm_client_class._parse_json_content(raw)
    assert parsed["match_score"] == 85


def test_parse_json_content_invalid_raises(llm_client_class):
    with pytest.raises(ValueError):
        llm_client_class._parse_json_content("这不是JSON")


# ---------------------------------------------------------------- #
# 2. env 优先于 config.json（密钥迁移契约）
# ---------------------------------------------------------------- #
def test_llm_env_takes_precedence(monkeypatch):
    from src.utils.llm_client import LLMClient
    monkeypatch.setenv("OPENAI_MODEL", "env-test-model")
    client = LLMClient()
    assert client.model == "env-test-model"
    monkeypatch.delenv("OPENAI_MODEL", raising=False)


def test_llm_config_fallback_when_env_unset(monkeypatch):
    from src.utils.llm_client import LLMClient
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    client = LLMClient()
    # config.json 中 llm.model 非空时应作为兜底值
    assert client.model  # 不依赖具体厂商, 只要求非空


# ---------------------------------------------------------------- #
# 3. job_finder 过滤逻辑(离线): 空公司/职位不再误杀, 排除非招聘页
# ---------------------------------------------------------------- #
def test_job_page_filter_logic():
    from src.models.instruction_schemas import TargetInstructionSchema
    from src.search.job_finder import JobFinder, JobFinderConfig

    cfg = JobFinderConfig(api_key="")
    finder = JobFinder(cfg)

    info = TargetInstructionSchema(company="", role="", location="")
    # 无公司/职位要求时, 正常招聘页通过
    # (域名白名单已下线: 原先只认海外 ATS, 国内公司官网会被全部误杀)
    assert finder._is_job_page(
        "https://jobs.bytedance.com/position/123", "招聘", "we are hiring", info
    )
    assert finder._is_job_page("https://example.com/jobs/1", "Software Engineer", "hiring", info)
    # 噪声站点拒绝(百科/内容站/应用商店等)
    assert not finder._is_job_page("https://zhuanlan.zhihu.com/p/1", "招聘", "hiring", info)
    assert not finder._is_job_page("https://apps.apple.com/cn/app/x", "招聘", "hiring", info)
    # blog / about 类页面拒绝
    assert not finder._is_job_page(
        "https://jobs.bytedance.com/blog/new-post", "招聘", "hiring", info
    )

    # 指定了公司名时, 公司必须出现在标题/描述/域名中
    info2 = TargetInstructionSchema(company="字节跳动", role="前端", location="北京")
    assert not finder._is_job_page(
        "https://jobs.meituan.com/x", "美团 前端工程师", "hiring", info2
    )
    assert finder._is_job_page(
        "https://jobs.example.com/x", "字节跳动 前端工程师", "hiring", info2
    )


# ---------------------------------------------------------------- #
# 4. WebhookService: 未配置/占位 URL 不发送; 配置后按渠道发送
# ---------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_webhook_skips_unconfigured_channels():
    from src.notifications.calendar_sync import WebhookService

    service = WebhookService({"feishu": "", "wechat": "your_wechat_webhook_url", "telegram": ""})
    await service.send_notification("test", channels=["feishu", "wechat", "telegram"])  # 不应抛错/不发网络


@pytest.mark.asyncio
async def test_webhook_sends_only_when_configured():
    from src.notifications.calendar_sync import WebhookService

    service = WebhookService({"feishu": "https://example.com/feishu"})
    sent = []

    async def fake_send(channel, message):
        sent.append(channel)

    service._send_to_channel = fake_send  # 替换为本地记录, 不触发真实网络
    await service.send_notification("hello", channels=["feishu", "wechat"])
    assert sent == ["feishu"]


# ---------------------------------------------------------------- #
# 5. resume_parser: 真实文本提取 + 无虚构身份
# ---------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_resume_parser_real_text(tmp_path):
    from src.parsers.resume_parser import parse_pdf

    resume_txt = tmp_path / "resume.txt"
    resume_txt.write_text(
        textwrap.dedent(
            """\
            李四
            电话：13900000001
            邮箱：lisi@example.com

            求职意向：Python 后端开发工程师

            技能
            Python, Django, PostgreSQL, Git
            """
        ),
        encoding="utf-8",
    )

    resume = await parse_pdf(str(resume_txt))
    assert resume is not None
    assert resume.name == "李四"
    assert resume.email == "lisi@example.com"
    assert resume.phone == "13900000001"
    assert "Python" in resume.skills


@pytest.mark.asyncio
async def test_resume_parser_no_fake_identity(tmp_path):
    """只有占位文本(无姓名/邮箱)的简历必须解析失败, 绝不回填虚构身份"""
    from src.parsers.resume_parser import parse_pdf

    empty_txt = tmp_path / "placeholder.txt"
    empty_txt.write_text("This is not a real resume.", encoding="utf-8")
    assert await parse_pdf(str(empty_txt)) is None


# ---------------------------------------------------------------- #
# 6. smart_form_filler: 疑似提交按钮识别(离线静态逻辑)
# ---------------------------------------------------------------- #
def test_submit_like_detection():
    from src.automation.smart_form_filler import SmartFormFiller

    assert SmartFormFiller._is_submit_like("提交申请")
    assert SmartFormFiller._is_submit_like("Apply Now")
    assert SmartFormFiller._is_submit_like("同意并投递")
    assert SmartFormFiller._is_submit_like("submit")
    assert not SmartFormFiller._is_submit_like("下一步")
    assert not SmartFormFiller._is_submit_like("添加工作经历")
