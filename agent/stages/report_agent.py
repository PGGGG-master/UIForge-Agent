from __future__ import annotations

from datetime import datetime

from agent import file_writer as fw
from agent.context import AgentContext
from agent.llm_client import LLMClient


def _build_test_report_fallback(ctx: AgentContext) -> str:
    tr = ctx.test_result or {}
    total = tr.get("total", 0)
    passed = tr.get("passed", 0)
    failed = tr.get("failed", 0)
    rate = tr.get("pass_rate", 0)
    lines = [
        "# UIForge 测试报告",
        "",
        "## 测试概况",
        f"- 测试用例总数：{total}",
        f"- 通过数量：{passed}",
        f"- 失败数量：{failed}",
        f"- 测试通过率：{rate}%",
        "",
    ]
    failures = tr.get("failures", [])
    if failures:
        lines.append("## 失败用例")
        for item in failures:
            lines.append(f"### {item.get('name', 'unknown')}")
            lines.append(f"```\n{item.get('message', '')}\n```")
            lines.append("")
    return "\n".join(lines)


def _build_test_report_with_llm(ctx: AgentContext, llm: LLMClient) -> str:
    status_path = ctx.output_path / "report" / "test_status.json"
    vitest_path = ctx.output_path / "report" / "vitest_result.json"
    status_json = status_path.read_text(encoding="utf-8") if status_path.exists() else "{}"
    vitest_json = vitest_path.read_text(encoding="utf-8") if vitest_path.exists() else "{}"
    if len(vitest_json) > 12000:
        vitest_json = vitest_json[:12000] + "\n... (truncated)"

    system, user_tpl = llm.load_prompt("report")
    user = user_tpl.format(
        requirement_text=ctx.requirement_text[:3000],
        test_status_json=status_json,
        vitest_result_json=vitest_json,
    )
    return llm.complete(system, user)


def write_test_report(ctx: AgentContext, llm: LLMClient | None = None) -> None:
    """根据 Vitest JSON 生成 report/test_report.md。"""
    ctx.log("[Test] 生成 Markdown 测试报告...")
    report = _build_test_report_fallback(ctx)
    if llm:
        try:
            report = _build_test_report_with_llm(ctx, llm)
        except Exception as exc:
            ctx.log(f"[Test] LLM 报告生成失败，使用简易报告: {exc}")
    fw.write_text(ctx.output_path, "report/test_report.md", report)
    ctx.add_manifest("report/test_report.md")


def _build_generation_summary(ctx: AgentContext) -> str:
    lines = [
        "# UIForge 生成摘要",
        "",
        f"- 任务类型：{ctx.task}",
        f"- 输入文件：{ctx.input_path}",
        f"- 输出目录：{ctx.output_dir}",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 产物清单",
    ]
    for path in sorted(ctx.file_manifest):
        lines.append(f"- {path}")
    lines.append("")
    lines.append("## 阶段日志")
    lines.append("```")
    lines.extend(ctx.logs)
    lines.append("```")
    return "\n".join(lines)


def run(ctx: AgentContext, llm: LLMClient | None = None) -> None:
    """design / code / full 阶段结束时写入 generation_summary（不含测试报告）。"""
    ctx.log("[ReportAgent] 生成摘要...")
    summary = _build_generation_summary(ctx)
    fw.write_text(ctx.output_path, "report/generation_summary.md", summary)
    ctx.add_manifest("report/generation_summary.md")
    ctx.log("[ReportAgent] 完成")
