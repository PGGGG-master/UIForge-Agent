from __future__ import annotations

import re
from pathlib import Path

from agent import file_writer as fw
from agent.code_integrity import find_missing_local_imports
from agent.context import AgentContext
from agent.validators import ValidationError, normalize_page_component, project_uses_rest_api

_IMPORT_RE = re.compile(
    r"""import\s+(?:[\w*{}\s,]+\s+from\s+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_COMPONENT_IMPORT_RE = re.compile(
    r"""from\s+['"](\.\./components/|\./components/|@/components/)([\w-]+)['"]""",
    re.MULTILINE,
)


def validate_main_page_file(path: Path, page_name: str) -> str | None:
    if not path.exists():
        return f"主页面不存在: {path.name}"
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        return "主页面文件为空"
    patterns = [
        rf"export\s+default\s+function\s+{re.escape(page_name)}\b",
        rf"export\s+default\s+{re.escape(page_name)}\b",
        r"export\s+default\s+function\s+\w+",
    ]
    if not any(re.search(p, text) for p in patterns):
        return f"主页面缺少 export default（期望组件名 {page_name}）"
    if re.search(r"\{\s*\.\.\.\s*\}", text):
        return "主页面含 `{ ... }` 占位符，非完整可编译代码"
    return None


def collect_css_imports(output_dir: Path) -> list[str]:
    rels: list[str] = []
    src = output_dir / "src"
    if not src.exists():
        return rels
    seen: set[str] = set()
    for file_path in sorted(src.rglob("*")):
        if file_path.suffix not in (".jsx", ".js"):
            continue
        from_rel = file_path.relative_to(output_dir).as_posix()
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        for spec in _IMPORT_RE.findall(text):
            if not spec.endswith(".css"):
                continue
            if spec.startswith("."):
                target = (file_path.parent / spec).resolve()
                try:
                    rel = target.relative_to(output_dir.resolve()).as_posix()
                except ValueError:
                    continue
            else:
                rel = spec.lstrip("/")
            if rel not in seen:
                seen.add(rel)
                rels.append(rel)
    return rels


def validate_css_imports(output_dir: Path) -> str | None:
    for rel in collect_css_imports(output_dir):
        if not (output_dir / rel).exists():
            return f"缺少 CSS 文件: {rel}"
    return None


def validate_api_artifacts(output_dir: Path) -> str | None:
    handlers = output_dir / "src" / "mocks" / "handlers.js"
    if not handlers.exists():
        return "缺少 src/mocks/handlers.js"
    text = handlers.read_text(encoding="utf-8", errors="ignore")
    if "http." not in text and "HttpResponse" not in text:
        return "handlers.js 未包含 MSW http 处理器"
    api_dir = output_dir / "src" / "api"
    if not api_dir.exists() or not list(api_dir.glob("*.js")):
        return "缺少 src/api/*.js"
    return None


def validate_code_outputs(ctx: AgentContext) -> list[str]:
    """收尾校验，返回软警告列表；硬错误抛 ValidationError。"""
    warnings: list[str] = []
    output_dir = ctx.output_path
    page = normalize_page_component(ctx.design_spec)
    main_rel = f"src/pages/{page}.jsx"
    main_path = output_dir / main_rel

    err = validate_main_page_file(main_path, page)
    if err:
        raise ValidationError(err)

    main_text = main_path.read_text(encoding="utf-8", errors="ignore")
    for m in _COMPONENT_IMPORT_RE.finditer(main_text):
        comp_name = m.group(2)
        comp_path = output_dir / "src" / "components" / f"{comp_name}.jsx"
        if not comp_path.exists():
            warnings.append(
                f"主页面 import 子组件 {comp_name}，但缺少 src/components/{comp_name}.jsx"
            )

    if project_uses_rest_api(ctx):
        api_err = validate_api_artifacts(output_dir)
        if api_err:
            raise ValidationError(api_err)

    missing = find_missing_local_imports(output_dir)
    css_missing = [m for m in missing if m["expected"].endswith(".css")]
    for m in css_missing[:5]:
        warnings.append(f"仍缺 CSS: {m['expected']}（integrity 阶段可能补全）")

    report_lines = ["# UIForge 代码校验报告", ""]
    if warnings:
        report_lines.append("## 警告")
        for w in warnings:
            report_lines.append(f"- {w}")
    else:
        report_lines.append("全部校验通过，无警告。")
    fw.write_text(output_dir, "report/code_validation.md", "\n".join(report_lines) + "\n")
    return warnings
