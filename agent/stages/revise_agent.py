from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from agent import file_writer as fw
from agent.code_integrity import repair_project_integrity
from agent.code_validate import validate_code_outputs
from agent.context import AgentContext
from agent.llm_client import LLMClient
from agent.revise_router import (
    ReviseRoute,
    classify_feedback,
    resolve_revise_routes,
    route_label,
)
from agent.stages.code_agent import (
    CodeBaseContext,
    _load_code_context,
    _step_api,
    _step_components,
    _step_main_page,
    _step_styles,
)
from agent.validators import ValidationError, project_uses_rest_api, validate_main_page_artifact

FEEDBACK_REL = "feedback/revision.md"
DESIGN_FOLLOWUP_REL = "feedback/design_followup.md"
HISTORY_REL = "report/revision_history.md"

EXECUTABLE_ROUTES: set[ReviseRoute] = {"main_page", "components", "api", "styles"}


def _feedback_path(ctx: AgentContext) -> Path:
    return ctx.output_path / FEEDBACK_REL


def load_feedback(ctx: AgentContext) -> str:
    path = _feedback_path(ctx)
    if not path.exists():
        raise ValidationError(
            f"缺少 {FEEDBACK_REL}。请在反馈 UI 填写意见或手动创建该文件。"
        )
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValidationError(f"{FEEDBACK_REL} 内容为空。")
    return text


def _append_history(ctx: AgentContext, feedback: str, routes: list[ReviseRoute], reason: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    route_text = ", ".join(route_label(r) for r in routes) or "无"
    block = (
        f"\n## {ts}\n\n"
        f"**路由**：{route_text}\n\n"
        f"**分类**：{reason}\n\n"
        f"**用户意见**：\n\n{feedback}\n"
    )
    hist = ctx.output_path / HISTORY_REL
    if hist.exists():
        fw.write_text(ctx.output_path, HISTORY_REL, hist.read_text(encoding="utf-8") + block)
    else:
        fw.write_text(ctx.output_path, HISTORY_REL, "# 修订历史\n" + block)


def _record_design_followup(ctx: AgentContext, feedback: str) -> None:
    note = (
        f"## {datetime.now(timezone.utc).isoformat()}\n\n"
        f"{feedback}\n\n"
        "请先执行：`python uiforge.py --task design --input <需求.md> --output <本目录>`\n"
        "再执行 `--task code` 或 `--task revise`。\n\n"
    )
    path = ctx.output_path / DESIGN_FOLLOWUP_REL
    if path.exists():
        fw.write_text(ctx.output_path, DESIGN_FOLLOWUP_REL, path.read_text(encoding="utf-8") + "\n" + note)
    else:
        fw.write_text(ctx.output_path, DESIGN_FOLLOWUP_REL, "# 设计跟进\n\n" + note)
    ctx.log(f"[ReviseAgent] 已记录设计级意见 → {DESIGN_FOLLOWUP_REL}")


def _run_route(
    ctx: AgentContext,
    llm: LLMClient,
    base: CodeBaseContext,
    route: ReviseRoute,
    feedback: str,
    *,
    round_no: int,
) -> None:
    prefix = "[ReviseAgent]"
    debug = f"llm_revise_r{round_no}_{route}.txt"
    kwargs = dict(user_feedback=feedback, log_prefix=prefix, debug_name=debug)

    if route == "main_page":
        _step_main_page(ctx, llm, base, **kwargs)
    elif route == "components":
        _step_components(ctx, llm, base, **kwargs)
    elif route == "api":
        if not project_uses_rest_api(ctx):
            ctx.log("[ReviseAgent] 跳过 API 步骤（当前项目无 REST API）")
            return
        _step_api(ctx, llm, base, **kwargs)
    elif route == "styles":
        _step_styles(ctx, llm, base, **kwargs)


def run(ctx: AgentContext, llm: LLMClient | None) -> None:
    ctx.log("[ReviseAgent] 开始按意见路由修订...")
    if not llm or not os.getenv("DEEPSEEK_API_KEY"):
        raise ValidationError("revise 阶段需要 DEEPSEEK_API_KEY。")

    feedback = load_feedback(ctx)
    base = _load_code_context(ctx)
    validate_main_page_artifact(ctx.output_path)

    routes, reason = classify_feedback(
        ctx,
        llm,
        feedback,
        design_spec_json=base.design_spec_json,
    )
    if not routes:
        raise ValidationError("无法从意见中识别修订范围。")

    routes = resolve_revise_routes(
        ctx,
        routes,
        main_page_rel=base.main_page_rel,
        feedback=feedback,
    )

    executable = [r for r in routes if r in EXECUTABLE_ROUTES]
    if "design" in routes:
        _record_design_followup(ctx, feedback)
        ctx.log("[ReviseAgent] 意见含设计级变更，请先 --task design")

    if not executable:
        raise ValidationError(
            "意见仅涉及设计级变更，请先执行 --task design 更新设计后再 revise。"
        )

    ctx.log(f"[ReviseAgent] 将执行: {[route_label(r) for r in executable]}")
    for i, route in enumerate(executable, start=1):
        ctx.log(f"[ReviseAgent] → {route_label(route)}")
        _run_route(ctx, llm, base, route, feedback, round_no=i)

    validate_main_page_artifact(ctx.output_path)
    warnings = validate_code_outputs(ctx)
    if warnings:
        ctx.log(f"[ReviseAgent] 收尾校验 {len(warnings)} 条警告")

    repair_project_integrity(ctx, llm)
    _append_history(ctx, feedback, routes, reason)
    ctx.log("[ReviseAgent] 修订完成")
