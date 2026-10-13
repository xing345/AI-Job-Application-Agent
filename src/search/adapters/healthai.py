"""北京医疗健康大模型校招适配器（智联zhiye平台）。"""
from __future__ import annotations

from src.search.adapters.base import register_adapter
from src.search.adapters.zhiye_base import ZhiyeBaseAdapter


@register_adapter
class HealthaiAdapter(ZhiyeBaseAdapter):
    """北京医疗健康大模型校招适配器。"""

    site_name = "healthai"
    company_name = "北京医疗健康大模型"
