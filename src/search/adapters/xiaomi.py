"""小米校招适配器（飞书招聘平台）。"""
from __future__ import annotations

from src.search.adapters.base import register_adapter
from src.search.adapters.feishu_base import FeishuBaseAdapter


@register_adapter
class XiaomiAdapter(FeishuBaseAdapter):
    """小米校招适配器。"""

    site_name = "xiaomi"
    company_name = "小米"
