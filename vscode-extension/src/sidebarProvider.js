const vscode = require('vscode');
const { runTask, runRevise, saveFeedbackToDisk } = require('./commandRunner');

class SidebarProvider {
  constructor(context, statusStore) {
    this.context = context;
    this.statusStore = statusStore;
    statusStore.onDidChange(() => this._refresh());
  }

  resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = this._getHtml();
    webviewView.webview.onDidReceiveMessage(async (msg) => {
      switch (msg.type) {
        case 'useCurrent':
          await vscode.commands.executeCommand('uiforge.useCurrentFile');
          break;
        case 'pickFile':
          await vscode.commands.executeCommand('uiforge.pickRequirementFile');
          break;
        case 'setTask':
          this.statusStore.setTask(msg.task);
          break;
        case 'run':
          await runTask(this.statusStore, this.context);
          break;
        case 'setFeedback':
          this.statusStore.setFeedback(msg.text || '');
          break;
        case 'saveFeedback':
          await this._saveFeedback(msg.text || '');
          break;
        case 'runRevise':
          if (typeof msg.text === 'string') {
            this.statusStore.setFeedback(msg.text);
          }
          await runRevise(this.statusStore, this.context);
          break;
      }
    });
    this._refresh();
  }

  async _saveFeedback(text) {
    const outputDir = this.statusStore.outputDir;
    if (!outputDir) {
      vscode.window.showWarningMessage('请先选择需求文件以确定输出目录');
      return;
    }
    try {
      saveFeedbackToDisk(outputDir, text);
      this.statusStore.setFeedback(text);
      vscode.window.showInformationMessage('修改意见已保存到 feedback/revision.md');
    } catch (e) {
      vscode.window.showErrorMessage(`保存失败: ${e.message}`);
    }
  }

  _refresh() {
    if (!this._view) return;
    this._view.webview.postMessage({ type: 'state', data: this.statusStore.getState() });
  }

  _getHtml() {
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    :root {
      --uf-gap: 10px;
      --uf-radius: 6px;
      --uf-radius-sm: 4px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 12px 10px 16px;
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size, 13px);
      color: var(--vscode-foreground);
      line-height: 1.45;
      background: var(--vscode-sideBar-background, var(--vscode-editor-background));
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--vscode-widget-border, rgba(128,128,128,.25));
    }
    .brand-icon {
      width: 28px; height: 28px;
      border-radius: var(--uf-radius);
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      display: flex; align-items: center; justify-content: center;
      font-size: 14px; font-weight: 600;
    }
    .brand-text { font-weight: 600; font-size: 13px; letter-spacing: 0.02em; }
    .brand-sub { font-size: 11px; color: var(--vscode-descriptionForeground); font-weight: normal; }

    .alert {
      padding: 8px 10px;
      border-radius: var(--uf-radius);
      font-size: 11px;
      line-height: 1.5;
      margin-bottom: var(--uf-gap);
      border-left: 3px solid transparent;
    }
    .alert-warn {
      background: color-mix(in srgb, var(--vscode-inputValidation-warningBackground, #cca700) 35%, transparent);
      border-left-color: var(--vscode-inputValidation-warningBorder, #cca700);
      color: var(--vscode-foreground);
    }
    .alert-info {
      background: var(--vscode-textBlockQuote-background, rgba(128,128,128,.12));
      border-left-color: var(--vscode-textLink-foreground, #3794ff);
      color: var(--vscode-descriptionForeground);
    }

    .card {
      background: var(--vscode-editor-background);
      border: 1px solid var(--vscode-widget-border, rgba(128,128,128,.2));
      border-radius: var(--uf-radius);
      padding: 10px;
      margin-bottom: var(--uf-gap);
    }
    .card-accent {
      border-color: color-mix(in srgb, var(--vscode-focusBorder, #007fd4) 50%, transparent);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--vscode-focusBorder) 15%, transparent);
    }
    .card-title {
      margin: 0 0 8px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--vscode-descriptionForeground);
    }
    .card-title-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 8px;
    }
    .card-title-row .card-title { margin: 0; }

    .file-chip {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 8px;
      margin-bottom: 8px;
      border-radius: var(--uf-radius-sm);
      background: var(--vscode-input-background);
      border: 1px dashed var(--vscode-input-border, rgba(128,128,128,.35));
      font-size: 12px;
      word-break: break-all;
    }
    .file-chip.empty { color: var(--vscode-descriptionForeground); font-style: italic; }
    .file-chip .dot {
      width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
      background: var(--vscode-descriptionForeground);
    }
    .file-chip.ready .dot { background: var(--vscode-testing-iconPassed, #73c991); }

    button {
      width: 100%;
      margin: 0 0 6px;
      padding: 7px 10px;
      font-size: 12px;
      font-family: inherit;
      cursor: pointer;
      border-radius: var(--uf-radius-sm);
      border: 1px solid transparent;
      transition: opacity 0.12s ease;
    }
    button:last-child { margin-bottom: 0; }
    button:hover:not(:disabled) { opacity: 0.92; }
    button:active:not(:disabled) { opacity: 0.85; }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    button:focus-visible {
      outline: 1px solid var(--vscode-focusBorder);
      outline-offset: 1px;
    }
    .btn-primary {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }
    .btn-secondary {
      background: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
      border-color: var(--vscode-widget-border, transparent);
    }
    .btn-ghost {
      background: transparent;
      color: var(--vscode-foreground);
      border-color: var(--vscode-widget-border, rgba(128,128,128,.3));
    }
    .btn-row { display: flex; gap: 6px; }
    .btn-row button { flex: 1; margin-bottom: 0; }

    .task-grid {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .task-opt {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 7px 8px;
      border-radius: var(--uf-radius-sm);
      cursor: pointer;
      border: 1px solid transparent;
      font-size: 12px;
      user-select: none;
    }
    .task-opt:hover {
      background: var(--vscode-list-hoverBackground, rgba(128,128,128,.12));
    }
    .task-opt input { margin: 0; accent-color: var(--vscode-focusBorder); cursor: pointer; }
    .task-opt:has(input:checked) {
      background: var(--vscode-list-activeSelectionBackground, rgba(128,128,128,.2));
      border-color: var(--vscode-focusBorder, rgba(128,128,128,.4));
    }
    .task-opt .task-desc {
      font-size: 10px;
      color: var(--vscode-descriptionForeground);
      margin-left: auto;
      flex-shrink: 0;
    }

    textarea {
      width: 100%;
      min-height: 88px;
      max-height: 200px;
      padding: 8px 10px;
      margin-bottom: 8px;
      font-size: 12px;
      line-height: 1.5;
      font-family: inherit;
      resize: vertical;
      color: var(--vscode-input-foreground);
      background: var(--vscode-input-background);
      border: 1px solid var(--vscode-input-border, rgba(128,128,128,.35));
      border-radius: var(--uf-radius-sm);
    }
    textarea:focus {
      outline: none;
      border-color: var(--vscode-focusBorder);
      box-shadow: 0 0 0 1px var(--vscode-focusBorder);
    }
    textarea::placeholder { color: var(--vscode-input-placeholderForeground, #888); }

    .hint-toggle {
      font-size: 11px;
      color: var(--vscode-textLink-foreground);
      cursor: pointer;
      background: none;
      border: none;
      padding: 0;
      width: auto;
      margin: 0;
      text-align: left;
    }
    .hint-toggle:hover { text-decoration: underline; }
    .hint-body {
      font-size: 11px;
      color: var(--vscode-descriptionForeground);
      line-height: 1.55;
      margin-top: 6px;
      padding: 8px;
      border-radius: var(--uf-radius-sm);
      background: var(--vscode-textBlockQuote-background, rgba(128,128,128,.08));
      display: none;
    }
    .hint-body.open { display: block; }
    .hint-body code {
      font-size: 10px;
      padding: 1px 4px;
      border-radius: 3px;
      background: var(--vscode-textCodeBlock-background, rgba(128,128,128,.2));
    }

    .status-panel { font-size: 11px; line-height: 1.65; }
    .status-row {
      display: flex;
      gap: 6px;
      padding: 3px 0;
      border-bottom: 1px solid var(--vscode-widget-border, rgba(128,128,128,.12));
    }
    .status-row:last-child { border-bottom: none; }
    .status-label {
      flex: 0 0 72px;
      color: var(--vscode-descriptionForeground);
    }
    .status-value { flex: 1; word-break: break-all; }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 10px;
      font-size: 11px;
      font-weight: 500;
    }
    .badge-idle { background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); }
    .badge-run { background: color-mix(in srgb, var(--vscode-progressBar-background, #0e70c0) 40%, transparent); color: var(--vscode-foreground); }
    .badge-ok { background: color-mix(in srgb, var(--vscode-testing-iconPassed, #73c991) 35%, transparent); }
    .badge-fail { background: color-mix(in srgb, var(--vscode-errorForeground, #f14c4c) 25%, transparent); color: var(--vscode-errorForeground); }

    .divider {
      height: 1px;
      margin: 4px 0 10px;
      background: var(--vscode-widget-border, rgba(128,128,128,.2));
    }
    .step-label {
      font-size: 10px;
      color: var(--vscode-descriptionForeground);
      margin-bottom: 6px;
    }
  </style>
</head>
<body>
  <header class="brand">
    <div class="brand-icon">U</div>
    <div>
      <div class="brand-text">UIForge-Agent</div>
      <div class="brand-sub">需求 → 设计 → 代码 → 修订</div>
    </div>
  </header>

  <div id="warn" class="alert alert-warn" style="display:none;"></div>
  <div id="hint" class="alert alert-info" style="display:none;"></div>

  <section class="card">
    <h3 class="card-title">1 · 需求文件</h3>
    <div id="file" class="file-chip empty"><span class="dot"></span><span class="file-name">未选择</span></div>
    <button type="button" class="btn-ghost" onclick="post('useCurrent')">使用当前打开文件</button>
    <button type="button" class="btn-ghost" onclick="post('pickFile')">选择需求文件…</button>
  </section>

  <section class="card">
    <h3 class="card-title">2 · 生成任务</h3>
    <div class="task-grid">
      <label class="task-opt"><input type="radio" name="task" value="full" onchange="setTask('full')"><span>完整生成</span><span class="task-desc">设计+代码+测试</span></label>
      <label class="task-opt"><input type="radio" name="task" value="design" onchange="setTask('design')"><span>生成设计</span></label>
      <label class="task-opt"><input type="radio" name="task" value="code" onchange="setTask('code')"><span>生成代码</span></label>
      <label class="task-opt"><input type="radio" name="task" value="test" onchange="setTask('test')"><span>生成测试</span><span class="task-desc">+ 报告</span></label>
    </div>
    <div class="divider"></div>
    <button type="button" class="btn-primary" id="btn-run" onclick="post('run')">开始执行</button>
  </section>

  <section class="card card-accent">
    <div class="card-title-row">
      <h3 class="card-title">3 · 修改意见</h3>
      <span class="step-label">修订代码</span>
    </div>
    <textarea id="feedback" placeholder="每行一条，例如：&#10;· 删除按钮改成红色&#10;· 空列表文案改为「还没有待办」" oninput="onFeedbackInput()"></textarea>
    <div class="btn-row">
      <button type="button" class="btn-secondary" onclick="saveFeedback()">保存</button>
      <button type="button" class="btn-primary" onclick="applyRevise()">应用修订</button>
    </div>
    <button type="button" class="hint-toggle" onclick="toggleHint()">路由说明 ▾</button>
    <div id="hint-revise" class="hint-body">
      需先完成「生成代码」。系统按意见自动路由：<br/>
      <code>逻辑/文案/按钮颜色(内联样式)</code> → Step 1 · <code>子组件</code> → Step 2 · <code>接口</code> → Step 3 · <code>.css 文件</code> → Step 4<br/>
      无 CSS 文件时改颜色会走主页面，不会只改 Step 4。
    </div>
  </section>

  <section class="card">
    <h3 class="card-title">执行状态</h3>
    <div class="status-panel" id="status">
      <div class="status-row"><span class="status-label">状态</span><span class="status-value"><span class="badge badge-idle" id="badge">空闲</span></span></div>
      <div class="status-row"><span class="status-label">工作区</span><span class="status-value" id="st-workspace">—</span></div>
      <div class="status-row"><span class="status-label">输出目录</span><span class="status-value" id="st-output">—</span></div>
      <div class="status-row"><span class="status-label">测试</span><span class="status-value" id="st-test">—</span></div>
    </div>
  </section>

  <script>
    const vscode = acquireVsCodeApi();
    let feedbackDirty = false;

    function post(type, extra) { vscode.postMessage({ type, ...extra }); }
    function setTask(task) { post('setTask', { task }); }

    function toggleHint() {
      const el = document.getElementById('hint-revise');
      el.classList.toggle('open');
    }

    function onFeedbackInput() {
      feedbackDirty = true;
      post('setFeedback', { text: document.getElementById('feedback').value });
    }

    function saveFeedback() {
      const text = document.getElementById('feedback').value;
      post('saveFeedback', { text });
      feedbackDirty = false;
    }

    function applyRevise() {
      const text = document.getElementById('feedback').value;
      post('runRevise', { text });
    }

    function shortPath(p) {
      if (!p) return '—';
      const parts = p.replace(/\\\\/g, '/').split('/');
      if (parts.length <= 2) return p;
      return '…/' + parts.slice(-2).join('/');
    }

    function basename(p) {
      if (!p) return '';
      return p.split(/[/\\\\]/).pop();
    }

    function updateBadge(status) {
      const b = document.getElementById('badge');
      const t = status || '空闲';
      b.textContent = t;
      b.className = 'badge';
      if (t.includes('执行')) b.classList.add('badge-run');
      else if (t.includes('完成') && !t.includes('失败')) b.classList.add('badge-ok');
      else if (t.includes('失败')) b.classList.add('badge-fail');
      else b.classList.add('badge-idle');
    }

    window.addEventListener('message', e => {
      if (e.data.type !== 'state') return;
      const s = e.data.data;

      const fileEl = document.getElementById('file');
      if (s.requirementFile) {
        fileEl.className = 'file-chip ready';
        fileEl.querySelector('.file-name').textContent = basename(s.requirementFile);
        fileEl.title = s.requirementFile;
      } else {
        fileEl.className = 'file-chip empty';
        fileEl.querySelector('.file-name').textContent = '未选择';
        fileEl.title = '';
      }

      document.querySelectorAll('input[name=task]').forEach(r => { r.checked = r.value === s.task; });

      const w = document.getElementById('warn');
      if (s.workspaceWarning) { w.style.display = 'block'; w.textContent = s.workspaceWarning; }
      else { w.style.display = 'none'; }

      const hint = document.getElementById('hint');
      if (s.outputModeHint) { hint.style.display = 'block'; hint.textContent = s.outputModeHint; }
      else { hint.style.display = 'none'; }

      const fb = document.getElementById('feedback');
      if (!feedbackDirty && typeof s.feedbackText === 'string' && fb.value !== s.feedbackText) {
        fb.value = s.feedbackText;
      }

      updateBadge(s.status);
      const canRun = !!(s.workspaceFolder && s.uiforgeHome && s.requirementFile);
      const btnRun = document.getElementById('btn-run');
      if (btnRun) {
        btnRun.disabled = !canRun;
        btnRun.title = canRun ? '' : '请先打开工作区文件夹并选择需求文件';
      }
      document.getElementById('st-workspace').textContent = s.workspaceFolder ? shortPath(s.workspaceFolder) : '无（请打开文件夹）';
      document.getElementById('st-workspace').title = s.workspaceFolder || '';
      document.getElementById('st-output').textContent = s.outputDir ? shortPath(s.outputDir) : '—';
      document.getElementById('st-output').title = s.outputDir || '';
      document.getElementById('st-test').textContent = s.testSummary || '—';
    });
  </script>
</body>
</html>`;
  }
}

module.exports = { SidebarProvider };
