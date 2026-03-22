# Intel Mac 下 PyTorch 依赖兼容性设计

- 日期：2026-03-21
- 项目：dataset_rag
- 主题：让 macOS x86_64（Intel Mac）本机可安装并尽量使用较新的 PyTorch 版本

## 背景

当前 `pyproject.toml` 中声明了：

- `torch>=2.10.0`
- `torchaudio>=2.10.0`
- `torchvision>=0.25.0`

但 PyTorch 官方自 2.3.0 起不再提供 macOS x86_64 wheel，因此当前 Intel Mac 环境在执行 `uv add` / `uv lock` / `uv sync` 时会因无法为当前平台解析 `torch>=2.10.0` 而失败。

## 目标

1. 保证当前 Intel Mac（macOS x86_64）可以在本机安装并运行项目。
2. 在满足兼容性的前提下，尽量接近较新的 PyTorch 版本。
3. 以最小改动修复当前依赖解析失败问题。

## 方案对比

### 方案 A：锁定到 Intel Mac 可用的最后一组官方兼容版本（推荐）

将三件套调整为官方匹配版本：

- `torch==2.2.2`
- `torchaudio==2.2.2`
- `torchvision==0.17.2`

并补充：

```toml
[tool.uv]
required-environments = [
  "sys_platform == 'darwin' and platform_machine == 'x86_64'"
]
```

优点：
- 改动最小
- 本机可安装可运行
- 版本组合有官方对应关系，风险较低

缺点：
- 无法继续使用 2.3+ 的新特性

### 方案 B：按平台拆分条件依赖

Intel Mac 使用 2.2.2，其它平台使用更高版本。

优点：
- 其它平台可以保持更高版本

缺点：
- 配置复杂度上升
- 增加跨平台测试与维护成本
- 容易出现环境不一致问题

### 方案 C：将 Torch 拆到可选依赖组

优点：
- 默认依赖安装更轻

缺点：
- 不满足“本机可安装并运行”目标

## 选型结论

采用**方案 A**。

原因：该方案最符合当前目标：在 Intel Mac 上获得真实可用的安装结果，并以最小复杂度修复 `uv` 解析失败问题。根据 PyTorch 官方信息，`torch 2.2.2` 是最后一代仍提供 macOS x86_64 wheel 的版本线，且与 `torchaudio 2.2.2`、`torchvision 0.17.2` 存在官方匹配关系。

## 具体修改

修改 `pyproject.toml`：

1. 将以下依赖调整为固定兼容版本：
   - `torch==2.2.2`
   - `torchaudio==2.2.2`
   - `torchvision==0.17.2`
2. 增加 `[tool.uv]` 配置并写入 `required-environments`

## 验证计划

修改后执行以下验证：

1. `uv lock`
2. `uv add loguru` 或确认依赖解析正常
3. 必要时执行最小导入验证，确认 `import torch` 成功

## 风险与边界

- 项目中若存在依赖 2.3+ 新特性的代码，后续可能需要额外适配。
- 该方案优先保证 Intel Mac 可用，不保证与其它平台保持最新版本一致。
- 若未来主开发环境迁移到 Apple Silicon 或 Linux，可再评估恢复更高版本。

## 用户确认

用户已确认采用本设计并执行修改。
