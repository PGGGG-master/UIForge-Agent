# 商品列表页面需求（强制子组件拆分）

实现一个纯前端的**商品列表管理**页面（React 18 + Vite）。页面主组件命名为 **ProductListPage**。  
数据保存在浏览器 **localStorage**，键名 `product-list-mvp`。**不调用后端 API**，不需要 MSW。

---

## 架构要求（必须遵守）

**本需求强制组件拆分，禁止把下列子组件内联写在主页面同一个文件里。**

- 主页面 `ProductListPage` **只负责**：状态管理、localStorage 读写、业务逻辑、布局编排
- 下列子组件 **必须** 各自独立为 `src/components/*.jsx`，由主页面通过 `import` 引用：

| 组件名 | 文件路径 | 职责 |
|--------|----------|------|
| `SearchBar` | `src/components/SearchBar.jsx` | 搜索框 + 分类筛选下拉 |
| `ProductCard` | `src/components/ProductCard.jsx` | 单条商品卡片（名称、价格、库存、编辑/删除按钮） |
| `ProductGrid` | `src/components/ProductGrid.jsx` | 商品网格列表，遍历渲染 `ProductCard` |
| `ProductFormModal` | `src/components/ProductFormModal.jsx` | 新增/编辑商品的弹窗表单 |

主页面中应出现类似：

```jsx
import SearchBar from '../components/SearchBar';
import ProductGrid from '../components/ProductGrid';
import ProductFormModal from '../components/ProductFormModal';
```

**不要**在 `ProductListPage.jsx` 里用 `function SearchBar()` 等方式内联定义子组件。

---

## 产品定位

- 页面标题：**商品管理**
- 顶部：`SearchBar` + **新增商品** 按钮（可放在主页面或 SearchBar 旁）
- 中部：`ProductGrid` 展示商品
- 点击新增/编辑：打开 `ProductFormModal`

---

## 功能范围

### 1. 数据与持久化

```json
{
  "products": [
    { "id": "1", "name": "示例商品", "price": 99.9, "stock": 10, "category": "数码" }
  ],
  "categories": ["数码", "家居", "食品"]
}
```

- 首次无数据时写入一条示例商品
- 增删改后写回 localStorage

### 2. SearchBar

- 关键词搜索（按商品名称包含匹配）
- 分类下拉筛选（全部 / 各 category）
- 通过 props 回调：`onSearchChange(query)`, `onCategoryChange(category)`

### 3. ProductCard

- 展示：名称、价格（¥）、库存、分类标签
- 按钮：**编辑**、**删除**（删除需主页面确认弹窗，文案含 **确认删除该商品**）

### 4. ProductGrid

- 无数据时显示：**暂无商品，点击新增**
- 有数据时网格布局展示多个 `ProductCard`

### 5. ProductFormModal

- 字段：名称（必填）、价格（数字）、库存（整数）、分类（下拉）
- 按钮：**保存**、**取消**
- 空名称时提示：**请输入商品名称**

### 6. 明确不做

- 后端 API、登录、分页、图片上传

---

## 验收要点

- [ ] `src/pages/ProductListPage.jsx` 存在且 `export default function ProductListPage`
- [ ] `src/components/` 下存在上述 4 个子组件文件
- [ ] 主页面通过 import 使用子组件，子组件未内联在主页面文件中
- [ ] `npm run dev` 可运行，能新增/编辑/删除/搜索/筛选商品
