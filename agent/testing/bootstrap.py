from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from agent import file_writer as fw
from agent.context import AgentContext
from agent.validators import apply_page_component_name, project_uses_rest_api


def _project_root(ctx: AgentContext) -> Path:
    return Path(ctx.project_root or Path(__file__).resolve().parent.parent.parent)


def ensure_vitest_infrastructure(ctx: AgentContext) -> None:
    """写入通用 Vitest 配置与 setupTests（不调用 LLM）。"""
    root = _project_root(ctx)
    templates_dir = root / "templates"
    testing_dir = root / "agent" / "testing"
    env = Environment(loader=FileSystemLoader(templates_dir), keep_trailing_newline=True)

    if not ctx.design_spec:
        ctx.design_spec = fw.read_json(ctx.output_path, "design/design_spec.json") or {}
    apply_page_component_name(ctx.design_spec)
    page = ctx.design_spec.get("page_component", "AppPage")
    ctx_vars = {"page_component": page, "project_name": ctx.output_path.name}

    for tpl, out in [
        ("package.json.j2", "package.json"),
        ("vite.config.js.j2", "vite.config.js"),
    ]:
        target = ctx.output_path / out
        if not target.exists():
            fw.write_text(ctx.output_path, out, env.get_template(tpl).render(**ctx_vars))
            ctx.add_manifest(out)

    use_api = project_uses_rest_api(ctx)
    setup_name = "setupTests.api.js" if use_api else "setupTests.local.js"
    setup_src = testing_dir / setup_name
    if setup_src.exists():
        fw.write_text(
            ctx.output_path,
            "src/setupTests.js",
            setup_src.read_text(encoding="utf-8"),
        )
        ctx.add_manifest("src/setupTests.js")

    if use_api:
        mocks_server = ctx.output_path / "src/mocks/server.js"
        if not mocks_server.exists():
            tpl = env.get_template("src/mocks/server.js.j2")
            fw.write_text(ctx.output_path, "src/mocks/server.js", tpl.render(**ctx_vars))
            ctx.add_manifest("src/mocks/server.js")
        handlers = ctx.output_path / "src/mocks/handlers.js"
        if not handlers.exists():
            ref = root / "templates" / "reference" / "src" / "mocks" / "handlers.js"
            if ref.exists():
                fw.write_text(
                    ctx.output_path,
                    "src/mocks/handlers.js",
                    ref.read_text(encoding="utf-8"),
                )
                ctx.add_manifest("src/mocks/handlers.js")
