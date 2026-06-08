from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REFERENCE_PAGE_COMPONENT = "UserListPage"


class ValidationError(Exception):
    pass


def coerce_design_spec(data: Any) -> dict:
    """将 LLM 返回的 design_spec 规范为 dict（有时是 list 或嵌套结构）。"""
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and (
                "page_component" in item or "components" in item or "state" in item
            ):
                return item
        if len(data) == 1 and isinstance(data[0], dict):
            return data[0]
        raise ValidationError(
            "design_spec JSON 为数组但无法识别主对象，请重新执行 design 或检查模型输出。"
        )
    raise ValidationError(
        f"design_spec 类型无效: {type(data).__name__}，期望 JSON 对象。"
    )


def normalize_page_component(design_spec: dict | None) -> str:
    """page_component 应为组件名字符串；LLM 有时返回整段对象。"""
    if not design_spec:
        return "AppPage"
    pc = design_spec.get("page_component", "AppPage")
    if isinstance(pc, str):
        return pc.strip() or "AppPage"
    if isinstance(pc, dict):
        for key in ("name", "component", "page"):
            val = pc.get(key)
            if val:
                return str(val).strip()
    return "AppPage"


def apply_page_component_name(design_spec: dict) -> str:
    name = normalize_page_component(design_spec)
    design_spec["page_component"] = name
    return name


def validate_input_file(path: Path) -> None:
    if not path.exists():
        raise ValidationError(f"需求文件不存在: {path}")
    if path.suffix.lower() != ".md":
        raise ValidationError("需求文件必须是 Markdown (.md) 格式")


def validate_design_artifacts(output_dir: Path) -> None:
    required = [
        "analysis/requirement_analysis.md",
        "analysis/interaction_analysis.md",
        "design/component_design.md",
        "design/state_design.md",
        "design/api_contract.md",
        "design/class_diagram.mmd",
        "design/state_machine.mmd",
        "design/design_spec.json",
    ]
    missing = [p for p in required if not (output_dir / p).exists()]
    if missing:
        raise ValidationError(
            "缺少设计产物，请先执行「生成设计」或「完整生成」。缺失: "
            + ", ".join(missing)
        )


def main_page_rel_path(design_spec: dict | None) -> str:
    name = normalize_page_component(design_spec)
    return f"src/pages/{name}.jsx"


def validate_code_artifacts(output_dir: Path) -> None:
    if not (output_dir / "src").exists():
        raise ValidationError("缺少 src/ 目录，请先执行「生成代码」或「完整生成」。")
    if not (output_dir / "package.json").exists():
        raise ValidationError("缺少 package.json，请先执行「生成代码」或「完整生成」。")
    validate_main_page_artifact(output_dir)


def tests_dir_has_files(output_dir: Path) -> bool:
    tests_dir = output_dir / "tests"
    if not tests_dir.exists():
        return False
    files = list(tests_dir.glob("*.test.jsx")) + list(tests_dir.glob("*.test.js"))
    files += list(tests_dir.glob("*.spec.jsx")) + list(tests_dir.glob("*.spec.js"))
    return len(files) > 0


def validate_test_files_artifact(output_dir: Path) -> None:
    if not tests_dir_has_files(output_dir):
        raise ValidationError(
            "缺少 tests/*.test.jsx 或 tests/*.test.js。"
            "请在 code 阶段生成项目专属测试。"
        )


def project_uses_rest_api(ctx) -> bool:
    """根据需求与设计判断是否使用 REST API（决定 setupTests 与 MSW）。"""
    req = ctx.requirement_text
    req_lower = req.lower()
    api_contract = ""
    spec_path = ctx.output_path / "design" / "api_contract.md"
    if spec_path.exists():
        api_contract = spec_path.read_text(encoding="utf-8").lower()

    if "localstorage" in req_lower and (
        "不调用" in req or "无 api" in req_lower or "不需要 msw" in req_lower
    ):
        return False
    if "/api/" in api_contract:
        return True
    return "/api/" in req_lower


def validate_main_page_artifact(output_dir: Path) -> None:
    spec_file = output_dir / "design" / "design_spec.json"
    design_spec: dict = {}
    if spec_file.exists():
        design_spec = json.loads(spec_file.read_text(encoding="utf-8"))
    rel = main_page_rel_path(design_spec)
    if not (output_dir / rel).exists():
        page = normalize_page_component(design_spec)
        raise ValidationError(
            f"主页面文件不存在: {rel}（design_spec.page_component={page}）。"
            "App.jsx 已引用该文件，请重新执行「生成代码」。"
        )
    app_jsx = output_dir / "src" / "App.jsx"
    if app_jsx.exists():
        text = app_jsx.read_text(encoding="utf-8")
        page = normalize_page_component(design_spec)
        if page not in text:
            raise ValidationError(
                f"App.jsx 未引用主页面 {page}，与 design_spec 不一致，请重新执行「生成代码」。"
            )


def derive_output_dir(
    input_path: Path,
    explicit: str | None,
    *,
    use_case_subfolder: bool = False,
) -> Path:
    """产物写入当前工作目录；可选 <用例名> 子目录。"""
    if explicit:
        return Path(explicit).resolve()
    case_name = input_path.stem
    cwd = Path.cwd().resolve()
    if use_case_subfolder:
        return (cwd / case_name).resolve()
    return cwd
