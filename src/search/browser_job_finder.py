"""
BrowserJobFinder - 基于真实浏览器的职位发现器

提供两条找岗通道：
A. 门户通道 discover()：Tavily 宽泛发现招聘聚合页 -> 浏览器打开 -> DOM 抽取职位链接
B. 公司官网通道 discover_company_careers()：
   1. 发现目标公司（Tavily 发现或用户指定公司名单，排除聚合招聘平台）
   2. 进入公司官网，确定性地定位「招聘/加入我们/Careers/Jobs」页面
      （首页锚点评分 + 常见路径探测 + jobs./career./hr. 子域探测）
   3. 在公司招聘站内按类别导航 + 列表遍历找岗（不使用站内关键词搜索）
   4. 遇登录墙 / 验证码 / 无法操作时停下汇报，等人处理后再从断点继续

输出统一为职位字典列表：
    {url, title, company, location, description, source, channel}
供 SearchPipeline 的后续「抓 JD -> LLM 匹配 -> 排序」阶段消费。
"""

import asyncio
import re
import sys
import os
from typing import Dict, List, Optional
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode, quote

from loguru import logger
from tavily import TavilyClient

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.models.instruction_schemas import TargetInstructionSchema
from src.search.query_expander import (
    query_terms,
    role_tokens,
    role_direction_words,
)
from src.search.hitl import BlockHandler
from src.search.nav_advisor import NavAdvisor, NavAdvisorConfig

# 招聘/职位详情页的 URL 特征（国内招聘平台 + 公司自有招聘站）
JOB_URL_HINTS = [
    # 国内平台
    "zhaopin.com", "bosszhipin.com", "zhipin.com", "liepin.com", "lagou.com",
    "51job.com", "jobs.51job", "zhipin", "/job_", "/jobs/", "/job/", "/zp/",
    "jobdetail", "position_detail", "/position/", "/a/",
    # 公司自有招聘站（国内外通用路径，不绑定具体厂商）
    "/career", "/careers", "/vacanc", "/recruit", "/join", "/hiring",
]

# 非职位页面（新闻、博客、帮助等），命中则跳过
NON_JOB_HINTS = [
    "blog", "news", "/about", "privacy", "terms", "legal", "contact",
    "support", "help", "press", "investor", "register", "download",
]

# 真正的验证墙特征（只保留硬信号；"请登录/登录后查看"常出现在正常页面页眉，会误判）
CAPTCHA_HINTS = [
    "验证码", "安全验证", "滑动验证", "人机验证", "网络不给力", "访问验证",
    "行为验证", "captcha", "are you a robot", "security check",
    "verify you are human", "access denied", "unusual traffic",
]

# 「强」验证墙特征：命中即可判定被挡，不需要再看 DOM 控件。
# 其余弱特征（"验证码"三个字）必须配合「页面里真的有验证控件」才判定——
# 否则 Boss / 智联这类正常页面里的「短信验证码登录」入口会把好页面判成验证墙。
STRONG_CAPTCHA_HINTS = [
    "请完成安全验证", "滑动验证", "拖动滑块", "行为验证", "人机验证",
    "访问验证", "安全验证失败", "网络不给力，请稍后重试",
    "captcha", "are you a robot", "unusual traffic", "access denied",
    "verify you are human", "security check",
]

# 浏览器内执行：探测「这道墙是不是真的」的 DOM 证据（只看存在的控件，不看文案）
_BLOCK_PROBE_SELECTORS = {
    "password_inputs": "input[type='password']",
    "captcha_inputs": ("input[placeholder*='验证码'], input[name*='captcha' i], "
                       "input[id*='captcha' i], input[maxlength='4'][autocomplete='off']"),
    "captcha_boxes": ("[class*='captcha' i], [id*='captcha' i], [class*='slider' i], "
                      "[class*='verify' i], iframe[src*='captcha' i]"),
    "login_forms": "form[action*='login' i], form[class*='login' i], [class*='login-modal' i]",
}

# 聚合门户的「站内搜索页」URL 模板。
# 这里是本项目对 AGENTS.md「不要依赖关键词搜索」的一处刻意例外：
#   公司官网（jobs.bytedance.com / 校招官网…）的职位索引就是它的类别导航，
#   用类别+翻页遍历是对的；
#   但聚合门户（Boss/猎聘/前程无忧/智联）整站产品就是「搜索框」，
#   打开它们的裸列表页只能拿到全网随机岗位（日志里 Boss 那一站抓到的全是
#   站点导航链接），方向过滤之后必然为 0。
# 因此只对 kind=portal 的站做「改写入口为站内搜索 URL」，公司官网通道行为不变。
PORTAL_SEARCH_URLS = {
    "zhipin.com": "https://www.zhipin.com/web/geek/job?query={q}",
    "liepin.com": "https://www.liepin.com/zhaopin/?key={q}",
    "51job.com": "https://we.51job.com/pc/search?keyword={q}",
    "zhaopin.com": "https://sou.zhaopin.com/?kw={q}",
    "lagou.com": "https://www.lagou.com/wn/jobs?kd={q}",
}

# 候选导航里绝不允许出现（也绝不允许 LLM 选中）的文本：投递/申请/登录类
# 红线1：绝不自动点击最终「提交/投递申请」按钮
DANGEROUS_NAV_TEXT = (
    "投递", "申请", "提交", "立即沟通", "立即联系", "发送简历", "登录", "注册",
    "apply", "submit", "send resume", "sign in", "log in", "register",
)

# 招聘聚合平台/内容站：公司通道发现公司时排除这些域名
AGGREGATOR_DOMAINS = [
    "liepin.com", "zhaopin.com", "bosszhipin.com", "zhipin.com", "51job.com",
    "lagou.com", "kanzhun.com", "maimai.cn", "zhihu.com",
    "baidu.com", "bing.com", "google.", "csdn.net", "jianshu.com", "sspai.com",
    "weibo.com", "bilibili.com", "tianyancha.com", "qcc.com", "qixin.com",
    "163.com", "sohu.com", "sina.com", "qq.com", "mp.weixin", "douyin.com",
    "github.com", "gitee.com", "baike", "wiki", "toutiao.com",
]

# 国内招聘平台（通道1/门户通道的优先级排序用）
CN_JOB_PLATFORMS = [
    "bosszhipin.com", "zhipin.com", "lagou.com", "liepin.com",
    "zhaopin.com", "51job.com",
]

# 聚合门户：列表是全网岗位，方向不相关就真的不要（不做「无命中就兜底全留」）
STRICT_RELEVANCE_DOMAINS = (
    "zhipin.com", "liepin.com", "51job.com", "zhaopin.com", "lagou.com",
)

# 应用商店/百科/社媒等非公司官网噪声域名
JUNK_DOMAINS = [
    "play.google.com", "apps.apple.com", "itunes.apple.com", "chrome.google.com",
    "appgallery", "samsungapps.com", "apk", "wikipedia.org", "wikimedia.org",
    "web.archive.org", "youtube.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "taobao.com", "jd.com", "amazon.",
    "91wllm", "chaojijianli", "cake.me", "nowcoder.com", "gaoxiaojob",
    "yuanjisong", "reddit.com", "heywhale", "jobui", "segmentfault",
    "juejin.cn", "cnblogs", "offcn", "fenbi", "yingjiesheng",
    "xiaohongshu.com", "douban.com", "tieba.baidu", "cuiqingcai",
    "niuqizp", "niuzhi",
]
# 登录/账号类主机特征（不是招聘页）
LOGIN_HOST_HINTS = ["passport", "login.", "signin", "account.", "id.", "auth."]
# 职位详情链接特征（区别于导航/介绍页）
JOB_DETAIL_RE = re.compile(
    r"(id=|jobid|job_id|positionid|position_id|postid|post_id|jobunionid|jobadid|"
    r"/position|/jobdetail|/job_detail|/job/|/jobs/|/detail/|/vacanc|/\d{5,}\.html)",
    re.I,
)

# 「这个 URL 是职位详情页」的强特征（用于卡片点击结果判定，避免把筛选条件当职位）
DETAIL_URL_RE = re.compile(
    r"(jobadid=|postid=|post_id=|positionid=|jobunionid=|jobid=|"
    r"#/job/|#/details\?|#/position/|/job_detail/|/jobdetail/|/positions?/[^/?#]+$|"
    r"/positions?/\d+|/detail\?|/job/\d+|\.shtml$|/vacanc)",
    re.I,
)

# 去重时忽略的跟踪参数（同一岗位不同来源会带不同参数）
_TRACKING_QUERY_KEYS = {
    "spread", "refcode", "srccode", "preactionid", "actionid", "pgref", "req",
    "s", "t", "from", "source", "callbackurl", "recommendid", "traceid", "clickid",
}

# 职位详情页 URL 模板（全部经 tools/verify_detail_urls.py 实测能渲染出 JD 正文）
# key = 站点主机特征；value = {seg: 模板} 或 {None: 模板}
DETAIL_URL_TEMPLATES = {
    "bytedance.com": {
        "campus": "https://jobs.bytedance.com/campus/position/{id}/detail",
        None: "https://jobs.bytedance.com/experienced/position/{id}/detail",
    },
    # 注意：B 站详情页是 /campus/positions/{id}，多写 /detail 会被重定向回首页
    "bilibili.com": {
        "campus": "https://jobs.bilibili.com/campus/positions/{id}",
        None: "https://jobs.bilibili.com/society/positions/{id}",
    },
    "meituan.com": {None: "https://zhaopin.meituan.com/web/position/detail?jobUnionId={id}"},
    "mihoyo.com": {
        "campus": "https://jobs.mihoyo.com/#/campus/position/{id}",
        None: "https://jobs.mihoyo.com/#/society/position/{id}",
    },
    "join.qq.com": {None: "https://join.qq.com/post_detail.html?postid={id}"},
    "campus.jd.com": {None: "https://campus.jd.com/#/details?id={id}"},
    "mokahr.com": {None: "{base}#/job/{id}"},
    "zhiye.com": {None: "{scheme}://{host}/{seg}/detail?jobAdId={id}"},
    "zhipin.com": {None: "https://www.zhipin.com/job_detail/{id}.html"},
    "liepin.com": {None: "https://www.liepin.com/job/{id}.shtml"},
    "feishu.cn": {None: "{scheme}://{host}/index/position/{id}/detail"},
}

# 部分站点的详情页 URL 用的是「非业务主键」字段（已实测：北森数字 JobAdId 打不开，
# 必须用 guid；腾讯必须用 postId 而不是自增 id）
DETAIL_ID_KEY_OVERRIDE = {
    "zhiye.com": ("id",),
    "join.qq.com": ("postid", "id"),
    "mokahr.com": ("id",),
}

# 分类导航里「看起来是职位名」的词：类别链接不该命中这些
_JOB_TITLE_WORDS = (
    "工程师", "开发工程师", "设计师", "产品经理", "专员", "实习生", "架构师",
    "分析师", "研究员", "主管", "总监", "顾问", "经理", "助理", "培训生", "管培生",
)

# 站内「不是职位导航」的子域前缀（百科/帮助/登录…）
_NON_NAV_HOST_PREFIXES = (
    "baike.", "wiki.", "help.", "support.", "passport.", "login.", "account.",
    "about.", "news.", "blog.", "www.baike.",
)

# 公司官网上「招聘入口」的文案/路径特征
CAREER_TEXT_HINTS = [
    "招聘", "加入我们", "人才招聘", "社会招聘", "校园招聘", "招贤纳士",
    "人力资源", "careers", "career", "jobs", "join us", "join-us", "joinus",
    "work with us", "hiring", "talent", "vacancies", "employment", "people",
]
CAREER_URL_HINTS = [
    "/career", "/jobs", "/join", "/recruit", "/zhaopin", "/hr", "/talent",
    "/hiring", "/vacanc", "/campus", "/xiaozhao", "/social",
]
# 招聘页常见直接路径
CAREER_PROBE_PATHS = [
    "/careers", "/career", "/jobs", "/joinus", "/join-us", "/join",
    "/about/careers", "/about/jobs", "/zh/careers", "/cn/careers",
    "/recruit", "/social", "/zhaopin",
]
# 招聘页常见子域前缀
CAREER_SUBDOMAIN_PREFIXES = [
    "jobs.", "job.", "career.", "careers.", "hr.", "campus.", "hire.",
    "xiaozhao.", "zhaopin.", "talent.",
]

# 官网「职位类别/方向」导航：用户要找某个方向时，先进对应类别再逐页遍历列表，
# 而不是在站内框里输关键词搜。文本命中即归类。
# key 与 query_expander.infer_direction() 的 category/label 对齐。
CATEGORY_NAV_HINTS = {
    # 只放「类别/栏目」词；「工程师/开发」是职位名词，放进来会把职位详情页当类别导航
    "技术类": [
        "技术类", "技术", "研发", "技术研发", "技术中心", "程序",
        "engineering", "r&d", "software", "tech",
    ],
    "产品类": ["产品类", "产品", "product", "pm"],
    "设计类": ["设计类", "设计", "ui", "ux", "visual", "designer", "design"],
    "运营类": ["运营类", "运营", "operations", "operation"],
    "市场/销售类": ["市场", "销售", "marketing", "sales", "商务", "bd"],
    "职能类": ["职能", "职能类", "人力", "hr", "财务", "行政", "finance", "行政类"],
}

# 翻页/加载更多按钮的文本特征
NEXT_PAGE_TEXTS = [
    "下一页", "next", "next page", "›", "»", ">", "more", "加载更多", "查看更多",
]

# 职位名通用词与分词逻辑统一由 query_expander 提供（ROLE_GENERIC_TOKENS 已从该模块导入）

# 浏览器内执行：抽取全部带 href 的锚点（浏览器自动把相对路径解析为绝对 URL）
_ANCHOR_JS = """els => els.map(e => ({
    text: (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim(),
    href: e.href || ''
})).filter(a => a.href && a.text)"""

# 列表页上的类别 Tab / 筛选按钮（不一定是 <a href>）
_CATEGORY_WIDGET_JS = """() => {
  const nodes = Array.from(document.querySelectorAll(
    'a, button, [role="tab"], [role="menuitem"], [role="option"], li'
  ));
  const seen = new Set();
  const out = [];
  for (const el of nodes) {
    const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    if (!text || text.length > 16 || text.length < 2) continue;
    if (seen.has(text)) continue;
    seen.add(text);
    out.push({text, href: el.href || ''});
    if (out.length >= 80) break;
  }
  return out;
}"""

# 浏览器内执行：从元素属性里挖职位链接（SPA 卡片常用 data-href / onclick 跳转）
_ATTR_LINK_JS = r"""() => {
  const out = [];
  const seen = new Set();
  const ATTRS = ["data-href","data-url","data-link","data-job-url","data-detail-url",
                 "data-jump-url","href","to","onclick"];
  const els = document.querySelectorAll("*");
  for (let i = 0; i < els.length && i < 4000; i++) {
    const el = els[i];
    let found = "";
    for (const a of ATTRS) {
      const v = el.getAttribute && el.getAttribute(a);
      if (!v || typeof v !== "string") continue;
      const m = v.match(/https?:\/\/[^\s"'<>)]+|\/[A-Za-z0-9_\-\/.]*\d[A-Za-z0-9_\-\/.?=&%#]*/);
      if (m && /job|position|post|detail|vacanc|recruit|zhiwei/i.test(m[0])) { found = m[0]; break; }
    }
    if (!found) continue;
    let abs = "";
    try { abs = new URL(found, location.href).href; } catch (e) { continue; }
    if (!/^https?:/i.test(abs) || seen.has(abs)) continue;
    seen.add(abs);
    const txt = (el.innerText || "").trim().split("\n")[0].slice(0, 60);
    out.push({text: txt, href: abs, weak: !txt});
    if (out.length >= 80) break;
  }
  return out;
}"""

# 浏览器内执行：扫描「职位卡片」节点 —— 国内校招站（腾讯/B站/米哈游/Moka/北森/京东…）
# 的职位卡片普遍不是 <a href>，而是 div + 点击事件；只数 a[href] 必然得到 0 个职位。
# 这里按「节点自身首行文本像一个职位名 + 是最内层承载节点」定位卡片，
# 给每个卡片打上 data-dsh-card 标记，供后续用选择器点击取真实详情页 URL。
CARD_SCAN_JS = r"""() => {
  const OCC = ["工程师","开发","研发","算法","产品","运营","设计师","设计","分析师","研究员",
    "经理","专员","实习生","实习","架构师","专家","测试","销售","市场","人力","财务","策划",
    "编辑","顾问","主管","总监","助理","培训生","管培生","技术","安全","运维","数据","游戏",
    "engineer","developer","manager","intern","scientist","analyst","designer","specialist",
    "architect","consultant","trainee"];
  const BAD = ["投递","申请","立即","提交","登录","注册","简历","收藏","分享","更多","全部",
    "清除","筛选","搜索","首页","返回","下一","上一","查看职位","了解","展开","收起","登录/注册",
    "apply","submit","sign in","log in","more","next","previous"];
  const out = [];
  const seen = new Set();
  // 每轮重扫前清掉上一轮的标记（点击后 DOM 复用，否则第二轮会一个都扫不到）
  document.querySelectorAll("[data-dsh-card]").forEach(e => e.removeAttribute("data-dsh-card"));
  const nodes = document.querySelectorAll(
    "a,button,li,div,span,h1,h2,h3,h4,h5,p,td,article,section");
  let idx = 0;
  for (const el of nodes) {
    if (idx >= 300) break;
    const raw = (el.innerText || "").trim();
    if (!raw || raw.length > 200) continue;
    const first = raw.split("\n")[0].trim();
    if (first.length < 4 || first.length > 40) continue;
    const low = first.toLowerCase();
    if (BAD.some(b => low.includes(b))) continue;
    if (!OCC.some(o => low.includes(o.toLowerCase()))) continue;
    // 只取最内层承载节点：子孙里若还有同样首行文本的节点，说明自己不是最小节点
    let deeper = false;
    const kids = el.querySelectorAll("*");
    for (let i = 0; i < kids.length && i < 60; i++) {
      const kt = (kids[i].innerText || "").trim();
      if (kt && kt.split("\n")[0].trim() === first) { deeper = true; break; }
    }
    if (deeper) continue;
    let href = "";
    try {
      const a = (el.tagName === "A" && el.getAttribute("href")) ? el
        : (el.closest("a[href]") || el.querySelector("a[href]"));
      if (a) {
        const h = a.getAttribute("href") || "";
        if (h && !h.startsWith("javascript:") && !h.startsWith("#") && !h.startsWith("mailto:"))
          href = new URL(h, location.href).href;
      }
    } catch (e) { href = ""; }
    const key = first + "||" + href;
    if (seen.has(key)) continue;
    seen.add(key);
    let clickable = false;
    try {
      clickable = !!(el.onclick) || getComputedStyle(el).cursor === "pointer"
        || !!el.closest("[onclick]");
    } catch (e) { clickable = false; }
    el.setAttribute("data-dsh-card", String(idx));
    out.push({idx: idx, text: first, tag: el.tagName,
              cls: String(el.className || "").slice(0, 60), href: href,
              clickable: clickable});
    idx++;
  }
  return out;
}"""


class BrowserJobFinder:
    """真实浏览器职位发现器（门户通道 + 公司官网通道）"""

    def __init__(
        self,
        tavily_api_key: str,
        headless: bool = True,
        timeout_ms: int = 30000,
        max_sites: int = 6,
        max_jobs_per_site: int = 25,
        max_companies: int = 5,
        interactive: bool = True,
        page_settle_ms: int = 2000,
        max_list_pages: int = 4,
        max_card_clicks: int = 16,
        block_handler: "BlockHandler" = None,
        max_api_objects: int = 200,
        portal_keyword_search: bool = False,
        nav_stay_min_job_links: int = 5,
        user_data_dir: str = None,
        persist_login: bool = True,
        nav_advisor: "NavAdvisor" = None,
    ):
        """
        Args:
            tavily_api_key: Tavily API Key（仅用于「发现有哪些公司/门户」，
                            不用于岗位关键词搜索；找岗本身走类别+列表遍历）
            headless: 是否无头浏览器（交互观察/人工过验证码时建议 False）
            timeout_ms: 页面操作超时（毫秒）
            max_sites: 门户通道单次最多打开几个聚合招聘站
            max_jobs_per_site: 每个站点最多抽取多少个职位链接（成本上限，可配置）
            max_companies: 公司通道单次最多进入几家公司招聘官网
            interactive: 交互模式（遇到登录墙/验证码时停下汇报给用户处理）
            page_settle_ms: 页面渲染等待时间（毫秒）
            max_list_pages: 每个类别下列表最多翻几页（逐页遍历，控制成本）
            max_card_clicks: 单站最多点击几张职位卡片（SPA 卡片不是 <a> 时取详情 URL 用）
            block_handler: 注入的 HITL 阻断处理器；为空则按 interactive/headless 自建
            max_api_objects: 单站最多从列表 XHR 里认多少条职位（字节/腾讯这类
                             1210 个岗位的列表靠接口翻页，40 条的上限会把它们砍到个位数）
            portal_keyword_search: 聚合门户是否改用「站内搜索 URL」（见 PORTAL_SEARCH_URLS）
            nav_stay_min_job_links: 当前页已渲染多少个职位详情链接时就认定「已经在列表页，
                                    不许再做类别导航跳转」（DOM 证据优先于 URL 形状）
            user_data_dir: 浏览器用户目录；给了就复用登录态（Boss 登录一次可跨轮使用）
            persist_login: 是否使用持久化用户目录（默认 True；失败自动回退匿名上下文）
            nav_advisor: 受约束的 LLM 导航裁决器；为空则本次构造按配置决定是否创建
        """
        self.api_key = tavily_api_key or ""
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.max_sites = max_sites
        self.max_jobs_per_site = max(1, int(max_jobs_per_site))
        self.max_companies = max_companies
        self.interactive = interactive
        self.page_settle_ms = page_settle_ms
        self.max_list_pages = max(1, int(max_list_pages))
        # 卡片点击上限：SPA（腾讯/B站/米哈游/Moka/北森…）靠点击拿详情 URL
        self.max_card_clicks = max(1, int(max_card_clicks))
        # 接口职位上限：列表 XHR 里的职位对象总数（按配置放开）
        self.max_api_objects = max(10, int(max_api_objects))
        self.portal_keyword_search = bool(portal_keyword_search)
        self.nav_stay_min_job_links = max(1, int(nav_stay_min_job_links))
        # 相对路径按项目根解析：否则从别的目录启动时登录态会落到别处（等于没复用）
        self.user_data_dir = self._abs_project_path(user_data_dir)
        self.persist_login = bool(persist_login)
        # 统一的「停下汇报 -> 用户处理 -> 回车继续」处理器
        self.block_handler = block_handler or BlockHandler(
            interactive=interactive, headless=headless
        )
        # 只做「选择/否决」，不做动作的 LLM 导航裁决器（可配置关闭）
        self.nav_advisor = nav_advisor

        self._client: Optional[TavilyClient] = None
        self._playwright = None
        self._browser = None
        self._context = None

    # ------------------------------------------------------------------ #
    @staticmethod
    def _abs_project_path(path: Optional[str]) -> Optional[str]:
        """把配置里的相对路径按项目根解析（浏览器用户目录必须固定位置）"""
        if not path:
            return None
        return path if os.path.isabs(path) else os.path.join(project_root, path)

    @staticmethod
    def build_nav_advisor(cfg: Dict = None,
                          llm_cfg: Dict = None) -> Optional[NavAdvisor]:
        """
        按 config.search.nav_advisor + config.llm 构造导航裁决器。

        cfg 为空 / enabled=false 时返回 None（纯确定性规则）。
        """
        cfg = cfg or {}
        if not cfg.get("enabled", False):
            return None
        llm_cfg = llm_cfg or {}
        return NavAdvisor(NavAdvisorConfig(
            enabled=True,
            api_key=llm_cfg.get("api_key") or None,
            base_url=llm_cfg.get("base_url") or None,
            model=llm_cfg.get("model") or None,
            max_calls_per_search=cfg.get("max_calls_per_search", 4),
            timeout_s=cfg.get("timeout_s", 25),
            max_candidates=cfg.get("max_candidates", 6),
        ))


    # ================================================================== #
    # 通道 A：招聘聚合门户
    # ================================================================== #
    async def discover(self, target_info: TargetInstructionSchema) -> List[Dict]:
        """
        门户通道：根据目标岗位指令，用真实浏览器从招聘聚合站发现职位链接。

        Returns:
            职位字典列表 [{url, title, company, location, description, source}]
        """
        candidates = await self._discover_portal_candidates(target_info)
        if not candidates:
            logger.warning("门户通道：Tavily 未发现任何候选招聘门户")
            return []

        logger.info(f"门户通道：发现 {len(candidates)} 个候选门户，开始用浏览器逐个打开")
        jobs: List[Dict] = []
        seen_urls = set()
        total_cap = self.max_sites * self.max_jobs_per_site

        try:
            await self._start_browser()
            for portal in candidates[: self.max_sites]:
                site_jobs = await self._extract_jobs_from_portal(portal, target_info)
                for job in site_jobs:
                    job["channel"] = "job_portal"
                    if job["url"] in seen_urls:
                        continue
                    seen_urls.add(job["url"])
                    jobs.append(job)
                if len(jobs) >= total_cap:
                    logger.info(f"已达门户通道上限 {total_cap}，停止打开更多门户")
                    break
                await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"门户通道过程异常: {e}")
        finally:
            await self._stop_browser()

        logger.info(f"门户通道完成，共抽取 {len(jobs)} 个职位链接")
        return jobs

    # ================================================================== #
    # 固定站点通道：内置 Boss直聘/猎聘/前程无忧 + 用户自定义文件
    # （不再用 Tavily 现搜「有哪些招聘网站」）
    # ================================================================== #
    async def discover_fixed_sites(
        self,
        target_info: TargetInstructionSchema,
        sites: List[Dict],
    ) -> List[Dict]:
        """
        从固定站点列表直接找岗：逐个打开站点入口 -> 校招类别 -> 列表逐页遍历。

        Args:
            sites: [{"name","url","kind"}]，来自 site_registry.resolve_sites()
        """
        if not sites:
            logger.warning("固定站点列表为空，跳过")
            return []

        logger.info(f"固定站点找岗：{len(sites)} 个站 —— "
                    f"{'、'.join(s.get('name', s['url']) for s in sites)}")
        jobs: List[Dict] = []
        seen_urls = set()

        try:
            await self._start_browser()
            for site in sites:
                portal = {
                    "url": site["url"],
                    "title": site.get("name", ""),
                    # kind 传下去：portal=聚合门户（改用站内搜索 URL），
                    # company_site=公司官网/公司招聘专页（按类别+列表遍历）
                    "kind": site.get("kind", "portal"),
                }
                try:
                    site_jobs = await self._extract_jobs_from_portal(portal, target_info)
                except Exception as e:
                    logger.warning(f"固定站点 {site.get('name')}({site['url']}) 失败: {e}")
                    continue
                for job in site_jobs:
                    job["channel"] = site.get("kind", "portal")
                    if job["url"] in seen_urls:
                        continue
                    seen_urls.add(job["url"])
                    jobs.append(job)
                await asyncio.sleep(1.0)
        except Exception as e:
            logger.error(f"固定站点通道过程异常: {e}")
        finally:
            await self._stop_browser()

        logger.info(f"固定站点通道完成，共抽取 {len(jobs)} 个职位链接")
        return jobs

    # ================================================================== #
    # 通道 B：公司自有招聘官网
    # ================================================================== #
    async def discover_company_careers(
        self,
        target_info: TargetInstructionSchema,
        known_companies: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        公司官网通道：发现公司 -> 进入官网定位招聘页 -> 站内抽取目标岗位。

        Args:
            target_info: 目标岗位指令
            known_companies: 用户指定的公司名/官网 URL 列表；为空时按岗位自动发现

        Returns:
            职位字典列表
        """
        companies = await self._discover_company_candidates(target_info, known_companies)
        if not companies:
            logger.warning("公司通道：未发现可进入的公司官网")
            return []

        logger.info(f"公司通道：候选公司 {len(companies)} 家，开始进入各自招聘官网")
        jobs: List[Dict] = []
        seen_urls = set()

        try:
            await self._start_browser()
            for company in companies[: self.max_companies]:
                name = company["name"]
                try:
                    career_url = company.get("career_url")
                    if not career_url:
                        career_url = await self._locate_career_page(company["url"])
                    if not career_url:
                        logger.info(f"公司通道：{name} 未找到招聘页，跳过")
                        continue

                    logger.info(f"公司通道：进入 {name} 招聘页 {career_url}")
                    site_jobs = await self._extract_company_jobs(
                        name, career_url, target_info
                    )
                    for job in site_jobs:
                        job["company"] = name
                        job["channel"] = "company_site"
                        if job["url"] in seen_urls:
                            continue
                        seen_urls.add(job["url"])
                        jobs.append(job)
                    logger.info(f"公司通道：{name} 抽取到 {len(site_jobs)} 个职位")
                except Exception as e:
                    logger.warning(f"公司通道：处理 {name} 失败: {e}")
                    continue
                finally:
                    await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"公司通道过程异常: {e}")
        finally:
            await self._stop_browser()

        logger.info(f"公司通道完成，共抽取 {len(jobs)} 个职位链接")
        return jobs

    async def _discover_company_candidates(
        self,
        target_info: TargetInstructionSchema,
        known_companies: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        发现公司候选：优先用户指定名单（名称自动找官网），否则按岗位 Tavily 发现。
        排除招聘聚合平台/应用商店/百科，只保留公司自有域名。
        返回 [{name, url, career_url?}]，可直达招聘页的排在前面。
        """
        candidates: Dict[str, Dict] = {}

        def add_result(url: str, title: str, preferred_name: str = "",
                        trusted: bool = False):
            kind = self._classify_company_result(url, trusted=trusted)
            if not kind or (not trusted and self._is_junk_title(title)):
                return
            host = urlparse(url).netloc.lower().replace("www.", "")
            if not host or host in candidates:
                return
            name = preferred_name or self._clean_company_name(title) or host
            is_direct = kind == "career" or trusted
            candidates[host] = {
                "name": name,
                "url": url if is_direct else self._homepage_of(url),
                "career_url": url if is_direct else None,
                "trusted": trusted,
            }

        if known_companies:
            # 用户指定：公司名 -> 多查询择优（招聘官网优先于首页）；本身是 URL 直接用
            for raw in known_companies:
                raw = (raw or "").strip()
                if not raw:
                    continue
                if raw.startswith("http"):
                    # 用户显式 URL：绕过黑名单，原样保留为可直达招聘页
                    add_result(raw, self._host_of(raw),
                               preferred_name=self._host_of(raw), trusted=True)
                    continue
                resolved = await self._resolve_named_company(raw)
                if resolved:
                    host = urlparse(resolved["url"]).netloc.lower().replace("www.", "")
                    candidates[host] = resolved
        else:
            location = (target_info.location or "").strip()
            # 每个岗位词各出一条查询，扩大同义岗位的公司召回
            queries = [
                f"{term} {location} 招聘 加入我们 官网".strip()
                for term in query_terms(target_info, limit=2)
            ]
            if target_info.keywords:
                queries = [
                    f"{q} {' '.join(str(k) for k in target_info.keywords[:3])}".strip()
                    for q in queries
                ]
            for q in queries:
                for item in await self._tavily_search(
                    q, max_results=10, exclude=AGGREGATOR_DOMAINS + JUNK_DOMAINS
                ):
                    add_result(item.get("url", ""), item.get("title", ""))

        # 用户显式 URL 优先，其次可直达招聘页，最后需要现找入口的官网
        return sorted(
            candidates.values(),
            key=lambda c: (0 if c.get("trusted") else 1,
                           0 if c.get("career_url") else 1),
        )

    async def _resolve_named_company(self, name: str) -> Optional[Dict]:
        """公司名 -> 官网/招聘页：以官网主域为准，优先同域招聘页，否则回退官网首页"""
        homes, careers = [], []
        for q in (f"{name} 招聘官网", f"{name} 官网", f"{name} careers"):
            resp = await self._tavily_search(
                q, max_results=6, exclude=AGGREGATOR_DOMAINS + JUNK_DOMAINS
            )
            for item in resp:
                url, title = item.get("url", ""), item.get("title", "")
                kind = self._classify_company_result(url)
                if not kind or name.lower() not in (title + url).lower():
                    continue
                record = {
                    "name": name,
                    "url": url if kind == "career" else self._homepage_of(url),
                    "career_url": url if kind == "career" else None,
                    "kind": kind, "regdom": self._registrable_domain(url),
                }
                (careers if kind == "career" else homes).append(record)

        if homes:
            home = sorted(homes, key=lambda r: 0 if r["kind"] == "home" else 1)[0]
            same = [c for c in careers if c["regdom"] == home["regdom"]]
            if same:
                c = same[0]
                return {"name": name, "url": c["url"], "career_url": c["career_url"]}
            return {"name": name, "url": home["url"], "career_url": None}
        if careers:
            c = careers[0]
            return {"name": name, "url": c["url"], "career_url": c["career_url"]}
        return None

    def _registrable_domain(self, url: str) -> str:
        """取可注册主域（兼容 com.cn 等二级后缀）"""
        host = urlparse(url).netloc.lower().replace("www.", "")
        parts = host.split(".")
        if len(parts) >= 3 and parts[-2] in ("com", "net", "org", "gov", "edu",
                                             "ac", "co"):
            return ".".join(parts[-3:])
        return ".".join(parts[-2:]) if len(parts) >= 2 else host

    def _classify_company_result(self, url: str, trusted: bool = False) -> Optional[str]:
        """分类搜索结果：career=公司招聘页 home=官网首页 subpage=官网子页 None=噪声
        trusted=True（用户显式给出的 URL）只做 http(s) 格式校验，绕过黑名单/登录主机过滤"""
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        if trusted:
            # 用户显式 URL 一律视为可直达招聘页，不再走降噪黑名单
            return "career"
        if self._is_aggregator(url) or self._is_junk(url):
            return None
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "/").lower()
        if not host or any(h in host for h in LOGIN_HOST_HINTS):
            return None
        if host.endswith((".edu.cn", ".ac.cn", ".edu", ".gov.cn", ".gov")):
            return None
        third_party_paths = ("/campus/view", "/xiaozhao/", "/jobfair",
                             "/xuanjiang", "/campus/detail")
        if any(p in path for p in third_party_paths):
            return None
        if self._host_has_career_prefix(host) or \
                any(h in path for h in CAREER_URL_HINTS):
            return "career"
        if path in ("/", "") or path.rstrip("/") in ("/zh", "/cn", "/en", "/zh-cn"):
            return "home"
        return "subpage"

    # ================================================================== #
    # 公司官网 -> 招聘页定位
    # ================================================================== #
    async def _locate_career_page(self, homepage: str) -> Optional[str]:
        """在公司官网上定位招聘页：先读首页锚点，再探测常见路径/子域"""
        page = None
        try:
            page = await self._context.new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                await page.goto(homepage, wait_until="domcontentloaded", timeout=self.timeout_ms)
            except Exception as e:
                logger.warning(f"公司官网打开失败 {homepage}: {e}")
                return None
            await self._settle_page(page, light=True)

            # 策略 1：首页锚点里找「招聘/加入我们/Careers」
            anchors = await self._collect_anchors(page)
            best = self._best_career_anchor(anchors)
            if best:
                return best

            # 策略 2：常见路径 + 招聘子域直接探测
            return await self._probe_career_urls(homepage, page)
        except Exception as e:
            logger.warning(f"定位招聘页失败 {homepage}: {e}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    def _best_career_anchor(self, anchors: List[Dict]) -> Optional[str]:
        """从首页锚点评出最可能的招聘入口（确定性，不依赖 LLM）"""
        best_href, best_score = None, 0
        for a in anchors:
            text = (a.get("text") or "").lower()
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("javascript:", "mailto:", "#", "tel:")):
                continue
            if len(text) > 20:
                continue
            score = 0
            for hint in CAREER_TEXT_HINTS:
                if hint in text:
                    score += 10
                    break
            low_href = href.lower()
            for hint in CAREER_URL_HINTS:
                if hint in low_href:
                    score += 6
                    break
            # 明确不是招聘的入口降权
            if any(x in low_href for x in ["/news", "/blog", "/product", "/about-us"]):
                score -= 5
            if score > best_score:
                best_score, best_href = score, href
        return best_href if best_score >= 10 else None

    async def _probe_career_urls(self, homepage: str, page) -> Optional[str]:
        """探测常见招聘路径与招聘子域，返回第一个内容像招聘页的 URL"""
        parsed = urlparse(homepage)
        host = parsed.netloc.lower().replace("www.", "")
        if not host:
            return None
        scheme = parsed.scheme or "https"

        candidates: List[str] = []
        base = f"{scheme}://{parsed.netloc}"
        for path in CAREER_PROBE_PATHS:
            candidates.append(urljoin(base + "/", path.lstrip("/")))
        for prefix in CAREER_SUBDOMAIN_PREFIXES:
            candidates.append(f"{scheme}://{prefix}{host}")

        for url in candidates[:18]:
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=10000)
                if resp and resp.status >= 400:
                    continue
                await asyncio.sleep(0.8)
                anchors = await self._collect_anchors(page)
                text = await self._safe_inner_text(page)
                jobish = sum(
                    1 for a in anchors
                    if self._score_anchor(a.get("text", ""), a.get("href", ""), []) >= 3
                )
                career_words = ["职位", "岗位", "招聘", "career", "job", "apply", "vacancy"]
                word_hit = sum(1 for w in career_words if w in text.lower()[:4000])
                if jobish >= 3 or word_hit >= 3:
                    return page.url
            except Exception:
                continue
        return None

    # ================================================================== #
    # 门户候选发现（Tavily 宽泛查询，国内平台优先）
    # ================================================================== #
    def _build_portal_queries(self, target_info: TargetInstructionSchema) -> List[str]:
        """门户通道查询词：只保留中文查询，避免把海外招聘站捞进来"""
        location = (target_info.location or "").strip()
        queries = []
        # 每个岗位词各出一条查询，提高同义岗位的召回
        for term in query_terms(target_info, limit=2):
            zh = f"{term} {location} 招聘".strip()
            if target_info.keywords:
                zh += " " + " ".join(str(k) for k in target_info.keywords[:4])
            queries.append(zh)

        company = (target_info.company or "").strip()
        if company:
            queries.append(f"{company} 招聘 职位 {target_info.role}")
        return queries

    async def _discover_portal_candidates(self, target_info: TargetInstructionSchema) -> List[Dict]:
        """用 Tavily 发现候选招聘门户（不做域名白名单限制，排除应用商店/百科等噪声）"""
        if not self.api_key:
            logger.warning("未配置 TAVILY_API_KEY，无法发现候选门户")
            return []

        candidates: Dict[str, Dict] = {}
        for query in self._build_portal_queries(target_info):
            for item in await self._tavily_search(query, max_results=10):
                url = item.get("url", "")
                if not url or url in candidates or self._looks_non_job(url) or self._is_junk(url):
                    continue
                title = item.get("title", "") or ""
                snippet = item.get("content", "") or item.get("snippet", "") or ""
                if self._looks_job_portal(url, title, snippet):
                    candidates[url] = {
                        "url": url,
                        "title": title,
                        "snippet": snippet[:300],
                    }

        return sorted(
            candidates.values(),
            key=lambda c: self._portal_score(c["url"], c["title"]),
            reverse=True,
        )

    async def _tavily_search(self, query: str, max_results: int = 10,
                             exclude: Optional[List[str]] = None) -> List[Dict]:
        """Tavily 搜索（同步客户端放到线程，失败返回空列表）"""
        if not self.api_key:
            return []
        kwargs = dict(
            query=query,
            search_depth="basic",
            max_results=max_results,
            include_answer=False,
            include_raw_content=False,
        )
        if exclude:
            kwargs["exclude_domains"] = exclude
        try:
            resp = await asyncio.to_thread(self._get_client().search, **kwargs)
            return (resp or {}).get("results", []) or []
        except Exception as e:
            logger.warning(f"Tavily 搜索失败 (query={query}): {e}")
            return []

    def _get_client(self) -> TavilyClient:
        if self._client is None:
            self._client = TavilyClient(api_key=self.api_key)
        return self._client

    # ================================================================== #
    # 浏览器生命周期与页面抽取
    # ================================================================== #
    async def _start_browser(self):
        """
        启动浏览器。

        persist_login=True 时使用持久化用户目录（launch_persistent_context）：
        - 用户在可见窗口里登录一次 Boss/猎聘，登录态会落盘并跨「发现阶段 → 抓 JD
          阶段 → 下一次运行」复用，不必反复登录（反复登录正是页面闪个不停的主因之一）；
        - 持久化启动失败（目录被占用、旧进程残留…）自动回退到匿名上下文，不中断流程。
        """
        from playwright.async_api import async_playwright

        await self._stop_browser()  # 避免重复启动导致旧实例泄漏
        self._playwright = await async_playwright().start()
        args = ["--disable-blink-features=AutomationControlled"]

        ctx = None
        if self.persist_login and self.user_data_dir:
            try:
                os.makedirs(self.user_data_dir, exist_ok=True)
                ctx = await self._playwright.chromium.launch_persistent_context(
                    self.user_data_dir,
                    headless=self.headless,
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    viewport={"width": 1366, "height": 800},
                    args=args,
                )
                await ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                )
                logger.info(f"职位发现浏览器已启动（复用登录态目录 {self.user_data_dir}, "
                            f"headless={self.headless}）")
            except Exception as e:
                logger.warning(f"持久化浏览器目录不可用（{e}），回退匿名上下文")
                ctx = None

        if ctx is not None:
            self._context = ctx
            try:
                self._browser = ctx.browser
            except Exception:
                self._browser = None
        else:
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless, args=args
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1366, "height": 800},
                locale="zh-CN",
            )
            logger.info(f"职位发现浏览器已启动 (headless={self.headless})")

        # 新浏览器 = 新会话：之前的「该站已人工处理过」记录不再成立，
        # 否则用户关掉窗口后自动重建的浏览器会被当成已登录，直接抓空。
        try:
            self.block_handler.reset()
        except Exception:
            pass

    def _context_alive(self) -> bool:
        """上下文是否还活着（持久化上下文拿不到 browser.is_connected，用页面探测）"""
        if self._context is None:
            return False
        try:
            _ = len(self._context.pages)
        except Exception:
            return False
        if self._browser is not None:
            try:
                return bool(self._browser.is_connected())
            except Exception:
                return False
        return True

    async def _ensure_browser(self) -> bool:
        """
        确保浏览器/上下文可用：被用户关闭或崩溃时自动重建。

        没有这一步时，一次「浏览器被关掉」会让后面所有站点都返回
        「Target page, context or browser has been closed」→ 抽取到 0 个职位。
        """
        if self._context_alive():
            return True
        logger.warning("职位发现浏览器已关闭/失联，正在重建...")
        try:
            await self._start_browser()
            return True
        except Exception as e:
            logger.error(f"重建职位发现浏览器失败: {e}")
            return False

    async def _stop_browser(self):
        try:
            if self._context:
                await self._context.close()
        except Exception as e:
            logger.warning(f"关闭职位发现上下文时出错: {e}")
        try:
            if self._browser:
                await self._browser.close()
        except Exception as e:
            logger.debug(f"关闭职位发现浏览器时出错（多为持久化上下文已随之关闭）: {e}")
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"停止 Playwright 时出错: {e}")
        finally:
            self._context = None
            self._browser = None
            self._playwright = None


    async def _new_page(self):
        """取一个可用页面；浏览器被关掉时先重建再取，取不到返回 None"""
        for _ in range(2):
            if not await self._ensure_browser():
                return None
            try:
                page = await self._context.new_page()
                page.set_default_timeout(self.timeout_ms)
                return page
            except Exception as e:
                logger.warning(f"新建页面失败，尝试重建浏览器: {e}")
                try:
                    await self._stop_browser()
                except Exception:
                    pass
        return None

    async def _collect_anchors(self, page, page_url: str = None) -> List[Dict]:
        """
        抽取页面上全部锚点（绝对 URL + 可见文本）。

        三层兜底，专治「抽取到 0 个职位」：
        1) 主文档 a[href]（常规列表页）
        2) 同源 iframe 内的 a[href]（部分招聘站把列表塞在 iframe 里）
        3) 属性里藏链接的卡片（data-href / onclick="location=..." 之类）
        """
        anchors: List[Dict] = []
        frames = []
        try:
            frames = list(page.frames)
        except Exception:
            frames = []
        for fr in frames[:6]:
            try:
                got = await fr.eval_on_selector_all("a[href]", _ANCHOR_JS)
            except Exception:
                continue
            if got:
                anchors.extend(got)
        if not anchors:
            try:
                anchors.extend(await page.evaluate(_ATTR_LINK_JS))
            except Exception:
                pass
        if not anchors:
            # 连锚点都没有：至少从 HTML 里捞出详情页 URL（SPA 把路由写在脚本里）
            anchors.extend(await self._links_from_html(page))
        return anchors

    async def _links_from_html(self, page) -> List[Dict]:
        """HTML 兜底：正则捞详情页链接（含内联 JSON/JS 路由），标题用 URL 末段"""
        try:
            html = await page.content()
        except Exception:
            return []
        out, seen = [], set()
        for m in re.finditer(
            r"""["'\(]((?:https?://[\w.\-]+)?/[\w\-/.]*"""
            r"""(?:job|position|post|vacanc|detail)[\w\-/.]*"""
            r"""(?:\?[^"'\)\s]{0,120})?)["'\)]""",
            html, re.I,
        ):
            url = m.group(1)
            if url in seen or len(url) < 8:
                continue
            seen.add(url)
            if not re.search(r"\d", url):  # 没有数字 ID 的多半是栏目页
                continue
            try:
                abs_url = urljoin(page.url, url)
            except Exception:
                continue
            tail = urlparse(abs_url).path.rstrip("/").split("/")[-1]
            out.append({"text": tail.replace("-", " ")[:60], "href": abs_url,
                        "weak": True})
            if len(out) >= 60:
                break
        return out

    async def _extract_company_jobs(self, company_name, career_url, target_info):
        """公司招聘站入口（薄封装）：走统一站点抽取流程"""
        return await self._discover_jobs_on_site(
            company_name, career_url, target_info, drill_list=True
        )

    # ------------------------------------------------------------------ #
    # 统一站点抽取流程（门户通道 / 公司官网通道共用）
    # ------------------------------------------------------------------ #
    async def _discover_jobs_on_site(self, site_name: str, entry_url: str,
                                     target_info: TargetInstructionSchema,
                                     drill_list: bool = False,
                                     portal_search: bool = False) -> List[Dict]:
        """
        单个站点的完整抽取流程：

        0) 打开入口页 -> 先查登录墙/验证码（被挡就按 AGENTS.md 停下等人，不瞎点）
        1) 公司官网：先钻取到「校园招聘/全部职位」列表页
        2) 按官网「类别/方向」导航进入目标分类
           （聚合门户则相反：入口直接改写成站内搜索 URL —— 见 portal_search）
        3) 列表逐页遍历，收集 <a href> 职位锚点
        4) 锚点不足 -> 用列表 XHR 里的职位对象 + 实测过的详情页 URL 模板补齐
        5) 仍不足 -> 扫描 DOM 职位卡片并点击，取真实详情页 URL
           （腾讯/B站/米哈游/Moka/北森/京东 的卡片都不是 <a href>，
             只数锚点必然 0 个职位，这一步是它们唯一的入口）
        6) 按标题方向相关度排序去重后返回

        Args:
            portal_search: True=这是聚合门户（Boss/猎聘/前程无忧），用站内搜索 URL 当入口

        Returns:
            职位字典列表 [{url, title, company, location, description, source, title_score}]
        """
        jobs: List[Dict] = []
        seen: set = set()
        page = None
        try:
            page = await self._new_page()
            if page is None:
                logger.warning(f"{site_name} 无法创建页面（浏览器不可用），跳过")
                return jobs

            # 聚合门户：把裸列表页入口换成「站内搜索目标岗位」的 URL。
            # 不做这一步时，打开的只是门户的全网默认 feed（Boss 那一站甚至只抓到
            # 站点导航链接），方向过滤后必然 0 个岗位。
            if portal_search and self.portal_keyword_search:
                search_url = self._portal_search_url(entry_url, target_info)
                if search_url and search_url != entry_url:
                    logger.info(f"{site_name} 聚合门户改用站内搜索入口: {search_url}")
                    entry_url = search_url

            api_jobs, handler, api_stats = self._make_api_capture()
            page.on("response", handler)

            try:
                await page.goto(entry_url, wait_until="domcontentloaded",
                                timeout=self.timeout_ms)
            except Exception as e:
                logger.warning(f"{site_name} 打开失败 {entry_url}: {e}")
                return jobs
            await self._settle_page(page)

            # 0) 进门先查登录墙/验证码：被挡就立刻停下等人，处理前不点任何东西
            if await self._wait_if_blocked(page, entry_url):
                logger.info(f"{site_name} 需要人工登录/验证，跳过本站")
                return jobs

            tk = getattr(target_info, "title_keywords", None)
            role_toks = self._role_tokens(target_info)

            # 1) 公司官网：钻取到职位列表页（聚合门户入口本身就是列表/搜索页）
            if drill_list:
                list_href = await self._find_job_list_href(page, target_info)
                await self._goto_settle(page, list_href, f"{site_name} 进入职位列表页")

            # 2) 先找官网岗位类别（技术类/产品类…）：可跳转类别页，或点列表上的 Tab
            pre_cat_url = page.url
            cat_href = await self._find_category_link(page, target_info)
            if cat_href:
                await self._goto_settle(page, cat_href, f"{site_name} 进入目标类别")
            else:
                await self._click_matching_category_tab(page, target_info)

            list_url = page.url

            # 3) 列表逐页遍历：先收齐岗位名称，再与画像/方向词比对
            scored = await self._collect_list_across_pages(
                page, target_info, api_items=api_jobs
            )

            # 列表需要登录 / 出现验证码：停下汇报给用户处理
            blocked_kind = await self._page_looks_blocked(page)
            if blocked_kind:
                ok = await self._handle_block(
                    page.url, page, kind=blocked_kind,
                    detail="职位列表需要登录或出现验证，请手动处理后继续",
                )
                if not ok:
                    logger.info(f"{site_name} 用户选择跳过，停止该站")
                    return jobs
                await self._settle_page(page)
                list_url = page.url
                scored = await self._collect_list_across_pages(
                    page, target_info, api_items=api_jobs
                )

            # 3.0) 类别导航自纠错：如果进「类别」后既没有方向相关的锚点，
            #      接口里也没有方向相关的职位，多半是点进了站点的关键词落地页
            #      （猎聘 /zpXXXX/ 这类），退回进类别之前的列表页重来。
            #      SPA 站（腾讯/B站/米哈游…）本来就没有 a[href]，靠接口判据兜住。
            if (cat_href and pre_cat_url and list_url != pre_cat_url
                    and not self._has_relevant_anchor(scored, tk)
                    and not self._has_relevant_api(api_jobs, tk)):
                if await self._goto_settle(page, pre_cat_url, f"{site_name} 退回原列表页"):
                    list_url = page.url
                    await self._click_matching_category_tab(page, target_info)
                    scored = await self._collect_list_across_pages(
                        page, target_info, api_items=api_jobs
                    )

            company = self._site_company_name(site_name, entry_url)
            # 聚合门户（Boss/猎聘/前程无忧/智联）：列表里什么方向的岗位都有，
            # 方向不相关就真的不要，不做「一个都没命中就全留下」的兜底
            strict = self._strict_relevance(entry_url)

            # 3.1) 锚点通道：真实 <a href>
            #
            # 顺序很重要：先按「像不像职位详情页」筛，再按方向筛标题。
            # 反过来的话日志会出现「方向相关 2 个 → 最终 0 个」的假相关
            # （那 2 个其实是页脚/筛选标签，下一道 _looks_like_job_detail 直接丢掉），
            # 让人误以为「筛得太狠」，实际是两套判据口径不一致。
            scored_all = scored                      # 兜底通道还要用未筛选的候选
            total_anchors = len(scored_all)
            detail_like, reject_stats = self._filter_detail_like(
                scored_all, list_url, role_toks, tk
            )
            scored = self._prune_by_title_relevance(
                detail_like, tk, keep_all_when_empty=not strict
            )
            relevant_anchors = len(scored)
            for score, a in scored:
                href = a["href"]
                head = self._clean_job_title((a.get("text") or "").split("\n", 1)[0])
                if not self._mark_seen(seen, href):
                    continue
                jobs.append({
                    "url": href, "title": head[:80], "company": company,
                    "location": target_info.location or "",
                    "description": "", "source": "browser", "title_score": score,
                })
                if len(jobs) >= self.max_jobs_per_site:
                    break
            if jobs:
                logger.info(f"{site_name} 列表锚点抽到 {len(jobs)} 个职位")

            # 3.2) 接口通道：列表 XHR 里的职位对象 + 详情 URL 模板
            #      一律按方向相关过滤：宁可先只要相关岗位，
            #      整站一个相关都没有时再走下面的「低分兜底」，避免把
            #      财务/市场这类岗位按 title_score=10 混进正式结果
            if len(jobs) < self.max_jobs_per_site:
                jobs.extend(self._jobs_from_api(
                    api_jobs, list_url, target_info, company,
                    target_info.location or "", seen,
                    self.max_jobs_per_site - len(jobs), strict=True,
                ))

            # 3.3) 卡片点击通道：SPA 职位卡片不是 <a href> 时的唯一入口
            if len(jobs) < self.max_jobs_per_site:
                jobs.extend(await self._jobs_from_cards_by_click(
                    page, list_url, target_info, company, target_info.location or "",
                    seen, self.max_jobs_per_site - len(jobs),
                    prefer_titles=[j["title"] for j in self._rank_api_jobs(api_jobs, tk)][:10],
                    skip_titles=[j["title"] for j in jobs],
                ))

            # 3.4) 低分兜底：公司官网整站都没有「方向相关」岗位时，
            #      保留该站真实存在的岗位（标 title_score=1，排序靠后），
            #      而不是整站静默返回空。聚合门户不做这个兜底（全网列表噪声太大）。
            if not jobs and not strict:
                fallback = self._fallback_site_jobs(
                    api_jobs, scored_all, list_url, target_info, company, seen,
                    self.max_jobs_per_site,
                )
                if fallback:
                    jobs.extend(fallback)
                    logger.warning(
                        f"{site_name} 没有「{target_info.role}」方向相关岗位，"
                        f"低分兜底保留 {len(fallback)} 个（title_score=1，排序会靠后）"
                    )

            logger.info(
                f"{site_name} 最终抽取 {len(jobs)} 个职位"
                f"（锚点 {total_anchors} 个 → 像职位详情 {len(detail_like)} 个 → "
                f"方向相关 {relevant_anchors} 个；JSON 响应 {api_stats['json_responses']} 个，"
                f"接口认出职位 {len(api_jobs)} 个）"
            )
            if not jobs:
                # 明确写出「0 个」的原因，避免日志里只剩一句「抽取到 0 个职位」
                logger.warning(
                    f"{site_name} 本站 0 个职位：列表页 {list_url} 上锚点 {total_anchors} 个"
                    f"（判非职位详情而丢弃 {reject_stats['rejected']} 个：导航文本 "
                    f"{reject_stats['nav_text']}、非职位路径 {reject_stats['non_job']}、"
                    f"仍是列表页 {reject_stats['same_list']}、不像详情页 "
                    f"{reject_stats['not_detail']}｜像详情页 {len(detail_like)} 个，"
                    f"其中方向相关 {relevant_anchors} 个）、"
                    f"接口职位 {len(api_jobs)} 个、页面可点卡片已尝试点击。"
                    f"常见原因：① 该站需登录/过验证码后才返回职位列表；"
                    f"② 该站当前确实没有「{target_info.role}」方向的岗位；"
                    f"③ 列表由登录态接口下发且卡片不可点击。"
                )
                ok = await self._handle_block(
                    page.url, page, kind="unknown", force=True,
                    detail=(
                        f"Agent 无法从本站抽出与「{target_info.role}」相关的岗位。"
                        "若页面需要登录、切换类别或点到职位列表，请在浏览器里做完后回车，"
                        "Agent 会再扫一遍；输入 skip 跳过本站。"
                    ),
                )
                if ok:
                    await self._settle_page(page)
                    await self._click_matching_category_tab(page, target_info)
                    scored = await self._collect_list_across_pages(
                        page, target_info, api_items=api_jobs
                    )
                    list_url = page.url
                    scored_all = scored
                    detail_like, reject_stats = self._filter_detail_like(
                        scored_all, list_url, role_toks, tk
                    )
                    scored = self._prune_by_title_relevance(
                        detail_like, tk, keep_all_when_empty=not strict
                    )
                    for score, a in scored:
                        href = a["href"]
                        head = self._clean_job_title(
                            (a.get("text") or "").split("\n", 1)[0]
                        )
                        if not self._mark_seen(seen, href):
                            continue
                        jobs.append({
                            "url": href, "title": head[:80], "company": company,
                            "location": target_info.location or "",
                            "description": "", "source": "browser",
                            "title_score": score,
                        })
                        if len(jobs) >= self.max_jobs_per_site:
                            break
                    if len(jobs) < self.max_jobs_per_site:
                        jobs.extend(self._jobs_from_api(
                            api_jobs, list_url, target_info, company,
                            target_info.location or "", seen,
                            self.max_jobs_per_site - len(jobs), strict=True,
                        ))
                    if len(jobs) < self.max_jobs_per_site:
                        jobs.extend(await self._jobs_from_cards_by_click(
                            page, list_url, target_info, company,
                            target_info.location or "", seen,
                            self.max_jobs_per_site - len(jobs),
                            prefer_titles=[
                                j["title"]
                                for j in self._rank_api_jobs(api_jobs, tk)
                            ][:10],
                            skip_titles=[j["title"] for j in jobs],
                        ))
                    logger.info(f"{site_name} 人工处理后重试，抽到 {len(jobs)} 个职位")
            return jobs

        except Exception as e:
            logger.warning(f"{site_name} 站内抽取失败 {entry_url}: {e}")
            return jobs
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    def _filter_detail_like(self, scored, list_url: str, role_toks, title_keywords):
        """
        从候选锚点里挑出「真的像职位详情页」的那些，并统计每个丢弃原因。

        之前这段判定内联在收录循环里，导致 `_prune_by_title_relevance` 报出的
        「方向相关 N 个」和最终真正入库的数量口径不一致（日志里出现
        「344 个锚点 → 方向相关 2 个 → 最终 0 个」这种看起来自相矛盾的记录）。
        抽成独立一步后：数字口径一致，且每个原因都能在日志里看到。

        Returns:
            (kept, stats)  kept=[(score, anchor)]；stats 为各丢弃原因的计数
        """
        kept = []
        stats = {"nav_text": 0, "non_job": 0, "same_list": 0, "not_detail": 0,
                 "rejected": 0}
        for score, a in (scored or []):
            href = a.get("href")
            head = self._clean_job_title((a.get("text") or "").split("\n", 1)[0])
            reason = ""
            if not href or self._is_nav_text(head):
                reason = "nav_text"
            elif self._looks_non_job(href):
                reason = "non_job"
            elif self._same_list_page(href, list_url):
                reason = "same_list"
            elif not self._looks_like_job_detail(head, href, role_toks, title_keywords):
                reason = "not_detail"
            if reason:
                stats[reason] += 1
                stats["rejected"] += 1
                continue
            kept.append((score, a))
        return kept, stats

    def _role_query(self, target_info: TargetInstructionSchema) -> str:
        """站内搜索框要输入的岗位词（主岗位名优先，缺省用最短变体）"""
        terms = query_terms(target_info, limit=2) or []
        return (target_info.role or "").strip() or (terms[0] if terms else "")

    def _portal_search_url(self, entry_url: str,
                           target_info: TargetInstructionSchema) -> Optional[str]:
        """
        聚合门户入口 -> 「站内搜索目标岗位」的 URL（不认识的门户返回 None）。

        只对已知门户主机改写；公司官网/公司招聘专页不受影响（它们由调用方
        用 portal_search=False 关掉，且这里的模板也不覆盖它们）。
        """
        role = self._role_query(target_info)
        if not role:
            return None
        try:
            host = (urlparse(entry_url).netloc or "").lower()
        except Exception:
            return None
        if not host:
            return None
        for key, tpl in PORTAL_SEARCH_URLS.items():
            if key in host:
                try:
                    return tpl.format(q=quote(role))
                except Exception:
                    return None
        return None

    def _fallback_site_jobs(self, api_items: List[Dict], scored_all, list_url: str,
                            target_info, company: str, seen: set,
                            limit: int) -> List[Dict]:
        """
        整站没有方向相关岗位时的低分兜底（只用于公司官网）：

        保留该站确实存在的岗位，但 title_score 只给 1（远低于相关岗位的 10），
        这样它们会排在结果末尾，也不会挤掉其它站的相关岗位。
        """
        out: List[Dict] = []
        if limit <= 0:
            return out
        role_toks = self._role_tokens(target_info)
        # 先兜底锚点里的真实职位（仍要求「像职位详情」，只是不要求方向命中）
        for _score, a in (scored_all or []):
            href = a.get("href")
            head = self._clean_job_title((a.get("text") or "").split("\n", 1)[0])
            if (not href or self._is_nav_text(head)
                    or self._looks_non_job(href) or self._same_list_page(href, list_url)):
                continue
            if not self._looks_like_job_detail(head, href, role_toks, None):
                continue
            if not self._mark_seen(seen, href):
                continue
            out.append({
                "url": href, "title": head[:80], "company": company,
                "location": target_info.location or "", "description": "",
                "source": "browser_fallback", "title_score": 1,
            })
            if len(out) >= limit:
                return out
        # 再兜底接口职位
        for item in api_items or []:
            title = (item.get("title") or "").strip()
            if not title or self._is_nav_text(title):
                continue
            href = self._build_detail_url(list_url, item)
            if not href or self._same_list_page(href, list_url):
                continue
            if not self._mark_seen(seen, href):
                continue
            out.append({
                "url": href, "title": title[:80], "company": company,
                "location": item.get("city") or target_info.location or "",
                "description": item.get("description") or "",
                "source": "browser_fallback", "title_score": 1,
            })
            if len(out) >= limit:
                break
        return out

    async def _find_job_list_href(self, page, target_info=None):
        """
        在招聘首页找职位列表页链接，按 recruit_type 加权：
        campus 优先「校园招聘/校招/campus」，social 优先「社会招聘/社招/experienced」。
        """
        try:
            anchors = await self._collect_anchors(page)
        except Exception:
            return None
        recruit = (getattr(target_info, "recruit_type", None) or "campus").lower()

        best, best_score = None, 0
        for a in anchors:
            t = (a.get("text") or "").strip()
            href = a.get("href") or ""
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            low_href = href.lower()
            low_blob = f"{t} {low_href}".lower()
            score = 0
            # 通用列表词
            if any(k in t for k in ["校园招聘", "校招", "社会招聘", "社招", "全部职位",
                                    "职位搜索", "搜索职位", "所有职位", "热门职位",
                                    "查看职位"]):
                score += 10
            if any(k in low_blob for k in ["all jobs", "search jobs", "open positions",
                                           "job opportunities", "early career", "campus",
                                           "experienced"]):
                score += 8
            if any(k in low_href for k in ["/position", "/search", "/jobs",
                                           "/joblist", "/job-list", "/list"]):
                score += 5

            is_campus = ("校园" in t or "校招" in t
                         or "campus" in low_href or "校园" in low_blob)
            is_social = ("社招" in t or "社会招聘" in t
                         or "experienced" in low_href or "/social" in low_href)
            if recruit == "campus":
                if is_campus:
                    score += 12
                if is_social:
                    score -= 8
            elif recruit == "social":
                if is_social:
                    score += 12
                if is_campus:
                    score -= 8

            # 首页/登录/注册不是列表页
            if t in ["首页", "登录", "注册"]:
                score -= 10
            if score > best_score:
                best, best_score = href, score
        return best if best_score >= 10 else None

    # ------------------------------------------------------------------ #
    # 类别识别 + 列表逐页遍历（替代站内关键词搜索）
    # ------------------------------------------------------------------ #
    def _category_match_terms(self, target_info: TargetInstructionSchema) -> List[str]:
        """
        该用户目标方向对应的官网类别词。

        只取「类别/栏目」性质的词（技术类/研发/Engineering…），
        刻意不取「工程师/开发」这类职位名词——否则列表页里的
        「机械工程师」链接会被当成「技术类导航」，一点就跳去别的岗位列表。
        """
        terms: List[str] = []
        cat = (getattr(target_info, "direction_category", None) or "").strip()
        if cat:
            terms.append(cat)
            # “技术类”这种大类，导航里常写成“技术/研发/Engineering”
            terms.extend(CATEGORY_NAV_HINTS.get(cat, []))
        return list(dict.fromkeys(t for t in terms if t))

    async def _find_category_link(self, page, target_info: TargetInstructionSchema) -> Optional[str]:
        """
        在职位列表页找「与目标方向匹配的类别导航」链接。

        例如用户找 AI 方向，官网类别栏有 技术类/产品类/设计类 -> 点进“技术类”。

        只接受「站内 + 短文本 + 不是职位详情页 + 不是提交/登录类」的锚点：
        之前这里会把 `jobs.51job.com/jixiegongchengshi/`、`baike.51job.com/...`、
        `app.mokahr.com/...#/job/<guid>` 之类当成类别导航，一点就离开列表页，
        结果整个站点抽取到 0 个职位。

        「已经在列表页」用两级证据判定，DOM 证据优先于 URL 形状：
        1) URL 明显是列表/搜索页（_looks_like_listing_url）；或
        2) 页面已经渲染出 >= nav_stay_min_job_links 个职位详情链接——
           此时无论导航栏里写了什么（字节校招页的「技术人才项目」「产品与技术」
           就是含「技术」二字的宣传链接），都不许再跳，否则等于主动丢掉已渲染的岗位。
        """
        if self._looks_like_listing_url(page.url):
            logger.info(f"{page.url} 已是职位列表页，跳过类别导航跳转")
            return None

        page_job_links = await self._job_link_count(page)
        if page_job_links >= self.nav_stay_min_job_links:
            logger.info(
                f"{page.url} 已渲染 {page_job_links} 个职位详情链接，"
                f"判定已在职位列表页，跳过类别导航跳转"
            )
            return None

        anchors = await self._collect_anchors(page)
        terms = [t.lower() for t in self._category_match_terms(target_info) if t]
        if not terms:
            return None

        try:
            cur = urlparse(page.url)
            cur_regdom = self._registrable_domain(page.url)
        except Exception:
            cur, cur_regdom = None, ""

        candidates: List = []          # [(score, text, href)]，供规则与 LLM 共用
        for a in anchors:
            text = (a.get("text") or "").strip()
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
                continue
            # 类别导航通常是短文本（技术类 / 研发 / Engineering），过长多半是职位标题
            if not (1 <= len(text) <= 12):
                continue
            # 职位详情页/职位名不是类别导航
            if self._looks_like_detail_url(href) or any(w in text for w in _JOB_TITLE_WORDS):
                continue
            # 宣传/专项项目类导航（人才项目/培养项目…）是介绍页，不是职位类别列表
            if text.endswith("项目"):
                continue
            # 投递/申请/登录类永远不是类别导航（红线1：绝不点提交按钮）
            if any(w in text.lower() for w in DANGEROUS_NAV_TEXT):
                continue
            if self._looks_non_job(href) or self._is_junk(href):
                continue
            # 同类目站内的百科/帮助/登录子域也不是类别导航
            # （51job 的 baike.51job.com 曾经把整站带偏到百科页）
            low_host = ""
            try:
                low_host = urlparse(href).netloc.lower()
            except Exception:
                low_host = ""
            if any(low_host.startswith(p) or f".{p}" in low_host
                   for p in _NON_NAV_HOST_PREFIXES):
                continue
            try:
                tgt = urlparse(href)
            except Exception:
                continue
            # 必须同站（含子域），避免跳到百度百科/其他站点
            if cur is not None and tgt.netloc:
                same = tgt.netloc.lower() == cur.netloc.lower()
                if not same and self._registrable_domain(href) != cur_regdom:
                    continue
            low = text.lower()
            score = 0
            for t in terms:
                if t and t in low:
                    # 大类词（技术类/产品类）权重高；短类别词次之
                    score += 5 if t.endswith("类") else 3
            if score >= 3:
                candidates.append((score, text, href))

        if not candidates:
            return None
        candidates.sort(key=lambda c: c[0], reverse=True)

        best_href = candidates[0][2]
        # 规则已经明确（最高分明显领先）时不花 LLM 的钱；
        # 只有「多个候选并列/接近」或「当前页已能看到职位链接但仍选了候选」
        # 这类规则真判不准的情况，才让受约束的裁决器在候选里选/否决。
        ambiguous = len(candidates) > 1 and candidates[1][0] == candidates[0][0]
        if self.nav_advisor is not None and (ambiguous or page_job_links > 0):
            try:
                pick = await self.nav_advisor.choose(
                    site=self._host_of(page.url),
                    page_url=page.url,
                    role=(target_info.role or ""),
                    recruit_type=(getattr(target_info, "recruit_type", None) or "campus"),
                    page_job_links=page_job_links,
                    candidates=[{"text": c[1], "href": c[2]} for c in candidates],
                    deterministic_pick={"text": candidates[0][1], "href": candidates[0][2]},
                )
            except Exception as e:      # 裁决器永不阻塞主流程
                logger.warning(f"导航裁决器异常（按规则继续）: {e}")
                pick = None
            if pick == -1:
                logger.info("导航裁决：留在当前页，不做类别跳转")
                return None
            if isinstance(pick, int) and 0 <= pick < len(candidates):
                best_href = candidates[pick][2]

        logger.info(f"按方向选中官网类别: {best_href}")
        return best_href

    def _pick_category_widget(
        self, widgets: List[Dict], target_info: TargetInstructionSchema
    ) -> Optional[Dict]:
        """从页面上的 Tab/筛选文案里挑出与目标方向匹配的类别。"""
        terms = [t.lower() for t in self._category_match_terms(target_info) if t]
        if not terms or not widgets:
            return None
        best, best_score = None, 0
        for w in widgets:
            text = (w.get("text") or "").strip()
            if not (1 <= len(text) <= 16):
                continue
            if self._is_nav_text(text):
                continue
            if any(d in text.lower() for d in DANGEROUS_NAV_TEXT):
                continue
            if any(word in text for word in _JOB_TITLE_WORDS):
                continue
            low = text.lower()
            score = 0
            for t in terms:
                if not t:
                    continue
                if t in low:
                    score += 8 if t.endswith("类") else 4
                else:
                    stem = t.rstrip("类")
                    if len(stem) >= 2 and stem in low:
                        score += 3
            if score > best_score:
                best, best_score = w, score
        return best if best_score >= 3 else None

    async def _click_matching_category_tab(self, page, target_info) -> bool:
        """
        已在职位列表页时，点页面上的类别 Tab / 筛选（不离开当前列表）。

        很多官网（字节/美团/B 站）类别是 Tab，URL 已经是 /jobs、/positions，
        _find_category_link 会故意不跳转；这里补上「先点目标类别再遍历岗位名」。
        """
        try:
            widgets = await page.evaluate(_CATEGORY_WIDGET_JS)
        except Exception:
            return False
        pick = self._pick_category_widget(widgets or [], target_info)
        if not pick:
            logger.info("当前页未发现与目标方向匹配的类别 Tab")
            return False
        text = pick["text"]
        href = (pick.get("href") or "").strip()
        if (href.startswith("http")
                and href.split("#")[0].rstrip("/") != (page.url or "").split("#")[0].rstrip("/")
                and not self._looks_like_detail_url(href)
                and not self._looks_non_job(href)):
            ok = await self._goto_settle(page, href, f"进入类别「{text}」")
            if ok:
                return True
        try:
            loc = page.get_by_text(text, exact=True).first
            await loc.click(timeout=3000)
            await self._settle_page(page)
            logger.info(f"已点击页面类别: {text}")
            return True
        except Exception:
            logger.info(f"点击类别「{text}」未成功，继续遍历当前列表")
            return False


    async def _goto_next_list_page(self, page) -> bool:
        """点击「下一页 / 加载更多」。成功翻到下一页返回 True，没有下一页返回 False。"""
        selectors = [
            "a.pagination__next", ".pager .next", "a.next", "li.next a",
            "a:has-text('下一页')", "button:has-text('下一页')",
            "a:has-text('Next')", "button:has-text('Next')",
            "a:has-text('加载更多')", "button:has-text('加载更多')",
            "a:has-text('查看更多')",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0 or not await loc.is_visible():
                    continue
                await loc.click(timeout=2500)
                await self._settle_page(page)
                return True
            except Exception:
                continue
        return False

    async def _collect_list_across_pages(
        self, page, target_info: TargetInstructionSchema, max_pages: int = None,
        api_items: List[Dict] = None,
    ) -> List:
        """
        在当前类别/列表页上逐页遍历，把每一页的职位锚点都收集起来。
        返回 [(score, anchor)] 保序去重，最多翻 max_pages 页。

        api_items：列表 XHR 的实时结果列表（response 回调一直在往里追加）。
        传进来只是为了在日志里显示「翻页后接口职位涨到多少」——SPA 站（字节/腾讯）
        往往一个 a[href] 都没有，翻页的收益全在接口职位数上，没有这个数字
        就看不出「翻了 4 页但一条新岗位都没多」这种问题。
        """
        role_toks = self._role_tokens(target_info)
        max_pages = max(1, int(max_pages or self.max_list_pages))
        collected: List = []
        seen = set()
        for page_no in range(max_pages):
            scored = await self._score_anchors(page, role_toks)
            added = 0
            for s, a in scored:
                href = a.get("href")
                if not href or href in seen:
                    continue
                seen.add(href)
                collected.append((s, a))
                added += 1
            api_note = f"，接口职位累计 {len(api_items)}" if api_items is not None else ""
            logger.info(
                f"列表第 {page_no + 1} 页收集 {added} 个职位锚点"
                f"（累计 {len(collected)}{api_note}）"
            )
            if page_no == max_pages - 1:
                break
            if not await self._goto_next_list_page(page):
                break
        return collected


    @staticmethod
    def _clean_job_title(text: str) -> str:
        """
        把锚点/卡片文本收拾成干净的职位名。

        招聘列表的卡片文本常连着「急 / NEW 角标 + 职位名 + 发布于 时间 + 薪资 + 学历 + 城市」，
        直接把整段当标题入库，会让报告很难看，也会让「标题是否命中方向词族」
        被薪资/城市/公司名里的噪声字母误导（例如 Baidu、Email 里的 ai）。
        """
        t = (text or "").strip()
        t = re.sub(r"^(急聘|急招|急|最新|新|热招|热聘|置顶|推荐|hot|new|urgent)[\s:：·|｜-]*",
                   "", t, flags=re.I)
        for sep in ("发布于", "更新时间", "更新于", "|", "｜", "\n"):
            if sep in t:
                t = t.split(sep, 1)[0]
        # 砍掉薪资尾巴（6-8千 / 1.2-2万·13薪 / 20-40k）
        t = re.split(r"\s*[·•]?\s*\d+(?:\.\d+)?\s*[-–~]\s*\d+(?:\.\d+)?\s*(?:千|万|k|K|元)",
                     t, maxsplit=1)[0]
        t = re.split(r"\s+\d+(?:\.\d+)?\s*(?:千|万|k|K)\b", t, maxsplit=1)[0]
        t = re.sub(r"\s{2,}", " ", t)
        return t.strip(" ·-—|｜·")

    @staticmethod
    def _kw_hit(text: str, kw: str) -> bool:
        """
        关键词是否命中。

        短英文词（ai / cv / pm / bd / gpt…）按词边界匹配：
        否则 'ai' 会在 'Baidu'、'Email'、'Daily' 里命中，
        'cv' 会在随机英文串里命中，把无关岗位全放进来。
        """
        if not text or not kw:
            return False
        text, kw = str(text).lower(), str(kw).lower()
        if re.fullmatch(r"[a-z0-9+#.]{1,3}", kw):
            return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", text) is not None
        return kw in text

    @staticmethod
    def _dedupe_key(url: str) -> str:
        """
        URL 去重键：忽略跟踪参数。

        同一个岗位的链接常带不同跟踪参数（字节 ?spread=DWA3PQP、猎聘 ?pgRef=…、
        51job ?s=pchome…&req=…），不归一化就会同一岗位入库两次。
        """
        try:
            p = urlparse(url or "")
        except Exception:
            return (url or "").strip()
        keep = []
        for k, v in parse_qsl(p.query, keep_blank_values=False):
            kl = k.lower()
            if kl.startswith("utm_") or kl in _TRACKING_QUERY_KEYS:
                continue
            keep.append((k, v))
        keep.sort()
        path = (p.path or "/").rstrip("/") or "/"
        query = urlencode(keep)
        return f"{p.scheme}://{p.netloc.lower()}{path}?{query}#{p.fragment}"

    def _mark_seen(self, seen: set, url: str) -> bool:
        """把 URL 记入去重集合；返回 True 表示是新的（False = 已收录过）"""
        key = self._dedupe_key(url)
        if not key or key in seen:
            return False
        seen.add(key)
        return True

    def _has_relevant_api(self, api_items: List[Dict], title_keywords) -> bool:
        """接口职位里是否存在方向相关的岗位"""
        kws = [str(k).lower() for k in (title_keywords or []) if k]
        if not kws:
            return bool(api_items)
        for item in api_items or []:
            title = str(item.get("title") or "").lower()
            if any(self._kw_hit(title, k) for k in kws):
                return True
        return False

    def _has_relevant_anchor(self, scored, title_keywords) -> bool:
        """候选锚点里是否存在「方向相关」的岗位（不做兜底保留）"""
        if not scored:
            return False
        if not title_keywords:
            return True
        return bool(self._prune_by_title_relevance(
            scored, title_keywords, keep_all_when_empty=False
        ))

    def _is_nav_text(self, text: str) -> bool:
        t = (text or "").strip().lower().strip("/")
        if len(t) <= 2:
            return True
        nav = ["首页", "登录", "注册", "校园招聘", "社会招聘", "常见问题", "行程", "赛事",
               "计划", "官网", "返回", "更多", "查看更多", "了解更多", "关于我们", "联系我们",
               "home", "login", "register", "about", "contact", "faq", "more", "back"]
        return any(t == n for n in nav)

    def _looks_like_job_detail(self, text: str, href: str, role_toks,
                               title_keywords=None) -> bool:
        """判断锚点是否真的是职位详情：URL 像详情页，且文本本身像一个职位"""
        t = (text or "").strip()
        if not JOB_DETAIL_RE.search(href or "") or len(t) < 4:
            return False
        occ = ["工程师", "开发", "设计师", "产品", "运营", "经理", "专员", "架构师",
               "分析师", "研究员", "主管", "总监", "顾问", "专家",
               "engineer", "developer", "designer", "manager", "specialist",
               "analyst", "intern", "scientist"]
        if any(w in t for w in occ):
            return True
        if role_toks and any(tok in t.lower() for tok in role_toks):
            return True
        if title_keywords and any(str(k).lower() in t for k in title_keywords):
            return True
        return False

    def _make_api_capture(self):
        """返回 (结果列表, response 事件处理器, 统计)，抓取招聘站 XHR 中的职位 JSON"""
        found = []
        stats = {"json_responses": 0, "job_objects": 0}

        async def on_response(response):
            try:
                ct = (response.headers or {}).get("content-type", "")
                if "json" not in ct:
                    return
                stats["json_responses"] += 1
                before = len(found)
                data = await response.json()
                self._walk_jobs_json(data, found)
                if len(found) > before:
                    stats["job_objects"] = len(found)
            except Exception:
                pass

        return found, on_response, stats

    def _walk_jobs_json(self, node, found, depth=0):
        """
        递归遍历 JSON，提取职位对象（职位名 + 职位ID/链接 + 城市）。

        上限原来是硬编码 40：字节校招列表有 1210+ 个岗位，翻页拿到的接口职位
        会被这条上限直接砍掉，表现就是「列表显示 1210 个岗位，Agent 只找到 6 个」。
        现在改成 max_api_objects（config.search.max_api_objects，可配置的成本上限）。
        """
        if depth > 9 or len(found) >= self.max_api_objects:
            return
        name_keys = ("positionname", "jobname", "postname", "jobtitle", "positiontitle",
                     "jobadname", "recruitpost", "adname", "name", "title")
        # 业务 ID 优先于裸 id；同时把所有 ID 字段都留档，
        # 因为有的站点（北森 zhiye）详情页 URL 用的是 guid 而不是数字业务 ID
        id_keys = ("jobunionid", "jobadid", "positionid", "jobid", "postid",
                   "recruitid", "id")
        # 列表接口常直接携带 JD 正文（如 B 站 positionList 的 positionDescription），
        # 一并提取，后续阶段无需再打开 SPA 详情页（详情页二次 XHR 常抓空）
        desc_keys = ("positiondescription", "jobdescription", "postdescription",
                     "description", "positionrequire", "requirement", "requirements",
                     "require", "responsibilities", "jobdetail", "detail", "content",
                     "duty")
        city_keys = ("worklocation", "workcity", "workcities", "positioncity",
                     "location", "city", "locnames", "area")
        if isinstance(node, dict):
            name, ids, link, cities, desc = None, {}, None, [], ""
            for k, v in node.items():
                kl = k.lower()
                if isinstance(v, str) and v.strip():
                    if kl in name_keys and len(v.strip()) >= 3:
                        name = v.strip()
                    elif kl in id_keys:
                        ids.setdefault(kl, v.strip())
                    elif kl in ("positionurl", "pcurl", "detailurl", "joburl",
                                "posturl", "h5url", "url", "link") and v.startswith("http"):
                        link = v
                    elif kl in desc_keys and len(v.strip()) >= 30:
                        desc = v.strip()
                    elif kl in city_keys and not cities:
                        # B 站等接口的城市是字符串（如 workLocation="上海"）
                        cities = [v.strip()]
                elif isinstance(v, (str, int)) and kl in id_keys and str(v).strip():
                    ids.setdefault(kl, str(v).strip())
                elif isinstance(v, list) and kl in ("citylist", "cities", "workcitylist"):
                    cities = [c.get("name", "") for c in v
                              if isinstance(c, dict) and c.get("name")]
            jid = next((ids[k] for k in id_keys if ids.get(k)), "")
            if name and (jid or link) and self._looks_like_job_name(name):
                if not (link and any(x.get("url") == link for x in found)) and \
                        not (jid and any(x.get("id") == jid for x in found)):
                    found.append({
                        "title": name, "id": jid, "ids": ids,
                        "url": link or "", "city": "、".join(cities),
                        "description": desc,
                    })
            for v in node.values():
                self._walk_jobs_json(v, found, depth + 1)
        elif isinstance(node, list):
            # 列表分支原来硬编码 node[:80]：一个 200 条的职位列表会被砍到 80 条。
            # 上限统一走 max_api_objects（成本上限，可配置）。
            for v in node[: max(1, self.max_api_objects)]:
                self._walk_jobs_json(v, found, depth + 1)


    def _looks_like_job_name(self, name: str) -> bool:
        """排除枚举/分类/城市等非职位名"""
        n = (name or "").strip()
        if len(n) < 4 or len(n) > 40:
            return False
        if n in ("社会招聘", "校园招聘", "应届生", "实习生", "正式", "北京", "上海"):
            return False
        if n.endswith(("类", "招聘", "计划", "专栏")) and len(n) <= 6:
            return False
        occ = ("工程师", "开发", "研发", "技术", "运维", "前端", "后端", "全栈",
               "客户端", "安全", "算法", "测试", "经理", "专员", "设计师", "运营",
               "产品", "分析师", "研究员", "主管", "总监", "顾问", "专家", "架构师",
               "营销", "品牌", "销售", "商务", "策划", "公关", "人力资源", "人事",
               "行政", "财务", "法务", "采购", "供应链", "客服", "编辑", "教师",
               "engineer", "developer", "manager", "intern", "designer",
               "specialist", "analyst", "scientist", "lead", "director",
               "marketing", "sales", "brand", "frontend", "backend", "devops")
        # 任何长度都必须含岗位词，过滤地址/分类/枚举对象
        if not any(w in n.lower() for w in occ):
            return False
        return True

    def _build_company_job_url(self, page_url: str, item: Dict) -> str:
        """根据招聘站主机与接口返回的职位 ID/链接构造详情页 URL（兼容旧调用名）"""
        return self._build_detail_url(page_url, item)

    def _build_detail_url(self, page_url: str, item: Dict) -> str:
        """
        由「列表页 URL + 接口职位对象」构造详情页 URL。

        - 接口自带绝对链接时优先用；
        - 否则按主机匹配 DETAIL_URL_TEMPLATES（模板全部实测能渲染出 JD 正文）；
        - 未知站点返回空串：宁可不入库，也不给一个打不开的假 URL
          （之前 B 站模板多写 /detail 会被重定向到首页，JD 抓取必然失败）。
        """
        link = (item.get("url") or "").strip()
        if link.startswith("http") and not self._same_list_page(link, page_url):
            return link
        jid = ""
        ids = item.get("ids") or {}
        try:
            host = (urlparse(page_url).netloc or "").lower()
        except Exception:
            host = ""
        # 有的站点详情页 URL 用的不是业务主键（北森用 guid、腾讯用 postId），实测确认过
        for site_key, pref_keys in DETAIL_ID_KEY_OVERRIDE.items():
            if site_key in host:
                jid = next((str(ids.get(k)) for k in pref_keys if ids.get(k)), "")
                break
        if not jid:
            jid = str(item.get("id") or "").strip()
        if not jid:
            return ""
        try:
            p = urlparse(page_url)
        except Exception:
            return ""
        host = (p.netloc or "").lower()
        blob = f"{p.path} {p.query} {p.fragment}".lower()
        seg = "campus" if "/campus" in blob else (
            "social" if any(k in blob for k in ("/social", "/society", "/experienced"))
            else None
        )
        for key, tpl in DETAIL_URL_TEMPLATES.items():
            if key not in host:
                continue
            tmpl = tpl.get(seg) or tpl.get(None)
            if not tmpl:
                return ""
            try:
                return tmpl.format(
                    id=jid,
                    base=f"{p.scheme}://{p.netloc}{p.path}",
                    scheme=p.scheme or "https", host=p.netloc,
                    seg=seg or "campus",
                )
            except Exception:
                return ""
        return ""

    def _jobs_from_api(self, api_items: List[Dict], list_url: str,
                       target_info, company: str, location: str,
                       seen: set, limit: int, strict: bool = False) -> List[Dict]:
        """
        接口通道：列表 XHR 里的职位对象 -> 详情页 URL（模板构造）。

        strict=True（聚合门户）：接口职位也按方向相关性过滤。
        _rank_api_jobs 在没有命中时会「全保留」兜底，那是给公司官网用的；
        对猎聘/前程无忧这种全网列表，兜底会把「质量工程师/机械结构工程师」
        这类无关岗位一起塞进结果。
        """
        out: List[Dict] = []
        if limit <= 0 or not api_items:
            return out
        for item in self._rank_api_jobs(
            api_items, getattr(target_info, "title_keywords", None)
        ):
            title = (item.get("title") or "").strip()
            if not title or self._is_nav_text(title):
                continue
            if strict and not self._title_relevant(title, target_info):
                continue
            href = self._build_detail_url(list_url, item)
            if not href or self._same_list_page(href, list_url):
                continue
            if not self._mark_seen(seen, href):
                continue
            out.append({
                "url": href, "title": title[:80], "company": company,
                "location": item.get("city") or location,
                # 接口列表已带 JD 正文时直接保留，免去详情页二次抓取
                "description": item.get("description") or "",
                "source": "browser_api", "title_score": 10,
            })
            if len(out) >= limit:
                break
        if out:
            logger.info(f"接口通道补齐 {len(out)} 个职位")
        return out

    # ------------------------------------------------------------------ #
    # 卡片点击通道（SPA 职位卡片不是 <a href> 时）
    # ------------------------------------------------------------------ #
    async def _jobs_from_cards_by_click(self, page, list_url: str, target_info,
                                        company: str, location: str, seen: set,
                                        limit: int,
                                        prefer_titles: List[str] = None,
                                        skip_titles: List[str] = None) -> List[Dict]:
        """
        扫描 DOM 职位卡片（div + 点击事件，而非 <a href>），点击卡片读回真实详情页 URL。

        只点「标题与目标方向相关」的卡片，且要求点击后 URL 真的像详情页
        （否则说明点到了筛选/类别标签，直接丢弃并回到列表页），
        保证了不会点到「投递/申请」这类按钮。
        """
        out: List[Dict] = []
        if limit <= 0:
            return out
        # 已经由锚点/接口通道收过的职位不用再点一遍
        skip_titles = {self._clean_job_title(t).lower()
                       for t in (skip_titles or []) if t}
        tried = set()
        clicks = 0
        max_clicks = max(limit, min(self.max_card_clicks, limit * 3))

        while len(out) < limit and clicks < max_clicks:
            try:
                cards = await page.evaluate(CARD_SCAN_JS)
            except Exception as e:
                logger.debug(f"卡片扫描失败: {e}")
                break
            pool = [c for c in cards
                    if c.get("text") and c["text"] not in tried
                    and self._clean_job_title(c["text"]).lower() not in skip_titles
                    and self._card_relevant(c["text"], target_info)]
            if not pool:
                break
            # 接口已经给出准确的职位名时，优先点这些标题对应的卡片
            prefer = [t for t in (prefer_titles or []) if t]
            if prefer:
                exact = [c for c in pool
                         if any(t[:10] in c["text"] or c["text"][:10] in t for t in prefer)]
                if exact:
                    pool = exact
            card = pool[0]
            tried.add(card["text"])

            url = card.get("href") or ""
            if url and not self._looks_like_detail_url(url):
                url = ""
            if not url:
                clicks += 1
                url = await self._click_card_and_read_url(
                    page, f'[data-dsh-card="{card["idx"]}"]', list_url
                )
            if (not url or self._looks_non_job(url)
                    or self._same_list_page(url, list_url)):
                continue
            if not self._mark_seen(seen, url):
                continue
            out.append({
                "url": url,
                "title": self._clean_job_title(card["text"])[:80],
                "company": company,
                "location": location, "description": "",
                "source": "browser_click", "title_score": 10,
            })

        if out:
            logger.info(f"卡片点击通道补齐 {len(out)} 个职位")
        return out

    def _card_relevant(self, text: str, target_info) -> bool:
        """卡片标题是否值得点：像职位名 + 与目标方向相关，排除筛选/类别标签"""
        t = (text or "").strip()
        if len(t) < 4 or len(t) > 40:
            return False
        if t.endswith(("；", "。", "，", ",", ";", "：", ":")):
            return False
        # 「程序&技术类」「实习生招聘」「校招职位」这类筛选/类别标签不是职位
        if t.endswith(("类", "招聘", "职位")) and len(t) <= 10:
            return False
        if self._is_nav_text(t):
            return False
        if any(w in t for w in _JOB_TITLE_WORDS):
            return self._title_relevant(t, target_info)
        return self._title_relevant(t, target_info)

    def _title_relevant(self, title: str, target_info) -> bool:
        """
        标题是否命中目标方向词族 / 岗位方向词。

        只用「能区分方向的词」（role_direction_words + 方向词族），不含
        「工程师/开发」这类通用岗位词，也不用跨词边界的二元组碎片：
        否则搜 AI 方向时，「个人护理产品创新研发工程师」会因为含「发工」
        被判成相关，聚合门户的无关岗位就会混进结果。
        """
        t = self._clean_job_title(title).lower()
        if not t:
            return False
        kws = [str(k).lower() for k in
               (getattr(target_info, "title_keywords", None) or []) if k]
        if any(self._kw_hit(t, k) for k in kws):
            return True
        words = role_direction_words(
            getattr(target_info, "role", "") or "",
            getattr(target_info, "keywords", None),
            getattr(target_info, "role_variants", None),
        )
        if not words and not kws:
            # 岗位输入太模糊（例如只写了「工程师」）：没有可判定的方向，不做否判定
            return True
        return any(self._kw_hit(t, w) for w in words)

    async def _click_card_and_read_url(self, page, selector: str, list_url: str) -> str:
        """
        点一张卡片，读回它跳转到的详情页 URL（新标签页或同页/hash 路由），随后回到列表页。

        拿不到「像详情页」的 URL 时返回空串（例如点到了筛选标签）。
        """
        before = page.url
        url = ""
        popup = None
        try:
            try:
                async with self._context.expect_page(timeout=3000) as pi:
                    await page.click(selector, timeout=3000)
                popup = await pi.value
            except Exception:
                popup = None

            if popup is not None:
                try:
                    await popup.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
                await asyncio.sleep(1.0)
                url = popup.url or ""
                try:
                    await popup.close()
                except Exception:
                    pass
            else:
                await asyncio.sleep(1.2)
                url = page.url if page.url != before else ""
        except Exception as e:
            logger.debug(f"点击卡片失败 {selector}: {e}")
        finally:
            await self._restore_list_page(page, list_url)

        if url and not self._looks_like_detail_url(url):
            logger.debug(f"点击卡片得到的不是详情页，忽略: {url[:120]}")
            return ""
        return url

    async def _restore_list_page(self, page, list_url: str) -> None:
        """点击后把页面恢复到职位列表页，供下一次抓取"""
        if not list_url:
            return
        try:
            if page.url != list_url:
                try:
                    await page.go_back(wait_until="domcontentloaded", timeout=10000)
                except Exception:
                    pass
            if page.url != list_url:
                try:
                    await page.goto(list_url, wait_until="domcontentloaded",
                                    timeout=self.timeout_ms)
                    await self._settle_page(page, light=True)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"回到列表页失败 {list_url}: {e}")

    @staticmethod
    def _looks_like_detail_url(url: str) -> bool:
        """URL 是否具备职位详情页特征（用于剔除筛选标签/类别跳转）"""
        return bool(DETAIL_URL_RE.search(url or ""))

    @staticmethod
    def _same_list_page(url: str, list_url: str) -> bool:
        """两个 URL 是否指向同一个列表页（同站点同路径且不带详情页特征）"""
        if not url or not list_url:
            return False
        if BrowserJobFinder._looks_like_detail_url(url):
            return False
        try:
            a, b = urlparse(url), urlparse(list_url)
        except Exception:
            return False
        return (a.netloc.lower() == b.netloc.lower()
                and (a.path or "/").rstrip("/") == (b.path or "/").rstrip("/"))

    async def _goto_settle(self, page, href: Optional[str], label: str = "") -> bool:
        """跳转并等待渲染完成；href 为空时什么都不做"""
        if not href:
            return False
        try:
            await page.goto(href, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await self._settle_page(page)
            if label:
                logger.info(f"{label} {page.url}")
            return True
        except Exception as e:
            logger.debug(f"跳转失败 {href}: {e}")
            return False

    def _site_company_name(self, site_name: str, entry_url: str) -> str:
        """站点名优先，其次从域名猜一个公司名（用于报告展示）"""
        name = (site_name or "").strip()
        if name and name not in ("portal", "company_site"):
            return name
        return self._guess_company(self._host_of(entry_url))

    def _strict_relevance(self, entry_url: str) -> bool:
        """是否按「严格方向相关」处理（聚合门户的列表是全网岗位，不做兜底保留）"""
        host = self._host_of(entry_url)
        return any(d in host for d in STRICT_RELEVANCE_DOMAINS)

    async def _extract_jobs_from_portal(self, portal: Dict, target_info) -> List[Dict]:
        """打开单个招聘页（聚合门户或公司招聘页），抽取职位详情链接"""
        url = portal["url"]
        jobs = await self._discover_jobs_on_site(
            portal.get("title") or self._guess_company(url) or url, url, target_info,
            drill_list=bool(portal.get("drill_list")),
            # 只有「聚合门户」才把入口改写成站内搜索 URL；公司官网仍走类别+列表遍历
            portal_search=(portal.get("kind") == "portal"),
        )
        for job in jobs:
            # 门户标题推断出的公司名作为缺失时的兜底；接口/页面已给出公司名时保留
            if not job.get("company"):
                job["company"] = self._guess_company(portal.get("title", ""))
            if not job.get("description"):
                job["description"] = portal.get("snippet", "")
        logger.info(f"页面 {url} 抽取到 {len(jobs)} 个职位链接")
        return jobs

    async def _score_anchors(self, page, role_toks: List[str]) -> List:
        """抽取锚点并评分排序，返回 [(score, anchor)] 降序"""
        anchors = await self._collect_anchors(page)
        scored = []
        for a in anchors:
            score = self._score_anchor(a["text"], a["href"], role_toks)
            if score > 0:
                scored.append((score, a))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _prune_by_title_relevance(self, scored, title_keywords, keep_all_when_empty=True):
        """
        锚点候选 [(score, anchor)] 按方向词族筛标题：
        有相关职位时只保留相关（无关方向滤掉）；一个都不相关时整体兜底保留，
        交给 JD 匹配阶段细判（避免词族不全导致空结果）。

        聚合门户（Boss/猎聘/前程无忧）不兜底：它们列表里什么都可能有，
        兜底会把「复合材料研发工程师」这类无关岗位当成结果返回。
        """
        if not scored or not title_keywords:
            return scored
        kws = [str(k).lower() for k in title_keywords if k]

        def title_hits(a):
            head = self._clean_job_title(
                (a.get("text") or "").split("\n", 1)[0]
            ).lower()
            return sum(1 for k in kws if self._kw_hit(head, k))

        related = [(s, a) for s, a in scored if title_hits(a) > 0]
        if related:
            logger.info(f"标题方向筛选：{len(scored)} 个职位锚点 -> {len(related)} 个相关")
            return related
        if not keep_all_when_empty:
            logger.info(
                f"标题方向筛选：{len(scored)} 个职位锚点里没有命中方向词族的岗位，"
                f"该站按「严格相关」处理，不兜底保留"
            )
            return []
        logger.info("标题方向筛选：无标题命中方向词族，保留全部候选兜底")
        return scored

    def _rank_api_jobs(self, api_jobs, title_keywords):
        """XHR 接口职位按方向词族排序/筛选：有相关只留相关并按命中数降序，否则全保留"""
        if not api_jobs:
            return []
        if not title_keywords:
            return list(api_jobs)
        kws = [str(k).lower() for k in title_keywords if k]

        def hits(j):
            t = (j.get("title") or "").lower()
            return sum(1 for k in kws if self._kw_hit(t, k))

        related = [(hits(j), j) for j in api_jobs]
        kept = [(h, j) for h, j in related if h > 0]
        if kept:
            kept.sort(key=lambda x: x[0], reverse=True)
            return [j for _, j in kept]
        return list(api_jobs)
    @staticmethod
    def _looks_like_listing_url(url: str) -> bool:
        """判断是否为职位列表页（直达列表页不应再被「找招聘入口」逻辑导航走）"""
        try:
            p = urlparse((url or "").lower())
            path, netloc = p.path or "", p.netloc or ""
        except Exception:
            return False
        if not netloc:
            return False
        # 介绍/帮助/首页不是列表页
        if any(h in path for h in ("/join.html", "/join.htm", "/about", "/help",
                                   "/index.", "/home")):
            return False
        # 数字 ID 详情页不是列表页
        if re.search(r"/(position|job)s?/\d+", path):
            return False
        list_hints = ("/positions", "/jobs", "/joblist", "/job-list", "/vacancies",
                      "/recruit", "/campus", "/social", "/experienced", "/hire",
                      # 聚合门户的「列表/搜索页」路径：Boss 的 /web/geek/job、
                      # 猎聘的 /zhaopin/。它们在 URL 上不像列表页，但一进去就是
                      # 岗位列表，同样不该再被类别导航带走。
                      "/geek/job", "/zhaopin", "/searchjob", "/joblist")
        blob = f"{netloc}{path}?{p.query}"
        return any(h in blob for h in list_hints)


    async def _try_role_search(self, page, role: str) -> bool:
        """招聘站带搜索框时，输入目标岗位触发站内检索"""
        if not role:
            return False
        selector = (
            "input[type='search'], input[placeholder*='搜索'], input[placeholder*='岗位'], "
            "input[placeholder*='Search'], input[placeholder*='search'], "
            "input[name*='keyword' i], input[name*='search' i], input[aria-label*='Search' i]"
        )
        try:
            box = await page.query_selector(selector)
            if not box or not await box.is_visible():
                return False
            await box.click(timeout=3000)
            await box.fill(role[:30], timeout=3000)
            await box.press("Enter", timeout=3000)
            await asyncio.sleep(2.5)
            logger.info(f"已在站内搜索框输入岗位: {role}")
            return True
        except Exception:
            return False

    async def _settle_page(self, page, light: bool = False):
        """等待页面渲染完成并滚动加载"""
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(1.0 if light else self.page_settle_ms / 1000)
        if light:
            return
        for _ in range(2):
            try:
                await page.mouse.wheel(0, 1200)
                await asyncio.sleep(0.6)
            except Exception:
                break

    async def _safe_inner_text(self, page) -> str:
        try:
            return await page.inner_text("body")
        except Exception:
            return ""

    async def _handle_block(self, url: str, page, kind: str = "captcha",
                            detail: str = "", force: bool = False) -> bool:
        """
        遇到登录墙 / 验证码 / AI 无法操作：统一交给 BlockHandler。

        Returns:
            True  -> 用户已手动处理，继续当前站点
            False -> 跳过当前站点
        """
        return await self.block_handler.handle(kind, url, detail, force=force)

    async def _wait_if_blocked(self, page, url: str) -> bool:
        """
        进门前先查登录墙/验证码：被挡住就立刻停下等人处理，
        在用户完成前**不点任何东西**（避免在登录弹窗上乱点导致浏览器闪烁）。

        判定标准是「页面到底能不能用」而不是「正文里有没有验证码这几个字」：
        智联招聘这类站点正常页面里也带着验证组件/登录入口文案，
        一出现就当被挡会让一个明明有 150+ 职位链接的页面被整站跳过，
        结果就是「抽取到 0 个职位」。

        Returns:
            True  -> 仍被挡住（用户选择 skip / 无头模式 / 处理不彻底），调用方应跳过本站
            False -> 没被挡 / 用户已处理且确认通行，可继续操作页面
        """
        kind = await self._page_looks_blocked(page)
        if not kind:
            return False
        ok = await self._handle_block(
            url, page, kind=kind,
            detail="页面需要登录或出现验证，请在浏览器里手动完成，"
                   "完成前 Agent 不会再操作这个页面",
        )
        if not ok:
            return True
        # 复核：用户说处理完了，但页面可能还是原来那道墙 —— 再问一次，不要静默跳过
        try:
            await self._settle_page(page, light=True)
        except Exception:
            pass
        again = await self._page_looks_blocked(page)
        if not again:
            return False
        ok = await self._handle_block(
            url, page, kind=again, force=True,
            detail="处理后页面仍像登录墙/验证页。请再完成操作后回车，或输入 skip 跳过本站",
        )
        if not ok:
            return True
        try:
            await self._settle_page(page, light=True)
        except Exception:
            pass
        still = await self._page_looks_blocked(page)
        if still:
            logger.warning(f"两次确认后页面仍不可用，跳过本站：{url}")
            return True
        return False

    async def _page_looks_blocked(self, page) -> str:
        """
        页面是否真的不可用：返回 'captcha' / 'login' / ''。

        判定顺序（尽可能少地误伤正常页面）：
        1) 页面上已经有足够多的职位链接（说明列表已渲染出来）→ 直接认为可用。
           智联/Boss 这类站点正常页面里也带着验证组件与「短信验证码登录」入口，
           只按文案判会把一个明明有 150+ 职位链接的页面整站跳过。
        2) 正文命中「强」验证墙特征（请完成安全验证/滑动验证/unusual traffic…）
           → 判定 captcha。
        3) 正文只命中弱特征（例如「验证码」三个字）时，**必须**同时满足
           「DOM 里真的有验证控件」或「DOM 里有密码输入框（登录弹窗）」才算被挡。
        4) 登录墙只认 DOM 证据（存在密码输入框且没有职位列表），不再按
           「扫码登录」这类页眉文案判定。
        """
        job_links = await self._job_link_count(page)
        if job_links >= 5:
            return ""
        body = await self._safe_inner_text(page)
        if job_links == 0 and len(body) < 200:
            # 内容都没有：可能是空白/跳转页，交给后续流程处理
            return ""
        low = (body or "").lower()
        if any(h.lower() in low for h in STRONG_CAPTCHA_HINTS):
            return "captcha"

        probe = await self._block_probe(page)
        if job_links == 0 and probe.get("password_inputs"):
            # 有密码框、又几乎没有职位链接：真正的登录墙
            return "login"
        if self._has_captcha_or_wall(body):
            if probe.get("captcha_inputs") or probe.get("captcha_boxes"):
                return "captcha"
            logger.info("页面正文含验证字样，但 DOM 里没有验证控件/密码框，按正常页面继续")
            return ""
        if self._looks_login_wall(body) and probe.get("login_forms"):
            return "login"
        return ""

    async def _block_probe(self, page) -> Dict:
        """
        用 DOM 证据回答「这道墙是不是真的」：数密码框、验证码输入框、验证控件、登录表单。

        只读计数、不点击任何东西。任何一步失败都按 0 计（宁可不判被挡，也不误伤）。
        """
        out = {"password_inputs": 0, "captcha_inputs": 0, "captcha_boxes": 0,
               "login_forms": 0}
        for key, selector in _BLOCK_PROBE_SELECTORS.items():
            try:
                n = await page.eval_on_selector_all(selector, "els => els.length")
                out[key] = int(n or 0)
            except Exception:
                out[key] = 0
        return out


    async def _job_link_count(self, page) -> int:
        """页面上「像职位详情」的链接数量（用于判断列表是否真的渲染出来了）"""
        try:
            hrefs = await page.eval_on_selector_all(
                "a[href]", "els => els.slice(0, 800).map(e => e.href || '')"
            )
        except Exception:
            return 0
        return sum(1 for h in hrefs
                   if JOB_DETAIL_RE.search(h) or self._looks_like_detail_url(h))

    # ================================================================== #
    # 评分 / 匹配 / 文本工具
    # ================================================================== #
    def _role_tokens(self, target_info: TargetInstructionSchema) -> List[str]:
        """从目标岗位 + 变体 + 关键词中拆出用于模糊匹配的 token"""
        return role_tokens(
            target_info.role,
            target_info.keywords,
            getattr(target_info, "role_variants", None),
        )

    def _fallback_role_terms(self, target_info: TargetInstructionSchema) -> List[str]:
        """站内搜索框可用的岗位词序列（主岗位名在前，变体在后）"""
        return query_terms(target_info, limit=3) or []

    def _score_anchor(self, text: str, href: str, role_toks: List[str],
                      title_keywords=None) -> int:
        """给单个锚点评分，>0 才认为是职位链接（只取首行职位名参与评分）"""
        head = (text or "").split("\n", 1)[0].strip()
        t = head.lower()
        h = href.lower()
        if len(head) < 2 or len(head) > 120:
            return 0
        score = 0
        if any(hint in h for hint in JOB_URL_HINTS):
            score += 3
        if any(tok in t for tok in ["工程师", "开发", "设计师", "产品经理", "运营",
                                    "架构师", "分析师", "研究员", "实习", "engineer",
                                    "developer", "designer", "manager"]):
            score += 3
        hit_tokens = [tok for tok in role_toks if tok in t]
        score += 2 * len(hit_tokens)
        # 方向词族（如 AI: 大模型/LLM/算法）命中越多，标题相关度越高
        if title_keywords:
            dir_hits = [str(k).lower() for k in title_keywords if str(k).lower() in t]
            score += 2 * len(dir_hits)
        if score == 0:
            return 0
        if self._looks_non_job(href) or any(x in t for x in ["登录", "注册", "下载", "帮助"]):
            return 0
        return score

    def _looks_job_portal(self, url: str, title: str, snippet: str) -> bool:
        blob = f"{url} {title} {snippet}".lower()
        if self._looks_non_job(url):
            return False
        portal_words = [
            "招聘", "职位", "岗位", "招人", "校招", "社招", "人才",
            "career", "job", "hire", "hiring", "vacancy", "position", "talent",
        ]
        return any(w in blob for w in portal_words)

    def _looks_non_job(self, url: str) -> bool:
        u = (url or "").lower()
        return any(hint in u for hint in NON_JOB_HINTS)

    @staticmethod
    def _host_hits(url: str, domains) -> bool:
        """主机名匹配：完整域名要求 host 相等或为其子域；
        query 不参与匹配，避免 ?ref=jd.com、fox.com 含 x.com 这类子串误伤"""
        try:
            p = urlparse((url or "").lower())
            host, path = p.netloc or "", p.path or ""
        except Exception:
            return False
        if not host:
            return False
        for raw in domains:
            d = raw.lower().rstrip(".")
            if "." in d:
                if host == d or host.endswith("." + d):
                    return True
            elif d and (d in host or d in path):
                # 非完整域名的启发词（如 baike/wiki），只匹配主机与路径
                return True
        return False

    def _is_aggregator(self, url: str) -> bool:
        return self._host_hits(url, AGGREGATOR_DOMAINS)

    def _url_has_career_hint(self, url: str) -> bool:
        p = urlparse((url or "").lower())
        if self._host_has_career_prefix(p.netloc):
            return True
        return any(h in p.path for h in CAREER_URL_HINTS)

    def _host_has_career_prefix(self, host: str) -> bool:
        host = (host or "").lower().replace("www.", "")
        return any(host.startswith(p) for p in CAREER_SUBDOMAIN_PREFIXES)

    def _is_junk(self, url: str) -> bool:
        return self._host_hits(url, JUNK_DOMAINS)

    def _is_junk_title(self, title: str) -> bool:
        t = (title or "")
        junk_words = ["公告", "简章", "宣讲会", "是干什么", "兼职", "是做什么",
                      "面经", "经验贴", "教程", "怎么", "如何", "r/", "latest "]
        return any(w.lower() in t.lower() for w in junk_words)

    def _portal_score(self, url: str, title: str) -> int:
        """门户排序：国内垂直招聘平台优先，其次公司自有招聘站"""
        u = (url or "").lower()
        t = (title or "").lower()
        score = 0
        for i, d in enumerate(CN_JOB_PLATFORMS):
            if d in u:
                score += 20 - i
        if self._url_has_career_hint(url):
            score += 8
        if any(w in t for w in ["招聘", "职位", "career", "job"]):
            score += 2
        return score

    def _guess_company(self, portal_title: str) -> str:
        """从门户标题粗略推断公司名（无法确定时返回空串）"""
        return re.split(r"[-_|–—]", (portal_title or "").strip())[0].strip()

    def _clean_company_name(self, title: str) -> str:
        """从搜索结果标题提取公司名（去掉官网/招聘等后缀噪声）"""
        name = (title or "").strip()
        name = re.split(r"[-_|–—,，|]", name)[0].strip()
        for noise in ["官网", "官方网站", "首页", "招聘", "百度百科", "百科"]:
            name = name.replace(noise, "")
        return name.strip()

    def _homepage_of(self, url: str) -> str:
        """把任意深层 URL 收敛为站点根 URL"""
        p = urlparse(url)
        if not p.scheme or not p.netloc:
            return url
        return f"{p.scheme}://{p.netloc}/"

    def _host_of(self, url: str) -> str:
        return urlparse(url).netloc.replace("www.", "")

    def _has_captcha_or_wall(self, body_text: str) -> bool:
        b = (body_text or "").lower()
        return any(hint.lower() in b for hint in CAPTCHA_HINTS)

    # 登录墙特征（正文出现这些词，且不是页面页眉的普通“登录”入口）
    _LOGIN_WALL_HINTS = (
        "请先登录", "登录后查看", "登录后继续", "登录后即可", "请登录后",
        "扫码登录", "账号密码登录", "登录/注册后查看", "sign in to continue",
        "please log in", "log in to view",
    )

    def _looks_login_wall(self, body_text: str) -> bool:
        b = (body_text or "").lower()
        if not b:
            return False
        return any(hint in b for hint in self._LOGIN_WALL_HINTS)
