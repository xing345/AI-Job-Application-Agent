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

def get_kpi_cards(df):
    """生成KPI卡片"""
    total_jobs = len(df)
    high_score_jobs = len(df[df['match_score'] >= 80]) if 'match_score' in df.columns else 0
    applied_jobs = len(df[df['status'] == 'APPLIED']) if 'status' in df.columns else 0
    interview_jobs = len(df[df['status'] == 'INTERVIEW_INVITE']) if 'status' in df.columns else 0
    success_rate = (interview_jobs / applied_jobs * 100) if applied_jobs > 0 else 0

    return [
        {"title": "已发现岗位", "value": total_jobs, "delta": "+12", "type": "info"},
        {"title": "高分岗位 (>80)", "value": high_score_jobs, "delta": "+5", "type": "success"},
        {"title": "已投递", "value": applied_jobs, "delta": "+8", "type": "warning"},
        {"title": "面试邀请", "value": interview_jobs, "delta": f"+{success_rate:.1f}%", "type": "success"},
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
                delta_color=("off" if card["type"] == "info" else card["type"])
            )

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