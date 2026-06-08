# 不依赖 F5：用新 Cursor/VS Code 窗口加载 UIForge 插件（扩展开发模式）
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$ExtPath = Join-Path $Root "vscode-extension"

Write-Host "项目根目录: $Root"
Write-Host "插件目录:   $ExtPath"
Write-Host ""
Write-Host "正在启动扩展开发主机..."

$cursor = Get-Command cursor -ErrorAction SilentlyContinue
$code = Get-Command code -ErrorAction SilentlyContinue

if ($cursor) {
  & cursor $Root --extensionDevelopmentPath=$ExtPath
} elseif ($code) {
  & code $Root --extensionDevelopmentPath=$ExtPath
} else {
  Write-Host "未找到 cursor 或 code 命令。请改用下面方式：" -ForegroundColor Yellow
  Write-Host "1. Ctrl+Shift+D 打开「运行和调试」"
  Write-Host "2. 顶部下拉选「启动 UIForge 侧边栏插件」"
  Write-Host "3. 新窗口：打开你的空文件夹 → 侧边栏开始执行"
  exit 1
}
