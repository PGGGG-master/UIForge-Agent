from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from agent import file_writer as fw
from agent.context import AgentContext
from agent.design_tools import (
    ensure_mmdc,
    validate_class_diagram_text,
    validate_design_spec_schema,
    validate_markdown_design,
    validate_mermaid_file,
    validate_state_machine_text,
)
from agent.design_validate import validate_design_outputs
from agent.file_writer import extract_fenced_blocks, extract_json_object
from agent.llm_client import LLMClient
from agent.validators import (
    ValidationError,
    apply_page_component_name,
    coerce_design_spec,
)


@dataclass
class DesignBaseContext:
    requirement_text: str
    requirement_analysis: str
    interaction_analysis: str
    requirement_spec_json: str


def _load_base_context(ctx: AgentContext) -> DesignBaseContext:
    req_spec = fw.read_json(ctx.output_path, "analysis/requirement_spec.json") or {}
    return DesignBaseContext(
        requirement_text=ctx.requirement_text,
        requirement_analysis=fw.read_text(ctx.output_path, "analysis/requirement_analysis.md") or "",
        interaction_analysis=fw.read_text(ctx.output_path, "analysis/interaction_analysis.md") or "",
        requirement_spec_json=json.dumps(req_spec, ensure_ascii=False, indent=2),
    )


def _read_design(ctx: AgentContext, rel: str) -> str:
    return fw.read_text(ctx.output_path, rel) or ""


def _parse_markdown_response(response: str) -> str:
    text = response.strip()
    if text.startswith("##") or text.startswith("#"):
        return text
    blocks = extract_fenced_blocks(response, "markdown")
    if blocks:
        return blocks[0][1]
    return text


def _parse_mermaid_response(response: str) -> str:
    blocks = extract_fenced_blocks(response, "mermaid")
    if blocks:
        return blocks[0][1].strip()
    text = response.strip()
    if text.startswith("classDiagram") or text.startswith("stateDiagram"):
        return text
    return text


def _append_revise_context(
    user: str,
    *,
    user_feedback: str = "",
    current_content: str = "",
) -> str:
    parts = [user]
    if current_content.strip():
        parts.append(f"\n\n## 当前内容（在此基础上修改）\n{current_content.strip()}")
    if user_feedback.strip():
        parts.append(
            f"\n\n## 用户修订意见（必须落实）\n{user_feedback.strip()}\n\n"
            "在保持本步输出约束下修改以满足上述意见。"
        )
    return "".join(parts)


def _save_llm_debug(ctx: AgentContext, name: str, text: str) -> None:
    ctx.output_path.joinpath("report").mkdir(parents=True, exist_ok=True)
    fw.write_text(ctx.output_path, f"report/{name}", text[:50000])


def _run_text_step(
    ctx: AgentContext,
    llm: LLMClient,
    *,
    step_no: int,
    prompt_name: str,
    user_kwargs: dict[str, str],
    out_rel: str,
    min_len: int = 30,
    extra_validate: Callable[[str], str | None] | None = None,
    user_feedback: str = "",
    current_content: str = "",
    log_prefix: str = "[DesignAgent]",
    debug_name: str | None = None,
) -> None:
    total = 6
    ctx.log(f"{log_prefix} Step {step_no}/{total} {prompt_name}...")
    system, user_tpl = llm.load_prompt(prompt_name)
    user = _append_revise_context(
        user_tpl.format(**user_kwargs),
        user_feedback=user_feedback,
        current_content=current_content,
    )
    last_err = ""

    for attempt in range(1, 3):
        prompt_user = user
        if attempt > 1 and last_err:
            prompt_user = f"{user}\n\n上次校验失败：{last_err}\n请修正后只输出本步要求的内容。"
        response = llm.complete(system, prompt_user)
        if debug_name:
            _save_llm_debug(ctx, f"{debug_name}_attempt{attempt}.txt", response)
        content = _parse_markdown_response(response)
        last_err = validate_markdown_design(content, min_len=min_len) or ""
        if not last_err and extra_validate:
            last_err = extra_validate(content) or ""
        if not last_err:
            fw.write_text(ctx.output_path, out_rel, content)
            ctx.add_manifest(out_rel)
            ctx.log(f"{log_prefix} Step {step_no}/{total} 完成 → {out_rel}")
            return

    raise ValidationError(f"Step {step_no} ({prompt_name}) 失败: {last_err}")


def _run_mermaid_step(
    ctx: AgentContext,
    llm: LLMClient,
    mmdc_cmd: list[str],
    *,
    step_no: int,
    prompt_name: str,
    user_kwargs: dict[str, str],
    out_rel: str,
    prefix_validate: Callable[[str], str | None],
    user_feedback: str = "",
    current_content: str = "",
    log_prefix: str = "[DesignAgent]",
    debug_name: str | None = None,
) -> None:
    total = 6
    ctx.log(f"{log_prefix} Step {step_no}/{total} {prompt_name}...")
    system, user_tpl = llm.load_prompt(prompt_name)
    user = _append_revise_context(
        user_tpl.format(**user_kwargs),
        user_feedback=user_feedback,
        current_content=current_content,
    )
    last_err = ""

    for attempt in range(1, 3):
        prompt_user = user
        if attempt > 1 and last_err:
            prompt_user = (
                f"{user}\n\n上次校验失败：{last_err}\n"
                "请输出可被 Mermaid 正确解析的代码块。"
            )
        response = llm.complete(system, prompt_user)
        if debug_name:
            _save_llm_debug(ctx, f"{debug_name}_attempt{attempt}.txt", response)
        content = _parse_mermaid_response(response)
        last_err = prefix_validate(content) or ""
        if not last_err:
            fw.write_text(ctx.output_path, out_rel, content)
            mmd_path = ctx.output_path / out_rel
            last_err = validate_mermaid_file(
                mmd_path,
                project_root=ctx.project_root,
                mmdc_cmd=mmdc_cmd,
            ) or ""
        if not last_err:
            ctx.add_manifest(out_rel)
            ctx.log(f"{log_prefix} Step {step_no}/{total} 完成 → {out_rel}")
            return

    raise ValidationError(f"Step {step_no} ({prompt_name}) 失败: {last_err}")


def _step_component(
    ctx: AgentContext,
    llm: LLMClient,
    base: DesignBaseContext,
    *,
    user_feedback: str = "",
    current_content: str = "",
    log_prefix: str = "[DesignAgent]",
    debug_name: str | None = None,
) -> None:
    _run_text_step(
        ctx,
        llm,
        step_no=1,
        prompt_name="design_component",
        user_kwargs={
            "requirement_text": base.requirement_text,
            "requirement_analysis": base.requirement_analysis,
            "interaction_analysis": base.interaction_analysis,
        },
        out_rel="design/component_design.md",
        min_len=50,
        user_feedback=user_feedback,
        current_content=current_content or _read_design(ctx, "design/component_design.md"),
        log_prefix=log_prefix,
        debug_name=debug_name,
    )


def _step_state(
    ctx: AgentContext,
    llm: LLMClient,
    base: DesignBaseContext,
    *,
    user_feedback: str = "",
    current_content: str = "",
    log_prefix: str = "[DesignAgent]",
    debug_name: str | None = None,
) -> None:
    _run_text_step(
        ctx,
        llm,
        step_no=2,
        prompt_name="design_state",
        user_kwargs={
            "requirement_text": base.requirement_text,
            "interaction_analysis": base.interaction_analysis,
            "component_design": _read_design(ctx, "design/component_design.md"),
        },
        out_rel="design/state_design.md",
        min_len=30,
        user_feedback=user_feedback,
        current_content=current_content or _read_design(ctx, "design/state_design.md"),
        log_prefix=log_prefix,
        debug_name=debug_name,
    )


def _step_api(
    ctx: AgentContext,
    llm: LLMClient,
    base: DesignBaseContext,
    *,
    user_feedback: str = "",
    current_content: str = "",
    log_prefix: str = "[DesignAgent]",
    debug_name: str | None = None,
) -> None:
    _run_text_step(
        ctx,
        llm,
        step_no=3,
        prompt_name="design_api",
        user_kwargs={
            "requirement_text": base.requirement_text,
            "requirement_spec_json": base.requirement_spec_json,
            "component_design": _read_design(ctx, "design/component_design.md"),
            "state_design": _read_design(ctx, "design/state_design.md"),
        },
        out_rel="design/api_contract.md",
        min_len=20,
        user_feedback=user_feedback,
        current_content=current_content or _read_design(ctx, "design/api_contract.md"),
        log_prefix=log_prefix,
        debug_name=debug_name,
    )


def _step_class_diagram(
    ctx: AgentContext,
    llm: LLMClient,
    base: DesignBaseContext,
    mmdc_cmd: list[str],
    *,
    user_feedback: str = "",
    current_content: str = "",
    log_prefix: str = "[DesignAgent]",
    debug_name: str | None = None,
) -> None:
    _run_mermaid_step(
        ctx,
        llm,
        mmdc_cmd,
        step_no=4,
        prompt_name="design_class_diagram",
        user_kwargs={
            "requirement_text": base.requirement_text[:3500],
            "component_design": _read_design(ctx, "design/component_design.md"),
            "state_design": _read_design(ctx, "design/state_design.md"),
        },
        out_rel="design/class_diagram.mmd",
        prefix_validate=validate_class_diagram_text,
        user_feedback=user_feedback,
        current_content=current_content or _read_design(ctx, "design/class_diagram.mmd"),
        log_prefix=log_prefix,
        debug_name=debug_name,
    )


def _step_state_machine(
    ctx: AgentContext,
    llm: LLMClient,
    base: DesignBaseContext,
    mmdc_cmd: list[str],
    *,
    user_feedback: str = "",
    current_content: str = "",
    log_prefix: str = "[DesignAgent]",
    debug_name: str | None = None,
) -> None:
    _run_mermaid_step(
        ctx,
        llm,
        mmdc_cmd,
        step_no=5,
        prompt_name="design_state_machine",
        user_kwargs={
            "interaction_analysis": base.interaction_analysis,
            "state_design": _read_design(ctx, "design/state_design.md"),
        },
        out_rel="design/state_machine.mmd",
        prefix_validate=validate_state_machine_text,
        user_feedback=user_feedback,
        current_content=current_content or _read_design(ctx, "design/state_machine.mmd"),
        log_prefix=log_prefix,
        debug_name=debug_name,
    )


def _step_design_spec(
    ctx: AgentContext,
    llm: LLMClient,
    base: DesignBaseContext,
    *,
    user_feedback: str = "",
    current_content: str = "",
    log_prefix: str = "[DesignAgent]",
    debug_name: str | None = None,
) -> None:
    step_no = 6
    ctx.log(f"{log_prefix} Step {step_no}/6 design_spec...")
    system, user_tpl = llm.load_prompt("design_spec")
    user = _append_revise_context(
        user_tpl.format(
            requirement_text=base.requirement_text[:3500],
            component_design=_read_design(ctx, "design/component_design.md"),
            state_design=_read_design(ctx, "design/state_design.md"),
            api_contract=_read_design(ctx, "design/api_contract.md"),
            class_diagram=_read_design(ctx, "design/class_diagram.mmd"),
            state_machine=_read_design(ctx, "design/state_machine.mmd"),
        ),
        user_feedback=user_feedback,
        current_content=current_content or _read_design(ctx, "design/design_spec.json"),
    )
    last_err = ""

    for attempt in range(1, 3):
        prompt_user = user
        if attempt > 1 and last_err:
            prompt_user = f"{user}\n\n上次校验失败：{last_err}\n请输出符合 schema 的 JSON 对象。"
        try:
            response = llm.complete(system, prompt_user)
            if debug_name:
                _save_llm_debug(ctx, f"{debug_name}_attempt{attempt}.txt", response)
            raw = extract_json_object(response)
        except ValueError:
            response = llm.complete_json(system, prompt_user)
            if debug_name:
                _save_llm_debug(ctx, f"{debug_name}_attempt{attempt}.txt", response)
            raw = extract_json_object(response)

        try:
            spec = coerce_design_spec(raw)
            apply_page_component_name(spec)
            last_err = validate_design_spec_schema(spec, project_root=ctx.project_root) or ""
            if not last_err:
                ctx.design_spec = spec
                fw.write_json(ctx.output_path, "design/design_spec.json", spec)
                ctx.add_manifest("design/design_spec.json")
                ctx.log(f"{log_prefix} Step 6/6 完成 → design/design_spec.json")
                return
        except ValidationError as exc:
            last_err = str(exc)

    raise ValidationError(f"Step 6 (design_spec) 失败: {last_err}")


def run(ctx: AgentContext, llm: LLMClient) -> None:
    ctx.log("[DesignAgent] 开始多步设计建模 (6 steps)...")
    mmdc_cmd = ensure_mmdc(ctx.project_root)
    base = _load_base_context(ctx)

    _step_component(ctx, llm, base)
    _step_state(ctx, llm, base)
    _step_api(ctx, llm, base)
    _step_class_diagram(ctx, llm, base, mmdc_cmd)
    _step_state_machine(ctx, llm, base, mmdc_cmd)
    _step_design_spec(ctx, llm, base)

    warnings = validate_design_outputs(
        ctx.output_path,
        ctx.requirement_text,
        project_root=ctx.project_root,
    )
    if warnings:
        ctx.log(f"[DesignAgent] 收尾校验完成，{len(warnings)} 条警告 → report/design_validation.md")
    else:
        ctx.log("[DesignAgent] 收尾校验通过")
    ctx.log("[DesignAgent] 完成")
