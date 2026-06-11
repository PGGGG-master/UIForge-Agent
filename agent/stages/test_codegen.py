from __future__ import annotations

import os
from pathlib import Path

from agent import file_writer as fw
from agent.context import AgentContext
from agent.llm_client import LLMClient
from agent.stages.blocks import write_fenced_blocks
from agent.test_validate import (
    extract_test_body_from_response,
    validate_test_outputs,
)
from agent.validators import (
    ValidationError,
    apply_page_component_name,
    main_page_rel_path,
    normalize_page_component,
)


def _project_code_summary(ctx: AgentContext, *, max_files: int = 24, per_file: int = 3500) -> str:
    """汇总项目源码，供 test 阶段 LLM 生成测试。"""
    parts: list[str] = []
    root = ctx.output_path
    candidates: list[Path] = []
    for pattern in ("src/**/*.jsx", "src/**/*.js", "src/**/*.css"):
        candidates.extend(sorted(root.glob(pattern)))
    for path in candidates[:max_files]:
        if "node_modules" in path.parts:
            continue
        if path.name in ("setupTests.js",):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        parts.append(f"### {rel}\n```\n{text[:per_file]}\n```")
    if not parts:
        return "（暂无 src 源码，请先执行 code 阶段）"
    return "\n\n".join(parts)


def _write_test_from_response(
    ctx: AgentContext,
    response: str,
    *,
    target_rel: str,
) -> int:
    body = extract_test_body_from_response(response, target_rel=target_rel)
    if body:
        fw.write_text(ctx.output_path, target_rel, body)
        ctx.add_manifest(target_rel)
        return 1
    return write_fenced_blocks(ctx, response, tests_only=True)


def generate(ctx: AgentContext, llm: LLMClient | None) -> None:
    """test 阶段：根据当前项目代码生成 tests/*.test.jsx（调用 LLM）。"""
    ctx.log("[TestCodegen] 根据项目代码生成测试...")
    if not ctx.design_spec:
        ctx.design_spec = fw.read_json(ctx.output_path, "design/design_spec.json") or {}
    apply_page_component_name(ctx.design_spec)
    page = normalize_page_component(ctx.design_spec)
    target_rel = f"tests/{page}.test.jsx"
    main_rel = main_page_rel_path(ctx.design_spec)

    if not llm or not os.getenv("DEEPSEEK_API_KEY"):
        raise ValidationError("test 阶段需要 DEEPSEEK_API_KEY 以生成测试用例。")

    code_summary = _project_code_summary(ctx)
    system, user_tpl = llm.load_prompt("test_codegen")
    user = user_tpl.format(
        requirement_text=ctx.requirement_text,
        design_spec=fw.read_text(ctx.output_path, "design/design_spec.json") or "{}",
        api_contract=fw.read_text(ctx.output_path, "design/api_contract.md") or "无 REST API",
        page_component=page,
        main_page_path=main_rel,
        code_summary=code_summary,
    )
    last_err = ""

    for attempt in range(1, 4):
        prompt_user = user
        if attempt > 1 and last_err:
            prompt_user = (
                f"{user}\n\n上次校验失败：{last_err}\n"
                f"请输出完整 tests/{page}.test.jsx：\n"
                f"- 使用 ```jsx 围栏，首行 // path: {target_rel}\n"
                f"- 必须包含 describe(...) 与至少 4 个 it(...)\n"
                f"- 禁止只输出 import，禁止输出思考说明文字"
            )
        response = llm.complete(system, prompt_user, max_tokens=16384)
        ctx.output_path.joinpath("report").mkdir(parents=True, exist_ok=True)
        fw.write_text(
            ctx.output_path,
            f"report/llm_test_codegen_attempt{attempt}.txt",
            response[:50000],
        )
        n = _write_test_from_response(ctx, response, target_rel=target_rel)
        ctx.log(f"[TestCodegen] 第 {attempt} 次解析写入 {n} 个测试文件")

        min_it = 4 if attempt < 3 else 2
        last_err = validate_test_outputs(ctx.output_path, min_it=min_it) or ""
        if not last_err:
            ctx.log("[TestCodegen] 完成")
            return

    raise ValidationError(f"test 阶段未能生成有效测试: {last_err}")
