from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent import file_writer as fw
from agent.context import AgentContext
from agent.validators import validate_test_files_artifact


def _run_cmd(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=sys.platform == "win32",
    )


def _parse_vitest_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def _summarize_vitest(data: dict[str, Any]) -> dict[str, Any]:
    tests = data.get("testResults", [])
    total = 0
    passed = 0
    failed = 0
    failures: list[dict[str, str]] = []
    for file_result in tests:
        for assertion in file_result.get("assertionResults", []):
            total += 1
            if assertion.get("status") == "passed":
                passed += 1
            else:
                failed += 1
                failures.append(
                    {
                        "name": assertion.get("fullName") or assertion.get("title", ""),
                        "message": "\n".join(assertion.get("failureMessages", []))[:500],
                    }
                )
    if total == 0:
        num_total = data.get("numTotalTests", 0)
        num_passed = data.get("numPassedTests", 0)
        num_failed = data.get("numFailedTests", 0)
        if num_total:
            total, passed, failed = num_total, num_passed, num_failed
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round((passed / total * 100) if total else 0, 1),
        "failures": failures,
        "success": failed == 0 and total > 0,
    }


def run(ctx: AgentContext) -> None:
    ctx.log("[TestRunner] 开始测试执行（仅 Vitest，无 LLM）...")
    cwd = ctx.output_path
    validate_test_files_artifact(cwd)
    report_dir = cwd / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    if not (cwd / "node_modules").exists():
        ctx.log("[TestRunner] npm install...")
        install = _run_cmd(cwd, ["npm", "install"])
        if install.returncode != 0:
            ctx.log(install.stdout)
            ctx.log(install.stderr)
            raise RuntimeError(f"npm install 失败: {install.stderr[:500]}")

    ctx.log("[TestRunner] npm run test:json...")
    result = _run_cmd(cwd, ["npm", "run", "test:json"])
    raw_output = (result.stdout or "") + (result.stderr or "")
    fw.write_text(cwd, "report/vitest_raw.log", raw_output)

    vitest_file = cwd / "report" / "vitest_result.json"
    vitest_data: dict[str, Any] = {}
    try:
        if vitest_file.exists():
            vitest_data = json.loads(vitest_file.read_text(encoding="utf-8"))
        else:
            vitest_data = _parse_vitest_json(result.stdout or raw_output)
    except (json.JSONDecodeError, ValueError):
        vitest_data = {"success": False, "error": "无法解析 Vitest JSON 输出", "raw": raw_output[:2000]}

    fw.write_json(cwd, "report/vitest_result.json", vitest_data)
    summary = _summarize_vitest(vitest_data)
    summary["exit_code"] = result.returncode
    fw.write_json(cwd, "report/test_status.json", summary)
    ctx.test_result = summary
    ctx.vitest_result = vitest_data
    ctx.add_manifest("report/vitest_result.json")
    ctx.add_manifest("report/test_status.json")
    ctx.log(
        f"[TestRunner] 完成: {summary.get('passed', 0)}/{summary.get('total', 0)} 通过"
    )
