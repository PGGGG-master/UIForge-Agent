from __future__ import annotations

from agent import file_writer as fw
from agent.context import AgentContext
from agent.file_writer import extract_json_object, extract_markdown_section
from agent.llm_client import LLMClient


def run(ctx: AgentContext, llm: LLMClient) -> None:
    ctx.log("[RequirementAgent] 开始需求分析...")
    system, user_tpl = llm.load_prompt("requirement")
    user = user_tpl.format(requirement_text=ctx.requirement_text)
    response = llm.complete(system, user)

    req_analysis = extract_markdown_section(response, "页面目标")
    if not req_analysis or len(req_analysis) < 20:
        req_analysis = response

    fw.write_text(ctx.output_path, "analysis/requirement_analysis.md", req_analysis)
    ctx.add_manifest("analysis/requirement_analysis.md")

    try:
        ctx.requirement_spec = extract_json_object(response)
    except ValueError:
        ctx.requirement_spec = llm.complete_json(
            "输出 JSON 对象，包含 page_name, features, interactions, apis, error_handling。",
            f"需求：\n{ctx.requirement_text}\n\n分析：\n{req_analysis}",
        )
    fw.write_json(ctx.output_path, "analysis/requirement_spec.json", ctx.requirement_spec)
    ctx.add_manifest("analysis/requirement_spec.json")

    int_system, int_user_tpl = llm.load_prompt("interaction")
    int_user = int_user_tpl.format(
        requirement_text=ctx.requirement_text,
        requirement_analysis=req_analysis,
    )
    interaction = llm.complete(int_system, int_user)
    fw.write_text(ctx.output_path, "analysis/interaction_analysis.md", interaction)
    ctx.add_manifest("analysis/interaction_analysis.md")
    ctx.log("[RequirementAgent] 完成")
