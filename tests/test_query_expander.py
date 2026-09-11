"""
query_expander 单元测试(离线, 不联网)

覆盖「岗位名模糊扩展」与「分词判定」两组纯函数逻辑。
"""

from src.models.instruction_schemas import TargetInstructionSchema
from src.search.query_expander import (
    expand_role_variants,
    matches_role,
    query_terms,
    role_match_tokens,
    role_tokens,
)


# ---------------------------------------------------------------- #
# 1. 岗位名扩展: 确定性、去重、原岗位名在首位
# ---------------------------------------------------------------- #
def test_expand_is_deterministic_and_deduped():
    first = expand_role_variants("前端工程师", ["React", "TypeScript"])
    second = expand_role_variants("前端工程师", ["React", "TypeScript"])

    assert first == second, "同一输入必须产出同一结果(纯规则, 无随机性)"
    assert first[0] == "前端工程师", "原岗位名应排在首位"
    assert len(first) == len(set(first)), "变体不应重复"


def test_expand_covers_synonyms_and_stack():
    variants = expand_role_variants("前端工程师", ["React"])

    # 后缀替换
    assert "前端开发" in variants
    assert "前端开发工程师" in variants
    # 方向词本身
    assert "前端" in variants
    # 技术栈派生
    assert "Web前端" in variants or "React开发" in variants


def test_expand_respects_limit():
    assert len(expand_role_variants("前端工程师", ["React", "Vue"], limit=3)) == 3


def test_expand_handles_empty_role():
    assert expand_role_variants("", ["React"]) == []


# ---------------------------------------------------------------- #
# 2. 分词: 通用词只能打分, 不能作为判定依据
# ---------------------------------------------------------------- #
def test_generic_words_are_not_decisive():
    decisive = role_match_tokens("前端工程师")
    everything = role_tokens("前端工程师")

    # 「工程师」这类通用词只出现在全量 token 里
    assert "工程师" not in decisive
    assert "工程师" in everything
    # 方向词必须留在判定集里
    assert "前端" in decisive


def test_direction_discriminates():
    role = "前端工程师"
    variants = expand_role_variants(role)

    assert matches_role("web前端开发工程师", role, variants)
    assert matches_role("高级前端", role, variants)
    # 方向相反: 不能因为都含「工程师」就判为命中
    assert not matches_role("后端开发工程师", role, variants)
    assert not matches_role("算法工程师", role, variants)


def test_matches_role_accepts_stack_variants():
    role = "Java开发"
    assert matches_role("Java工程师", role, expand_role_variants(role, ["Java"]))
    assert not matches_role("Python工程师", role, expand_role_variants(role, ["Java"]))


def test_matches_role_empty_text():
    assert not matches_role("", "前端工程师")
    assert not matches_role("前端工程师", "")


# ---------------------------------------------------------------- #
# 3. 查询词: 挑差异大的几个, 避免只做后缀替换
# ---------------------------------------------------------------- #
def test_query_terms_are_diverse():
    role = "前端工程师"
    target = TargetInstructionSchema(
        company="", role=role,
        keywords=["React"],
        role_variants=expand_role_variants(role, ["React"]),
    )

    terms = query_terms(target, limit=3)
    assert terms[0] == role
    assert len(terms) == len(set(terms))
    # 不应退化成「前端工程师 / 前端开发工程师」这种只换后缀的冗余查询
    assert "前端开发工程师" not in terms
    assert "前端" in terms


def test_query_terms_without_variants():
    target = TargetInstructionSchema(company="", role="前端工程师")
    assert query_terms(target, limit=3) == ["前端工程师"]
