from __future__ import annotations

from agent.context import AgentContext
from agent.validators import validate_code_artifacts, validate_design_artifacts


def design_load_check(ctx: AgentContext) -> None:
    ctx.log("[检查] 验证设计产物...")
    validate_design_artifacts(ctx.output_path)


def code_load_check(ctx: AgentContext) -> None:
    ctx.log("[检查] 验证代码产物...")
    validate_code_artifacts(ctx.output_path)
