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


_PROSE_LINE_START_RE = re.compile(
    r"^\s*(?:我们|此外|需要|错误|显然|根据|用户|下面|开始|注意|修复|构建|请|不要|已经|可以|应该|文件|报错)",
)
_CJK_LEADING_RE = re.compile(r"^\s*[\u4e00-\u9fff]")
_CODE_LINE_RE = re.compile(
    r"^\s*(?:"
    r"import\s|export\s|const\s|let\s|var\s|function\s|return\s|if\s|else\s|for\s|while\s|"
    r"switch\s|case\s|default\s|throw\s|try\s|catch\s|className|style=\{|</?[\w!?]"
    r")|^\s*[{});]\s*$|^\s*//|^\s*/\*|^\s*\*|^\s*<[A-Za-z/]"
)


def _is_llm_prose_line(line: str) -> bool:
    """判断是否为混入源码的 LLM 说明行（非注释、非 JSX 字符串内文本）。"""
    s = line.strip()
    if not s:
        return False
    if _CODE_LINE_RE.match(line):
        return False
    if s.startswith(("/*", "//", "*")):
        return False
    if _PROSE_LINE_START_RE.match(s):
        return True
    if _CJK_LEADING_RE.match(s) and not re.search(r"[=<>();{}[\]]", s):
        return True
    return False


def _trim_trailing_llm_prose(body: str) -> str:
    """去掉文件末尾被误写入的思考/说明文字。"""
    lines = body.splitlines()
    end = len(lines)
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    while end > 0 and _is_llm_prose_line(lines[end - 1]):
        end -= 1
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    if end <= 0:
        return ""
    return "\n".join(lines[:end]).rstrip() + "\n"


def _sanitize_code_body(body: str, lang: str = "", rel_path: str = "") -> str:
    ext = Path(rel_path).suffix.lower() if rel_path else ""
    is_source = ext in (".jsx", ".js", ".css") or lang in ("jsx", "javascript", "js", "css")
    if not is_source and not re.search(r"\b(import|export)\s+", body):
        return body.strip()
    return _trim_trailing_llm_prose(body.strip())


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
    body = _sanitize_code_body(body, lang, path_hint)
    return lang, path_hint, body


def _strip_trailing_fence(text: str) -> str:
    t = text.strip()
    if t.endswith("```"):
        t = t[:-3].strip()
    return t


def _iter_path_prefixed_chunks(response: str) -> list[str]:
    """按 // path: 行切分无围栏的多文件输出。"""
    if not re.search(r"^\s*//\s*path:\s*", response, re.MULTILINE):
        return []
    parts = re.split(r"(?=^\s*//\s*path:\s*)", response, flags=re.MULTILINE)
    chunks: list[str] = []
    for part in parts:
        part = _strip_trailing_fence(part.strip())
        if part and re.match(r"^\s*//\s*path:\s*", part):
            chunks.append(part)
    return chunks


def _iter_code_blocks(response: str) -> list[tuple[str, str, str]]:
    """返回 [(lang, path_hint, body), ...]；支持未闭合的截断代码块。"""
    blocks: list[tuple[str, str, str]] = []
    for m in _FENCE_CLOSED_RE.finditer(response):
        lang = (m.group(1) or "").lower()
        blocks.append(_parse_fence_chunk(lang, m.group(2)))

    if blocks:
        return blocks

    for marker in ("```jsx\n", "```javascript\n", "```js\n", "```css\n", "```\n"):
        idx = response.rfind(marker)
        if idx >= 0:
            lang = marker.strip("`").strip().lower() or ""
            chunk = response[idx + len(marker) :].strip()
            chunk = re.split(r"\n```", chunk, maxsplit=1)[0].strip()
            if chunk and ("import " in chunk or "export " in chunk or "function " in chunk):
                blocks.append(_parse_fence_chunk(lang, chunk))
            break
    if blocks:
        return blocks

    for chunk in _iter_path_prefixed_chunks(response):
        blocks.append(_parse_fence_chunk("jsx", chunk))
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
        body = _sanitize_code_body(body, rel_path=rel_path)
        if not body.strip():
            continue
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

        body = _sanitize_code_body(body, lang, rel_path)
        if not body.strip():
            continue
        fw.write_text(ctx.output_path, rel_path, body)
        ctx.add_manifest(rel_path)
        written += 1
    return written
