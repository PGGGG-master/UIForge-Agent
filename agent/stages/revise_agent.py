from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from agent import file_writer as fw
from agent.code_integrity import repair_project_integrity
from agent.code_validate import validate_code_outputs
from agent.context import AgentContext
from agent.design_tools import ensure_mmdc
from agent.design_validate import validate_design_outputs
from agent.llm_client import LLMClient
from agent.revise_router import (
    CODE_ROUTES,
    DESIGN_ROUTES,
    ReviseRoute,
    classify_feedback,
    is_code_route,
    is_design_route,
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
from agent.stages.design_agent import (
    DesignBaseContext,
    _load_base_context,
    _step_api as _step_design_api,
    _step_class_diagram,
    _step_component,
    _step_design_spec,
    _step_state,
    _step_state_machine,
)
from agent.validators import (
    ValidationError,
    project_uses_rest_api,
    validate_design_artifacts,
    validate_main_page_artifact,
)

FEEDBACK_REL = "feedback/revision.md"
HISTORY_REL = "report/revision_history.md"


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


def _run_code_route(
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
            ctx.log("[ReviseAgent] 跳过 Code API 步骤（当前项目无 REST API）")
            return
        _step_api(ctx, llm, base, **kwargs)
    elif route == "styles":
        _step_styles(ctx, llm, base, **kwargs)


def _run_design_route(
    ctx: AgentContext,
    llm: LLMClient,
    base: DesignBaseContext,
    mmdc_cmd: list[str],
    route: ReviseRoute,
    feedback: str,
    *,
    round_no: int,
) -> None:
    prefix = "[ReviseAgent]"
    debug = f"llm_revise_r{round_no}_{route}.txt"
    kwargs = dict(user_feedback=feedback, log_prefix=prefix, debug_name=debug)

    if route == "design_component":
        _step_component(ctx, llm, base, **kwargs)
    elif route == "design_state":
        _step_state(ctx, llm, base, **kwargs)
    elif route == "design_api":
        _step_design_api(ctx, llm, base, **kwargs)
    elif route == "design_class":
        _step_class_diagram(ctx, llm, base, mmdc_cmd, **kwargs)
    elif route == "design_state_machine":
        _step_state_machine(ctx, llm, base, mmdc_cmd, **kwargs)
    elif route == "design_spec":
        _step_design_spec(ctx, llm, base, **kwargs)


def run(ctx: AgentContext, llm: LLMClient | None) -> None:
    ctx.log("[ReviseAgent] 开始按意见路由修订...")
    if not llm or not os.getenv("DEEPSEEK_API_KEY"):
        raise ValidationError("revise 阶段需要 DEEPSEEK_API_KEY。")

    feedback = load_feedback(ctx)

    design_spec_json = ""
    spec_path = ctx.output_path / "design" / "design_spec.json"
    if spec_path.exists():
        design_spec_json = spec_path.read_text(encoding="utf-8")

    routes, reason = classify_feedback(
        ctx,
        llm,
        feedback,
        design_spec_json=design_spec_json,
    )
    if not routes:
        raise ValidationError("无法从意见中识别修订范围。")

    main_page_rel = "src/pages/AppPage.jsx"
    if spec_path.exists():
        try:
            import json

            spec = json.loads(design_spec_json)
            page = spec.get("page_component", "AppPage")
            if isinstance(page, str) and page.strip():
                main_page_rel = f"src/pages/{page.strip()}.jsx"
        except Exception:
            pass

    routes = resolve_revise_routes(
        ctx,
        routes,
        main_page_rel=main_page_rel,
        feedback=feedback,
    )

    design_routes = [r for r in routes if is_design_route(r)]
    code_routes = [r for r in routes if is_code_route(r)]

    if design_routes:
        validate_design_artifacts(ctx.output_path)
    if code_routes:
        validate_main_page_artifact(ctx.output_path)

    if not design_routes and not code_routes:
        raise ValidationError("无法从意见中识别可执行的修订范围。")

    ctx.log(f"[ReviseAgent] 将执行: {[route_label(r) for r in routes]}")

    design_base: DesignBaseContext | None = None
    mmdc_cmd: list[str] | None = None
    if design_routes:
        design_base = _load_base_context(ctx)
        mmdc_cmd = ensure_mmdc(ctx.project_root)

    code_base: CodeBaseContext | None = None
    if code_routes:
        code_base = _load_code_context(ctx)

    for i, route in enumerate(routes, start=1):
        ctx.log(f"[ReviseAgent] → {route_label(route)}")
        if is_design_route(route):
            assert design_base is not None and mmdc_cmd is not None
            _run_design_route(
                ctx, llm, design_base, mmdc_cmd, route, feedback, round_no=i
            )
        elif is_code_route(route):
            assert code_base is not None
            _run_code_route(ctx, llm, code_base, route, feedback, round_no=i)

    if design_routes:
        warnings = validate_design_outputs(
            ctx.output_path,
            ctx.requirement_text,
            project_root=ctx.project_root,
        )
        if warnings:
            ctx.log(f"[ReviseAgent] 设计收尾校验 {len(warnings)} 条警告")

    if code_routes:
        validate_main_page_artifact(ctx.output_path)
        warnings = validate_code_outputs(ctx)
        if warnings:
            ctx.log(f"[ReviseAgent] 代码收尾校验 {len(warnings)} 条警告")
        repair_project_integrity(ctx, llm)

    _append_history(ctx, feedback, routes, reason)
    ctx.log("[ReviseAgent] 修订完成")
