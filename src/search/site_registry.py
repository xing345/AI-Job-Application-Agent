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
    # ============================================================
    # 已有站点
    # ============================================================
    "bytedance": SiteConfig(
        name="bytedance",
        base_url="https://jobs.bytedance.com",
        category_url="https://jobs.bytedance.com/campus/position",
        max_applications_per_cycle=3,
        cycle_days=30,
        job_card_selector="a[href*='/campus/position/'][href*='/detail']",
        pagination_type="pagination",
        max_pages=800,
        description="字节跳动校招",
    ),
    "bilibili": SiteConfig(
        name="bilibili",
        base_url="https://jobs.bilibili.com",
        category_url="https://jobs.bilibili.com/campus/positions",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="哔哩哔哩校招",
    ),
    "tencent": SiteConfig(
        name="tencent",
        base_url="https://join.qq.com",
        category_url="https://join.qq.com/post.html",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="api",
        max_pages=100,
        description="腾讯校招",
    ),
    "jd": SiteConfig(
        name="jd",
        base_url="https://campus.jd.com",
        category_url="https://campus.jd.com/home#/jobs",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="京东校招",
    ),
    "mihoyo": SiteConfig(
        name="mihoyo",
        base_url="https://jobs.mihoyo.com",
        category_url="https://jobs.mihoyo.com/#/campus/position",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="米哈游校招",
    ),
    "zte": SiteConfig(
        name="zte",
        base_url="https://app.mokahr.com",
        category_url="https://app.mokahr.com/campus-recruitment/zte/46903#/jobs",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="中兴校招（MokaHR）",
    ),
    "alibaba": SiteConfig(
        name="alibaba",
        base_url="https://campus-talent.alibaba.com",
        category_url="https://campus-talent.alibaba.com/campus/index",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="阿里巴巴校招",
    ),
    "baidu": SiteConfig(
        name="baidu",
        base_url="https://talent.baidu.com",
        category_url="https://talent.baidu.com/jobs/list",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="百度校招",
    ),
    "meituan": SiteConfig(
        name="meituan",
        base_url="https://campus.meituan.com",
        category_url="https://campus.meituan.com/jobs",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="美团校招",
    ),

    # ============================================================
    # 飞书招聘平台（feishu.cn / mioffice.cn）
    # ============================================================
    "xiaomi": SiteConfig(
        name="xiaomi",
        base_url="https://xiaomi.jobs.f.mioffice.cn",
        category_url="https://xiaomi.jobs.f.mioffice.cn/campus/position",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="小米校招（飞书招聘）",
    ),
    "zhipu": SiteConfig(
        name="zhipu",
        base_url="https://zhipu-ai.jobs.feishu.cn",
        category_url="https://zhipu-ai.jobs.feishu.cn/zhipucampus/position",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="智谱AI校招（飞书招聘）",
    ),
    "modelbest": SiteConfig(
        name="modelbest",
        base_url="https://modelbest.jobs.feishu.cn",
        category_url="https://modelbest.jobs.feishu.cn/campus/position",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="面壁智能校招（飞书招聘）",
    ),
    "minimax": SiteConfig(
        name="minimax",
        base_url="https://vrfi1sk8a0.jobs.feishu.cn",
        category_url="https://vrfi1sk8a0.jobs.feishu.cn/referral/campus/position",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="MiniMax校招（飞书招聘）",
    ),
    "qianxun": SiteConfig(
        name="qianxun",
        base_url="https://nwd4iy9rd2s.jobs.feishu.cn",
        category_url="https://nwd4iy9rd2s.jobs.feishu.cn/campusofSpiritAI/position",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="千寻智能校招（飞书招聘）",
    ),

    # ============================================================
    # Moka 招聘平台（mokahr.com）
    # ============================================================
    "shopee": SiteConfig(
        name="shopee",
        base_url="https://app.mokahr.com",
        category_url="https://app.mokahr.com/su/sungwl",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="Shopee虾皮校招（Moka）",
    ),
    "stepfun": SiteConfig(
        name="stepfun",
        base_url="https://app.mokahr.com",
        category_url="https://app.mokahr.com/campus-recruitment/step/94905",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="阶跃星辰校招（Moka）",
    ),
    "moonshot": SiteConfig(
        name="moonshot",
        base_url="https://app.mokahr.com",
        category_url="https://app.mokahr.com/campus-recruitment/moonshot/148507",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="月之暗面校招（Moka）",
    ),
    "shanshu": SiteConfig(
        name="shanshu",
        base_url="https://join.shanshu.ai",
        category_url="https://join.shanshu.ai/m/campus-recruitment/shanshu/57987",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="杉数科技校招（Moka）",
    ),
    "jingwei": SiteConfig(
        name="jingwei",
        base_url="https://app.mokahr.com",
        category_url="https://app.mokahr.com/campus-recruitment/jingweihengrun/172235",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="经纬恒润校招（Moka）",
    ),
    "kuaicang": SiteConfig(
        name="kuaicang",
        base_url="https://app.mokahr.com",
        category_url="https://app.mokahr.com/campus_apply/flashhold/40527",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="快仓智能校招（Moka）",
    ),

    # ============================================================
    # 智联 zhiye 平台（zhiye.com）
    # ============================================================
    "iflytek": SiteConfig(
        name="iflytek",
        base_url="https://iflytek.zhiye.com",
        category_url="https://iflytek.zhiye.com/jobs",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=60,
        description="科大讯飞校招（智联zhiye）",
    ),
    "aispeech": SiteConfig(
        name="aispeech",
        base_url="https://aispeech.zhiye.com",
        category_url="https://aispeech.zhiye.com/campus/jobs",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=60,
        description="云知声校招（智联zhiye）",
    ),
    "healthai": SiteConfig(
        name="healthai",
        base_url="https://healthai.zhiye.com",
        category_url="https://healthai.zhiye.com/",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=60,
        description="北京医疗健康大模型校招（智联zhiye）",
    ),

    # ============================================================
    # 大厂自有平台（续）
    # ============================================================
    "kuaishou": SiteConfig(
        name="kuaishou",
        base_url="https://campus.kuaishou.cn",
        category_url="https://campus.kuaishou.cn",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="快手校招",
    ),
    "xiaohongshu": SiteConfig(
        name="xiaohongshu",
        base_url="https://job.xiaohongshu.com",
        category_url="https://job.xiaohongshu.com",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="小红书校招",
    ),
    "sensetime": SiteConfig(
        name="sensetime",
        base_url="https://hr-jobs.sensetime.com",
        category_url="https://hr-jobs.sensetime.com",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="商汤科技校招",
    ),
    "ctrip": SiteConfig(
        name="ctrip",
        base_url="https://careers.ctrip.com",
        category_url="https://careers.ctrip.com",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="携程校招",
    ),
    "netease": SiteConfig(
        name="netease",
        base_url="http://campus.163.com",
        category_url="http://campus.163.com",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=80,
        description="网易有道校招",
    ),

    # ============================================================
    # 中小厂自有平台
    # ============================================================
    "baichuan": SiteConfig(
        name="baichuan",
        base_url="https://careers.baichuan-inc.com",
        category_url="https://careers.baichuan-inc.com/origin-program",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=30,
        description="百川智能校招",
    ),
    "richinfo": SiteConfig(
        name="richinfo",
        base_url="https://www.richinfo.cn",
        category_url="https://www.richinfo.cn/jobs/campus/59",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="pagination",
        max_pages=30,
        description="彩讯股份校招",
    ),
    "indeed": SiteConfig(
        name="indeed",
        base_url="https://www.ai-indeed.com",
        category_url="https://www.ai-indeed.com/apply",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=30,
        description="实在智能校招",
    ),
    "ztccloud": SiteConfig(
        name="ztccloud",
        base_url="http://www.ztccloud.com.cn",
        category_url="http://www.ztccloud.com.cn/careers.html",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="pagination",
        max_pages=30,
        description="中兴新云校招",
    ),
    "kunlun": SiteConfig(
        name="kunlun",
        base_url="https://www.nowcoder.com",
        category_url="https://www.nowcoder.com/jobs/jump/WlDpjz",
        max_applications_per_cycle=3,
        cycle_days=30,
        pagination_type="scroll",
        max_pages=30,
        description="昆仑万维校招（牛客跳转）",
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
