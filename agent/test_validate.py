from __future__ import annotations

import re
from pathlib import Path

from agent.stages.blocks import (
    _is_llm_prose_line,
    _iter_code_blocks,
    _sanitize_code_body,
    _trim_trailing_llm_prose,
)

_DESCRIBE_RE = re.compile(r"\bdescribe\s*\(")
_IT_RE = re.compile(r"\bit\s*\(")
_IMPORT_RE = re.compile(r"^\s*import\s+", re.MULTILINE)
_FENCE_LINE_RE = re.compile(r"^\s*```")


def list_test_files(output_dir: Path) -> list[Path]:
    tests_dir = output_dir / "tests"
    if not tests_dir.exists():
        return []
    patterns = ("*.test.jsx", "*.test.js", "*.spec.jsx", "*.spec.js")
    files: list[Path] = []
    for pat in patterns:
        files.extend(tests_dir.glob(pat))
    return sorted(set(files))


def _strip_fence_lines(text: str) -> str:
    lines = [ln for ln in text.splitlines() if not _FENCE_LINE_RE.match(ln)]
    return "\n".join(lines).strip()


def _strip_embedded_prose(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        if _is_llm_prose_line(line):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _extract_balanced_describe_block(text: str) -> str | None:
    """提取第一个完整 describe(..., () => { ... }); 块，避免贪婪匹配到全文末尾。"""
    m = re.search(r"\bdescribe\s*\(", text)
    if not m:
        return None
    start = m.start()
    depth = 0
    i = m.end() - 1
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                rest = text[i + 1 :]
                am = re.match(r"\s*,\s*(?:async\s*)?\(\)\s*=>\s*\{", rest)
                if not am:
                    return None
                brace_start = i + 1 + am.end() - 1
                brace_depth = 0
                for j in range(brace_start, len(text)):
                    cj = text[j]
                    if cj == "{":
                        brace_depth += 1
                    elif cj == "}":
                        brace_depth -= 1
                        if brace_depth == 0:
                            return text[start : j + 1].strip()
                return None
        i += 1
    return None


def _suffix_after_block(response: str, body: str, *, limit: int = 6000) -> str:
    """取代码块在回复中紧随其后的片段（用于拼接 describe，不扫描全文）。"""
    needle = body.strip()[:120]
    if not needle:
        return ""
    idx = response.find(needle)
    if idx < 0:
        return ""
    tail = response[idx + len(body.strip()) :]
    fence = tail.find("```")
    if fence >= 0:
        tail = tail[:fence]
    return tail[:limit]


def _normalize_test_source(text: str, *, rel_path: str) -> str:
    body = _strip_fence_lines(text)
    body = _strip_embedded_prose(body)
    body = _sanitize_code_body(body, "jsx", rel_path)
    body = _trim_trailing_llm_prose(body)
    return body.strip()


def _attach_describe_block(response: str, prefix: str, *, block_body: str = "") -> str:
    """把紧随代码块后的 describe(...) 拼到仅有 import 的前缀后。"""
    if _DESCRIBE_RE.search(prefix):
        return prefix.strip()
    search_in = _suffix_after_block(response, block_body or prefix) if block_body else response[:8000]
    tail = _extract_balanced_describe_block(search_in)
    if not tail or not _IT_RE.search(tail):
        return prefix.strip()
    head = prefix.strip()
    return f"{head}\n\n{tail}".strip() if head else tail.strip()


def _score_test_body(body: str, *, target_rel: str, rel_hint: str) -> int:
    if not body.strip():
        return -1
    if "```" in body:
        return -1
    score = 0
    if re.search(r"from\s+['\"]vitest['\"]", body):
        score += 20
    elif _IMPORT_RE.search(body):
        score += 8
    if _DESCRIBE_RE.search(body):
        score += 10
    score += len(_IT_RE.findall(body))
    if rel_hint == target_rel.replace("\\", "/"):
        score += 5
    imp = _IMPORT_RE.search(body)
    desc = _DESCRIBE_RE.search(body)
    if imp and desc and imp.start() < desc.start():
        score += 5
    elif desc and (not imp or desc.start() < imp.start()):
        score -= 15
    for line in body.splitlines():
        if _is_llm_prose_line(line):
            score -= 50
            break
    return score


def validate_test_file_text(text: str, *, min_it: int = 4) -> str | None:
    t = text.strip()
    if not t:
        return "测试文件为空"
    if "```" in t:
        return "含非法 markdown 围栏"
    for line in t.splitlines():
        if _is_llm_prose_line(line):
            return "含 LLM 说明文字，非可执行测试代码"
    if not _IMPORT_RE.search(t):
        return "缺少 import 语句"
    if not _DESCRIBE_RE.search(t):
        return "须包含 describe(...)"
    imp = _IMPORT_RE.search(t)
    desc = _DESCRIBE_RE.search(t)
    if imp and desc and desc.start() < imp.start():
        return "import 须在 describe 之前"
    it_count = len(_IT_RE.findall(t))
    if it_count < 1:
        return "须包含至少 1 个 it(...)"
    if it_count < min_it:
        return f"it() 过少（{it_count} 个），至少需要 {min_it} 个"
    return None


def validate_test_outputs(output_dir: Path, *, min_it: int = 4) -> str | None:
    files = list_test_files(output_dir)
    if not files:
        return "缺少 tests/*.test.jsx 或 tests/*.test.js"
    errors: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        err = validate_test_file_text(text, min_it=min_it)
        if err:
            errors.append(f"{path.name}: {err}")
    return "; ".join(errors) if errors else None


def extract_test_body_from_response(
    response: str,
    *,
    target_rel: str,
) -> str | None:
    """从 LLM 完整回复中提取可运行的测试源码（含 import + describe/it）。"""
    target_rel = target_rel.replace("\\", "/")
    best = ""
    best_score = -1

    for _lang, path_hint, body in _iter_code_blocks(response):
        rel = (path_hint or "").replace("\\", "/").lstrip("/")
        if rel and not rel.startswith("tests/"):
            continue
        merged = _attach_describe_block(response, body, block_body=body)
        merged = _normalize_test_source(merged, rel_path=rel or target_rel)
        score = _score_test_body(merged, target_rel=target_rel, rel_hint=rel)
        if score > best_score:
            best_score = score
            best = merged

    if best_score >= 25:
        return best

    tail = _extract_balanced_describe_block(response)
    if tail:
        imports = ""
        for _lang, _path, body in _iter_code_blocks(response):
            if "import " in body and "vitest" in body:
                imports = _normalize_test_source(body.split("describe")[0], rel_path=target_rel)
                break
        if imports:
            merged = _normalize_test_source(f"{imports}\n\n{tail}", rel_path=target_rel)
            score = _score_test_body(merged, target_rel=target_rel, rel_hint=target_rel)
            if score > best_score:
                best_score = score
                best = merged

    if best_score >= 25 and validate_test_file_text(best, min_it=1) is None:
        return best
    return None
