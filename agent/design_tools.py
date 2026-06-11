from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from agent.validators import ValidationError

MERMAID_VALIDATOR_HINT = (
    "Mermaid 语法校验不可用。请在 UIForge-Agent 目录执行：\n"
    "  npm install\n"
    "并确保已安装 Node.js（node 在 PATH 中）。"
)


def _project_root(project_root: str | Path | None) -> Path:
    if project_root:
        return Path(project_root).resolve()
    return Path(__file__).resolve().parent.parent


def _resolve_node() -> str:
    node = shutil.which("node")
    if node:
        return node
    raise ValidationError(MERMAID_VALIDATOR_HINT)


def _validator_script(root: Path) -> Path:
    script = root / "scripts" / "validate-mermaid.mjs"
    if not script.exists():
        raise ValidationError(f"缺少 Mermaid 校验脚本: {script}")
    return script


def _run_mermaid_validator(node: str, script: Path, input_path: Path) -> str | None:
    try:
        result = subprocess.run(
            [node, str(script), str(input_path.resolve())],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(script.parent.parent),
        )
    except FileNotFoundError:
        return MERMAID_VALIDATOR_HINT
    except subprocess.TimeoutExpired:
        return "Mermaid 语法校验超时"
    if result.returncode != 0:
        return (result.stderr or result.stdout or "Mermaid 语法校验失败").strip()
    return None


def ensure_mmdc(project_root: str | Path | None) -> list[str]:
    """
    确认 Mermaid 语法校验可用（基于 node + mermaid.parse，无需 Chrome/mmdc）。
    保留函数名以兼容 design_agent 调用。
    """
    root = _project_root(project_root)
    node = _resolve_node()
    script = _validator_script(root)
    sample = "classDiagram\n  class A {\n    +x: int\n  }\n"
    with tempfile.TemporaryDirectory() as tmp:
        inp = Path(tmp) / "probe.mmd"
        inp.write_text(sample, encoding="utf-8")
        err = _run_mermaid_validator(node, script, inp)
        if err:
            raise ValidationError(f"Mermaid 校验不可用: {err}\n{MERMAID_VALIDATOR_HINT}")
    return [node, str(script)]


def validate_mermaid_file(
    mmd_path: Path,
    *,
    project_root: str | Path | None,
    mmdc_cmd: list[str] | None = None,
) -> str | None:
    """校验 .mmd 语法；成功返回 None，失败返回错误信息。"""
    root = _project_root(project_root)
    if mmdc_cmd and len(mmdc_cmd) >= 2:
        node, script = mmdc_cmd[0], Path(mmdc_cmd[1])
    else:
        node = _resolve_node()
        script = _validator_script(root)
    return _run_mermaid_validator(node, script, mmd_path.resolve())


def load_design_spec_schema(project_root: str | Path | None = None) -> dict[str, Any]:
    root = _project_root(project_root)
    path = root / "schemas" / "design_spec.schema.json"
    if not path.exists():
        raise ValidationError(f"缺少 JSON Schema: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_design_spec_schema(
    data: dict[str, Any],
    *,
    project_root: str | Path | None = None,
) -> str | None:
    try:
        import jsonschema
    except ImportError as exc:
        raise ValidationError(
            "缺少 jsonschema 包，请执行: pip install jsonschema"
        ) from exc
    schema = load_design_spec_schema(project_root)
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        return str(exc)
    return None


_CLASS_DEF_RE = re.compile(r"^\s*class\s+(\w+)", re.MULTILINE)
_CLASS_REL_RE = re.compile(
    r"^\s*(\w+)\s+(?:<\|--|<\|\.\.|\|--|\|\?>|-->|\.->|\.\.>|\*--|o--|--)\s*(\w+)\s*(?::.*)?$",
    re.MULTILINE,
)
_STATE_TRANSITION_RE = re.compile(
    r"^\s*(\[\*\]|[A-Za-z_]\w*)\s+-->\s*(\[\*\]|[A-Za-z_]\w*)\s*(?::.*)?$",
    re.MULTILINE,
)
_NAMED_STATE_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s+-->", re.MULTILINE)
_COMPOSITE_STATE_RE = re.compile(r"^\s*state\s+(\w+)\s*\{", re.MULTILINE)
# 禁止直接拿组件/面板名作状态（语义化命名如 CreateModalOpen、DetailOpen 允许）
_FORBIDDEN_STATE_NAMES = frozenset(
    {
        "modal",
        "dashboard",
        "detailpanel",
        "panel",
        "toolbar",
        "header",
        "column",
        "card",
        "page",
        "view",
        "formmodal",
        "boardheader",
        "filtertoolbar",
        "kanbancolumn",
        "taskcard",
        "taskform",
        "sidebar",
        "dialog",
        "popup",
    }
)
_EVENT_LIKE_STATE_RE = re.compile(
    r"(?:loaded|success|failure|error|click|submit|mounted?)$",
    re.IGNORECASE,
)


def _collect_state_machine_state_names(text: str) -> set[str]:
    names: set[str] = set()
    for src, dst in _STATE_TRANSITION_RE.findall(text):
        for token in (src, dst):
            if token != "[*]":
                names.add(token)
    names.update(_COMPOSITE_STATE_RE.findall(text))
    return names


def validate_class_diagram_text(text: str) -> str | None:
    """类型 + Mermaid 类图最小结构（类定义与关系）。"""
    t = text.strip()
    if not t:
        return "类图为空"
    if not t.startswith("classDiagram"):
        return "类图必须以 classDiagram 开头"
    if "stateDiagram" in t.splitlines()[0]:
        return "类图不能使用 stateDiagram 头"

    classes = _CLASS_DEF_RE.findall(t)
    if len(classes) < 1:
        return "类图须至少包含 1 个 class 定义（如 class TodoPage { ... }）"
    if len(set(classes)) < 1:
        return "类图 class 名称无效"

    relations = _CLASS_REL_RE.findall(t)
    if len(relations) < 1:
        return "类图须至少包含 1 条类关系（如 TodoPage --> TodoList 或 A <|-- B）"

    related = set()
    for a, b in relations:
        related.add(a)
        related.add(b)
    if not related.intersection(set(classes)):
        return "关系线须连接已定义的 class（关系两端应出现在 class 定义或关系引用中）"

    return None


def validate_state_machine_text(text: str) -> str | None:
    """类型 + Mermaid 状态机最小结构（初始态与转移）。"""
    t = text.strip()
    if not t:
        return "状态机图为空"
    if not t.startswith("stateDiagram"):
        return "状态机图必须以 stateDiagram 或 stateDiagram-v2 开头"
    if t.startswith("classDiagram"):
        return "状态机图不能使用 classDiagram 头"

    if "[*]" not in t:
        return "状态机图须包含初始/终止伪态 [*]（如 [*] --> Idle）"

    transitions = _STATE_TRANSITION_RE.findall(t)
    if len(transitions) < 2:
        return "状态机图须至少包含 2 条状态转移（如 A --> B : event）"

    named_states = {m.group(1) for m in _NAMED_STATE_RE.finditer(t)}
    if len(named_states) < 1:
        return "状态机图须至少包含 1 个具名状态（除 [*] 外的状态名）"

    has_initial = any(src == "[*]" for src, _ in transitions)
    if not has_initial:
        return "状态机图须从 [*] 出发（如 [*] --> Idle : mount）"

    if re.search(r"\[\*\][A-Za-z_]", t):
        return "禁止将 [*] 与状态名粘连（如 [*]BoardReady）"

    state_names = _collect_state_machine_state_names(t)
    ui_like = [n for n in sorted(state_names) if n.lower() in _FORBIDDEN_STATE_NAMES]
    if ui_like:
        return (
            f"状态名不应使用 UI 组件/面板名（如 {', '.join(ui_like[:4])}），"
            "请改为语义状态（如 DashboardViewing、CreateModalOpen、DetailOpen）"
        )

    event_like = [n for n in sorted(state_names) if _EVENT_LIKE_STATE_RE.search(n)]
    if event_like:
        return f"状态名不应像事件/副作用（如 {', '.join(event_like[:3])}），请写在箭头标签上"

    if len(state_names) > 12:
        return f"状态过多（{len(state_names)} 个），请合并为约 6～10 个核心抽象状态"

    composites = _COMPOSITE_STATE_RE.findall(t)
    if len(composites) > 1:
        return "复合状态过多，请优先使用扁平 stateDiagram"

    if composites and re.search(r"state\s+\w+\s*\{[^}]*\[\*\]\s*-->", t, re.DOTALL):
        return "复合状态内不要用 [*] 指向 UI 子面板，请改为扁平抽象状态"

    if re.search(r"\[\*\]\s*-->\s*\[\*\]", t):
        return "禁止 [*] 直接转移到 [*]"

    return None


def validate_markdown_design(text: str, *, min_len: int = 30) -> str | None:
    t = text.strip()
    if not t:
        return "Markdown 内容为空"
    if len(t) < min_len:
        return f"Markdown 内容过短（<{min_len} 字符）"
    return None
