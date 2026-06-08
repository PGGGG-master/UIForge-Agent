from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_text(base: Path, relative: str, content: str) -> Path:
    target = base / relative
    ensure_parent(target)
    target.write_text(content, encoding="utf-8")
    return target


def write_json(base: Path, relative: str, data: Any) -> Path:
    target = base / relative
    ensure_parent(target)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def read_text(base: Path, relative: str) -> str | None:
    target = base / relative
    if not target.exists():
        return None
    return target.read_text(encoding="utf-8")


def read_json(base: Path, relative: str) -> dict | None:
    text = read_text(base, relative)
    if not text:
        return None
    return json.loads(text)


def extract_markdown_section(text: str, heading: str) -> str:
    pattern = rf"^#+\s*{re.escape(heading)}\s*$"
    lines = text.splitlines()
    start = None
    level = 0
    for i, line in enumerate(lines):
        if re.match(pattern, line.strip(), re.IGNORECASE):
            start = i + 1
            level = len(line.strip()) - len(line.strip().lstrip("#"))
            break
    if start is None:
        return text.strip()
    collected: list[str] = []
    for line in lines[start:]:
        if line.startswith("#") and (len(line.strip()) - len(line.strip().lstrip("#"))) <= level:
            break
        collected.append(line)
    return "\n".join(collected).strip()


def extract_fenced_blocks(text: str, lang: str | None = None) -> list[tuple[str, str]]:
    pattern = r"```(\w+)?\n(.*?)```"
    blocks: list[tuple[str, str]] = []
    for match in re.finditer(pattern, text, re.DOTALL):
        block_lang = (match.group(1) or "").lower()
        body = match.group(2).strip()
        if lang is None or block_lang == lang.lower():
            blocks.append((block_lang, body))
    return blocks


def extract_json_object(text: str) -> Any:
    fenced = extract_fenced_blocks(text, "json")
    candidates = [body for _, body in fenced]
    candidates.append(text.strip())
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(candidate[start : end + 1])
                except json.JSONDecodeError:
                    pass
            start_arr = candidate.find("[")
            end_arr = candidate.rfind("]")
            if start_arr >= 0 and end_arr > start_arr:
                try:
                    return json.loads(candidate[start_arr : end_arr + 1])
                except json.JSONDecodeError:
                    continue
    raise ValueError("无法从 LLM 响应中解析 JSON")
