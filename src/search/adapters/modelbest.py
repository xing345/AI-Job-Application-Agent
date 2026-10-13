"""面壁智能校招适配器（飞书招聘平台）。"""
from __future__ import annotations

from src.search.adapters.base import register_adapter
from src.search.adapters.feishu_base import FeishuBaseAdapter


@register_adapter
class ModelbestAdapter(FeishuBaseAdapter):
    """面壁智能校招适配器。"""

    site_name = "modelbest"
    company_name = "面壁智能"
