"""快仓智能校招适配器（Moka招聘平台）。"""
from __future__ import annotations

from src.search.adapters.base import register_adapter
from src.search.adapters.moka_base import MokaBaseAdapter


@register_adapter
class KuaicangAdapter(MokaBaseAdapter):
    """快仓智能校招适配器。"""

    site_name = "kuaicang"
    company_name = "快仓智能"
