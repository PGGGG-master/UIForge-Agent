from __future__ import annotations

import os

from agent.context import AgentContext
from agent.llm_client import LLMClient
from agent.stages import report_agent, test_asset_agent, test_codegen
from agent.test_runner import run as run_vitest
from agent.validators import ValidationError, validate_test_files_artifact


def run(ctx: AgentContext, llm: LLMClient | None = None) -> None:
    """
    test 阶段（两次 LLM + 一次 Vitest）：
    1. 准备 Vitest 环境
    2. LLM：根据项目源码生成 tests/*.test.jsx
    3. Vitest 执行（无 LLM）→ report/vitest_result.json
    4. LLM：根据测试结果生成 report/test_report.md
    """
    ctx.log("[Test] 开始...")

    if not llm:
        try:
            llm = LLMClient()
        except RuntimeError as exc:
            raise ValidationError(
                f"test 阶段需要 DEEPSEEK_API_KEY（生成测试与报告）: {exc}"
            ) from exc

    if not os.getenv("DEEPSEEK_API_KEY"):
        raise ValidationError("test 阶段需要配置 DEEPSEEK_API_KEY。")

    test_asset_agent.run(ctx)

    ctx.log("[Test] 第 1 次 LLM：根据项目代码生成测试文件...")
    test_codegen.generate(ctx, llm)
    validate_test_files_artifact(ctx.output_path)

    ctx.log("[Test] 执行 Vitest（无 LLM）...")
    run_vitest(ctx)

    ctx.log("[Test] 第 2 次 LLM：根据测试结果生成检测报告...")
    report_agent.write_test_report(ctx, llm)

    ctx.log("[Test] 完成，报告: report/test_report.md")
