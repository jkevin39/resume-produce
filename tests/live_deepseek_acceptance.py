"""Opt-in DeepSeek live acceptance using only synthetic data.

The default output contains aggregate metrics and validation outcomes. An explicit
--show-output adds reviewable synthetic fields. Exact rendered HTML and ResumeSpec
are saved for each successful scenario; prompts, raw API responses and keys are not.
"""
from __future__ import annotations

import json
import re
import tempfile
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path

from resume_app.skill import LLMError, ResumeSkill
from resume_app.rendering import ResumeRenderer
from resume_app.storage import ProfileRepository, write_yaml


PROJECT = Path(__file__).resolve().parent.parent
SCENARIOS = [
    ("中文 JD", "负责分析产品使用数据和用户反馈，要求 SQL 与 Python；有 LLM 项目经验优先。"),
    ("英文 JD", "Analyze product usage and customer feedback. SQL and Python are required; LLM experience is preferred."),
    ("较长履历", "负责跨团队数据分析、指标体系和看板建设，要求 Python、SQL、沟通能力和严谨文档。"),
    ("明显能力缺口", "要求三年以上 Kubernetes 生产运维和 AWS 架构经验。"),
    ("needs_details", "负责用 Python 建立可量化的数据自动化流程，并说明业务成果。"),
]


def seed_repository(root: Path) -> ProfileRepository:
    write_yaml(root / "data/profile.yaml", {
        "profile": {"name": "测试用户", "phone": "", "email": "test@example.com", "location": "", "summary": "数据方向求职者"},
        "education": [{"education_id": "edu_1", "school": "示例大学", "degree": "本科", "major": "统计学", "date": "2022–2026", "details": ""}],
    })
    write_yaml(root / "data/skills.yaml", {"skills": [
        {"name": "Python", "evidence_ids": ["ev_confirmed"], "user_confirmed": False},
        {"name": "SQL", "evidence_ids": [], "user_confirmed": True},
    ]})
    write_yaml(root / "data/experiences/synthetic.yaml", {
        "experience_id": "exp_synthetic", "type": "project", "organization": "课程项目", "title": "成员", "date": "2025", "location": "",
        "source_refs": ["synthetic"], "evidence": [
            {"evidence_id": "ev_confirmed", "original_fact": "使用 Python 和 SQL 清洗 12000 条匿名反馈，并制作周报看板。", "structured_fact": {"action": "清洗反馈并制作看板", "method": "Python、SQL", "scale": "12000 条", "result": "形成周报看板", "skills": ["Python", "SQL"]}, "candidate_zh": "使用 Python 和 SQL 清洗 12000 条匿名反馈并制作周报看板。", "status": "confirmed"},
            {"evidence_id": "ev_needs", "original_fact": "尝试过 LLM 分类实验，但没有记录准确率和数据规模。", "structured_fact": {"action": "进行分类实验", "method": "LLM", "scale": "", "result": "", "skills": ["LLM"]}, "candidate_zh": "进行 LLM 分类实验。", "status": "needs_details"},
        ],
    })
    return ProfileRepository(root)


def estimated_cost(metrics: list[dict]) -> float:
    now = datetime.now(timezone.utc)
    peak = now.weekday() < 5 and (1 <= now.hour < 4 or 6 <= now.hour < 10)
    miss_rate, hit_rate, output_rate = ((0.44, 0.014, 1.32) if peak else (0.22, 0.007, 0.66))
    total = 0.0
    for metric in metrics:
        usage = metric.get("usage", {})
        hit = usage.get("prompt_cache_hit_tokens", 0) or 0
        miss = usage.get("prompt_cache_miss_tokens")
        if miss is None:
            miss = max((usage.get("prompt_tokens", 0) or 0) - hit, 0)
        output = usage.get("completion_tokens", 0) or 0
        total += (miss * miss_rate + hit * hit_rate + output * output_rate) / 1_000_000
    return total


def save_html_artifact(renderer: ResumeRenderer, spec: dict, scenario_dir: Path) -> None:
    scenario_dir.mkdir(parents=True, exist_ok=False)
    (scenario_dir / "resume-spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    (scenario_dir / "resume.html").write_text(
        renderer.render_document(renderer.current_context(spec)), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=[name for name, _ in SCENARIOS])
    parser.add_argument(
        "--show-output", action="store_true",
        help="输出合成样本的可审阅字段；仍不输出密钥、提示词或原始响应",
    )
    parser.add_argument(
        "--artifact-dir", type=Path,
        help="保存每个成功场景的原始 HTML 和 ResumeSpec；默认写入 tests/artifacts 下的时间戳目录",
    )
    args = parser.parse_args()
    scenarios = [item for item in SCENARIOS if not args.scenario or item[0] == args.scenario]
    artifact_dir = (args.artifact_dir or PROJECT / "tests" / "artifacts" / datetime.now().strftime("v06-live-%Y%m%d-%H%M%S")).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="resume-v06-live-") as temporary:
        repo = seed_repository(Path(temporary))
        renderer = ResumeRenderer(repo, PROJECT)
        skill = ResumeSkill({"llm": {"mode": "live", "base_url": "https://api.deepseek.com", "model": "deepseek-flash", "timeout_seconds": 90, "max_tokens": 8192}}, repo)
        started = time.monotonic()
        extraction_count = 0
        extraction_preview = None
        results = []
        try:
            extraction = skill.extract_experience("匿名课程项目\n使用 Python 分析 5000 条合成记录。", "synthetic-input")
            extraction_count = len(extraction["evidence"])
            if args.show_output:
                extraction_preview = {
                    "type": extraction["type"], "organization": extraction["organization"],
                    "title": extraction["title"],
                    "evidence": [
                        {"candidate_zh": item["candidate_zh"], "status": item["status"], "structured_fact": item["structured_fact"]}
                        for item in extraction["evidence"]
                    ],
                }
        except LLMError as exc:
            results.append({"scenario": "履历拆解", "ok": False, "stage": "履历拆解", "error_category": exc.category})
        for scenario_index, (name, jd) in enumerate(scenarios, start=1):
            try:
                analysis = skill.analyze_jd(jd)
            except LLMError as exc:
                results.append({"scenario": name, "ok": False, "stage": "JD 分析", "error_category": exc.category})
                continue
            try:
                match = skill.match(analysis)
            except LLMError as exc:
                results.append({"scenario": name, "ok": False, "stage": "证据匹配", "error_category": exc.category})
                continue
            try:
                spec = skill.build_spec("zh", ["ev_confirmed", "ev_needs"], "示例公司", "数据岗位", analysis)
            except LLMError as exc:
                results.append({"scenario": name, "ok": False, "stage": "ResumeSpec", "error_category": exc.category})
                continue
            scenario_dir = artifact_dir / f"{scenario_index:02d}-{name}"
            save_html_artifact(renderer, spec, scenario_dir)
            bullets = [bullet for entry in spec["experiences"] + spec["projects"] for bullet in entry["bullets"]]
            numeric_tokens = sorted({token for bullet in bullets for token in re.findall(r"\d+(?:\.\d+)?", bullet["text"])})
            new_numeric_tokens = sorted(set(numeric_tokens) - {"12000"})
            claim_text = " ".join([
                spec["profile"]["summary"],
                *(bullet["text"] for bullet in bullets),
                *(item["name"] for item in spec["skills"]),
            ])
            unsupported_terms = [term for term in ("Kubernetes", "AWS") if term.lower() in claim_text.lower()]
            needs_asserted_result = any(
                "ev_needs" in bullet["evidence_ids"] and (re.search(r"\d", bullet["text"]) or any(word in bullet["text"] for word in ("提升", "降低", "达到", "准确率")))
                for bullet in bullets
            )
            result = {
                "scenario": name, "ok": not new_numeric_tokens and not unsupported_terms and not needs_asserted_result,
                "match_count": len(match["matches"]), "gap_count": len(match["gaps"]), "bullet_count": len(bullets),
                "new_numeric_tokens": new_numeric_tokens, "unsupported_claim_terms": unsupported_terms,
                "needs_details_asserted_result": bool(needs_asserted_result),
            }
            if args.show_output:
                result["review"] = {
                    "synthetic_jd": jd,
                    "analysis": analysis,
                    "gaps": match["gaps"],
                    "resume": {
                        "summary": spec["profile"]["summary"],
                        "experiences": spec["experiences"],
                        "projects": spec["projects"],
                        "skills": spec["skills"],
                    },
                }
            results.append(result)
        usage = {key: sum((item.get("usage", {}).get(key, 0) or 0) for item in skill.call_metrics) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
        print(json.dumps({
            "model": "deepseek-flash", "prompt_version": skill.provenance(True)["prompt_version"],
            "scenario_count": len(scenarios), "call_count": len(skill.call_metrics),
            "extracted_evidence_count": extraction_count, "usage": usage,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "estimated_cost_usd": round(estimated_cost(skill.call_metrics), 6),
            "artifact_dir": str(artifact_dir), "extraction_review": extraction_preview, "results": results,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
