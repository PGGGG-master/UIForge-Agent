from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent import file_writer as fw
from agent.design_tools import (
    ensure_mmdc,
    validate_class_diagram_text,
    validate_design_spec_schema,
    validate_markdown_design,
    validate_mermaid_file,
    validate_state_machine_text,
)
from agent.validators import ValidationError, normalize_page_component

DESIGN_FILES = [
    "design/component_design.md",
    "design/state_design.md",
    "design/api_contract.md",
    "design/class_diagram.mmd",
    "design/state_machine.mmd",
    "design/design_spec.json",
]


def _requirement_expects_no_api(requirement_text: str) -> bool:
    req_lower = requirement_text.lower()
    return "localstorage" in req_lower and (
        "不调用" in requirement_text
        or "无 api" in req_lower
        or "不需要 msw" in req_lower
    )


def validate_design_outputs(
    output_dir: Path,
    requirement_text: str,
    *,
    project_root: str | Path | None = None,
) -> list[str]:
    """
    设计阶段收尾校验。硬错误抛 ValidationError；返回软警告列表。
    同时写入 report/design_validation.md（若有警告）。
    """
    warnings: list[str] = []
    mmdc_cmd = ensure_mmdc(project_root)

    for rel in DESIGN_FILES:
        path = output_dir / rel
        if not path.exists() or not path.read_text(encoding="utf-8").strip():
            raise ValidationError(f"设计产物缺失或为空: {rel}")

    spec_path = output_dir / "design" / "design_spec.json"
    design_spec: dict[str, Any] = json.loads(spec_path.read_text(encoding="utf-8"))
    schema_err = validate_design_spec_schema(design_spec, project_root=project_root)
    if schema_err:
        raise ValidationError(f"design_spec.json 不符合 schema: {schema_err}")

    for mmd_rel, struct_fn in (
        ("design/class_diagram.mmd", validate_class_diagram_text),
        ("design/state_machine.mmd", validate_state_machine_text),
    ):
        mmd_text = (output_dir / mmd_rel).read_text(encoding="utf-8")
        struct_err = struct_fn(mmd_text)
        if struct_err:
            raise ValidationError(f"{mmd_rel} 结构不符合标准: {struct_err}")
        mmd_err = validate_mermaid_file(
            output_dir / mmd_rel,
            project_root=project_root,
            mmdc_cmd=mmdc_cmd,
        )
        if mmd_err:
            raise ValidationError(f"{mmd_rel} Mermaid 语法错误: {mmd_err}")

    page = normalize_page_component(design_spec)
    component_md = (output_dir / "design" / "component_design.md").read_text(encoding="utf-8")
    class_mmd = (output_dir / "design" / "class_diagram.mmd").read_text(encoding="utf-8")
    if page not in component_md and page not in class_mmd:
        warnings.append(f"page_component「{page}」未出现在 component_design.md 或 class_diagram.mmd")

    api_contract = (output_dir / "design" / "api_contract.md").read_text(encoding="utf-8")
    apis = design_spec.get("apis") or []
    if _requirement_expects_no_api(requirement_text):
        if "/api/" in api_contract.lower() or apis:
            warnings.append("需求为 localStorage 无 API，但 api_contract 或 design_spec.apis 含 API 定义")
    elif "/api/" in api_contract.lower() and not apis:
        warnings.append("api_contract 含 /api/ 但 design_spec.apis 为空")

    state_md = (output_dir / "design" / "state_design.md").read_text(encoding="utf-8")
    fields = (design_spec.get("state") or {}).get("fields") or []
    for field in fields:
        name = field.get("name") if isinstance(field, dict) else None
        if name and str(name) not in state_md:
            warnings.append(f"design_spec.state.fields 中的「{name}」未在 state_design.md 中出现")

    report_lines = ["# UIForge 设计校验报告", ""]
    if warnings:
        report_lines.append("## 警告")
        for w in warnings:
            report_lines.append(f"- {w}")
    else:
        report_lines.append("全部校验通过，无警告。")
    fw.write_text(output_dir, "report/design_validation.md", "\n".join(report_lines) + "\n")

    return warnings
