from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agent import file_writer as fw
from agent.build_debug_memory import BuildDebugExperience
from agent.context import AgentContext
from agent.llm_client import LLMClient
from agent.stages.blocks import write_fenced_blocks


@dataclass
class DebugAttempt:
    attempt_no: int
    error_text: str
    code_snapshot_before: str
    code_snapshot_after: str = ""
    retrieved_lessons: list[BuildDebugExperience] = field(default_factory=list)


@dataclass
class DebugSession:
    attempts: list[DebugAttempt] = field(default_factory=list)
    initial_snapshot: str = ""
    final_snapshot: str = ""


def format_retrieved_lessons(lessons: list[BuildDebugExperience]) -> str:
    if not lessons:
        return "（无可用历史经验；请仅根据报错日志与当前源码修复，勿臆造经验）"
    parts: list[str] = []
    for i, lesson in enumerate(lessons, start=1):
        parts.append(
            f"### 经验 {i}（相似度 {lesson.score:.2f}）\n"
            f"历史报错摘要：{lesson.error_signature or lesson.error_text[:300]}\n"
            f"错误原因：{lesson.root_cause}\n"
            f"避坑指南：{lesson.pitfalls}\n"
            f"改正经验：{lesson.fix_experience}"
        )
    return "\n\n".join(parts)


def run_debug_fix(
    ctx: AgentContext,
    llm: LLMClient,
    *,
    attempt_no: int,
    error_log: str,
    frontend_sources: str,
    retrieved_lessons: list[BuildDebugExperience],
    code_snapshot_before: str,
) -> tuple[int, str]:
    system, user_tpl = llm.load_prompt("debug_fix")
    user = user_tpl.format(
        requirement_text=ctx.requirement_text[:3000],
        error_log=error_log[:12000],
        frontend_sources=frontend_sources[:40000],
        retrieved_lessons=format_retrieved_lessons(retrieved_lessons),
    )
    response = llm.complete(system, user, max_tokens=16384)
    ctx.output_path.joinpath("report").mkdir(parents=True, exist_ok=True)
    fw.write_text(ctx.output_path, f"report/debug_fix_r{attempt_no}.txt", response[:50000])
    fw.write_json(
        ctx.output_path,
        f"report/debug_retrieved_lessons_r{attempt_no}.json",
        [
            {
                "id": l.id,
                "score": l.score,
                "error_signature": l.error_signature,
                "root_cause": l.root_cause,
                "pitfalls": l.pitfalls,
                "fix_experience": l.fix_experience,
            }
            for l in retrieved_lessons
        ],
    )
    n = write_fenced_blocks(ctx, response, tests_only=False)
    return n, response


def run_debug_summary(
    ctx: AgentContext,
    llm: LLMClient,
    session: DebugSession,
) -> list[dict[str, str]]:
    attempts_text: list[str] = []
    for att in session.attempts:
        attempts_text.append(
            f"## 第 {att.attempt_no} 轮\n"
            f"报错：\n{att.error_text[:4000]}\n\n"
            f"修复前代码摘要（前 2000 字）：\n{att.code_snapshot_before[:2000]}\n\n"
            f"修复后代码摘要（前 2000 字）：\n{att.code_snapshot_after[:2000]}"
        )

    system, user_tpl = llm.load_prompt("debug_summary")
    user = user_tpl.format(
        requirement_text=ctx.requirement_text[:2500],
        initial_code=session.initial_snapshot[:6000],
        final_code=session.final_snapshot[:6000],
        attempts_history="\n\n".join(attempts_text),
    )
    ctx.output_path.joinpath("report").mkdir(parents=True, exist_ok=True)
    try:
        data = llm.complete_json(system, user)
        fw.write_text(
            ctx.output_path,
            "report/debug_summary_raw.txt",
            json.dumps(data, ensure_ascii=False, indent=2)[:50000],
        )
    except Exception as exc:
        fw.write_text(ctx.output_path, "report/debug_summary_raw.txt", str(exc)[:5000])
        data = {"lessons": []}

    lessons_raw = data.get("lessons") if isinstance(data, dict) else []
    lessons: list[dict[str, str]] = []
    if isinstance(lessons_raw, list):
        for item in lessons_raw:
            if not isinstance(item, dict):
                continue
            lessons.append(
                {
                    "error_text": str(item.get("error_text") or ""),
                    "root_cause": str(item.get("root_cause") or ""),
                    "pitfalls": str(item.get("pitfalls") or ""),
                    "fix_experience": str(item.get("fix_experience") or ""),
                }
            )

    fw.write_json(ctx.output_path, "report/debug_summary.json", {"lessons": lessons})
    return lessons
