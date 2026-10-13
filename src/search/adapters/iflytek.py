"""科大讯飞校招适配器（智联zhiye平台）。"""
from __future__ import annotations

from src.search.adapters.base import register_adapter
from src.search.adapters.zhiye_base import ZhiyeBaseAdapter


@register_adapter
class IflytekAdapter(ZhiyeBaseAdapter):
    """科大讯飞校招适配器。"""

    site_name = "iflytek"
    company_name = "科大讯飞"
