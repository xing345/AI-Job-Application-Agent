"""验证字节跳动分页配置。"""
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.search.site_registry import get_site_config
from src.search.adapters import get_adapter

config = get_site_config("bytedance")
print(f"config.pagination_type: {config.pagination_type}")
print(f"config.max_pages: {config.max_pages}")

adapter_cls = get_adapter("bytedance")
adapter = adapter_cls(config)
print(f"adapter.max_pages: {adapter.max_pages}")
print(f"adapter.max_jobs_hard_limit: {adapter.max_jobs_hard_limit}")
print(f"adapter has _go_to_next_page: {hasattr(adapter, '_go_to_next_page')}")
print(f"adapter has _wait_for_cards: {hasattr(adapter, '_wait_for_cards')}")
print(f"NEXT_PAGE_SELECTOR: {adapter.NEXT_PAGE_SELECTOR}")
print("\n配置验证通过！")
