from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentContext:
    input_path: str
    output_dir: str
    task: str
    requirement_text: str = ""
    requirement_spec: dict[str, Any] = field(default_factory=dict)
    design_spec: dict[str, Any] = field(default_factory=dict)
    file_manifest: list[str] = field(default_factory=list)
    test_result: dict[str, Any] = field(default_factory=dict)
    vitest_result: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    project_root: str = ""
    feedback_port: int = 8765
    preview_url: str = "http://localhost:5173"
    open_browser: bool = True

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir)

    def log(self, message: str) -> None:
        line = message.strip()
        self.logs.append(line)
        print(line)

    def add_manifest(self, relative_path: str) -> None:
        if relative_path not in self.file_manifest:
            self.file_manifest.append(relative_path)
