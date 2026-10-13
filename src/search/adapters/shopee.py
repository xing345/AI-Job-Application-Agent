"""Shopee虾皮校招适配器（Moka招聘平台）。"""
from __future__ import annotations

from src.search.adapters.base import register_adapter
from src.search.adapters.moka_base import MokaBaseAdapter


@register_adapter
class ShopeeAdapter(MokaBaseAdapter):
    """Shopee虾皮校招适配器。"""

    site_name = "shopee"
    company_name = "Shopee虾皮"
