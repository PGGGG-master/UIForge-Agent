const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const {
  getUiforgeHome,
  getWorkspaceFolder,
  getWorkspaceWarning,
  getOutputModeHint,
  deriveOutputDir,
} = require('./workspace');
const { loadFeedbackFromDisk } = require('./commandRunner');

class StatusStore {
  constructor(extensionContext) {
    this.extensionContext = extensionContext;
    this.requirementFile = '';
    this.task = 'full';
    this.status = '空闲';
    this.outputDir = '';
    this.testSummary = '';
    this.feedbackText = '';
    this.workspaceWarning = '';
    this.outputModeHint = '';
    this._updateWorkspaceWarning();
  }

  _updateWorkspaceWarning() {
    this.workspaceWarning = getWorkspaceWarning(this.extensionContext);
    this.outputModeHint = getOutputModeHint(this.extensionContext);
  }

  setRequirement(filePath) {
    this.requirementFile = filePath;
    this.outputDir = deriveOutputDir(filePath, this.extensionContext);
    this.feedbackText = loadFeedbackFromDisk(this.outputDir);
    this._notify();
  }

  setFeedback(text) {
    this.feedbackText = text || '';
    this._notify();
  }

  setTask(task) {
    this.task = task;
    this._notify();
  }

  setRunning() {
    this.status = '执行中...';
    this.testSummary = '';
    this._notify();
  }

  setCompleted(success = true) {
    this.status = success ? '已完成' : '失败';
    this._loadTestStatus();
    this._notify();
  }

  setFailed(message) {
    this.status = `失败: ${message}`;
    this._notify();
  }

  _loadTestStatus() {
    if (!this.outputDir) return;
    const statusFile = path.join(this.outputDir, 'report', 'test_status.json');
    if (!fs.existsSync(statusFile)) {
      this.testSummary = '';
      return;
    }
    try {
      const data = JSON.parse(fs.readFileSync(statusFile, 'utf-8'));
      this.testSummary = `${data.passed || 0}/${data.total || 0} 通过`;
    } catch {
      this.testSummary = '';
    }
  }

  _notify() {
    this._updateWorkspaceWarning();
    if (this.requirementFile) {
      this.outputDir = deriveOutputDir(this.requirementFile, this.extensionContext);
    }
    if (this._onChange) this._onChange();
  }

  refresh() {
    this._notify();
  }

  onDidChange(callback) {
    this._onChange = callback;
  }

  getState() {
    return {
      requirementFile: this.requirementFile,
      task: this.task,
      status: this.status,
      outputDir: this.outputDir,
      testSummary: this.testSummary,
      feedbackText: this.feedbackText,
      workspaceWarning: this.workspaceWarning,
      outputModeHint: this.outputModeHint,
      uiforgeHome: getUiforgeHome(this.extensionContext) || '',
      workspaceFolder: getWorkspaceFolder(),
    };
  }
}

module.exports = { StatusStore };
