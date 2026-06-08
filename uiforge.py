#!/usr/bin/env python3
"""UIForge-Agent CLI entry."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent.context import AgentContext
from agent.pipeline import run_pipeline
from agent.validators import ValidationError, derive_output_dir, validate_input_file


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    parser = argparse.ArgumentParser(description="UIForge-Agent: 前端页面需求到代码与测试")
    parser.add_argument(
        "--task",
        required=True,
        choices=["full", "design", "code", "test", "revise", "revise-ui"],
        help="任务类型（revise：按意见路由修订；revise-ui：打开反馈界面）",
    )
    parser.add_argument("--input", required=True, help="Markdown 需求文件路径")
    parser.add_argument(
        "--output",
        default=None,
        help="输出目录，默认为当前工作目录（可先 cd 到目标空文件夹）",
    )
    parser.add_argument(
        "--use-case-subfolder",
        action="store_true",
        help="输出到当前目录下的 <用例名>/ 子文件夹",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="revise-ui 反馈服务端口（默认 8765）",
    )
    parser.add_argument(
        "--preview-url",
        default="http://localhost:5173",
        help="revise-ui 内嵌预览的 Vite 地址",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="revise-ui 启动时不自动打开浏览器",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    input_path = Path(args.input).resolve()
    use_sub = args.use_case_subfolder or os.getenv("UIFORGE_USE_CASE_SUBFOLDER", "").lower() in (
        "1",
        "true",
        "yes",
    )

    try:
        validate_input_file(input_path)
        output_dir = derive_output_dir(
            input_path,
            args.output,
            use_case_subfolder=use_sub,
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        requirement_text = input_path.read_text(encoding="utf-8")
        ctx = AgentContext(
            input_path=str(input_path),
            output_dir=str(output_dir),
            task=args.task,
            requirement_text=requirement_text,
            project_root=str(root),
            feedback_port=args.port,
            preview_url=args.preview_url,
            open_browser=not args.no_browser,
        )
        ctx.log(f"UIForge-Agent 启动 | task={args.task}")
        ctx.log(f"输入: {input_path}")
        ctx.log(f"输出: {output_dir}")

        run_pipeline(ctx)
        ctx.log("全部阶段完成。")
        return 0
    except ValidationError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
