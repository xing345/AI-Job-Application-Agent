"""招聘站点配置注册表。

岗位发现使用通用策略（URL 模式 + 文本特征 + 滚动加载），
不依赖特定网站的 selector。专用 selector 仅作为可选优化。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class SiteConfig:
    """招聘站点配置。"""

    name: str
    base_url: str
    category_url: str = ""  # 分类导航页 URL
    max_applications_per_cycle: int = 3
    cycle_days: int = 30

    # 专用 selector（可选，留空则使用通用发现策略）
    job_card_selector: str = ""
    job_title_selector: str = ""
    job_link_selector: str = ""
    job_location_selector: str = ""
    job_company_selector: str = ""

    # 分页
    pagination_type: str = "scroll"  # scroll / page_param / click_next
    page_param_name: str = "page"
    max_pages: int = 50

    description: str = ""


# 内置站点配置
# 注意：大部分站点不配置专用 selector，使用通用发现策略
# 只有经过验证的站点才配置专用 selector 作为优化
_SITES: Dict[str, SiteConfig] = {
    "bytedance": SiteConfig(
        name="bytedance",
        base_url="https://jobs.bytedance.com",
        category_url="https://jobs.bytedance.com/campus/position",
        max_applications_per_cycle=3,
        cycle_days=30,
        # 字节跳动已验证：岗位链接格式 /campus/position/{ID}/detail
        job_card_selector="a[href*='/campus/position/'][href*='/detail']",
        pagination_type="scroll",
        max_pages=50,
        description="字节跳动校招",
    ),
    "bilibili": SiteConfig(
        name="bilibili",
        base_url="https://jobs.bilibili.com",
        category_url="https://jobs.bilibili.com/campus/positions",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=50,
        description="哔哩哔哩校招",
    ),
    "tencent": SiteConfig(
        name="tencent",
        base_url="https://join.qq.com",
        category_url="https://join.qq.com/post.html",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=50,
        description="腾讯校招",
    ),
    "jd": SiteConfig(
        name="jd",
        base_url="https://campus.jd.com",
        category_url="https://campus.jd.com/home#/jobs",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=50,
        description="京东校招",
    ),
    "mihoyo": SiteConfig(
        name="mihoyo",
        base_url="https://jobs.mihoyo.com",
        category_url="https://jobs.mihoyo.com/#/campus/position",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=50,
        description="米哈游校招",
    ),
    "zte": SiteConfig(
        name="zte",
        base_url="https://app.mokahr.com",
        category_url="https://app.mokahr.com/campus-recruitment/zte/46903#/jobs",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=50,
        description="中兴校招（MokaHR）",
    ),
    "alibaba": SiteConfig(
        name="alibaba",
        base_url="https://talent.alibaba.com",
        category_url="https://talent.alibaba.com/campus",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=50,
        description="阿里巴巴校招",
    ),
    "baidu": SiteConfig(
        name="baidu",
        base_url="https://talent.baidu.com",
        category_url="https://talent.baidu.com/jobs/list",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=50,
        description="百度校招",
    ),
    "meituan": SiteConfig(
        name="meituan",
        base_url="https://campus.meituan.com",
        category_url="https://campus.meituan.com/jobs",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=50,
        description="美团校招",
    ),
    "xiaomi": SiteConfig(
        name="xiaomi",
        base_url="https://hr.xiaomi.com",
        category_url="https://hr.xiaomi.com/campus",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=50,
        description="小米校招",
    ),
}


def get_site_config(name: str) -> Optional[SiteConfig]:
    """获取站点配置。"""
    return _SITES.get(name.lower())


def list_sites() -> List[str]:
    """列出所有支持的站点。"""
    return list(_SITES.keys())


def register_site(config: SiteConfig) -> None:
    """注册自定义站点配置。

    只需提供 name, base_url, category_url，岗位发现使用通用策略。
    示例：
        register_site(SiteConfig(
            name="mycompany",
            base_url="https://jobs.mycompany.com",
            category_url="https://jobs.mycompany.com/campus",
        ))
    """
    _SITES[config.name.lower()] = config
