"""千寻智能校招适配器（飞书招聘平台）。"""
from __future__ import annotations

from src.search.adapters.base import register_adapter
from src.search.adapters.feishu_base import FeishuBaseAdapter


@register_adapter
class QianxunAdapter(FeishuBaseAdapter):
    """千寻智能校招适配器。"""

    site_name = "qianxun"
    company_name = "千寻智能"
