const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const { getUiforgeHome, getWorkspaceHint, getWorkspaceFolder } = require('./workspace');

const OPEN_FILES = {
  full: 'report/test_report.md',
  test: 'report/test_report.md',
  design: 'design/component_design.md',
  code: 'src/pages',
  revise: 'report/revision_history.md',
};

const FEEDBACK_REL = path.join('feedback', 'revision.md');

/** PowerShell 中 "python" "script.py" 会报错，需 & 调用或勿给 python 加引号 */
function psQuote(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

function isPowerShellShell() {
  const shell = (vscode.env.shell || '').toLowerCase();
  return shell.includes('powershell') || shell.includes('pwsh');
}

function buildRunCommand(pythonPath, uiforge, task, input, outputDir) {
  if (isPowerShellShell()) {
    const py = pythonPath.trim();
    let pyPart;
    if (/^py(?:\.exe)?\s/i.test(py) || /^python(?:\.exe)?$/i.test(py)) {
      pyPart = py;
    } else if (/[\\/]/.test(py) || py.includes(' ')) {
      pyPart = `& ${psQuote(py)}`;
    } else {
      pyPart = py;
    }
    return `${pyPart} ${psQuote(uiforge)} --task ${task} --input ${psQuote(input)} --output ${psQuote(outputDir)}`;
  }
  return `"${pythonPath}" "${uiforge}" --task ${task} --input "${input}" --output "${outputDir}"`;
}

async function openResultFile(outputDir, task) {
  const rel = OPEN_FILES[task];
  if (!rel) return;
  const full = path.join(outputDir, rel);
  if (rel.endsWith('pages')) {
    if (!fs.existsSync(full)) return;
    const files = fs.readdirSync(full).filter((f) => f.endsWith('.jsx'));
    if (files.length) {
      await vscode.window.showTextDocument(vscode.Uri.file(path.join(full, files[0])));
    }
    return;
  }
  if (fs.existsSync(full)) {
    await vscode.window.showTextDocument(vscode.Uri.file(full));
  }
}

function loadFeedbackFromDisk(outputDir) {
  if (!outputDir) return '';
  const full = path.join(outputDir, FEEDBACK_REL);
  if (!fs.existsSync(full)) return '';
  try {
    return fs.readFileSync(full, 'utf-8');
  } catch {
    return '';
  }
}

function saveFeedbackToDisk(outputDir, text) {
  if (!outputDir) {
    throw new Error('无输出目录');
  }
  const dir = path.join(outputDir, 'feedback');
  fs.mkdirSync(dir, { recursive: true });
  const body = (text || '').trim();
  fs.writeFileSync(path.join(dir, 'revision.md'), body ? body + '\n' : '', 'utf-8');
}

async function runRevise(statusStore, extensionContext) {
  if (!statusStore.requirementFile) {
    vscode.window.showWarningMessage('请先选择需求文件');
    return;
  }

  const root = getUiforgeHome(extensionContext);
  if (!root || !fs.existsSync(path.join(root, 'uiforge.py'))) {
    vscode.window.showWarningMessage('找不到 uiforge.py，请配置 uiforge.projectRoot');
    return;
  }

  const outputDir = statusStore.outputDir;
  if (!outputDir) {
    vscode.window.showWarningMessage('无法推导输出目录');
    return;
  }

  const feedback = (statusStore.feedbackText || '').trim();
  if (!feedback) {
    vscode.window.showWarningMessage('请先在侧边栏填写修改意见');
    return;
  }

  if (!fs.existsSync(path.join(outputDir, 'src'))) {
    vscode.window.showWarningMessage('输出目录尚无代码，请先执行「生成代码」或「完整生成」');
    return;
  }

  saveFeedbackToDisk(outputDir, feedback);

  const cfg = vscode.workspace.getConfiguration('uiforge');
  const pythonPath = cfg.get('pythonPath') || 'python';
  const uiforge = path.join(root, 'uiforge.py');
  const term = vscode.window.createTerminal({ name: 'UIForge-Agent Revise', cwd: root });
  term.show();
  statusStore.setRunning();

  const cmd = buildRunCommand(pythonPath, uiforge, 'revise', statusStore.requirementFile, outputDir);
  term.sendText(cmd);

  vscode.window.showInformationMessage('UIForge 正在按意见路由修订（revise），请查看终端输出。');

  const disposable = vscode.window.onDidCloseTerminal((closed) => {
    if (closed !== term) return;
    disposable.dispose();
    statusStore.setCompleted(true);
    openResultFile(outputDir, 'revise');
    statusStore.setFeedback(loadFeedbackFromDisk(outputDir));
  });
}

async function runTask(statusStore, extensionContext) {
  if (!statusStore.requirementFile) {
    vscode.window.showWarningMessage('请先选择需求文件');
    return;
  }

  const root = getUiforgeHome(extensionContext);
  if (!root || !fs.existsSync(path.join(root, 'uiforge.py'))) {
    const action = await vscode.window.showErrorMessage(
      '找不到 uiforge.py。请先打开 UIForge-Agent 项目文件夹。',
      '打开文件夹',
      '查看说明'
    );
    if (action === '打开文件夹') {
      await vscode.commands.executeCommand('vscode.openFolder');
    } else if (action === '查看说明') {
      await vscode.window.showInformationMessage(getWorkspaceHint());
    }
    statusStore.setFailed('未配置工作区');
    return;
  }

  const cfg = vscode.workspace.getConfiguration('uiforge');
  const pythonPath = cfg.get('pythonPath') || 'python';
  const uiforge = path.join(root, 'uiforge.py');
  const outputDir = statusStore.outputDir;

  if (!outputDir) {
    const msg = getWorkspaceFolder()
      ? '无法推导输出目录，请检查需求文件路径'
      : '请先：文件 → 打开文件夹（产物将写入该目录），再点「开始执行」';
    vscode.window.showWarningMessage(msg);
    statusStore.setFailed(msg);
    return;
  }

  const term = vscode.window.createTerminal({ name: 'UIForge-Agent', cwd: root });
  term.show();
  statusStore.setRunning();

  const cmd = buildRunCommand(
    pythonPath,
    uiforge,
    statusStore.task,
    statusStore.requirementFile,
    outputDir
  );
  term.sendText(cmd);

  vscode.window.showInformationMessage(
    `UIForge 已在终端执行 (${statusStore.task})，请等待终端完成。`
  );

  const disposable = vscode.window.onDidCloseTerminal((closed) => {
    if (closed !== term) return;
    disposable.dispose();
    statusStore.setCompleted(true);
    openResultFile(outputDir, statusStore.task);
  });
}

module.exports = { runTask, runRevise, openResultFile, loadFeedbackFromDisk, saveFeedbackToDisk };
