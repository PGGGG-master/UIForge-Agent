# 项目任务看板需求（主页面 + 子组件 + CSS）

实现一个纯前端的**项目任务看板**（React 18 + Vite）。页面主组件命名为 **ProjectBoardPage**。  
数据保存在浏览器 **localStorage**，键名 `project-kanban-mvp`。**不调用后端 API**，不需要 MSW。

**本期目标：** 单次生成即可 `npm run dev` 打开，用户能明显感知「这是一个可管理多状态任务的项目看板」——能筛选、新建/编辑/删除任务、在三列看板间移动任务、刷新后数据仍在。

---

## 架构要求（必须遵守）

### 1. 主页面与子组件拆分

**禁止**把下列 UI 内联写在 `ProjectBoardPage.jsx` 同一个文件里。

| 组件名 | 文件路径 | 职责 |
|--------|----------|------|
| `BoardHeader` | `src/components/BoardHeader.jsx` | 顶部：项目标题、任务总数统计、**新建任务** 按钮 |
| `FilterToolbar` | `src/components/FilterToolbar.jsx` | 关键词搜索、负责人筛选、优先级筛选、**清空筛选** |
| `KanbanColumn` | `src/components/KanbanColumn.jsx` | 单列看板容器（列标题、任务数量、任务列表区域） |
| `TaskCard` | `src/components/TaskCard.jsx` | 单张任务卡片（标题、负责人、优先级标签、截止日期、操作按钮） |
| `TaskFormModal` | `src/components/TaskFormModal.jsx` | 新建/编辑任务弹窗表单 |
| `TaskDetailPanel` | `src/components/TaskDetailPanel.jsx` | 右侧任务详情侧栏（查看描述、快捷改状态/优先级） |

主页面 `ProjectBoardPage` **只负责**：

- 全局 state（tasks、filters、选中任务、弹窗开关）
- localStorage 读写与业务逻辑
- 组合上述子组件，**不写**子组件 UI 实现

主页面中 **必须** 出现类似 import（子组件不得内联定义）：

```jsx
import BoardHeader from '../components/BoardHeader';
import FilterToolbar from '../components/FilterToolbar';
import KanbanColumn from '../components/KanbanColumn';
import TaskCard from '../components/TaskCard';
import TaskFormModal from '../components/TaskFormModal';
import TaskDetailPanel from '../components/TaskDetailPanel';
import '../styles/kanban-board.css';
```

> 说明：`TaskCard` 可由 `KanbanColumn` 内部 import 使用，但文件必须独立存在于 `src/components/TaskCard.jsx`。

### 2. 样式必须用独立 CSS（禁止全靠内联 style）

- **必须** 创建 `src/styles/kanban-board.css`，并在主页面（或 `App.jsx`）中 `import '../styles/kanban-board.css'`
- 布局、配色、卡片、列头、标签、弹窗、侧栏样式 **写在 CSS 里**，用 className 绑定
- **禁止** 仅在 jsx 里用大量 `style={{ ... }}` 完成整体 UI（允许极少量内联，如动态宽度）
- **不要** 引入 Tailwind；使用普通 CSS
- 设计 token 建议在 CSS 中定义，例如：

```css
:root {
  --kb-primary: #2563eb;
  --kb-danger: #dc2626;
  --kb-bg: #f4f6f8;
  --kb-column-todo: #e0e7ff;
  --kb-column-doing: #fef3c7;
  --kb-column-done: #d1fae5;
}
```

---

## 产品定位（用户可感知）

- 页面主标题（由 `BoardHeader` 展示）：**项目任务看板**
- 三列看板：**待办**、**进行中**、**已完成**
- 顶部工具条：搜索 + 筛选 + 新建
- 点击任务卡片：右侧打开 `TaskDetailPanel`
- 整体风格：清爽 B 端风，卡片有阴影与圆角，优先级用彩色标签区分

---

## 数据模型

```json
{
  "tasks": [
    {
      "id": "t1",
      "title": "完成需求评审",
      "description": "整理本期范围并与产品确认。",
      "status": "todo",
      "priority": "high",
      "assignee": "张三",
      "dueDate": "2026-06-15",
      "tags": ["需求", "评审"],
      "updatedAt": "2026-06-01T10:00:00.000Z"
    }
  ],
  "assignees": ["张三", "李四", "王五"]
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | `"todo" \| "doing" \| "done"` | 看板列 |
| `priority` | `"low" \| "medium" \| "high"` | 优先级 |
| `assignee` | string | 负责人，来自 `assignees` 列表 |
| `dueDate` | string | `YYYY-MM-DD`，可空 |
| `tags` | string[] | 最多展示 3 个标签 |

- 首次打开（无数据）时写入 **3 条示例任务**，分别落在 todo / doing / done 各至少 1 条
- 任意增删改后写回 localStorage

---

## 功能范围（本期必须实现）

### 1. BoardHeader

- 展示标题 **项目任务看板**
- 展示统计：`共 N 项任务`（N 为当前筛选后的数量）
- 按钮 **新建任务**：打开 `TaskFormModal`（新建模式）

### 2. FilterToolbar

- 搜索框：`placeholder` **搜索任务标题**
- 负责人下拉：全部 + `assignees` 各项
- 优先级下拉：全部 / 低 / 中 / 高
- 按钮 **清空筛选**：恢复默认
- 筛选逻辑：标题包含关键词 **且** 负责人匹配 **且** 优先级匹配（下拉选「全部」时不限制该项）

### 3. KanbanColumn（三列）

- 列配置：
  - 待办（status=todo，列头文案 **待办**）
  - 进行中（status=doing，列头文案 **进行中**）
  - 已完成（status=done，列头文案 **已完成**）
- 列头显示：`列名 (数量)`
- 列内渲染该状态下、且通过筛选的 `TaskCard` 列表
- 列空时显示：**本列暂无任务**

### 4. TaskCard

- 展示：标题（单行省略）、负责人、优先级标签（低=灰、中=橙、高=红）、截止日期（有则显示 `截止 YYYY-MM-DD`）
- 标签区：最多 3 个 `tags` 小标签
- 按钮：
  - **详情** → 主页面打开 `TaskDetailPanel` 并选中该任务
  - **左移** / **右移** → 在 todo→doing→done 间移动（已在边界则禁用对应按钮）
  - **删除** → 主页面确认，文案含 **确认删除该任务**

### 5. TaskFormModal（新建/编辑）

- 字段：标题（必填）、描述（多行）、负责人（下拉）、优先级（下拉）、截止日期（date）、状态（下拉）、标签（逗号分隔输入，保存时拆成数组）
- 按钮：**保存**、**取消**
- 标题为空时提示：**请输入任务标题**
- 保存后关闭弹窗并持久化

### 6. TaskDetailPanel（右侧侧栏）

- 未选中任务时不渲染或隐藏
- 展示选中任务全部字段；描述支持多行只读
- 快捷操作：
  - 下拉改 **状态**、改 **优先级**（变更后立即持久化）
  - 按钮 **编辑** → 打开 `TaskFormModal` 编辑模式
  - 按钮 **关闭** → 收起侧栏

### 7. 主页面布局（ProjectBoardPage）

- 结构建议：
  - 顶：`BoardHeader`
  - 次：`FilterToolbar`
  - 主体：左侧三列 `KanbanColumn` 横向排列；右侧 `TaskDetailPanel`（宽屏时并排，窄屏时侧栏可覆盖或下移，CSS 控制）
- 所有业务回调由主页面传入子组件 props（如 `onMoveTask`, `onDeleteTask`, `onSaveTask`）

### 8. 明确不做（本期省略）

- 拖拽排序（用左移/右移按钮即可）
- 后端 API、登录权限、评论、附件、甘特图
- 富文本编辑器

---

## 验收要点

- [ ] `src/pages/ProjectBoardPage.jsx` 存在，`export default function ProjectBoardPage`
- [ ] `src/components/` 下存在上述 6 个子组件文件，**未**内联在主页面
- [ ] 存在 `src/styles/kanban-board.css` 且被 import
- [ ] 三列看板、筛选、新建/编辑/删除、移动状态、详情侧栏均可操作
- [ ] 刷新后 localStorage 数据仍在
- [ ] `npm run dev` 可运行；`npm run build` 可通过

---

## 给代码生成阶段的提示

- **Step 1** 只生成 `ProjectBoardPage.jsx`（含 import 子组件与 css，子组件 UI 可先用占位或简单结构，但不得内联完整子组件实现）
- **Step 2** 生成 `src/components/*.jsx`
- **Step 3** 跳过（无 REST API）
- **Step 4** 生成 `src/styles/kanban-board.css`（及主页面已 import 的其它 css 如有）
