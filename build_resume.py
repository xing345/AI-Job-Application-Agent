# -*- coding: utf-8 -*-
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import ParagraphStyle

pdfmetrics.registerFont(TTFont("CN", r"C:\Windows\Fonts\msyh.ttc", subfontIndex=0))
pdfmetrics.registerFont(TTFont("CNB", r"C:\Windows\Fonts\msyhbd.ttc", subfontIndex=0))

NAVY = HexColor("#1F3A5F")
GREY = HexColor("#555555")
LINE = HexColor("#BBBBBB")
INK = HexColor("#222222")

PAGE_W, PAGE_H = A4
LM = RM = 16*mm
TM = BM = 13*mm
CONTENT_W = PAGE_W - LM - RM

styles = {
    "name": ParagraphStyle("name", fontName="CNB", fontSize=20, leading=24, textColor=NAVY, spaceAfter=1),
    "meta": ParagraphStyle("meta", fontName="CN", fontSize=9, leading=13, textColor=GREY),
    "h": ParagraphStyle("h", fontName="CNB", fontSize=12, leading=15, textColor=NAVY, spaceBefore=6, spaceAfter=2),
    "body": ParagraphStyle("body", fontName="CN", fontSize=9, leading=13.5, textColor=INK, wordWrap="CJK", spaceAfter=1),
    "bullet": ParagraphStyle("bullet", fontName="CN", fontSize=9, leading=13.5, textColor=INK, wordWrap="CJK", leftIndent=11, bulletIndent=1, spaceAfter=1),
}

# 标题行：左 项目名(粗)+技术栈(灰)，右 时间(右对齐)
_h_name = ParagraphStyle("h_name", fontName="CNB", fontSize=10, leading=13.5, textColor=INK)
_h_stack = ParagraphStyle("h_stack", fontName="CN", fontSize=8.4, leading=11.5, textColor=GREY)
_h_date = ParagraphStyle("h_date", fontName="CN", fontSize=9, leading=13.5, textColor=GREY, alignment=2)

def sec(t):
    return [Paragraph(t, styles["h"]), HRFlowable(width="100%", thickness=0.6, color=LINE, spaceAfter=3)]

def b(t):
    return Paragraph(t, styles["bullet"], bulletText="•")

def header_row(name, stack, date):
    left = Paragraph(f'<b>{name}</b>', _h_name)
    if stack:
        left = [left, Paragraph(stack, _h_stack)]
    t = Table(
        [[left, Paragraph(date, _h_date)]],
        colWidths=[CONTENT_W - 30*mm, 30*mm],
    )
    t.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "BOTTOM"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 1),
    ]))
    return t

story = []
story.append(Paragraph("张亚辉", styles["name"]))
story.append(Paragraph("出生年月：2005.04　民族：汉　身高：180cm　政治面貌：共青团员", styles["meta"]))
story.append(Spacer(1, 4))

story += sec("个人简介")
story.append(Paragraph("软件工程专业学生，习惯把对新技术的兴趣落到代码和项目中：会自建环境、调接口、写脚本并验证方案。已完成 AI Agent、Java/Spring Boot 后端与 Vue/uni-app 小程序、Cocos 小游戏，以及 Solidity、FISCO BCOS、IPFS 访问控制研究支持；持续通过动手实现理解系统并复盘实践。", styles["body"]))

story += sec("理论基础")
story.append(Paragraph("具备数据结构与算法、计算机网络、操作系统、数据库、软件工程、面向对象程序设计等计算机基础理论，能够将基础概念用于项目中的数据建模、流程设计、接口交互和模块拆分。", styles["body"]))

story += sec("教育背景")
story.append(header_row("重庆移通学院 | 软件工程本科", "", "2023.09 - 至今"))
story.append(Paragraph("围绕 AI 应用、后端工程与区块链安全开展项目实践和科研训练。", styles["body"]))

story += sec("技术能力")
tech = [
    ("编程语言", "Python、Java、C、C++、JavaScript、TypeScript"),
    ("AI / LLM / Agent", "LLM API、AI Agent、LangGraph、Prompt Engineering、Pydantic"),
    ("后端开发", "Spring Boot、MyBatis、Django、Java 后端、Python 异步编程、REST 风格 API"),
    ("前端开发", "Vue 2、uni-app、HTML、CSS、Cocos Creator 3.8.8"),
    ("数据库", "MySQL、SQLite"),
    ("区块链", "Solidity、FISCO BCOS、Hyperledger Fabric、智能合约、属性/角色访问控制、联盟链配置"),
    ("存储与分布式", "IPFS、CID、链上链下协同存储"),
    ("工程组件 / 工具", "Spring Security/JWT、Redis、Druid、Swagger、七牛云、Playwright、Streamlit、Web3.js、Node.js"),
]
for k, v in tech:
    story.append(Paragraph(f"<b>{k}：</b>{v}", styles["bullet"], bulletText="•"))

story += sec("项目经历")

story.append(header_row("AI 智能求职 Agent", "Python / LangGraph / Playwright / LLM API / SQLite / Streamlit", "2026.08 - 2026.09"))
story.append(b("<b>Agent 编排：</b>将简历、目标岗位与匹配结果建模为 Pydantic v2 结构，用 LangGraph StateGraph 串联简历解析、岗位发现、JD 抓取、LLM 匹配、浏览器填报与人工审批，条件边路由到完成/失败分支，全程日志可追溯。"))
story.append(b("<b>岗位发现与三通道抓取：</b>按招聘官网分类导航逐页遍历（默认关闭 Tavily 关键词搜索），实现“列表锚点→列表 XHR 接口→DOM 卡片点击”三通道定位详情页链接，解决国内校招站职位卡片非超链接问题；先按职位标题/方向初筛，再开详情页用 LLM-as-a-Judge 按技术栈、经验、职业方向多维打分（阈值 70），JD 抓不到时以标题兜底、全军覆没时降级返回最接近岗位。"))
story.append(b("<b>自动化与 HITL：</b>Playwright 异步渲染并持久化浏览器用户数据目录，实现登录态跨阶段/跨轮复用；智能表单填充支持断点续填，缺失字段经人工确认后写入 SQLite 记忆库下次自动带出；单轮 JD 评估上限 40 个、3 路并发抓取（可见浏览器收敛为 2 个标签页）；遇登录墙/验证码/被拦截时由 BlockHandler 停下汇报、手动处理后从断点续跑，最终“提交/投递”按钮按红线绝不自动点击。"))
story.append(b("<b>自反思与可视化：</b>经 IMAP 监听拒信邮件，LLM 做根因分析并生成搜索过滤、权重调整、画像更新类策略规则持久化到 SQLite；Streamlit + Plotly 输出投递漏斗、匹配分布与反思日志面板。"))

story.append(header_row("郭扶镇旅游综合服务小程序与管理后台", "项目负责人 / Java / Spring Boot / MyBatis / Vue / uni-app / MySQL", "2025.06 - 2025.10"))
story.append(b("<b>系统推进与架构：</b>负责项目推进并参与前后端开发；项目由 Spring Boot 多模块后端、Vue 管理后台和 uni-app 微信小程序组成，采用 Controller-Service-Mapper 分层与 MySQL 持久化。"))
story.append(b("<b>业务开发与集成：</b>参与微信登录、景点/民宿、采摘预约、游记、评论/收藏和地图点位的接口与页面开发；/mini 控制层含 65 个请求映射，统一请求层处理 Authorization 与异常跳转，后端集成 JWT、Redis、Druid 和七牛云上传。用户规模与上线数据待确认。"))

story.append(header_row("2D 像素双人射击游戏原型（NewProject）", "TypeScript / Cocos Creator 3.8.8", "2026.05 - 2026.06"))
story.append(b("<b>地图生成：</b>实现默认 20×20 网格、支持固定种子复现的地图生成器，包含边缘围墙、障碍/掩体密度控制和中心 3×3 出生保护区。"))
story.append(b("<b>交互与碰撞：</b>设计 getTileTypeAt、worldToGrid、gridToWorld、isWalkable 和 isBulletBlocking 接口，并实现 WASD/方向键双人控制、对角线归一化、分轴移动和四角碰撞检测。"))
story.append(b("<b>素材整理：</b>通过 Pillow 素材脚本将 212 个像素素材整理为地砖、角色、武器/道具和特效四类。"))

story.append(header_row("区块链访问控制与链上链下存储技术支持（论文配套）", "Solidity / FISCO BCOS / IPFS / Node.js", "2025 - 至今"))
story.append(b("<b>访问控制合约：</b>围绕角色、属性必选标记、背书者和事件权限设计数据结构与校验流程，完成 addRole、addUser、addEvent、validateAccess 等实验性 Solidity 实现。"))
story.append(b("<b>联盟链部署：</b>参与 FISCO BCOS 本地节点、机构与 Group 1/2/3 配置，结合编译产物和部署日志验证 HelloIPFS 及 AttributeBasedAccessControl 合约。"))
story.append(b("<b>链上链下实验：</b>使用 Node.js 与 ipfs-http-client 上传文件并获取 CID，再通过 Web3/控制台执行链上写入、查询和 IPFS 下载；另设仅链上模拟 CID 基线与 1KB-5MB 文件测试，属于实验性实现。"))

story += sec("科研、论文与专利")
story.append(b("<b>链上链下存储研究：</b>技术支持《区块链赋能的 ISAC 基站数据安全：细粒度访问控制与链上-链下协同存储》，参与通感一体物理层安全研究及链上-链下存储设计，以降低数据访问延迟；状态：待确认。"))
story.append(b("<b>隐私访问控制研究：</b>技术支持《基于智能合约的隐私安全保护与细粒度访问控制模型研究》，开发支撑智能合约、生成实验数据并参与角色与属性双重验证机制研究；已在知网公开发表。"))
story.append(b("<b>专利申请：</b>《基于区块链的公共区域隐私数据访问控制方案》，申请号：2025.04.25.0002；当前状态：待确认。"))

story += sec("技术兴趣")
story.append(Paragraph("喜欢因问题和好奇心主动研究新技术，并通过搭环境、写代码、做实验和小项目验证想法。当前兴趣集中在 AI Agent、LLM 自动化、联盟链、智能合约、IPFS 链上链下存储，以及 Cocos 小游戏开发。", styles["body"]))

out = r"D:\x\简历\张亚辉简历_更新版.pdf"
doc = BaseDocTemplate(out, pagesize=A4, leftMargin=LM, rightMargin=RM, topMargin=TM, bottomMargin=BM)
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
doc.addPageTemplates([PageTemplate(id="p", frames=[frame])])
doc.build(story)
print("OK", out)
