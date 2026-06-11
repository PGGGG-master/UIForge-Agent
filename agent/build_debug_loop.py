from __future__ import annotations

import json
import re
from pathlib import Path

from agent import file_writer as fw
from agent.build_debug_memory import (
    get_build_debug_memory_store,
    normalize_build_error,
)
from agent.context import AgentContext
from agent.llm_client import LLMClient
from agent.stages.debug_agent import DebugAttempt, DebugSession, run_debug_fix, run_debug_summary
from agent.validators import ValidationError

_SRC_GLOB = ("*.jsx", "*.js", "*.css")
_MAX_SOURCES_CHARS = 40000


def _files_mentioned_in_log(log: str, output_dir: Path) -> list[str]:
    rels: list[str] = []
    seen: set[str] = set()
    patterns = (
        r"(src[/\\][\w./\\-]+\.(?:jsx?|css))",
        r"([\w-]+\.(?:jsx?|css)):\d+",
    )
    for pat in patterns:
        for m in re.finditer(pat, log, re.IGNORECASE):
            raw = m.group(1).replace("\\", "/")
            if raw.startswith("src/"):
                candidate = raw
            else:
                hits = list(output_dir.glob(f"src/**/{raw}"))
                candidate = hits[0].relative_to(output_dir).as_posix() if hits else ""
            if candidate and candidate not in seen and (output_dir / candidate).exists():
                seen.add(candidate)
                rels.append(candidate)
    return rels


def collect_frontend_sources(ctx: AgentContext, build_log: str = "") -> str:
    output = ctx.output_path
    src = output / "src"
    if not src.exists():
        return "（无 src 目录）"

    priority: list[Path] = []
    for rel in _files_mentioned_in_log(build_log, output):
        priority.append(output / rel)

    for pattern in _SRC_GLOB:
        for p in sorted(src.rglob(pattern)):
            if p not in priority:
                priority.append(p)

    parts: list[str] = []
    total = 0
    for path in priority:
        if not path.is_file():
            continue
        rel = path.relative_to(output).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        block = f"--- {rel} ---\n{text}"
        if total + len(block) > _MAX_SOURCES_CHARS:
            remain = _MAX_SOURCES_CHARS - total
            if remain > 500:
                parts.append(block[:remain] + "\n... (truncated)")
            break
        parts.append(block)
        total += len(block)

    return "\n\n".join(parts) if parts else "（无可读前端源码）"


def snapshot_frontend_sources(ctx: AgentContext, build_log: str = "") -> str:
    return collect_frontend_sources(ctx, build_log)


def run_build_with_debug(
    ctx: AgentContext,
    llm: LLMClient | None,
    *,
    run_build_fn,
    max_attempts: int = 3,
) -> None:
    """
    build 失败时启动 Debug 循环；成功且经历过修复则总结并写入记忆库。
    run_build_fn: (ctx, attempt_label) -> tuple[bool, str]
    """
    session = DebugSession()
    had_failure = False

    for attempt in range(1, max_attempts + 1):
        label = str(attempt) if attempt > 1 else ""
        ok, log = run_build_fn(ctx, label)
        if ok:
            # 仅 Debug 修复成功后才总结并入库；首次 build 即通过不写经验
            if had_failure and llm and session.attempts:
                ctx.log("[BuildDebug] build 已通过，总结本次 Debug 经验并入库...")
                session.final_snapshot = snapshot_frontend_sources(ctx, log)
                lessons = run_debug_summary(ctx, llm, session)
                store = get_build_debug_memory_store(ctx.project_root)
                stored = 0
                for lesson in lessons:
                    if not _lesson_worth_storing(lesson):
                        continue
                    mem_id = store.store_lesson(
                        error_text=lesson["error_text"],
                        root_cause=lesson.get("root_cause", ""),
                        pitfalls=lesson.get("pitfalls", ""),
                        fix_experience=lesson.get("fix_experience", ""),
                        metadata={
                            "task": ctx.task,
                            "output_dir": str(ctx.output_path),
                            "attempts": len(session.attempts),
                            "resolved": True,
                        },
                    )
                    if mem_id:
                        stored += 1
                        ctx.log(f"[BuildDebug] 经验已入库: {mem_id[:8]}...")
                if stored:
                    ctx.log(f"[BuildDebug] 共写入 {stored} 条经验（仅成功修复后）")
            ctx.log("[CodeIntegrity] build 通过")
            return

        had_failure = True
        error_text = normalize_build_error(log)
        if not error_text:
            error_text = log[-8000:]

        fw.write_text(ctx.output_path, f"report/build_check_attempt_{attempt}.log", log[:30000])

        if not llm:
            raise ValidationError(
                f"项目未能通过 npm run build（第 {attempt} 次），"
                "未配置 LLM，无法自动 Debug。详见 report/build_check.log"
            )

        if attempt >= max_attempts:
            raise ValidationError(
                f"build 未通过，已尝试 {max_attempts} 轮 Debug，"
                "详见 report/debug_fix_r*.txt 与 report/build_check_attempt_*.log"
            )

        ctx.log(f"[BuildDebug] build 失败，启动第 {attempt}/{max_attempts} 轮 Debug...")
        code_before = snapshot_frontend_sources(ctx, log)
        if not session.initial_snapshot:
            session.initial_snapshot = code_before

        store = get_build_debug_memory_store(ctx.project_root)
        retrieved: list = []
        if store.has_experience():
            retrieved = store.search_similar_errors(error_text, limit=3)
            if retrieved:
                ctx.log(f"[BuildDebug] 检索到 {len(retrieved)} 条相似历史经验")
            else:
                ctx.log("[BuildDebug] 经验库有数据但未命中相似报错，本次不使用历史经验")
        else:
            ctx.log("[BuildDebug] 经验库为空，本次仅根据报错与源码修复")

        frontend_sources = collect_frontend_sources(ctx, log)
        n, _ = run_debug_fix(
            ctx,
            llm,
            attempt_no=attempt,
            error_log=error_text,
            frontend_sources=frontend_sources,
            retrieved_lessons=retrieved,
            code_snapshot_before=code_before,
        )
        code_after = snapshot_frontend_sources(ctx, log)
        session.attempts.append(
            DebugAttempt(
                attempt_no=attempt,
                error_text=error_text,
                code_snapshot_before=code_before,
                code_snapshot_after=code_after,
                retrieved_lessons=retrieved,
            )
        )
        ctx.log(f"[BuildDebug] 第 {attempt} 轮写入 {n} 个文件，重新 build...")

    raise ValidationError(
        f"build 未通过，已尝试 {max_attempts} 轮 Debug，详见 report/debug_*.txt"
    )


def _lesson_worth_storing(lesson: dict) -> bool:
    """成功修复后的经验须具备可检索价值，避免空占位入库。"""
    error_text = (lesson.get("error_text") or "").strip()
    root = (lesson.get("root_cause") or "").strip()
    fix = (lesson.get("fix_experience") or "").strip()
    if not error_text or not root or not fix:
        return False
    placeholders = (
        "见 report/debug_fix",
        "参考当次报错日志",
        "build 报错经多轮修复后通过",
    )
    if any(p in root and len(root) < 40 for p in placeholders):
        return False
    if any(p in fix and len(fix) < 40 for p in placeholders):
        return False
    return True
