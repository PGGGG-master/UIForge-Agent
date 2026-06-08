from __future__ import annotations

import re
from typing import Literal

from pathlib import Path

from agent.code_validate import collect_css_imports
from agent.context import AgentContext
from agent.file_writer import extract_json_object
from agent.llm_client import LLMClient
from agent.validators import project_uses_rest_api

_STYLE_FEEDBACK_KEYS = (
    "颜色", "红色", "蓝色", "绿色", "黄色", "橙色", "紫色",
    "样式", "CSS", "css", "布局", "间距", "字体", "hover", "圆角", "背景色", "按钮",
)


def main_page_has_inline_styles(output_dir: Path, main_page_rel: str) -> bool:
    path = output_dir / main_page_rel
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    return "style={{" in text or "backgroundColor" in text or "color:" in text


def resolve_revise_routes(
    ctx: AgentContext,
    routes: list[ReviseRoute],
    *,
    main_page_rel: str,
    feedback: str,
) -> list[ReviseRoute]:
    """无 CSS 文件或内联样式时，颜色/按钮类意见不能仅走 Step 4。"""
    adjusted: list[ReviseRoute] = list(routes)
    has_css = bool(collect_css_imports(ctx.output_path))
    inline = main_page_has_inline_styles(ctx.output_path, main_page_rel)
    styleish = any(k in feedback for k in _STYLE_FEEDBACK_KEYS)

    if "styles" in adjusted and not has_css:
        adjusted = [r for r in adjusted if r != "styles"]
        ctx.log("[ReviseAgent] 项目未 import CSS，样式意见改由 Step 1 主页面处理")
        if "main_page" not in adjusted:
            adjusted.insert(0, "main_page")
    elif "styles" in adjusted and inline and styleish and "main_page" not in adjusted:
        adjusted.insert(0, "main_page")
        ctx.log("[ReviseAgent] 主页面为内联样式，颜色/按钮类意见同时修订主页面")

    return _sort_routes(adjusted)

ReviseRoute = Literal["main_page", "components", "api", "styles", "design"]

ROUTE_ORDER: list[ReviseRoute] = [
    "main_page",
    "components",
    "api",
    "styles",
    "design",
]

_ROUTE_LABELS: dict[ReviseRoute, str] = {
    "main_page": "Step 1 主页面",
    "components": "Step 2 子组件",
    "api": "Step 3 API/MSW",
    "styles": "Step 4 样式",
    "design": "需先更新设计",
}


def route_label(route: ReviseRoute) -> str:
    return _ROUTE_LABELS[route]


def _sort_routes(routes: list[str]) -> list[ReviseRoute]:
    valid: list[ReviseRoute] = []
    seen: set[str] = set()
    for r in ROUTE_ORDER:
        if r in routes and r not in seen:
            valid.append(r)
            seen.add(r)
    return valid


def classify_feedback_keywords(feedback: str) -> list[ReviseRoute]:
    routes: list[ReviseRoute] = []
    text = feedback
    lower = feedback.lower()

    if any(k in text for k in ("接口", "API", "api", "MSW", "msw", "fetch", "handlers", "REST")):
        routes.append("api")
    if any(k in text for k in ("组件", "子组件", "component", "Component")):
        routes.append("components")
    if any(
        k in text
        for k in ("颜色", "红色", "蓝色", "绿色", "样式", "CSS", "css", "布局", "间距", "字体", "hover", "圆角", "背景色")
    ):
        routes.append("styles")
    if any(
        k in text
        for k in ("新功能", "新页面", "新状态", "重新设计", "架构", "状态机", "类图", "新增模块")
    ):
        routes.append("design")
    if any(
        k in text
        for k in ("逻辑", "文案", "按钮", "弹窗", "搜索", "添加", "删除", "bug", "Bug", "交互")
    ):
        routes.append("main_page")

    if not routes:
        routes.append("main_page")
    return _sort_routes(routes)


def classify_feedback(
    ctx: AgentContext,
    llm: LLMClient | None,
    feedback: str,
    *,
    design_spec_json: str,
) -> tuple[list[ReviseRoute], str]:
    """返回 (路由列表, 分类理由)。"""
    feedback = feedback.strip()
    if not feedback:
        return [], "意见为空"

    if llm and __import__("os").getenv("DEEPSEEK_API_KEY"):
        system, user_tpl = llm.load_prompt("revise_classify")
        user = user_tpl.format(
            requirement_text=ctx.requirement_text[:2500],
            design_spec=design_spec_json[:3000],
            has_rest_api="是" if project_uses_rest_api(ctx) else "否",
            user_feedback=feedback[:4000],
        )
        response = llm.complete(system, user, max_tokens=1024)
        try:
            data = extract_json_object(response)
        except Exception:
            data = None
        if isinstance(data, dict):
            routes_raw = data.get("routes")
            if isinstance(routes_raw, list):
                allowed = {"main_page", "components", "api", "styles", "design"}
                cleaned = [r for r in routes_raw if isinstance(r, str) and r in allowed]
                routes = _sort_routes(cleaned)
                if routes:
                    reason = str(data.get("reason") or "LLM 分类")
                    ctx.log(f"[ReviseAgent] LLM 路由: {routes} ({reason})")
                    return routes, reason

    routes = classify_feedback_keywords(feedback)
    ctx.log(f"[ReviseAgent] 关键词路由: {routes}")
    return routes, "关键词规则分类"
