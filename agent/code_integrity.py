from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from agent import file_writer as fw
from agent.context import AgentContext
from agent.llm_client import LLMClient
from agent.stages.blocks import write_fenced_blocks
from agent.validators import ValidationError

_IMPORT_RE = re.compile(
    r"""import\s+(?:[\w*{}\s,]+\s+from\s+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_RESOLVE_EXTS = (".jsx", ".js", ".css", ".json")


def _is_local_import(spec: str) -> bool:
    return spec.startswith(".")


def _resolve_import(from_file: Path, spec: str, project_root: Path) -> Path | None:
    base = from_file.parent
    candidate = (base / spec).resolve()
    if candidate.exists() and candidate.is_file():
        return candidate
    if candidate.suffix:
        return None
    for ext in _RESOLVE_EXTS:
        p = Path(str(candidate) + ext)
        if p.exists() and p.is_file():
            return p
    for name in ("index.jsx", "index.js"):
        p = candidate / name
        if p.exists():
            return p
    return None


def _expected_rel_path(output_dir: Path, from_rel: str, spec: str) -> str:
    from_file = output_dir / from_rel
    target = (from_file.parent / spec).resolve()
    return target.relative_to(output_dir.resolve()).as_posix()


def find_missing_local_imports(output_dir: Path) -> list[dict[str, str]]:
    src = output_dir / "src"
    if not src.exists():
        return []
    missing: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for file_path in sorted(src.rglob("*")):
        if file_path.suffix not in (".js", ".jsx"):
            continue
        from_rel = file_path.relative_to(output_dir).as_posix()
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        for spec in _IMPORT_RE.findall(text):
            if not _is_local_import(spec):
                continue
            if _resolve_import(file_path, spec, output_dir):
                continue
            key = (spec, from_rel)
            if key in seen:
                continue
            seen.add(key)
            missing.append(
                {
                    "spec": spec,
                    "from_file": from_rel,
                    "expected": _expected_rel_path(output_dir, from_rel, spec),
                }
            )
    return missing


def _stub_css_path(project_root: Path, css_name: str) -> Path | None:
    stubs = project_root / "templates" / "stubs"
    named = stubs / css_name
    if named.exists():
        return named
    if (stubs / "notes.css").exists():
        return stubs / "notes.css"
    return None


def _write_css_stub(ctx: AgentContext, rel_path: str) -> None:
    root = Path(ctx.project_root or Path(__file__).resolve().parent.parent)
    stub = _stub_css_path(root, Path(rel_path).name)
    content = stub.read_text(encoding="utf-8") if stub else (
        "/* UIForge 自动生成的占位样式 */\nbody { margin: 0; font-family: system-ui, sans-serif; }\n"
    )
    fw.write_text(ctx.output_path, rel_path, content)
    ctx.add_manifest(rel_path)
    ctx.log(f"[CodeIntegrity] 已写入缺失样式: {rel_path}")


def _repair_with_llm(ctx: AgentContext, llm: LLMClient, missing: list[dict[str, str]]) -> int:
    files_desc = "\n".join(
        f"- {m['expected']}（被 {m['from_file']} 以 '{m['spec']}' 引用）" for m in missing
    )
    system = (
        "你是 React 工程师。仅补全缺失的被 import 文件，使 Vite 项目可编译、可运行。\n"
        "每个文件单独一个代码块，首行 // path: 相对路径。\n"
        "不要输出已有文件，不要解释。"
    )
    user = (
        f"需求摘要：\n{ctx.requirement_text[:3000]}\n\n"
        f"必须补全的文件：\n{files_desc}\n"
    )
    response = llm.complete(system, user, max_tokens=16384)
    ctx.output_path.joinpath("report").mkdir(parents=True, exist_ok=True)
    fw.write_text(ctx.output_path, "report/llm_repair_missing.txt", response[:50000])
    return write_fenced_blocks(ctx, response, tests_only=False)


def _resolve_npm() -> str:
    npm = shutil.which("npm")
    if npm:
        return npm
    if sys.platform == "win32":
        for base in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "nodejs",
        ):
            candidate = base / "npm.cmd"
            if candidate.exists():
                return str(candidate)
    return "npm"


def run_build_check(ctx: AgentContext) -> None:
    cwd = ctx.output_path
    if not (cwd / "package.json").exists():
        return
    npm = _resolve_npm()
    if not (cwd / "node_modules").exists():
        ctx.log("[CodeIntegrity] npm install（build 前）...")
        install = subprocess.run(
            [npm, "install"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        if install.returncode != 0:
            raise ValidationError(f"npm install 失败: {(install.stderr or '')[:500]}")

    ctx.log("[CodeIntegrity] npm run build 冒烟检查...")
    result = subprocess.run(
        [npm, "run", "build"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    log = (result.stdout or "") + (result.stderr or "")
    fw.write_text(cwd, "report/build_check.log", log[:30000])
    if result.returncode != 0:
        raise ValidationError("项目未能通过 npm run build，详见 report/build_check.log")
    ctx.log("[CodeIntegrity] build 通过")


def repair_project_integrity(ctx: AgentContext, llm: LLMClient | None) -> None:
    missing = find_missing_local_imports(ctx.output_path)
    if not missing:
        ctx.log("[CodeIntegrity] 相对 import 均已解析")
        run_build_check(ctx)
        return

    ctx.log(f"[CodeIntegrity] 发现 {len(missing)} 个缺失 import 目标")

    for item in missing:
        expected = item["expected"]
        if expected.endswith(".css") or item["spec"].endswith(".css"):
            if not (ctx.output_path / expected).exists():
                _write_css_stub(ctx, expected)

    missing = find_missing_local_imports(ctx.output_path)
    if missing and llm and os.getenv("DEEPSEEK_API_KEY"):
        ctx.log("[CodeIntegrity] LLM 补全缺失模块...")
        _repair_with_llm(ctx, llm, missing)
        missing = find_missing_local_imports(ctx.output_path)

    if missing:
        names = ", ".join(m["expected"] for m in missing[:8])
        raise ValidationError(f"仍有未解析的 import 目标: {names}")

    run_build_check(ctx)
