from __future__ import annotations

import re
from pathlib import Path

from agent import file_writer as fw
from agent.context import AgentContext
from agent.validators import normalize_page_component

_PATH_COMMENT_RE = re.compile(r"^\s*//\s*path:\s*(.+?)\s*$", re.MULTILINE)
_FENCE_CLOSED_RE = re.compile(r"```(\w+)?\s*\n(.*?)```", re.DOTALL)


def _strip_path_from_body(body: str) -> tuple[str, str | None]:
    """从正文首行解析 // path:，返回 (正文, 路径)。"""
    lines = body.splitlines()
    if not lines:
        return body, None
    m = re.match(r"^\s*//\s*path:\s*(.+?)\s*$", lines[0])
    if m:
        return "\n".join(lines[1:]).strip(), m.group(1).strip()
    m2 = _PATH_COMMENT_RE.search(body[:300])
    if m2:
        path = m2.group(1).strip()
        body = _PATH_COMMENT_RE.sub("", body, count=1).strip()
        return body, path
    return body.strip(), None


def _looks_like_react_component(body: str, page: str) -> bool:
    if not body.strip():
        return False
    patterns = [
        rf"export\s+default\s+function\s+{re.escape(page)}\b",
        r"export\s+default\s+function\s+\w+",
        rf"function\s+{re.escape(page)}\b",
        rf"const\s+{re.escape(page)}\s*=",
        r"export\s+default\s+\w+",
        r"from\s+['\"]react['\"]",
    ]
    return any(re.search(p, body) for p in patterns)


def _infer_component_path(ctx: AgentContext, body: str, lang: str) -> str | None:
    page = normalize_page_component(ctx.design_spec)
    if lang == "css" or (body.strip().startswith((".", "#", "@", "*")) and "{" in body):
        m = re.search(r"([\w-]+\.css)", body[:80])
        if m:
            return f"src/{m.group(1)}"
        return "src/notes.css"
    if "handlers" in body[:200].lower() or ("http." in body and "msw" in body.lower()):
        return "src/mocks/handlers.js"
    if "test" in lang or "describe(" in body[:500]:
        return None
    m_comp = re.search(r"export\s+default\s+function\s+(\w+)", body)
    if m_comp:
        name = m_comp.group(1)
        if name != page:
            return f"src/components/{name}.jsx"
    if _looks_like_react_component(body, page):
        return f"src/pages/{page}.jsx"
    if "components/" in body[:400] or "/components/" in body[:400]:
        m = re.search(r"components/(\w+)\.jsx", body)
        if m:
            return f"src/components/{m.group(1)}.jsx"
    return None


def _parse_fence_chunk(lang: str, chunk: str) -> tuple[str, str, str]:
    path_hint = ""
    body = chunk
    pm = re.match(r"^\s*//\s*path:\s*(.+?)\s*\n", chunk)
    if pm:
        path_hint = pm.group(1).strip()
        body = chunk[pm.end() :].strip()
    else:
        body, extracted = _strip_path_from_body(chunk)
        if extracted:
            path_hint = extracted
    return lang, path_hint, body


def _iter_code_blocks(response: str) -> list[tuple[str, str, str]]:
    """返回 [(lang, path_hint, body), ...]；支持未闭合的截断代码块。"""
    blocks: list[tuple[str, str, str]] = []
    for m in _FENCE_CLOSED_RE.finditer(response):
        lang = (m.group(1) or "").lower()
        blocks.append(_parse_fence_chunk(lang, m.group(2)))

    if blocks:
        return blocks

    for marker in ("```jsx\n", "```javascript\n", "```js\n", "```\n"):
        idx = response.rfind(marker)
        if idx >= 0:
            lang = marker.strip("`").strip().lower() or ""
            chunk = response[idx + len(marker) :].strip()
            if chunk and ("import " in chunk or "export " in chunk or "function " in chunk):
                blocks.append(_parse_fence_chunk(lang, chunk))
            break
    return blocks


_PLACEHOLDER_BODY_RE = re.compile(
    r"\{\s*\.\.\.\s*\}|//\s*(state|effects|handlers)\.\.\.|>\s*\.\.\.\s*<|>\s*\.\.\.\s*/>"
)


def _has_placeholder_stubs(body: str) -> bool:
    return bool(_PLACEHOLDER_BODY_RE.search(body))


def write_step_fenced_blocks(
    ctx: AgentContext,
    response: str,
    *,
    path_prefixes: list[str] | None = None,
    path_suffixes: list[str] | None = None,
    pick_best_path: str | None = None,
    tests_only: bool = False,
) -> int:
    """按步骤过滤代码块；同路径多块时取最长且无占位符的正文。"""
    candidates: dict[str, str] = {}
    page = normalize_page_component(ctx.design_spec)

    for lang, path_hint, body in _iter_code_blocks(response):
        if not body.strip():
            continue

        rel_path = path_hint
        if not rel_path:
            if tests_only:
                if "describe(" in body or "it(" in body or "test" in lang:
                    rel_path = f"tests/{page}.test.jsx"
                else:
                    continue
            else:
                rel_path = _infer_component_path(ctx, body, lang) or ""
                if not rel_path:
                    continue

        rel_path = rel_path.replace("\\", "/").lstrip("/")
        if path_prefixes and not any(rel_path.startswith(p) for p in path_prefixes):
            continue
        if path_suffixes and not any(rel_path.endswith(s) for s in path_suffixes):
            continue
        if pick_best_path and rel_path != pick_best_path:
            continue

        prev = candidates.get(rel_path)
        if prev is None:
            candidates[rel_path] = body
            continue
        prev_bad = _has_placeholder_stubs(prev)
        body_bad = _has_placeholder_stubs(body)
        if prev_bad and not body_bad:
            candidates[rel_path] = body
        elif not prev_bad and body_bad:
            continue
        elif len(body) > len(prev):
            candidates[rel_path] = body

    written = 0
    for rel_path, body in candidates.items():
        fw.write_text(ctx.output_path, rel_path, body)
        ctx.add_manifest(rel_path)
        written += 1
    return written


def write_fenced_blocks(
    ctx: AgentContext,
    response: str,
    *,
    tests_only: bool = False,
) -> int:
    """解析 LLM 回复中的代码块并写入项目，返回写入文件数。"""
    written = 0
    page = normalize_page_component(ctx.design_spec)

    for lang, path_hint, body in _iter_code_blocks(response):
        if not body.strip():
            continue

        rel_path = path_hint
        if not rel_path:
            if tests_only:
                if "describe(" in body or "it(" in body or "test" in lang:
                    rel_path = f"tests/{page}.test.jsx"
                else:
                    continue
            else:
                rel_path = _infer_component_path(ctx, body, lang) or ""
                if not rel_path:
                    continue

        rel_path = rel_path.replace("\\", "/").lstrip("/")
        if tests_only and "test" not in rel_path.lower():
            if "describe(" in body or "it(" in body:
                rel_path = f"tests/{Path(rel_path).name if rel_path else page + '.test.jsx'}"
            else:
                continue
        if not rel_path.startswith("tests/") and tests_only:
            rel_path = f"tests/{Path(rel_path).name}"

        fw.write_text(ctx.output_path, rel_path, body)
        ctx.add_manifest(rel_path)
        written += 1
    return written
