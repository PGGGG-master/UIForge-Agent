const vscode = require('vscode');
const path = require('path');
const { StatusStore } = require('./statusStore');
const { SidebarProvider } = require('./sidebarProvider');
const { getUiforgeHome, getWorkspaceHint, getWorkspaceWarning } = require('./workspace');

/** @param {vscode.ExtensionContext} context */
function activate(context) {
  const statusStore = new StatusStore(context);

  const sidebarProvider = new SidebarProvider(context, statusStore);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('uiforge.sidebar', sidebarProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => statusStore.refresh())
  );

  if (getWorkspaceWarning(context)) {
    vscode.window
      .showWarningMessage(
        'UIForge: 请先打开目标文件夹（产物输出位置），并配置 uiforge.projectRoot。',
        '打开文件夹',
        '配置说明'
      )
      .then((action) => {
        if (action === '打开文件夹') {
          vscode.commands.executeCommand('vscode.openFolder');
        } else if (action === '配置说明') {
          vscode.commands.executeCommand('uiforge.showSetupHelp');
        }
      });
  }

  context.subscriptions.push(
    vscode.commands.registerCommand('uiforge.useCurrentFile', () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || !editor.document.fileName.endsWith('.md')) {
        vscode.window.showWarningMessage('请打开 Markdown 需求文件');
        return;
      }
      statusStore.setRequirement(editor.document.uri.fsPath);
      vscode.window.showInformationMessage('已选择当前需求文件');
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('uiforge.pickRequirementFile', async () => {
      const defaultUri = vscode.workspace.workspaceFolders?.[0]?.uri;
      const uris = await vscode.window.showOpenDialog({
        canSelectMany: false,
        filters: { Markdown: ['md'] },
        defaultUri,
      });
      if (uris?.[0]) {
        statusStore.setRequirement(uris[0].fsPath);
        vscode.window.showInformationMessage(`已选择: ${path.basename(uris[0].fsPath)}`);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('uiforge.runTask', async () => {
      const { runTask } = require('./commandRunner');
      await runTask(statusStore, context);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('uiforge.runRevise', async () => {
      const { runRevise } = require('./commandRunner');
      await runRevise(statusStore, context);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('uiforge.showSetupHelp', async () => {
      await vscode.window.showInformationMessage(getWorkspaceHint(), { modal: true });
    })
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
