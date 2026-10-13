"""站点适配器基类。

每个招聘网站使用独立适配器，封装导航、分页、岗位卡片定位、详情页和申请入口逻辑。
适配器只负责结构化提取，不调用 LLM。
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.async_api import Page

from src.models.job import JobDetail, JobPosting
from src.search.site_registry import SiteConfig

logger = logging.getLogger(__name__)


def normalize_url(url: str, base_url: str = "") -> str:
    """规范化 URL 用于去重。

    策略：
    1. 相对路径转绝对路径
    2. 移除 fragment（# 后面的内容）
    3. 移除尾部斜杠（保守处理，只移除路径末尾的单个斜杠）
    4. 移除常见跟踪参数（utm_*、spm、from 等）
    5. 统一 scheme 和 netloc 为小写

    注意：不合并查询参数顺序，不删除所有查询参数（某些岗位 ID 在查询参数中）。
    """
    if not url:
        return ""

    # 相对路径转绝对
    if base_url and not url.startswith(("http://", "https://")):
        url = urljoin(base_url, url)

    try:
        parsed = urlparse(url)
    except Exception:
        return url

    # 统一 scheme/netloc 小写
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # 移除尾部斜杠（保守：只移除路径末尾的单个 /）
    path = parsed.path
    if path.endswith("/") and len(path) > 1:
        path = path[:-1]

    # 移除跟踪参数
    tracking_params = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                        "spm", "from", "source", "ref", "referer", "track_id", "trace_id"}
    if parsed.query:
        params = []
        for pair in parsed.query.split("&"):
            if "=" in pair:
                key = pair.split("=", 1)[0].lower()
                if key not in tracking_params:
                    params.append(pair)
            else:
                params.append(pair)
        query = "&".join(params)
    else:
        query = ""

    # 重新组装（移除 fragment）
    normalized = urlunparse((scheme, netloc, path, "", query, ""))
    return normalized


class SiteAdapter(ABC):
    """站点适配器基类。

    子类必须实现：
    - site_name: 站点名称（与 site_registry 中的 name 对应）
    - discover_jobs(): 主入口，返回岗位列表

    可选重写：
    - _scroll_page(): 滚动加载策略
    - _extract_jobs_from_page(): 当前可见区域的岗位提取
    """

    site_name: str = ""

    # 默认配置
    max_pages: int = 50
    scroll_pause_ms: int = 1500
    no_new_threshold: int = 5  # 连续 N 次无新岗位则停止
    max_jobs_hard_limit: int = 500

    def __init__(self, config: SiteConfig):
        self.config = config
        # 子类定义的 max_pages 优先；config.max_pages 仅作为兜底
        # （基类默认值为50，子类可覆盖为站点特定值）
        if self.max_pages == 50 and config.max_pages > 0:
            self.max_pages = config.max_pages

    @abstractmethod
    async def discover_jobs(self, page: Page) -> List[JobPosting]:
        """从当前页面发现所有岗位。

        子类实现应：
        1. 等待页面加载
        2. 循环滚动+提取，直到无新岗位或达到上限
        3. 去重（按规范化 URL）
        4. 返回 JobPosting 列表
        """
        ...

    async def extract_jd_detail(self, page: Page, posting: JobPosting) -> Optional[JobDetail]:
        """在已打开的 JD 详情页上提取结构化信息。

        子类可选重写。默认返回 None，表示使用通用提取逻辑。

        注意：调用方负责页面导航、等待加载、HITL 检测。
        本方法只负责在当前页面上提取信息。

        Returns:
            JobDetail（包含结构化的职责/要求/薪资/地点等），
            或 None 表示使用通用提取。
        """
        return None

    # ============================================================
    # 通用工具方法
    # ============================================================

    async def _scroll_page(self, page: Page) -> None:
        """滚动页面触发懒加载。

        策略：
        1. 滚动整个页面到底部
        2. 等待 scroll_pause_ms
        3. 尝试滚动可滚动容器（虚拟滚动列表）
        """
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(self.scroll_pause_ms)

            # 尝试滚动可滚动容器
            await page.evaluate("""() => {
                const containers = document.querySelectorAll('*');
                for (const el of containers) {
                    const style = window.getComputedStyle(el);
                    if ((style.overflowY === 'auto' || style.overflowY === 'scroll')
                        && el.scrollHeight > el.clientHeight + 100) {
                        el.scrollTop = el.scrollHeight;
                    }
                }
            }""")
            await page.wait_for_timeout(self.scroll_pause_ms // 2)
        except Exception as e:
            logger.debug("Scroll failed: %s", e)

    def _make_job_posting(
        self,
        title: str,
        detail_url: str,
        company: str = "",
        location: str = "",
        category_path: str = "",
    ) -> Optional[JobPosting]:
        """构造 JobPosting，包含 URL 规范化和基本校验。"""
        if not title or not detail_url:
            return None

        # 标题清洗
        title = title.strip()
        if len(title) < 2 or len(title) > 200:
            return None

        # URL 规范化
        normalized_url = normalize_url(detail_url, self.config.base_url)
        if not normalized_url:
            return None

        return JobPosting(
            title=title,
            company=company,
            location=location,
            detail_url=normalized_url,
            category_path=category_path,
            site_name=self.config.name,
        )

    def _dedup_jobs(self, jobs: List[JobPosting]) -> List[JobPosting]:
        """按规范化 URL 去重，保留先出现的。"""
        seen: Set[str] = set()
        unique: List[JobPosting] = []
        for job in jobs:
            key = job.dedup_key()
            if key not in seen:
                seen.add(key)
                unique.append(job)
        return unique

    def _is_noise_title(self, title: str) -> bool:
        """判断是否为噪声文本（导航/按钮/非岗位标题）。"""
        noise = {
            "首页", "关于我们", "联系我们", "隐私政策", "用户协议",
            "登录", "注册", "退出", "更多", "查看更多", "加载更多",
            "下一页", "上一页", "全部", "筛选", "排序", "搜索",
            "校招", "校园招聘", "社招", "实习", "职位", "岗位",
            "技术", "产品", "设计", "运营", "市场", "职能", "销售",
            "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "西安", "南京", "重庆",
            "立即投递", "申请职位", "投递简历", "了解更多", "查看详情",
        }
        return title.strip().lower() in {n.lower() for n in noise}


# ============================================================
# 适配器注册表
# ============================================================

_ADAPTER_REGISTRY: dict[str, type[SiteAdapter]] = {}


def register_adapter(adapter_cls: type[SiteAdapter]) -> type[SiteAdapter]:
    """注册站点适配器（装饰器）。"""
    if not adapter_cls.site_name:
        raise ValueError(f"Adapter {adapter_cls.__name__} must define site_name")
    _ADAPTER_REGISTRY[adapter_cls.site_name] = adapter_cls
    logger.info("Registered adapter: %s -> %s", adapter_cls.site_name, adapter_cls.__name__)
    return adapter_cls


def get_adapter(site_name: str) -> Optional[type[SiteAdapter]]:
    """获取站点适配器类。"""
    return _ADAPTER_REGISTRY.get(site_name.lower())


def list_adapters() -> List[str]:
    """列出所有已注册的适配器。"""
    return list(_ADAPTER_REGISTRY.keys())
