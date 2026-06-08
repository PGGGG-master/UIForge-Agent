const vscode = require('vscode');
const fs = require('fs');
const path = require('path');

function hasUiforgeRoot(dir) {
  return Boolean(dir && fs.existsSync(path.join(dir, 'uiforge.py')));
}

/** UIForge 工具安装目录（含 uiforge.py） */
function getUiforgeHome(extensionContext) {
  const cfg = vscode.workspace.getConfiguration('uiforge');
  const configured = (cfg.get('projectRoot') || '').trim();
  if (configured && hasUiforgeRoot(configured)) {
    return path.resolve(configured);
  }

  if (extensionContext?.extensionUri?.fsPath) {
    const fromExt = path.resolve(extensionContext.extensionUri.fsPath, '..');
    if (hasUiforgeRoot(fromExt)) {
      return fromExt;
    }
  }

  const folders = vscode.workspace.workspaceFolders;
  if (folders?.length) {
    for (const folder of folders) {
      const root = folder.uri.fsPath;
      if (hasUiforgeRoot(root)) {
        return root;
      }
    }
  }

  return null;
}

function getProjectRoot(extensionContext) {
  return getUiforgeHome(extensionContext);
}

/** 当前工作区 = 产物输出位置 */
function getWorkspaceFolder() {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
}

/**
 * 产物始终写入当前打开的工作区文件夹。
 * useCaseSubfolder=true 时使用 工作区/<用例名>/
 */
function deriveOutputDir(requirementFile, extensionContext) {
  if (!requirementFile) return '';

  const workspace = getWorkspaceFolder();
  if (!workspace) return '';

  const caseName = path.basename(requirementFile, path.extname(requirementFile));
  const useSub = vscode.workspace.getConfiguration('uiforge').get('useCaseSubfolder', false);
  return useSub ? path.join(workspace, caseName) : workspace;
}

function getWorkspaceWarning(extensionContext) {
  if (!getWorkspaceFolder()) {
    return '⚠ 请先：文件 → 打开文件夹（你的空目录或项目目录），产物将写入该文件夹。';
  }
  if (!getUiforgeHome(extensionContext)) {
    return '⚠ 请设置 uiforge.projectRoot 为 UIForge 安装路径（含 uiforge.py），例如 D:\\UIForgeA\\UIForge-Agent';
  }
  return '';
}

function getOutputModeHint() {
  const workspace = getWorkspaceFolder();
  if (!workspace) return '';
  const useSub = vscode.workspace.getConfiguration('uiforge').get('useCaseSubfolder', false);
  return useSub
    ? `产物将写入：${workspace}/<用例名>/`
    : `产物将写入当前工作区：${workspace}`;
}

function getWorkspaceHint() {
  return [
    '使用步骤：',
    '1. 设置 uiforge.projectRoot → UIForge 安装目录（含 uiforge.py）',
    '2. 文件 → 打开文件夹 → 选择你的空目录（产物输出位置）',
    '3. 侧边栏选择需求 .md → 完整生成 → 开始执行',
    '4. analysis/ design/ src/ tests/ 会出现在该文件夹中',
    '',
    'CLI：先 cd 到目标文件夹，再执行 uiforge.py（无需 --output）',
  ].join('\n');
}

module.exports = {
  getUiforgeHome,
  getProjectRoot,
  getWorkspaceFolder,
  deriveOutputDir,
  getWorkspaceWarning,
  getOutputModeHint,
  getWorkspaceHint,
  hasUiforgeRoot,
};
