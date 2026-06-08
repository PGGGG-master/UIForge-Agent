from __future__ import annotations

import os
from pathlib import Path

from agent import file_writer as fw
from agent.context import AgentContext
from agent.llm_client import LLMClient
from agent.stages.blocks import write_fenced_blocks
from agent.validators import (
    ValidationError,
    apply_page_component_name,
    main_page_rel_path,
    normalize_page_component,
    tests_dir_has_files,
)


def _project_code_summary(ctx: AgentContext, *, max_files: int = 24, per_file: int = 3500) -> str:
    """汇总项目源码，供 test 阶段 LLM 生成测试。"""
    parts: list[str] = []
    root = ctx.output_path
    candidates: list[Path] = []
    for pattern in ("src/**/*.jsx", "src/**/*.js", "src/**/*.css"):
        candidates.extend(sorted(root.glob(pattern)))
    for path in candidates[:max_files]:
        if "node_modules" in path.parts or "mocks" in path.parts and "handlers" not in path.name:
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


def generate(ctx: AgentContext, llm: LLMClient | None) -> None:
    """test 阶段：根据当前项目代码生成 tests/*.test.jsx（调用 LLM）。"""
    ctx.log("[TestCodegen] 根据项目代码生成测试...")
    if not ctx.design_spec:
        ctx.design_spec = fw.read_json(ctx.output_path, "design/design_spec.json") or {}
    apply_page_component_name(ctx.design_spec)
    page = normalize_page_component(ctx.design_spec)
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
    response = llm.complete(system, user, max_tokens=16384)
    n = write_fenced_blocks(ctx, response, tests_only=True)
    ctx.log(f"[TestCodegen] 解析写入 {n} 个测试文件")

    if not tests_dir_has_files(ctx.output_path):
        ctx.log("[TestCodegen] 首次未落盘，重试...")
        retry_user = (
            f"{user}\n\n"
            f"上次未生成有效测试文件。请只输出：\n"
            f"// path: tests/{page}.test.jsx\n"
            f"至少 4 个 it()，针对已提供的项目源码与需求文案断言。"
        )
        response2 = llm.complete(system, retry_user, max_tokens=16384)
        fw.write_text(ctx.output_path, "report/llm_test_codegen_retry.txt", response2[:50000])
        write_fenced_blocks(ctx, response2, tests_only=True)

    if not tests_dir_has_files(ctx.output_path):
        raise ValidationError(
            "test 阶段未能生成 tests/*.test.jsx，请检查 code 产物或重试。"
        )
    ctx.log("[TestCodegen] 完成")
