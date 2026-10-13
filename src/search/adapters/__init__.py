"""站点适配器包。

每个招聘网站一个独立适配器，封装导航、分页、岗位卡片定位逻辑。
"""
from src.search.adapters.base import (
    SiteAdapter,
    get_adapter,
    list_adapters,
    normalize_url,
    register_adapter,
)

# 导入各站点适配器以触发注册（按平台分组）

# 已有适配器
from src.search.adapters import bytedance  # noqa: F401

# === 飞书招聘平台（feishu.cn / mioffice.cn）===
from src.search.adapters import xiaomi  # noqa: F401
from src.search.adapters import zhipu  # noqa: F401
from src.search.adapters import modelbest  # noqa: F401
from src.search.adapters import minimax  # noqa: F401
from src.search.adapters import qianxun  # noqa: F401

# === Moka 招聘平台（mokahr.com）===
from src.search.adapters import shopee  # noqa: F401
from src.search.adapters import stepfun  # noqa: F401
from src.search.adapters import moonshot  # noqa: F401
from src.search.adapters import shanshu  # noqa: F401
from src.search.adapters import jingwei  # noqa: F401
from src.search.adapters import kuaicang  # noqa: F401
from src.search.adapters import zte  # noqa: F401

# === 智联 zhiye 平台（zhiye.com）===
from src.search.adapters import iflytek  # noqa: F401
from src.search.adapters import aispeech  # noqa: F401
from src.search.adapters import healthai  # noqa: F401

# === 大厂自有平台 ===
from src.search.adapters import tencent  # noqa: F401
from src.search.adapters import baidu  # noqa: F401
from src.search.adapters import meituan  # noqa: F401
from src.search.adapters import jd  # noqa: F401
from src.search.adapters import bilibili  # noqa: F401
from src.search.adapters import mihoyo  # noqa: F401
from src.search.adapters import alibaba  # noqa: F401
from src.search.adapters import kuaishou  # noqa: F401
from src.search.adapters import xiaohongshu  # noqa: F401
from src.search.adapters import sensetime  # noqa: F401
from src.search.adapters import ctrip  # noqa: F401
from src.search.adapters import netease  # noqa: F401

# === 中小厂自有平台 ===
from src.search.adapters import baichuan  # noqa: F401
from src.search.adapters import richinfo  # noqa: F401
from src.search.adapters import indeed  # noqa: F401
from src.search.adapters import ztccloud  # noqa: F401
from src.search.adapters import kunlun  # noqa: F401

__all__ = [
    "SiteAdapter",
    "get_adapter",
    "list_adapters",
    "normalize_url",
    "register_adapter",
]
