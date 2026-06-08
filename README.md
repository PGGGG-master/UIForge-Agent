# UIForge-Agent

面向 Web 前端功能页面开发的**需求 → 分析 → 设计 → 代码 → 测试**生成智能体。

**产物始终写入你打开的目标文件夹**（可为空目录），不会默认写到 `runs/`。

## 环境要求

- Python 3.10+
- Node.js 18+ / npm
- [DeepSeek API Key](https://platform.deepseek.com/)

## 快速开始（CLI）

```bash
cd d:\UIForge-Agent
pip install -r requirements.txt
copy .env.example .env
# 编辑 DEEPSEEK_API_KEY
```

创建并进入你的输出目录（空文件夹即可）：

```bash
mkdir d:\MyPageOutput
cd d:\MyPageOutput
python d:\UIForge-Agent\uiforge.py --task full --input d:\UIForge-Agent\examples\user_list_page.md
```

完成后，`d:\MyPageOutput\` 下会出现 `analysis/`、`design/`、`src/`、`tests/`、`report/` 等。

可选：使用子目录 `MyPageOutput\user_list_page\`：

```bash
python d:\UIForge-Agent\uiforge.py --task full --input ... --use-case-subfolder
```

## VSCode / Cursor 插件

### 1. 配置（一次）

设置 **`uiforge.projectRoot`** = `d:\UIForge-Agent`（含 `uiforge.py` 的目录）

### 2. 启动插件

- **Ctrl+Shift+D** → 选 **「启动 UIForge 侧边栏插件」** → ▶  
- 或：`.\scripts\start-extension-dev.ps1`

在 **`[扩展开发主机]`** 新窗口中操作。

### 3. 使用

1. **文件 → 打开文件夹** → 选你的空目录（如 `d:\MyPageOutput`）
2. 左侧 **火箭图标** → 选需求 `.md` → **完整生成** → **开始执行**
3. 产物出现在该文件夹；报告在 `report/test_report.md`

侧边栏会显示：**产物将写入当前工作区：d:\MyPageOutput**

## 输出结构

在目标文件夹（工作区）根目录：

```
你的文件夹/
├── analysis/
├── design/
├── src/
├── tests/
├── report/
│   └── test_report.md
├── package.json
└── vite.config.js
```

## 分阶段任务

```bash
cd 你的输出文件夹
python d:\UIForge-Agent\uiforge.py --task design --input 需求.md
python d:\UIForge-Agent\uiforge.py --task code   --input 需求.md
# test：LLM 根据源码生成测试 → Vitest → LLM 生成 report/test_report.md
python d:\UIForge-Agent\uiforge.py --task test   --input 需求.md
```

## 设置项

| 配置 | 说明 |
|------|------|
| `uiforge.projectRoot` | UIForge 安装路径（插件必填） |
| `uiforge.pythonPath` | Python 命令，默认 `python` |
| `uiforge.useCaseSubfolder` | `true` 时用 `工作区/<用例名>/` 子目录 |

## 架构说明

- **工具目录**（`uiforge.projectRoot`）：放 `uiforge.py`、模板、Agent 逻辑
- **工作区目录**：你打开的空文件夹，**所有生成物写在这里**
