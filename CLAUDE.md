# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

基于 RAG（Retrieval-Augmented Generation）的数据集处理工具，支持 PDF 等格式文件的导入、解析与向量化。核心依赖 LangGraph 构建处理流水线。

## 常用命令

```bash
# 安装依赖（使用 uv）
uv sync

# 运行项目（示例入口，按实际调整）
python -m app
```

> 依赖管理：项目使用 `pyproject.toml` + `uv`，Python >= 3.11。

## 架构概览

### 整体流程

```
文件输入
  └─▶ validate_and_prepare   # 校验文件、注入默认参数
        └─▶ convert_pdf_to_md   # PDF → Markdown（当前为占位实现，待接入 marker/pymupdf4llm）
              └─▶ find_image_in_md_content   # 扫描 Markdown，提取本地图片引用
                    └─▶ END
```

所有节点共享 `GraphState`（TypedDict），通过 `{**state, ...}` 模式传递状态，不可变地叠加字段。

### 关键模块

| 路径 | 职责 |
|------|------|
| `app/import_process/agent/graph.py` | 用 LangGraph 组装并编译 DAG |
| `app/import_process/agent/state.py` | `GraphState` 定义，所有节点共享的状态结构 |
| `app/import_process/agent/nodes/` | 各处理节点，每个节点签名为 `(state: GraphState) -> GraphState` |
| `app/utils/logger.py` | 基于标准库 `logging` 的简单封装 |

### 上下文分块策略（`find_image_in_md_content`）

- 以**行**为单位，按 `chunk_size`（默认 50）**无重叠**切块
- 仅保留含本地图片引用（排除 `http` 链接）的 chunk
- 输出字段 `image_contexts: List[dict]`，每项含 `chunk_index`、`chunk_text`、`image_refs`

### 扩展约定

- 新增节点：在 `app/import_process/agent/nodes/` 下新建文件，在 `graph.py` 中注册
- 新增状态字段：在 `state.py` 的 `GraphState` 中声明（`total=False` 所有字段可选）
- `convert_pdf_to_md` 目前为占位实现，TODO 注释处接入真实转换库
