from __future__ import annotations

from agent import file_writer as fw
from agent.context import AgentContext
from agent.testing.bootstrap import ensure_vitest_infrastructure
from agent.validators import apply_page_component_name


def run(ctx: AgentContext, llm=None) -> None:
    """test 阶段：准备 Vitest 通用配置（package.json、vite、setupTests），不调用 LLM。"""
    ctx.log("[TestPrepare] 准备 Vitest 环境...")
    if not ctx.design_spec:
        ctx.design_spec = fw.read_json(ctx.output_path, "design/design_spec.json") or {}
    apply_page_component_name(ctx.design_spec)
    ensure_vitest_infrastructure(ctx)
    ctx.log("[TestPrepare] 完成")
