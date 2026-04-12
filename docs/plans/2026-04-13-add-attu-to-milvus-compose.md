# Add Attu To Milvus Compose Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在现有 Milvus Docker Compose 中追加 Attu 可视化客户端，保持与当前 Milvus 2.6.x 版本兼容。

**Architecture:** 继续复用当前 `docker/docker-compose.yml` 中的同一网络与服务编排，新增 `attu` 服务并通过内部服务地址 `standalone:19530` 连接 Milvus。对外仅新增 `8000` 端口用于浏览器访问，避免影响现有 Milvus、MinIO、etcd 端口。

**Tech Stack:** Docker Compose, Milvus Standalone, Attu

---

### Task 1: 记录兼容方案

**Files:**
- Create: `docs/plans/2026-04-13-add-attu-to-milvus-compose.md`
- Modify: `docker/docker-compose.yml`

**Step 1: 确认当前 compose 结构**

读取 `docker/docker-compose.yml`，确认现有服务为 `etcd`、`minio`、`standalone`。

**Step 2: 选择兼容的 Attu 镜像**

使用适配 Milvus 2.6.x 的 `zilliz/attu:v2.6.3`，避免引入 2.4 时代的老版本客户端。

### Task 2: 追加 Attu 服务

**Files:**
- Modify: `docker/docker-compose.yml`

**Step 1: 新增 `attu` 服务**

增加如下核心配置：

```yaml
  attu:
    container_name: milvus-attu
    image: zilliz/attu:v2.6.3
    ports:
      - "8000:3000"
    environment:
      MILVUS_URL: standalone:19530
    depends_on:
      - "standalone"
```

**Step 2: 保持最小改动**

不调整现有 Milvus、MinIO、etcd 的端口和卷挂载。

### Task 3: 配置级验证

**Files:**
- Modify: `docker/docker-compose.yml`

**Step 1: 校验 compose 文件**

运行：

```bash
docker compose -f "/Users/liuwx/Workspace/learning/dataset_rag/docker/docker-compose.yml" config
```

预期：配置可以成功展开，输出包含 `attu` 服务。

**Step 2: 给出启动入口**

运行：

```bash
cd "/Users/liuwx/Workspace/learning/dataset_rag/docker"
docker compose -p rag up -d
```

预期：若镜像拉取网络正常，`attu` 会和 `standalone` 一起归到 `rag` 分组中。
