"""云知声校招适配器（智联zhiye平台）。"""
from __future__ import annotations

from src.search.adapters.base import register_adapter
from src.search.adapters.zhiye_base import ZhiyeBaseAdapter


@register_adapter
class AispeechAdapter(ZhiyeBaseAdapter):
    """云知声校招适配器。"""

    site_name = "aispeech"
    company_name = "云知声"
