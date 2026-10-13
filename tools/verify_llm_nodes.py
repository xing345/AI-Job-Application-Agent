"""阶段5 LLM节点验证：测试4个LLM节点的实际输出格式和质量。"""
import asyncio
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.agent.nodes.screen_titles import screen_batch
from src.agent.nodes.match_jobs import match_one
from src.agent.nodes.confirm_list import quota_sort
from src.agent.nodes.fill_application import llm_generate_values
from src.agent.state import AgentState
from src.models.job import JobDetail, JobPosting
from src.models.match import FillField, MatchResult
from src.models.profile import UserProfile


async def test_title_screen():
    """测试1：标题语义初筛。"""
    print("\n" + "=" * 60)
    print("【测试1】标题语义初筛")
    print("=" * 60)

    titles = [
        "前端开发工程师",
        "后端开发工程师（Java）",
        "算法工程师-推荐系统",
        "产品经理",
        "UI设计师",
        "人力资源专员",
        "财务分析师",
        "AI大模型算法实习生",
        "全栈开发工程师",
        "测试开发工程师",
    ]
    target_directions = ["前端开发", "后端开发", "AI算法", "全栈开发"]

    print(f"目标方向: {target_directions}")
    print(f"测试标题 ({len(titles)}个):")
    for i, t in enumerate(titles):
        print(f"  {i}. {t}")

    try:
        result = await screen_batch(titles, target_directions, run_id="test_screen")
        print(f"\n结果: 相关 {len(result.related_indices)} 个, 不相关 {len(result.unrelated_indices)} 个")
        print(f"相关序号: {result.related_indices}")
        print(f"不相关序号: {result.unrelated_indices}")
        print("\n相关岗位:")
        for idx in result.related_indices:
            if idx < len(titles):
                print(f"  ✓ {titles[idx]}")
        print("\n过滤岗位:")
        for idx in result.unrelated_indices:
            if idx < len(titles):
                print(f"  ✗ {titles[idx]}")
        print("\n[标题初筛] 输出格式: OK")
        return True
    except Exception as e:
        print(f"\n[标题初筛] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_job_match():
    """测试2：JD深度匹配。"""
    print("\n" + "=" * 60)
    print("【测试2】JD深度匹配")
    print("=" * 60)

    resume_text = """
张亚辉，重庆移通学院软件工程本科（2023-2027）。
技能：JavaScript、TypeScript、React、Vue、Node.js、Python、MySQL、Git。
项目经历：
1. 校园二手交易平台（React + Node.js + MySQL）：负责前端开发和后端API设计
2. AI智能问答助手（Python + LangChain）：基于大模型的对话系统开发
3. 微信小程序商城（Vue + 微信小程序）：全栈开发，包含支付和订单管理
目标方向：前端开发、Web前端、小程序、全栈、AI Agent开发
可到岗时间：2027年7月
"""

    job_title = "前端开发工程师"
    jd_text = """
【岗位职责】
1. 负责公司Web产品的前端开发，包括PC端和移动端
2. 与设计师和后端工程师协作，完成产品功能实现
3. 优化前端性能，提升用户体验
4. 参与前端技术方案设计和代码评审

【任职要求】
1. 本科及以上学历，计算机相关专业
2. 熟练掌握HTML、CSS、JavaScript，熟悉ES6+
3. 熟悉React或Vue框架，有实际项目经验
4. 了解Node.js，有后端开发经验者优先
5. 有良好的代码习惯和团队协作能力
6. 对AI技术有了解者优先
"""

    print(f"岗位: {job_title}")
    print(f"JD长度: {len(jd_text)}")
    print(f"简历长度: {len(resume_text)}")

    try:
        result = await match_one(resume_text, job_title, jd_text, run_id="test_match")
        print(f"\n匹配结果:")
        print(f"  分数: {result.score}/100")
        print(f"  方向匹配: {'是' if result.direction_match else '否'}")
        print(f"  方向理由: {result.direction_reason}")
        print(f"  硬性要求: {result.hard_requirements_met}/{result.hard_requirements_total}")
        print(f"\n  匹配点 ({len(result.matched_points)}):")
        for p in result.matched_points:
            print(f"    ✓ {p}")
        print(f"\n  缺失点 ({len(result.missing_points)}):")
        for p in result.missing_points:
            print(f"    ✗ {p}")
        print(f"\n  综合理由: {result.reason[:300]}")
        print("\n[JD匹配] 输出格式: OK")
        return True
    except Exception as e:
        print(f"\n[JD匹配] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_quota_sort():
    """测试3：配额排序。"""
    print("\n" + "=" * 60)
    print("【测试3】配额排序")
    print("=" * 60)

    # 构造模拟匹配结果
    candidates = []
    matches = []
    test_jobs = [
        ("前端开发工程师", 90, True, 5, 5),
        ("全栈开发工程师", 85, True, 4, 5),
        ("AI算法工程师", 80, True, 3, 4),
        ("后端开发工程师", 75, True, 4, 5),
        ("产品经理", 40, False, 1, 5),
        ("UI设计师", 30, False, 0, 4),
    ]

    for title, score, direction, hard_met, hard_total in test_jobs:
        posting = JobPosting(title=title, detail_url=f"https://example.com/{title}", site_name="test")
        detail = JobDetail(posting=posting, full_jd=f"{title}的JD内容")
        candidates.append(detail)
        matches.append(MatchResult(
            job_url=posting.detail_url,
            job_title=title,
            score=score,
            direction_match=direction,
            hard_requirements_met=hard_met,
            hard_requirements_total=hard_total,
            reason=f"{title}匹配理由",
        ))

    # 构造 state
    profile = UserProfile(
        name="测试用户",
        target_directions=["前端开发", "全栈开发", "AI算法"],
    )
    state = AgentState(run_id="test_sort", profile=profile, match_results=matches)

    print(f"候选岗位: {len(candidates)} 个")
    print(f"配额上限: 3 个")
    print("\n候选列表:")
    for i, (c, m) in enumerate(zip(candidates, matches)):
        print(f"  {i}. {c.posting.title} (分数:{m.score}, 方向:{'✓' if m.direction_match else '✗'}, 硬性:{m.hard_requirements_met}/{m.hard_requirements_total})")

    try:
        recommended = await quota_sort(state, candidates, max_count=3)
        print(f"\n推荐序号: {recommended}")
        print("推荐岗位:")
        for idx in recommended:
            if idx < len(candidates):
                print(f"  ✓ {candidates[idx].posting.title}")
        print("\n[配额排序] 输出格式: OK")
        return True
    except Exception as e:
        print(f"\n[配额排序] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_field_generation():
    """测试4：表单字段语义理解与值生成。"""
    print("\n" + "=" * 60)
    print("【测试4】表单字段理解与值生成")
    print("=" * 60)

    fields = [
        FillField(label="姓名", field_type="text", placeholder="请输入姓名"),
        FillField(label="手机号码", field_type="text", placeholder="请输入手机号"),
        FillField(label="电子邮箱", field_type="email", placeholder="请输入邮箱"),
        FillField(label="毕业院校", field_type="text", placeholder="请输入学校名称"),
        FillField(label="学历", field_type="select", options=["本科", "硕士", "博士", "大专"]),
        FillField(label="期望薪资", field_type="text", placeholder="请输入期望薪资"),
        FillField(label="是否同意隐私政策", field_type="radio", options=["同意", "不同意"]),
        FillField(label="个人简介", field_type="textarea", placeholder="请简要介绍自己"),
    ]

    resume_text = """张亚辉，重庆移通学院软件工程本科（2023-2027）。
手机：13800138000，邮箱：test@example.com"""
    profile_summary = "目标方向：前端开发，可到岗2027年7月"
    job_title = "前端开发工程师"
    jd_text = "前端开发岗位，要求熟悉React/Vue"

    print(f"测试字段 ({len(fields)}个):")
    for i, f in enumerate(fields):
        print(f"  {i}. {f.label} (type={f.field_type})")

    try:
        result = await llm_generate_values(fields, resume_text, profile_summary, job_title, jd_text, run_id="test_fields")
        print(f"\n生成结果:")
        for i, f in enumerate(result):
            value_display = f.value if f.value else "(null/不确定)"
            print(f"  {i}. {f.label}: semantic={f.semantic_type}, value={value_display}")

        # 验证关键字段
        name_field = result[0]
        phone_field = result[1]
        email_field = result[2]
        print(f"\n关键字段验证:")
        print(f"  姓名: {name_field.value} (semantic={name_field.semantic_type})")
        print(f"  手机: {phone_field.value} (semantic={phone_field.semantic_type})")
        print(f"  邮箱: {email_field.value} (semantic={email_field.semantic_type})")
        print("\n[表单字段理解] 输出格式: OK")
        return True
    except Exception as e:
        print(f"\n[表单字段理解] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("=" * 60)
    print("阶段5 LLM节点验证")
    print("=" * 60)

    results = {}

    # 测试1：标题初筛
    results["title_screen"] = await test_title_screen()

    # 测试2：JD匹配
    results["job_match"] = await test_job_match()

    # 测试3：配额排序
    results["quota_sort"] = await test_quota_sort()

    # 测试4：表单字段理解
    results["field_generation"] = await test_field_generation()

    # 汇总
    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)
    for name, ok in results.items():
        status = "✅ 通过" if ok else "❌ 失败"
        print(f"  {name}: {status}")

    passed = sum(1 for v in results.values() if v)
    print(f"\n总计: {passed}/{len(results)} 项通过")


if __name__ == "__main__":
    asyncio.run(main())
