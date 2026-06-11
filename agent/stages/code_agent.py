from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader

from agent import file_writer as fw
from agent.code_integrity import find_missing_local_imports, repair_project_integrity
from agent.code_validate import (
    collect_css_imports,
    validate_api_artifacts,
    validate_code_outputs,
    validate_css_imports,
    validate_main_page_file,
)
from agent.context import AgentContext
from agent.llm_client import LLMClient
from agent.stages.blocks import write_fenced_blocks, write_step_fenced_blocks
from agent.validators import (
    REFERENCE_PAGE_COMPONENT,
    ValidationError,
    apply_page_component_name,
    main_page_rel_path,
    normalize_page_component,
    project_uses_rest_api,
    validate_main_page_artifact,
)


@dataclass
class CodeBaseContext:
    requirement_text: str
    design_spec_json: str
    component_design: str
    api_contract: str
    page_component: str
    main_page_rel: str


def _load_code_context(ctx: AgentContext) -> CodeBaseContext:
    if not ctx.design_spec:
        ctx.design_spec = fw.read_json(ctx.output_path, "design/design_spec.json") or {}
    apply_page_component_name(ctx.design_spec)
    page = normalize_page_component(ctx.design_spec)
    return CodeBaseContext(
        requirement_text=ctx.requirement_text,
        design_spec_json=fw.read_text(ctx.output_path, "design/design_spec.json") or "{}",
        component_design=fw.read_text(ctx.output_path, "design/component_design.md") or "",
        api_contract=fw.read_text(ctx.output_path, "design/api_contract.md") or "",
        page_component=page,
        main_page_rel=main_page_rel_path(ctx.design_spec),
    )


def _render_templates(ctx: AgentContext, templates_dir: Path) -> None:
    env = Environment(loader=FileSystemLoader(templates_dir), keep_trailing_newline=True)
    page_name = ctx.design_spec.get("page_component", "AppPage")
    ctx_vars = {
        "page_component": page_name,
        "project_name": ctx.output_path.name,
    }
    mapping = {
        "package.json.j2": "package.json",
        "vite.config.js.j2": "vite.config.js",
        "index.html.j2": "index.html",
        "src/main.jsx.j2": "src/main.jsx",
        "src/App.jsx.j2": "src/App.jsx",
    }
    if project_uses_rest_api(ctx):
        mapping["src/mocks/server.js.j2"] = "src/mocks/server.js"
    for tpl_name, out_rel in mapping.items():
        content = env.get_template(tpl_name).render(**ctx_vars)
        fw.write_text(ctx.output_path, out_rel, content)
        ctx.add_manifest(out_rel)


def _copy_reference_fallback(ctx: AgentContext, templates_dir: Path) -> None:
    page = normalize_page_component(ctx.design_spec)
    if page != REFERENCE_PAGE_COMPONENT:
        ctx.log(
            f"[CodeAgent] 跳过 reference 拷贝（主页面为 {page}，"
            f"reference 仅适配 {REFERENCE_PAGE_COMPONENT}）"
        )
        return
    ref_dir = templates_dir / "reference"
    if not ref_dir.exists():
        return
    for path in ref_dir.rglob("*"):
        if path.is_file():
            rel = path.relative_to(ref_dir).as_posix()
            target = ctx.output_path / rel
            if not target.exists():
                fw.write_text(ctx.output_path, rel, path.read_text(encoding="utf-8"))
                ctx.add_manifest(rel)


def _save_llm_debug(ctx: AgentContext, name: str, text: str) -> None:
    ctx.output_path.joinpath("report").mkdir(parents=True, exist_ok=True)
    fw.write_text(ctx.output_path, f"report/{name}", text[:50000])


def _read_main_page_source(ctx: AgentContext, base: CodeBaseContext) -> str:
    path = ctx.output_path / base.main_page_rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_component_sources(ctx: AgentContext, main_src: str) -> str:
    """读取主页面 import 的子组件源码，供样式步骤对齐 className。"""
    imports = re.findall(
        r"""from\s+['"](?:\.\./|\./)components/([\w-]+)['"]""",
        main_src,
    )
    parts: list[str] = []
    for name in imports:
        comp_path = ctx.output_path / "src" / "components" / f"{name}.jsx"
        if not comp_path.exists():
            continue
        rel = f"src/components/{name}.jsx"
        text = comp_path.read_text(encoding="utf-8", errors="ignore")
        parts.append(f"--- {rel} ---\n{text}")
    return "\n\n".join(parts) if parts else "（无子组件文件）"


_SKIP_LINE_RE = re.compile(
    r"^\s*(?:无需额外子组件文件|无需额外子组件|无需\s*CSS\s*文件|无需\s*CSS)\s*\.?\s*$",
    re.MULTILINE | re.IGNORECASE,
)

_COMPONENT_IMPORT_RE = re.compile(
    r"""from\s+['"](?:\.\./|\./)components/([\w-]+)['"]""",
)


def _is_skip_response(response: str) -> bool:
    """仅当回复为明确的单行跳过声明且无代码块时视为跳过。"""
    t = response.strip()
    if not t:
        return True
    if "```" in t or re.search(r"^\s*//\s*path:\s*", t, re.MULTILINE):
        return False
    if _SKIP_LINE_RE.search(t):
        return True
    # 极短且无代码特征时才视为跳过
    if len(t) < 80 and "无需" in t and "组件" in t:
        return True
    return False


def _missing_component_imports(ctx: AgentContext, base: CodeBaseContext) -> list[str]:
    main_src = _read_main_page_source(ctx, base)
    names = _COMPONENT_IMPORT_RE.findall(main_src)
    missing: list[str] = []
    for name in dict.fromkeys(names):
        comp = ctx.output_path / "src" / "components" / f"{name}.jsx"
        if not comp.exists():
            missing.append(name)
    return missing


def _run_code_step(
    ctx: AgentContext,
    llm: LLMClient,
    *,
    step_no: int,
    total: int,
    prompt_name: str,
    user_kwargs: dict[str, str],
    validate_fn: Callable[[], str | None],
    optional: bool = False,
    path_prefixes: list[str] | None = None,
    path_suffixes: list[str] | None = None,
    pick_best_path: str | None = None,
    user_feedback: str = "",
    log_prefix: str = "[CodeAgent]",
    debug_name: str | None = None,
    allow_skip: bool = True,
) -> int:
    ctx.log(f"{log_prefix} Step {step_no}/{total} {prompt_name}...")
    system, user_tpl = llm.load_prompt(prompt_name)
    user = user_tpl.format(**user_kwargs)
    if user_feedback.strip():
        user = (
            f"{user}\n\n## 用户修订意见（必须落实）\n{user_feedback.strip()}\n\n"
            "在保持本步输出约束下修改现有实现以满足上述意见；输出完整可替换的文件。"
        )
    last_err = ""

    for attempt in range(1, 3):
        prompt_user = user
        if attempt > 1 and last_err:
            prompt_user = (
                f"{user}\n\n上次校验失败：{last_err}\n"
                "请修正并输出完整代码块（首行 // path: ...）。"
            )
        response = llm.complete(system, prompt_user, max_tokens=16384)
        _save_llm_debug(
            ctx,
            debug_name or f"llm_code_step{step_no}_attempt{attempt}.txt",
            response,
        )

        if optional and allow_skip and _is_skip_response(response):
            ctx.log(f"{log_prefix} Step {step_no}/{total} 跳过（无需额外文件）")
            return 0

        n = write_step_fenced_blocks(
            ctx,
            response,
            path_prefixes=path_prefixes,
            path_suffixes=path_suffixes,
            pick_best_path=pick_best_path,
            tests_only=False,
        )
        if n:
            ctx.log(f"{log_prefix} Step {step_no}/{total} 写入 {n} 个文件")

        last_err = validate_fn() or ""
        if not last_err:
            ctx.log(f"{log_prefix} Step {step_no}/{total} 完成")
            return n

        if optional and allow_skip and n == 0 and _is_skip_response(response):
            ctx.log(f"{log_prefix} Step {step_no}/{total} 完成（无文件）")
            return 0

    if optional and allow_skip:
        ctx.log(f"{log_prefix} Step {step_no}/{total} 警告: {last_err}（可选步骤继续）")
        return 0
    raise ValidationError(f"Step {step_no} ({prompt_name}) 失败: {last_err}")


def _step_main_page(
    ctx: AgentContext,
    llm: LLMClient,
    base: CodeBaseContext,
    *,
    user_feedback: str = "",
    log_prefix: str = "[CodeAgent]",
    debug_name: str | None = None,
) -> None:
    def validate() -> str | None:
        return validate_main_page_file(
            ctx.output_path / base.main_page_rel,
            base.page_component,
        )

    _run_code_step(
        ctx,
        llm,
        step_no=1,
        total=4,
        prompt_name="code_main_page",
        user_kwargs={
            "requirement_text": base.requirement_text[:4000],
            "design_spec": base.design_spec_json[:5000],
            "component_design": base.component_design[:3000],
            "page_component": base.page_component,
            "main_page_rel": base.main_page_rel,
        },
        validate_fn=validate,
        pick_best_path=base.main_page_rel,
        path_prefixes=["src/pages/"],
        user_feedback=user_feedback,
        log_prefix=log_prefix,
        debug_name=debug_name,
    )


def _step_components(
    ctx: AgentContext,
    llm: LLMClient,
    base: CodeBaseContext,
    *,
    user_feedback: str = "",
    log_prefix: str = "[CodeAgent]",
    debug_name: str | None = None,
) -> None:
    main_src = _read_main_page_source(ctx, base)
    missing_before = _missing_component_imports(ctx, base)
    allow_skip = len(missing_before) == 0
    if missing_before:
        ctx.log(
            f"[CodeAgent] Step 2 需生成子组件: {', '.join(missing_before)}"
        )

    def validate() -> str | None:
        err = validate_main_page_file(
            ctx.output_path / base.main_page_rel,
            base.page_component,
        )
        if err:
            return err
        still = _missing_component_imports(ctx, base)
        if not still:
            return None
        return (
            f"主页面仍缺子组件: {', '.join(still)}。"
            "请为每个 import 输出独立 ```jsx 代码块（首行 // path: src/components/Name.jsx）。"
        )

    import_list = ", ".join(dict.fromkeys(_COMPONENT_IMPORT_RE.findall(main_src)))
    user_kwargs = {
        "requirement_text": base.requirement_text[:3000],
        "design_spec": base.design_spec_json[:5000],
        "component_design": base.component_design[:3000],
        "main_page_rel": base.main_page_rel,
        "main_page_source": main_src[:8000] or "(主页面尚未生成)",
    }
    if import_list:
        user_kwargs["required_components"] = import_list
    else:
        user_kwargs["required_components"] = "（主页面未 import 子组件）"

    _run_code_step(
        ctx,
        llm,
        step_no=2,
        total=4,
        prompt_name="code_components",
        user_kwargs=user_kwargs,
        validate_fn=validate,
        optional=True,
        allow_skip=allow_skip,
        path_prefixes=["src/components/"],
        user_feedback=user_feedback,
        log_prefix=log_prefix,
        debug_name=debug_name,
    )


def _step_api(
    ctx: AgentContext,
    llm: LLMClient,
    base: CodeBaseContext,
    *,
    user_feedback: str = "",
    log_prefix: str = "[CodeAgent]",
    debug_name: str | None = None,
) -> None:
    def validate() -> str | None:
        return validate_api_artifacts(ctx.output_path)

    _run_code_step(
        ctx,
        llm,
        step_no=3,
        total=4,
        prompt_name="code_api",
        user_kwargs={
            "requirement_text": base.requirement_text[:3500],
            "design_spec": base.design_spec_json[:5000],
            "api_contract": base.api_contract[:4000],
        },
        validate_fn=validate,
        path_prefixes=["src/api/", "src/mocks/"],
        user_feedback=user_feedback,
        log_prefix=log_prefix,
        debug_name=debug_name,
    )


def _step_styles(
    ctx: AgentContext,
    llm: LLMClient,
    base: CodeBaseContext,
    *,
    user_feedback: str = "",
    log_prefix: str = "[CodeAgent]",
    debug_name: str | None = None,
) -> None:
    css_imports = collect_css_imports(ctx.output_path)
    css_list = "\n".join(f"- {p}" for p in css_imports) if css_imports else "（无）"
    main_src = _read_main_page_source(ctx, base)
    component_src = _read_component_sources(ctx, main_src)

    def validate() -> str | None:
        if not css_imports:
            return None
        err = validate_css_imports(ctx.output_path)
        if err:
            return err
        still_missing = [
            m["expected"]
            for m in find_missing_local_imports(ctx.output_path)
            if m["expected"].endswith(".css")
        ]
        if still_missing:
            return f"仍缺 CSS: {', '.join(still_missing[:3])}"
        return None

    _run_code_step(
        ctx,
        llm,
        step_no=4,
        total=4,
        prompt_name="code_styles",
        user_kwargs={
            "requirement_text": base.requirement_text[:2000],
            "css_imports": css_list,
            "main_page_rel": base.main_page_rel,
            "main_page_source": main_src[:8000] or "(主页面尚未生成)",
            "component_sources": component_src[:12000],
        },
        validate_fn=validate,
        optional=not bool(css_imports),
        path_suffixes=[".css"],
        user_feedback=user_feedback,
        log_prefix=log_prefix,
        debug_name=debug_name,
    )


def run(ctx: AgentContext, llm: LLMClient | None) -> None:
    ctx.log("[CodeAgent] 开始多步代码生成 (4 steps)...")
    base = _load_code_context(ctx)
    ctx.log(f"[CodeAgent] 主页面组件: {base.page_component} → {base.main_page_rel}")
    fw.write_json(ctx.output_path, "design/design_spec.json", ctx.design_spec)

    root = Path(ctx.project_root or Path(__file__).resolve().parent.parent.parent)
    templates_dir = root / "templates"
    _render_templates(ctx, templates_dir)

    if llm and os.getenv("DEEPSEEK_API_KEY"):
        _step_main_page(ctx, llm, base)
        _step_components(ctx, llm, base)
        if project_uses_rest_api(ctx):
            _step_api(ctx, llm, base)
        else:
            ctx.log("[CodeAgent] Step 3/4 跳过（无 REST API）")
        _step_styles(ctx, llm, base)
    else:
        ctx.log("[CodeAgent] 未配置 LLM，跳过模型生成")

    _copy_reference_fallback(ctx, templates_dir)

    page = base.page_component
    main_exists = (ctx.output_path / base.main_page_rel).exists()
    if not main_exists:
        if page == REFERENCE_PAGE_COMPONENT:
            _copy_reference_fallback(ctx, templates_dir)
        else:
            raise ValidationError(
                f"缺少主页面 {base.main_page_rel}。"
                f"请配置 DEEPSEEK_API_KEY 后重新执行 code。"
            )

    validate_main_page_artifact(ctx.output_path)
    warnings = validate_code_outputs(ctx)
    if warnings:
        ctx.log(f"[CodeAgent] 收尾校验 {len(warnings)} 条警告 → report/code_validation.md")

    repair_project_integrity(ctx, llm if llm and os.getenv("DEEPSEEK_API_KEY") else None)

    apply_page_component_name(ctx.design_spec)
    ctx.log("[CodeAgent] 完成")
