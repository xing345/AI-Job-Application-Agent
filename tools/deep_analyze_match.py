"""深度分析匹配报告中的问题岗位。"""
import json

with open(r"D:\x\ai agent\output\match_report_20261012_220211.json", "r", encoding="utf-8") as f:
    report = json.load(f)

# 可疑岗位URL
SUSPECT_URLS = [
    "https://jobs.mihoyo.com/#/campus/position/9119",  # 推荐算法工程师，score=88
    "https://jobs.mihoyo.com/#/campus/position/8935",  # LLM预训练数据，score=78
    "https://jobs.mihoyo.com/#/campus/position/9368",  # 国际化生态平台，score=72
    "https://jobs.mihoyo.com/#/campus/position/5287",  # 3D生成算法实习生，score=30
    "https://jobs.mihoyo.com/#/campus/position/8090",  # 游戏运营实习生，score=30
]

for url in SUSPECT_URLS:
    for r in report["results"]:
        if r["job_url"] == url:
            print(f"{'='*70}")
            print(f"URL: {url}")
            print(f"score: {r.get('score')}")
            print(f"direction_match: {r.get('direction_match')}")
            print(f"硬性: {r.get('hard_requirements_met')}/{r.get('hard_requirements_total')}")
            print(f"\ndirection_reason: {r.get('direction_reason', '')}")
            print(f"\nreason: {r.get('reason', '')}")
            print(f"\nmatched_points:")
            for p in r.get("matched_points", []):
                print(f"  - {p[:100]}")
            print(f"\nmissing_points:")
            for p in r.get("missing_points", []):
                print(f"  - {p[:100]}")
            # 检查是否有jd_text字段
            if "jd_text" in r:
                print(f"\njd_text长度: {len(r['jd_text'])}")
                print(f"jd_text前300字符: {r['jd_text'][:300]}")
            print()
            break

# 统计所有岗位的字段
print(f"\n{'='*70}")
print(f"匹配报告字段: {list(report['results'][0].keys())}")
