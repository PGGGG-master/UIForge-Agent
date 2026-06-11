# UIForge-Agent

面向 Web 前端功能页面开发的**需求 → 分析 → 设计 → 代码 → 测试**生成智能体。

**产物始终写入你指定的输出目录**（可为空文件夹，或 `runs/<用例名>/` 等开发目录），不会静默写到无关路径。

## 环境要求

| 依赖 | 说明 |
|------|------|
| Python 3.10+ | Agent 主程序 |
| Node.js 18+ / npm | 生成项目的 build / Vitest |
| [DeepSeek API Key](https://platform.deepseek.com/) | design / code / test / revise / build debug 必需 |
| Qdrant + 本地嵌入模型 | **可选**，用于 build debug 经验向量检索；未配置时回退 SQLite 关键词匹配 |

## 快速开始（CLI）

```bash
cd UIForge-Agent
pip install -r requirements.txt
copy .env.example .env
# 编辑 DEEPSEEK_API_KEY；可选配置 QDRANT_URL / HUGGINGFACE_HUB_CACHE
```

创建输出目录并执行完整流水线：

```bash
mkdir MyPageOutput
cd MyPageOutput
python ..\UIForge-Agent\uiforge.py --task full --input ..\UIForge-Agent\examples\user_list_page.md
```

完成后，输出目录下会出现 `analysis/`、`design/`、`src/`、`tests/`、`report/` 等。

**用例子目录**（输出到 `当前目录/<用例名>/`）：

```bash
python ..\UIForge-Agent\uiforge.py --task full --input ..\UIForge-Agent\examples\project_kanban_board.md --use-case-subfolder
```

仓库内开发示例：`runs/test2/`（看板项目）。

## 流水线概览

```
需求 Markdown
    │
    ▼
[Requirement] 需求分析 → analysis/
    │
    ▼
[Design] 6 步设计建模 → design/
    │   component → state → api → class_diagram → state_machine → design_spec
    ▼
[Code] 4 步源码生成 → src/
    │   main_page → components → api（REST 项目）→ styles
    │   └── 完整性修复 + npm run build（失败时 Build Debug 最多 3 轮）
    ▼
[Test] Vitest 测试
    │   准备环境 → LLM 生成 tests/*.test.jsx → Vitest → LLM 写 report/test_report.md
    ▼
[Report] 阶段报告
```

### Design 阶段（6 步）

| 步骤 | 产物 |
|------|------|
| component | `design/component.md` |
| state | `design/state.md` |
| api | `design/api_contract.md` |
| class_diagram | `design/class_diagram.mmd` |
| state_machine | `design/state_machine.mmd` |
| design_spec | `design/design_spec.json` |

### Code 阶段（4 步 + 完整性）

1. 主页面 `src/pages/<Page>.jsx`
2. 子组件 `src/components/*.jsx`
3. MSW API（仅 REST 需求）`src/mocks/*`
4. 样式 `src/styles/*.css`

Code 结束后自动执行：

- 本地 import 缺失检测与 LLM 补全
- `npm install` + `npm run build`
- **Build Debug 循环**：build 失败时收集源码与报错，最多 3 轮 LLM 修复；**仅修复成功**后写入经验库（SQLite + 可选 Qdrant）

### Test 阶段

1. 写入 Vitest / Testing Library 脚手架（`package.json`、`vite.config.js`、`src/setupTests.js`）
2. **LLM 根据项目源码生成** `tests/<Page>.test.jsx`（最多 3 次生成 + 校验重试）
3. 运行 Vitest → `report/vitest_result.json`
4. LLM 生成 `report/test_report.md`

测试提取与校验（避免 thinking 模型把说明文字写入测试文件）：

- 从围栏代码块提取 `import` + 完整 `describe`/`it` 块（括号平衡，非贪婪全文匹配）
- 过滤 markdown 围栏、中文说明行；要求 `import` 在 `describe` 之前、至少 4 个 `it()`
- Vitest `0/0` 用例时流水线报错，不会静默通过

## 分阶段任务

在**输出目录**下执行（或 `--output` 指定）：

```bash
python path\to\uiforge.py --task design --input 需求.md
python path\to\uiforge.py --task code   --input 需求.md
python path\to\uiforge.py --task test   --input 需求.md
python path\to\uiforge.py --task full   --input 需求.md
```

| `--task` | 说明 |
|----------|------|
| `full` | design → code → test → 报告 |
| `design` | 仅需求分析 + 设计建模 |
| `code` | 需已有 `design/`；生成源码并 build |
| `test` | 需已有 `src/`；生成测试并跑 Vitest |
| `revise` | 根据 `report/feedback.txt` 或命令行意见，路由修订 design/code 步骤 |
| `revise-ui` | 启动本地反馈页（预览 + 提交修订意见） |

修订路由（`revise`）覆盖 10 条路径：design 六步 + code 四步；上游 design 变更会自动追加 `design_spec` 同步。

```bash
# 先 cd 到项目目录并启动预览（另开终端）
npm run dev

# 打开反馈界面（默认 http://localhost:8765）
python path\to\uiforge.py --task revise-ui --input 需求.md --preview-url http://localhost:5173
```

## 输出结构

```
你的输出目录/
├── analysis/           # 需求分析
├── design/             # 设计文档与 design_spec.json
├── src/                # React 源码
├── tests/              # Vitest 测试
├── report/
│   ├── test_report.md
│   ├── vitest_result.json
│   ├── llm_*_attempt*.txt   # LLM 原始回复（调试用）
│   └── debug_*              # build debug 轮次记录
├── package.json
└── vite.config.js
```

经验库（工具目录内，非输出目录）：

```
UIForge-Agent/memory/build_debug/experience.db
```

## 配置

### `config.yaml`

| 段 | 关键项 |
|----|--------|
| `llm` | `model`、`thinking.enabled`、`reasoning_effort` |
| `debug_memory` | `max_build_retries`（默认 3）、`sqlite_path`、`qdrant_collection` |

### `.env`

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | 必需 |
| `QDRANT_URL` / `QDRANT_API_KEY` | 可选，向量检索 |
| `EMBED_MODEL_NAME` / `HUGGINGFACE_HUB_CACHE` | 可选，本地嵌入模型 |

### VSCode / Cursor 插件

1. 设置 **`uiforge.projectRoot`** = UIForge-Agent 安装路径（含 `uiforge.py`）
2. **Ctrl+Shift+D** → **「启动 UIForge 侧边栏插件」** → ▶，或运行 `.\scripts\start-extension-dev.ps1`
3. 在 **[扩展开发主机]** 窗口：**打开文件夹**选输出目录 → 侧边栏选需求 `.md` → **完整生成**

| 设置项 | 说明 |
|--------|------|
| `uiforge.projectRoot` | UIForge 安装路径（必填） |
| `uiforge.pythonPath` | Python 命令，默认 `python` |
| `uiforge.useCaseSubfolder` | `true` 时使用 `工作区/<用例名>/` 子目录 |

## 仓库结构

```
UIForge-Agent/
├── uiforge.py              # CLI 入口
├── config.yaml
├── agent/                  # 流水线、校验、build debug、修订路由
│   ├── pipeline.py
│   ├── test_validate.py    # 测试提取与校验
│   ├── build_debug_loop.py
│   └── stages/             # 各阶段 Agent
├── prompts/                # LLM 提示词
├── examples/               # 示例需求 Markdown
├── runs/                   # 内部开发用例输出（如 test2）
└── memory/build_debug/     # build 修复经验库
```

## 本地验证生成项目

```bash
cd 你的输出目录
npm install
npm run dev      # 预览
npm test         # 单独跑 Vitest
npm run build    # 单独构建
```

## 架构说明

- **工具目录**（`uiforge.projectRoot`）：`uiforge.py`、Agent 逻辑、prompts、经验库
- **输出目录**：你打开或 `--output` 指定的文件夹，**所有生成物写在这里**
