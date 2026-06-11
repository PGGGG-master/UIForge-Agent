from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.file_writer import extract_json_object


def _is_deepseek_base_url(base_url: str) -> bool:
    return "deepseek" in (base_url or "").lower()


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_project_env() -> None:
    """从 UIForge-Agent 安装目录加载 .env，避免在 D:\\yty 等输出目录执行时读不到 Key。"""
    load_dotenv(_project_root() / ".env")


def _message_text(message: Any) -> str:
    content = (getattr(message, "content", None) or "").strip()
    reasoning = (getattr(message, "reasoning_content", None) or "").strip()
    if not content:
        return reasoning
    if not reasoning:
        return content
    # thinking 模型有时把代码放在 reasoning 或截断 content；合并并优先含代码块的部分
    if "```" in reasoning and "```" not in content:
        return f"{reasoning}\n\n{content}".strip()
    if "```" in content and "```" not in reasoning:
        return content
    # 测试代码常只有 import 落在 content，describe/it 在 reasoning
    if "describe(" in reasoning and "describe(" not in content:
        return f"{content}\n\n{reasoning}".strip()
    if "it(" in reasoning and "it(" not in content and "import " in content:
        return f"{content}\n\n{reasoning}".strip()
    return f"{content}\n\n{reasoning}".strip()


class LLMClient:
    def __init__(self, config_path: str | Path | None = None) -> None:
        _load_project_env()
        root = _project_root()
        cfg_file = Path(config_path) if config_path else root / "config.yaml"
        with cfg_file.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        llm_cfg = cfg["llm"]
        key_env = llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY")
        api_key = os.getenv(key_env, "")
        if not api_key:
            raise RuntimeError(
                f"未设置环境变量 {key_env}。请在 {root / '.env'} 中配置 DeepSeek API Key。"
            )
        self.base_url = llm_cfg["base_url"]
        self.model = llm_cfg["model"]
        self.temperature = llm_cfg.get("temperature", 0.2)
        self.max_tokens = llm_cfg.get("max_tokens", 8192)
        timeout_s = float(llm_cfg.get("timeout_seconds", 300))
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_s),
        )

        thinking_cfg = llm_cfg.get("thinking") or {}
        self._is_deepseek = _is_deepseek_base_url(self.base_url)
        self._use_thinking = self._is_deepseek and thinking_cfg.get("enabled", True)
        self._reasoning_effort = thinking_cfg.get("reasoning_effort", "high")

    def _chat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        *,
        max_tokens: int | None = None,
        use_thinking: bool | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "stream": False,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        # DeepSeek：config.thinking.enabled 时每次请求均开启 thinking（忽略 use_thinking=False）
        thinking_on = bool(self._is_deepseek and self._use_thinking)
        if thinking_on:
            kwargs["reasoning_effort"] = self._reasoning_effort
            extra = dict(kwargs.get("extra_body") or {})
            extra["thinking"] = {"type": "enabled"}
            kwargs["extra_body"] = extra
        thinking_hint = "thinking=on" if thinking_on else "thinking=off"
        print(f"[LLM] 请求中 model={self.model} {thinking_hint} ...", flush=True)
        response = self.client.chat.completions.create(**kwargs)
        usage = getattr(response, "usage", None)
        if usage:
            print(
                f"[LLM] 完成 tokens: prompt={usage.prompt_tokens} "
                f"completion={usage.completion_tokens} total={usage.total_tokens}",
                flush=True,
            )
        text = _message_text(response.choices[0].message)
        if not text:
            raise RuntimeError("模型返回为空（content 与 reasoning_content 均无有效文本）")
        return text

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=8))
    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int | None = None,
        use_thinking: bool | None = None,
    ) -> str:
        return self._chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            use_thinking=use_thinking,
        )

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=8))
    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        content = self._chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            json_mode=True,
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return extract_json_object(content)

    def load_prompt(self, name: str) -> tuple[str, str]:
        root = Path(__file__).resolve().parent.parent / "prompts"
        system = (root / f"{name}_system.txt").read_text(encoding="utf-8")
        user_tpl = (root / f"{name}_user.txt").read_text(encoding="utf-8")
        return system, user_tpl
