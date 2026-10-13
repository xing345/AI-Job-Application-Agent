"""杉数科技校招适配器（Moka招聘平台）。"""
from __future__ import annotations

from src.search.adapters.base import register_adapter
from src.search.adapters.moka_base import MokaBaseAdapter


@register_adapter
class ShanshuAdapter(MokaBaseAdapter):
    """杉数科技校招适配器。"""

    site_name = "shanshu"
    company_name = "杉数科技"
