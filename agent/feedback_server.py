from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from pathlib import Path

from agent.context import AgentContext
from agent.llm_client import LLMClient
from agent.stages import revise_agent
from agent.validators import ValidationError

FEEDBACK_UI_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>UIForge 修订反馈</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: system-ui, sans-serif; background: #0f1419; color: #e7ecf3; }
    header { padding: 12px 20px; background: #1a2332; border-bottom: 1px solid #2a3548; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
    header h1 { margin: 0; font-size: 1.1rem; font-weight: 600; }
    header .meta { font-size: 0.85rem; color: #9aa8bc; }
    main { display: grid; grid-template-columns: 1fr 380px; gap: 0; min-height: calc(100vh - 52px); }
    @media (max-width: 960px) { main { grid-template-columns: 1fr; } }
    .preview { background: #111; border-right: 1px solid #2a3548; display: flex; flex-direction: column; }
    .preview-bar { padding: 8px 12px; font-size: 0.8rem; color: #9aa8bc; background: #151c28; }
    iframe { flex: 1; width: 100%; border: 0; min-height: 480px; background: #fff; }
    .panel { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
    label { font-size: 0.85rem; color: #9aa8bc; }
    textarea { width: 100%; min-height: 220px; padding: 12px; border-radius: 8px; border: 1px solid #2a3548; background: #151c28; color: #e7ecf3; font-size: 0.95rem; resize: vertical; }
    .btns { display: flex; gap: 8px; flex-wrap: wrap; }
    button { padding: 10px 16px; border-radius: 8px; border: none; cursor: pointer; font-size: 0.9rem; }
    .primary { background: #3b82f6; color: #fff; }
    .secondary { background: #2a3548; color: #e7ecf3; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    #status { font-size: 0.85rem; min-height: 3em; white-space: pre-wrap; color: #9aa8bc; }
    .tips { font-size: 0.8rem; color: #6b7a90; line-height: 1.5; }
    .tips code { background: #151c28; padding: 2px 6px; border-radius: 4px; }
  </style>
</head>
<body>
  <header>
    <h1>UIForge 修订反馈</h1>
    <span class="meta" id="output-dir"></span>
  </header>
  <main>
    <section class="preview">
      <div class="preview-bar">页面预览（请先在项目目录运行 <code>npm run dev</code>）</div>
      <iframe id="preview" title="preview"></iframe>
    </section>
    <aside class="panel">
      <label for="feedback">修改意见</label>
      <textarea id="feedback" placeholder="- 删除按钮改成红色&#10;- 空列表文案改成「还没有待办」&#10;- 搜索框移到标题下方"></textarea>
      <div class="btns">
        <button type="button" class="secondary" id="btn-save">保存意见</button>
        <button type="button" class="primary" id="btn-revise">应用修订（路由到 Step）</button>
      </div>
      <div id="status"></div>
      <div class="tips">
        路由规则：样式 → Step 4；子组件 → Step 2；接口 → Step 3；逻辑/文案 → Step 1。<br/>
        涉及新功能/新状态时请先 <code>--task design</code>。
      </div>
    </aside>
  </main>
  <script>
    const previewUrl = __PREVIEW_URL__;
    document.getElementById('preview').src = previewUrl;
    document.getElementById('output-dir').textContent = __OUTPUT_DIR__;

    const statusEl = document.getElementById('status');
    const feedbackEl = document.getElementById('feedback');

    async function loadFeedback() {
      try {
        const r = await fetch('/api/feedback');
        const j = await r.json();
        if (j.text) feedbackEl.value = j.text;
      } catch (e) { /* ignore */ }
    }
    loadFeedback();

    function setStatus(msg, ok) {
      statusEl.textContent = msg;
      statusEl.style.color = ok ? '#6ee7a0' : ok === false ? '#f87171' : '#9aa8bc';
    }

    document.getElementById('btn-save').onclick = async () => {
      setStatus('保存中…');
      const r = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: feedbackEl.value }),
      });
      const j = await r.json();
      setStatus(j.message || (r.ok ? '已保存' : '保存失败'), r.ok);
    };

    document.getElementById('btn-revise').onclick = async () => {
      const btn = document.getElementById('btn-revise');
      btn.disabled = true;
      setStatus('正在保存并应用修订（可能需 1～2 分钟）…');
      await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: feedbackEl.value }),
      });
      try {
        const r = await fetch('/api/revise', { method: 'POST' });
        const j = await r.json();
        setStatus(j.message || JSON.stringify(j), r.ok);
        if (r.ok) document.getElementById('preview').src = previewUrl + '?t=' + Date.now();
      } catch (e) {
        setStatus('请求失败: ' + e, false);
      } finally {
        btn.disabled = false;
      }
    };
  </script>
</body>
</html>
"""


class _ReviseState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.last_message = ""


def _make_handler(ctx: AgentContext, preview_url: str, state: _ReviseState):
    output_dir = ctx.output_path
    feedback_path = output_dir / revise_agent.FEEDBACK_REL

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, content: str) -> None:
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                html = (
                    FEEDBACK_UI_HTML.replace("__PREVIEW_URL__", json.dumps(preview_url))
                    .replace("__OUTPUT_DIR__", json.dumps(str(output_dir)))
                )
                self._html(html)
                return
            if path == "/api/feedback":
                text = ""
                if feedback_path.exists():
                    text = feedback_path.read_text(encoding="utf-8")
                self._json(200, {"text": text})
                return
            if path == "/api/status":
                self._json(200, {"running": state.running, "message": state.last_message})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                data = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                self._json(400, {"message": "无效 JSON"})
                return

            if path == "/api/feedback":
                text = str(data.get("text") or "")
                feedback_path.parent.mkdir(parents=True, exist_ok=True)
                feedback_path.write_text(text.strip() + ("\n" if text.strip() else ""), encoding="utf-8")
                self._json(200, {"message": f"已保存 → {revise_agent.FEEDBACK_REL}"})
                return

            if path == "/api/revise":
                with state.lock:
                    if state.running:
                        self._json(409, {"message": "已有修订任务进行中，请稍候"})
                        return
                    state.running = True
                try:
                    if not feedback_path.exists() or not feedback_path.read_text(encoding="utf-8").strip():
                        self._json(400, {"message": "请先填写修改意见"})
                        return
                    llm = LLMClient()
                    revise_agent.run(ctx, llm)
                    state.last_message = "修订完成"
                    self._json(200, {"message": "修订完成，请刷新预览 iframe 查看效果"})
                except ValidationError as e:
                    state.last_message = str(e)
                    self._json(400, {"message": str(e)})
                except Exception as e:
                    state.last_message = str(e)
                    self._json(500, {"message": f"修订失败: {e}"})
                finally:
                    state.running = False
                return

            self._json(404, {"error": "not found"})

    return Handler


def serve(
    ctx: AgentContext,
    *,
    port: int = 8765,
    preview_url: str = "http://localhost:5173",
    open_browser: bool = True,
) -> None:
    if not (ctx.output_path / "src").exists():
        raise ValidationError("输出目录尚无代码产物，请先执行 --task code。")

    feedback_path = ctx.output_path / revise_agent.FEEDBACK_REL
    if not feedback_path.exists():
        tpl = Path(ctx.project_root) / "templates" / "feedback" / "revision.md"
        feedback_path.parent.mkdir(parents=True, exist_ok=True)
        if tpl.exists():
            feedback_path.write_text(tpl.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            feedback_path.write_text("", encoding="utf-8")

    state = _ReviseState()
    handler = _make_handler(ctx, preview_url.rstrip("/"), state)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    ctx.log(f"[FeedbackUI] 反馈界面: {url}")
    ctx.log(f"[FeedbackUI] 预览地址: {preview_url}")
    ctx.log("[FeedbackUI] 请先在输出目录运行 npm run dev，再填写意见并「应用修订」")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        ctx.log("[FeedbackUI] 已停止")
        server.shutdown()
