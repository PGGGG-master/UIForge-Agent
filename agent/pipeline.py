from __future__ import annotations

from agent.context import AgentContext
from agent.llm_client import LLMClient
from agent.stages import (
    code_agent,
    design_agent,
    report_agent,
    requirement_agent,
    test_agent,
)
from agent.stages.checks import code_load_check, design_load_check
from agent.stages import revise_agent
from agent import feedback_server


def _get_llm() -> LLMClient:
    return LLMClient()


def run_pipeline(ctx: AgentContext) -> AgentContext:
    task = ctx.task

    if task in ("full", "design"):
        requirement_agent.run(ctx, _get_llm())
        design_agent.run(ctx, _get_llm())

    if task == "full":
        code_agent.run(ctx, _get_llm())
        test_agent.run(ctx, _get_llm())
        report_agent.run(ctx)

    elif task == "design":
        report_agent.run(ctx)

    elif task == "code":
        design_load_check(ctx)
        code_agent.run(ctx, _get_llm())
        report_agent.run(ctx)

    elif task == "test":
        code_load_check(ctx)
        test_agent.run(ctx, _get_llm())

    elif task == "revise":
        code_load_check(ctx)
        revise_agent.run(ctx, _get_llm())
        report_agent.run(ctx)

    elif task == "revise-ui":
        code_load_check(ctx)
        feedback_server.serve(
            ctx,
            port=getattr(ctx, "feedback_port", 8765),
            preview_url=getattr(ctx, "preview_url", "http://localhost:5173"),
            open_browser=getattr(ctx, "open_browser", True),
        )

    else:
        raise ValueError(f"未知任务类型: {task}")

    return ctx
