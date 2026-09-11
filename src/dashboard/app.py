"""
AI Job Agent Dashboard - Agent指挥中心
基于Streamlit的实时监控大盘
"""

import sqlite3
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
from pathlib import Path

# 页面配置
st.set_page_config(
    page_title="AI Job Agent Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义CSS
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .success { color: #28a745; }
    .warning { color: #ffc107; }
    .danger { color: #dc3545; }
    .info { color: #17a2b8; }
</style>
""", unsafe_allow_html=True)

def init_db():
    """初始化数据库表"""
    db_path = Path(__file__).parent.parent.parent / "data" / "agent_state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # 创建job_applications表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS job_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        company_name TEXT NOT NULL,
        job_title TEXT NOT NULL,
        match_score REAL,
        status TEXT DEFAULT 'PENDING',
        url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        error_message TEXT,
        search_source TEXT
    )
    ''')

    # 创建reflections表 - 自反思日志
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reflections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER,
        failure_reason_category TEXT,
        root_cause_analysis TEXT,
        actionable_advice TEXT,
        should_update_persona BOOLEAN,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (application_id) REFERENCES job_applications (id)
    )
    ''')

    # 创建strategy_rules表 - 动态策略规则
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS strategy_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_type TEXT,
        rule_content TEXT,
        confidence_score REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_used TIMESTAMP,
        is_active BOOLEAN DEFAULT 1
    )
    ''')

    # 创建job_search_log表 - 搜索结果日志 (供「找到的岗位」视图)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS job_search_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT,
        title TEXT,
        company TEXT,
        description TEXT,
        match_score REAL,
        searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()
    return db_path

@st.cache_data(ttl=60)
def load_applications_data():
    """加载申请数据"""
    db_path = init_db()
    try:
        conn = sqlite3.connect(str(db_path))
        query = """
        SELECT * FROM job_applications
        ORDER BY updated_at DESC
        LIMIT 1000
        """
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"加载数据失败: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_reflections_data():
    """加载反思数据"""
    db_path = init_db()
    try:
        conn = sqlite3.connect(str(db_path))
        query = """
        SELECT r.*, ja.company_name, ja.job_title
        FROM reflections r
        JOIN job_applications ja ON r.application_id = ja.id
        ORDER BY r.created_at DESC
        LIMIT 50
        """
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"加载反思数据失败: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_strategy_rules():
    """加载策略规则"""
    db_path = init_db()
    try:
        conn = sqlite3.connect(str(db_path))
        query = """
        SELECT * FROM strategy_rules
        WHERE is_active = 1
        ORDER BY last_used DESC, created_at DESC
        """
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"加载策略规则失败: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_search_log():
    """加载搜索结果日志 (找到的岗位)"""
    db_path = init_db()
    try:
        conn = sqlite3.connect(str(db_path))
        query = """
        SELECT * FROM job_search_log
        ORDER BY searched_at DESC
        LIMIT 500
        """
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"加载搜索结果失败: {e}")
        return pd.DataFrame()

def get_kpi_cards(df):
    """生成KPI卡片"""
    total_jobs = len(df)
    high_score_jobs = len(df[df['match_score'] >= 80]) if 'match_score' in df.columns else 0
    applied_jobs = len(df[df['status'] == 'APPLIED']) if 'status' in df.columns else 0
    interview_jobs = len(df[df['status'] == 'INTERVIEW_INVITE']) if 'status' in df.columns else 0
    success_rate = (interview_jobs / applied_jobs * 100) if applied_jobs > 0 else 0

    # 注: 无历史基线数据, 不展示伪造的增量
    return [
        {"title": "已发现岗位", "value": total_jobs, "delta": None, "type": "info"},
        {"title": "高分岗位 (>80)", "value": high_score_jobs, "delta": None, "type": "success"},
        {"title": "已投递", "value": applied_jobs, "delta": None, "type": "warning"},
        {"title": "面试邀请", "value": interview_jobs, "delta": f"成功率 {success_rate:.1f}%", "type": "success"},
    ]

def create_funnel_chart(df):
    """创建漏斗图"""
    if df.empty or 'status' not in df.columns:
        return None

    status_counts = df['status'].value_counts().reset_index()
    status_counts.columns = ['状态', '数量']

    # 重新排序以创建漏斗效果
    funnel_order = ['PENDING', 'APPLIED', 'INTERVIEW_INVITE', 'REJECTED', 'OFFER']
    status_counts['状态'] = pd.Categorical(status_counts['状态'], categories=funnel_order, ordered=True)
    status_counts = status_counts.sort_values('状态')

    fig = px.funnel(
        status_counts,
        x='数量',
        y='状态',
        title="投递漏斗转化率",
        labels={'数量': '数量', '状态': '流程阶段'}
    )
    fig.update_layout(
        yaxis={'categoryorder': 'array', 'categoryarray': funnel_order},
        showlegend=False
    )
    return fig

def create_match_score_distribution(df):
    """创建匹配分数分布图"""
    if df.empty or 'match_score' not in df.columns:
        return None

    fig = px.histogram(
        df,
        x="match_score",
        nbins=20,
        title="匹配分数分布",
        color_discrete_sequence=['#636EFA'],
        labels={"match_score": "匹配分数", "count": "数量"}
    )
    fig.update_layout(
        xaxis_title="匹配分数",
        yaxis_title="职位数量",
        bargap=0.1
    )
    return fig

def create_company_ranking(df):
    """创建公司排名图"""
    if df.empty or 'company_name' not in df.columns:
        return None

    company_counts = df['company_name'].value_counts().head(10).reset_index()
    company_counts.columns = ['公司名称', '职位数量']

    fig = px.bar(
        company_counts,
        x='职位数量',
        y='公司名称',
        orientation='h',
        title="热门公司TOP10",
        labels={'职位数量': '职位数量', '公司名称': '公司'},
        color_discrete_sequence=['#0088FE']
    )
    fig.update_layout(
        xaxis_title="职位数量",
        yaxis_title="公司名称",
        height=400
    )
    return fig

def create_timeline_chart(df):
    """创建时间线图"""
    if df.empty or 'created_at' not in df.columns:
        return None

    # 提取日期
    df['date'] = pd.to_datetime(df['created_at']).dt.date

    # 按日期统计
    daily_counts = df.groupby('date').size().reset_index(name='count')

    fig = px.line(
        daily_counts,
        x='date',
        y='count',
        title="每日发现/投递趋势",
        labels={'date': '日期', 'count': '数量'}
    )
    fig.update_traces(mode='markers+lines')
    fig.update_layout(
        xaxis_title="日期",
        yaxis_title="数量"
    )
    return fig

def display_reflections(reflections_df):
    """显示反思日志"""
    st.subheader("🧠 Agent自反思日志")

    if reflections_df.empty:
        st.info("暂无反思记录")
        return

    # 显示最近的反思
    latest_reflections = reflections_df.head(5)

    for _, row in latest_reflections.iterrows():
        with st.expander(f"反思 #{row['id']} - {row['company_name']} - {row['job_title']}"):
            st.markdown(f"""
            **时间**: {row['created_at']}

            **失败原因分类**: {row['failure_reason_category']}

            **根因分析**: {row['root_cause_analysis']}

            **行动建议**:
            """)

            # 格式化建议列表
            advice_list = json.loads(row['actionable_advice']) if isinstance(row['actionable_advice'], str) else row['actionable_advice']
            for i, advice in enumerate(advice_list, 1):
                st.markdown(f"  {i}. {advice}")

            st.markdown(f"""
            **是否需要更新画像**: {'是' if row['should_update_persona'] else '否'}
            """)

def display_strategy_rules(rules_df):
    """显示策略规则"""
    st.subheader("🎯 Agent学习规则")

    if rules_df.empty:
        st.info("暂无学习规则")
        return

    # 规则类型分组显示
    rule_types = rules_df['rule_type'].unique()

    for rule_type in rule_types:
        type_rules = rules_df[rules_df['rule_type'] == rule_type]

        with st.expander(f"{rule_type} ({len(type_rules)}条规则)"):
            for _, rule in type_rules.iterrows():
                st.markdown(f"""
                **规则内容**: {rule['rule_content']}

                **置信度**: {rule['confidence_score']:.2f}

                **最后使用**: {rule['last_used'] or '未使用'}
                """)

# 主界面
def main():
    # 标题和描述
    st.title("🤖 Autonomous Job Rover 指挥中心")
    st.markdown("*实时监控AI求职Agent的执行状态和学习过程*")

    # 侧边栏设置
    st.sidebar.header("📊 实时数据")

    # 加载数据
    with st.spinner("加载数据中..."):
        df_applications = load_applications_data()
        df_reflections = load_reflections_data()
        df_rules = load_strategy_rules()

    # KPI卡片
    st.subheader("📈 核心指标")
    kpi_cards = get_kpi_cards(df_applications)
    cols = st.columns(len(kpi_cards))

    for i, card in enumerate(kpi_cards):
        with cols[i]:
            st.metric(
                card["title"],
                card["value"],
                delta=card["delta"],
                delta_color="off"
            )

    # ============ 找到的岗位 ============
    st.markdown("---")
    st.subheader("🎯 找到的岗位")
    df_jobs = load_search_log()
    if not df_jobs.empty:
        has_score = 'match_score' in df_jobs.columns
        min_score = st.slider("最低匹配分", 0, 100, 60, key="job_min_score")

        # 降级批次提示：本轮没有达标岗位时，展示的是「最接近的岗位」而不是达标的
        if 'is_qualified' in df_jobs.columns and not df_jobs['is_qualified'].astype(bool).any():
            st.warning(
                "⚠️ 最近一轮搜索没有任何岗位达到匹配分门槛，下表是**最接近的岗位**，"
                "仅供参考，建议不要直接投递。可放宽岗位关键词或换个岗位方向重试。"
            )

        filtered = df_jobs[df_jobs['match_score'] >= min_score] if has_score else df_jobs
        if filtered.empty:
            st.info(f"当前筛选条件下没有岗位 (匹配分 ≥ {min_score})")
        else:
            st.caption(f"共找到 {len(df_jobs)} 个岗位，其中匹配分 ≥ {min_score} 的有 {len(filtered)} 个")
            display_jobs = filtered.rename(columns={
                'searched_at': '发现时间',
                'title': '职位',
                'company': '公司',
                'match_score': '匹配分',
                'is_qualified': '达标',
                'url': '链接'
            })
            cols = ['发现时间', '职位', '公司', '匹配分', '链接']
            if '达标' in display_jobs.columns:
                display_jobs['达标'] = display_jobs['达标'].map({1: '✅', 0: '⚠️ 未达门槛'})
                cols.insert(4, '达标')
            display_jobs = display_jobs[cols]
            st.dataframe(
                display_jobs,
                column_config={
                    "链接": st.column_config.LinkColumn("打开职位", display_text="🔗 打开"),
                    "匹配分": st.column_config.NumberColumn("匹配分", format="%.0f"),
                },
                width="stretch",
                hide_index=True
            )
            # 匹配分分布图
            if has_score:
                fig_jobs = px.histogram(
                    filtered, x="match_score", nbins=20,
                    title=f"找到岗位的匹配分分布 (≥{min_score})",
                    color_discrete_sequence=['#00C49F'],
                    labels={"match_score": "匹配分"}
                )
                fig_jobs.update_layout(xaxis_title="匹配分", yaxis_title="岗位数", bargap=0.1)
                st.plotly_chart(fig_jobs, width="stretch")
    else:
        st.info("暂无搜索结果。运行 Agent 执行一次岗位搜索后，找到的岗位会自动出现在这里。")

    # ============ 准备投递的简历 ============
    st.markdown("---")
    st.subheader("📄 准备投递的简历")
    root = Path(__file__).parent.parent.parent

    # 简历文件状态
    resume_candidates = [
        root / "data" / "resume.pdf",
        root / "data" / "resume.docx",
        root / "data" / "resume.txt",
    ]
    found_resume = next((p for p in resume_candidates if p.exists()), None)
    if found_resume:
        size_kb = found_resume.stat().st_size / 1024
        st.success(f"✅ 简历文件已就绪: `{found_resume.name}` ({size_kb:.0f} KB)")
    else:
        st.warning("⚠️ 未找到简历文件。请将 `resume.pdf` / `resume.docx` / `resume.txt` 放到 `data/` 目录。")

    # 用户画像
    persona_path = root / "data" / "user_persona.json"
    if persona_path.exists():
        try:
            persona = json.loads(persona_path.read_text(encoding='utf-8'))
            st.success("✅ 用户画像已生成 (投递时使用的信息源)")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**基本信息**")
                st.markdown(f"- 姓名: {persona.get('name', '未知')}")
                st.markdown(f"- 邮箱: {persona.get('email', '未知')}")
                st.markdown(f"- 电话: {persona.get('phone') or '未填写'}")
            with col2:
                objective = persona.get('career_objective') or {}
                st.markdown("**求职意向**")
                target_positions = objective.get('target_positions') or []
                st.markdown(f"- 目标岗位: {'、'.join(target_positions) if target_positions else '未设置'}")
                locations = objective.get('location_preference') or []
                st.markdown(f"- 期望地点: {'、'.join(locations) if locations else '不限'}")
                st.markdown(f"- 期望薪资: {objective.get('salary_expectation') or '面议'}")

            # 技能
            tech_skills = persona.get('technical_skills') or []
            if isinstance(tech_skills, list) and tech_skills:
                st.markdown(f"**技术技能**: `{'`, `'.join(tech_skills)}`")
            elif isinstance(tech_skills, dict):
                all_skills = []
                for v in tech_skills.values():
                    if isinstance(v, list):
                        all_skills.extend(v)
                    elif isinstance(v, str):
                        all_skills.append(v)
                if all_skills:
                    st.markdown(f"**技术技能**: `{'`, `'.join(sorted(set(all_skills)))}`")

            # 核心优势
            strengths = persona.get('strengths') or []
            if isinstance(strengths, list) and strengths:
                st.markdown(f"**核心竞争力**: {', '.join(strengths[:5])}")

            # 展开查看完整画像
            with st.expander("查看完整画像 JSON"):
                st.json(persona)
        except Exception as e:
            st.error(f"解析用户画像失败: {e}")
    else:
        st.info("尚未生成用户画像。Agent 解析简历后会自动生成并保存到 `data/user_persona.json`。")

    # ============ 岗位诊断 ============
    st.markdown("---")
    st.subheader("🧭 岗位诊断")

    directions_path = root / "data" / "career_directions.json"
    profile_path = root / "data" / "user_profile.json"

    # 用户实际情况
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text(encoding='utf-8'))
            with st.expander("📋 访谈收集到的实际情况"):
                st.markdown(f"**姓名**: {profile.get('name') or '未提供'} | **邮箱**: {profile.get('email') or '未提供'} | **电话**: {profile.get('phone') or '未提供'}")
                skills = profile.get('all_skills') or []
                if skills:
                    st.markdown(f"**技能**: `{'`, `'.join(skills)}`")
                exp = profile.get('work_experience') or []
                if exp:
                    st.markdown(f"**经历**: " + "、".join(f"{e.get('company')}({e.get('role')})" for e in exp if e.get('company')))
                if profile.get('locations'):
                    st.markdown(f"**期望地点**: {'、'.join(profile.get('locations'))}")
                if profile.get('salary_expectation'):
                    st.markdown(f"**期望薪资**: {profile.get('salary_expectation')}")
        except Exception as e:
            st.error(f"解析 user_profile.json 失败: {e}")

    if not directions_path.exists():
        st.info("尚未运行岗位诊断。启动时选「岗位诊断模式」或执行 `diagnose` 命令, 诊断结果会出现在这里。")
    else:
        try:
            analysis = json.loads(directions_path.read_text(encoding='utf-8'))
            directions = analysis.get('directions', [])
            if directions:
                for i, d in enumerate(directions, 1):
                    priority = d.get('priority', 1)
                    stars = "★" * priority + "☆" * (5 - priority)
                    with st.expander(f"[{i}] {d.get('title')}  {stars}"):
                        st.markdown(f"**为什么适合**: {d.get('summary', '')}")
                        st.markdown(f"**目标职位**: {'、'.join(d.get('target_positions', []))}")
                        st.markdown(f"**搜索关键词**: `{'`、`'.join(d.get('keywords', []))}`")
                        st.markdown(f"**你的亮点**: {'、'.join(d.get('skill_highlights', []))}")
                        gaps = d.get('skill_gaps', [])
                        st.markdown(f"**需要补**: {'、'.join(gaps) if gaps else '暂无明显短板'}")
                        st.markdown(f"**市场情况**: {d.get('market_note', '')}")
                        st.markdown(f"**建议**: {d.get('advice', '')}")
                if analysis.get('overall_advice'):
                    st.info(f"💡 **总体建议**: {analysis.get('overall_advice')}")
            else:
                st.warning("诊断结果中没有方向数据。")
        except Exception as e:
            st.error(f"解析 career_directions.json 失败: {e}")

    # 数据可视化
    st.markdown("---")
    st.subheader("📊 数据可视化")

    # 创建两列布局
    col1, col2 = st.columns([2, 1])

    with col1:
        # 漏斗图
        if df_applications is not None and not df_applications.empty:
            funnel_fig = create_funnel_chart(df_applications)
            if funnel_fig:
                st.plotly_chart(funnel_fig, use_container_width=True)

    with col2:
        # 匹配分数分布
        hist_fig = create_match_score_distribution(df_applications)
        if hist_fig:
            st.plotly_chart(hist_fig, use_container_width=True)

    # 公司排名和时间线
    col1, col2 = st.columns([1, 1])

    with col1:
        company_fig = create_company_ranking(df_applications)
        if company_fig:
            st.plotly_chart(company_fig, use_container_width=True)

    with col2:
        timeline_fig = create_timeline_chart(df_applications)
        if timeline_fig:
            st.plotly_chart(timeline_fig, use_container_width=True)

    # 数据表格
    st.markdown("---")
    st.subheader("📋 最近处理记录")

    if not df_applications.empty:
        # 添加筛选器
        status_filter = st.multiselect(
            "筛选状态",
            options=df_applications['status'].unique() if 'status' in df_applications.columns else [],
            default=[]
        )

        if status_filter:
            display_df = df_applications[df_applications['status'].isin(status_filter)]
        else:
            display_df = df_applications

        # 显示表格
        st.dataframe(
            display_df[
                ['created_at', 'company_name', 'job_title', 'match_score', 'status']
            ].rename(columns={
                'created_at': '创建时间',
                'company_name': '公司',
                'job_title': '职位',
                'match_score': '匹配分数',
                'status': '状态'
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("数据库目前为空，等待 Agent 执行首次漫游抓取。")

    # 反思日志和策略规则
    st.markdown("---")

    # 创建两列布局显示反思和规则
    col1, col2 = st.columns([1, 1])

    with col1:
        display_reflections(df_reflections)

    with col2:
        display_strategy_rules(df_rules)

    # 底部信息
    st.markdown("---")
    st.markdown(
        "*最后更新时间: " +
        datetime.now().strftime("%Y-%m-%d %H:%M:%S") +
        " | 数据每60秒自动刷新*"
    )

if __name__ == "__main__":
    main()