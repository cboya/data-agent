# Windows 开发与运行指南

**推荐方式：** Windows + WSL2 Ubuntu + Docker Desktop  
**应用位置：** WSL2 Linux 文件系统  
**模型运行时：** Windows/WSL Ollama，或已配置的 OpenAI-compatible 远端服务

本文档说明如何在 Windows 上构建、启动和使用 Data Agent。当前仓库的主要开发入口
使用 POSIX Shell 语法，因此推荐在 WSL2 中运行仓库，而不是直接在 PowerShell 或 CMD
中运行 `Taskfile.yml`。

官方参考：

- [Microsoft：安装 WSL](https://learn.microsoft.com/windows/wsl/install)
- [Docker：WSL2 backend](https://docs.docker.com/desktop/features/wsl/)
- [Docker：在 WSL2 中开发](https://docs.docker.com/desktop/features/wsl/use-wsl/)
- [Ollama：Windows](https://docs.ollama.com/windows)
- [uv：安装](https://docs.astral.sh/uv/getting-started/installation/)
- [Task：安装](https://taskfile.dev/docs/installation)

## 1. 推荐拓扑

```text
Windows
├── Windows 浏览器
├── Docker Desktop（WSL2 backend）
├── Ollama（可选，Windows 原生或 WSL 内运行）
└── WSL2 Ubuntu
    ├── Git 工作区
    ├── uv / Python
    ├── Task
    ├── Data Agent API :8000
    └── docker compose CLI
        └── MySQL 8.4 :3306
```

如果选择 Cloudflare 等 OpenAI-compatible 远端模型，Windows 和 WSL 中都不需要运行
Ollama；Docker MySQL 仍用于默认的本地合成数据环境。

## 2. 系统要求

- 支持 WSL2 的 Windows 10 或 Windows 11；
- BIOS/UEFI 已启用硬件虚拟化；
- 建议至少 16 GiB 内存；
- Docker Desktop；
- 足够的磁盘空间容纳 Docker MySQL、Python 环境和可选的 Ollama 模型；
- 如果使用本地大模型，需要与模型体积匹配的内存/显存。

初次运行不建议使用 30B 模型。大型模型会明显增加下载空间、内存占用和单次请求
时间，但不会改变 Harness 的安全控制边界。

## 3. 安装 WSL2 Ubuntu

以管理员身份打开 PowerShell：

```powershell
wsl --install -d Ubuntu
```

安装完成后重启 Windows，打开 Ubuntu，并创建 Linux 用户。然后在 PowerShell 中检查：

```powershell
wsl --list --verbose
```

Ubuntu 的 `VERSION` 应为 `2`。必要时执行：

```powershell
wsl --set-version Ubuntu 2
wsl --update
```

如果 WSL 已安装但没有 Ubuntu，可以先查看可用发行版：

```powershell
wsl --list --online
```

## 4. 安装并配置 Docker Desktop

安装 Docker Desktop for Windows，启动后确认：

```text
Settings
→ General
→ Use the WSL 2 based engine
```

然后启用 Ubuntu 集成：

```text
Settings
→ Resources
→ WSL Integration
→ Ubuntu
→ Apply
```

在 Ubuntu 中验证：

```bash
docker version
docker compose version
```

不要同时在同一个 WSL 发行版中另外安装一套 Docker Engine。仓库应通过 Docker
Desktop 提供的 WSL 集成访问同一个 Docker daemon。

## 5. 在 WSL 中安装开发工具

以下命令都在 Ubuntu 中执行。

安装基础工具：

```bash
sudo apt update
sudo apt install -y git curl ca-certificates
```

安装 `uv`：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

重新打开 Ubuntu，或者加载安装器写入的环境：

```bash
source ~/.local/bin/env
```

安装仓库支持的 Python 版本：

```bash
uv python install 3.12
```

安装 Task：

```bash
sh -c "$(curl --location https://taskfile.dev/install.sh)" -- \
  -d -b ~/.local/bin
```

验证工具：

```bash
git --version
uv --version
task --version
docker --version
docker compose version
```

## 6. 克隆仓库

把仓库放在 WSL 的 Linux 文件系统中：

```bash
mkdir -p ~/Workspace
cd ~/Workspace
git clone https://github.com/cboya/data-agent.git
cd data-agent
```

如果仓库是私有的，需要先为该 Windows/WSL 用户配置 GitHub 访问权限。

不要优先使用：

```text
/mnt/c/Users/<name>/.../data-agent
```

Docker 官方建议 WSL2 开发工作区放在 Linux 文件系统内。这通常具有更好的文件系统
性能，也能减少 Windows/Unix 权限与换行符差异。

如需精确复现 Phase 2 冻结基线：

```bash
git switch --detach 6397a9a6872e8c887a097a8a5bcf59af5b51a0c2
```

该命令进入 detached HEAD，只适合复现。需要开发时应从最新 `main` 创建新分支。

## 7. 选择模型运行时

### 7.1 方案 A：Windows 原生 Ollama

安装 Ollama for Windows。正常安装后 Ollama 在 Windows 后台运行，并在
`http://localhost:11434` 提供 API。

在 Windows PowerShell 中拉取模型：

```powershell
ollama pull gemma4:latest
ollama pull qwen3-embedding:0.6b
```

`gemma4:latest` 是项目的初始本地参考 Chat 模型；它适合验证运行链路，但不代表
Product NL2SQL 行为已经通过验收。`qwen3-embedding:0.6b` 是轻量的本地 Embedding
参考模型。

在 WSL Ubuntu 中测试 Windows Ollama：

```bash
curl http://127.0.0.1:11434/api/version
```

如果成功，配置：

```ini
MODEL_RUNTIME_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CHAT_MODEL=gemma4:latest
OLLAMA_EMBED_MODEL=qwen3-embedding:0.6b
```

如果无法访问，依次尝试：

1. 更新 WSL：`wsl --update`；
2. 退出并重新启动 Windows Ollama；
3. 在 PowerShell 中执行 `wsl --shutdown`，再打开 Ubuntu；
4. 将 Ollama 与应用都放在 WSL 内运行；或
5. 改用 OpenAI-compatible 远端配置。

不要为了跨 WSL 访问而直接把无鉴权的 Ollama API 暴露到局域网。

### 7.2 方案 B：在 WSL 内运行 Ollama

这种方式让应用与模型共享同一个 Linux `localhost`，网络最直接。按 Ollama Linux
官方说明在 Ubuntu 中安装，然后在 Ubuntu 内拉取模型并保持服务运行。

配置仍然是：

```ini
MODEL_RUNTIME_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

不要同时在 Windows 和 WSL 各维护一套不必要的模型副本。

### 7.3 方案 C：OpenAI-compatible 远端服务

没有合适 GPU 时，可以使用仓库已验证的远端适配器。以 Cloudflare Workers AI 为例：

```ini
MODEL_RUNTIME_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_BASE_URL=https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1
OPENAI_COMPATIBLE_IDENTITY_PROFILE=cloudflare_workers_ai
OPENAI_COMPATIBLE_API_KEY=<YOUR_API_TOKEN>
OPENAI_COMPATIBLE_CHAT_MODEL=@cf/meta/llama-3.3-70b-instruct-fp8-fast
OPENAI_COMPATIBLE_EMBED_MODEL=@cf/baai/bge-m3
```

每个使用者必须提供自己的账号和密钥。不要共享、提交或截图传播 `.env`。远端
`ALIAS_ONLY` 模型身份可以用于可移植性和诊断，但不能单独授权 Product acceptance。

## 8. 创建 `.env`

在仓库目录执行：

```bash
cp .env.example .env
```

本地 Ollama + 本地合成 MySQL 的最小关键配置：

```ini
MODEL_RUNTIME_PROVIDER=ollama

OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CHAT_MODEL=gemma4:latest
OLLAMA_EMBED_MODEL=qwen3-embedding:0.6b

APP_HOST=127.0.0.1
APP_PORT=8000

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=data_agent
MYSQL_READONLY_USER=data_agent_reader
MYSQL_READONLY_PASSWORD=<LOCAL_READER_PASSWORD>

MYSQL_CONTROL_HOST=127.0.0.1
MYSQL_CONTROL_PORT=3306
MYSQL_CONTROL_DATABASE=data_agent_control
MYSQL_CONTROL_USER=data_agent_control
MYSQL_CONTROL_PASSWORD=<LOCAL_CONTROL_PASSWORD>

MYSQL_ROOT_PASSWORD=<LOCAL_ROOT_PASSWORD>
```

`.env` 已被 `.gitignore` 排除。任何密码和远端 API Key 都只能存在于本地环境或正式
的 secret manager 中。

如果 Windows 或 WSL 已有 MySQL 占用 `3306`，可以把本项目改为：

```ini
MYSQL_PORT=3307
MYSQL_CONTROL_PORT=3307
```

两个端口必须一起修改，因为默认本地分析库和控制库位于同一个 Docker MySQL 实例。

## 9. 初始化环境

确认以下服务已就绪：

- Docker Desktop 正在运行；
- 选择 Ollama 时，Ollama API 可以从 WSL 访问；
- 选择远端模型时，WSL 可以访问对应 HTTPS endpoint。

执行：

```bash
task bootstrap
```

Bootstrap 会：

1. 安装锁定的 Python 环境；
2. 启动 Docker MySQL 8.4；
3. 执行控制库迁移；
4. 创建并验证隔离的只读/控制账号；
5. 灌入确定性合成数据；
6. 生成 Schema/Catalog；
7. 调用 Embedding 模型构建检索索引。

完成后可运行：

```bash
task quality
```

完整 `task eval` 会运行冻结的评估套件并产生较多模型调用。普通首次体验不需要先
运行它，而且当前冻结的 Product behavioral verdict 本身就是 `REJECTED`。

## 10. 启动 API

```bash
task dev
```

在 WSL 内验证：

```bash
curl http://127.0.0.1:8000/health
```

预期返回：

```json
{
  "status": "ok"
}
```

然后在 Windows 浏览器中打开：

- Swagger UI：<http://127.0.0.1:8000/docs>
- ReDoc：<http://127.0.0.1:8000/redoc>

接口使用方式见 [`API.md`](API.md)。

## 11. 第一次 API 调用

在 WSL 中创建 Session：

```bash
curl -X POST http://127.0.0.1:8000/sessions
```

复制响应里的 `id`，然后提交消息：

```bash
curl -X POST \
  http://127.0.0.1:8000/sessions/<SESSION_ID>/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"请按天统计最近30天实际支付金额"}'
```

这个消息调用不会启动 Ollama。它会使用已经运行并在应用启动时绑定的模型运行时。

## 12. 常见问题

### 12.1 WSL 中没有 `docker` 命令

确认 Docker Desktop 已启动，并在：

```text
Settings → Resources → WSL Integration
```

启用了当前 Ubuntu 发行版。如果 Docker Desktop 正处于 Windows Containers 模式，切换
回 Linux Containers。

### 12.2 MySQL 端口冲突

检查：

```powershell
Get-NetTCPConnection -LocalPort 3306 -ErrorAction SilentlyContinue
```

如果端口已被占用，将 `.env` 中的 `MYSQL_PORT` 和 `MYSQL_CONTROL_PORT` 一起改为
`3307`，然后重新运行 `task bootstrap`。

### 12.3 WSL 访问不到 Windows Ollama

先在 Windows PowerShell 测试：

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/version
```

再在 WSL 测试：

```bash
curl http://127.0.0.1:11434/api/version
```

如果只有 Windows 成功，更新/重启 WSL 与 Ollama。仍不稳定时，优先让 Ollama 与应用
运行在同一个 WSL 网络空间，或使用远端模型；不要关闭安全边界来换取连通性。

### 12.4 Windows 浏览器打不开端口 8000

先确认 WSL 内：

```bash
curl http://127.0.0.1:8000/health
```

如果 WSL 内成功，执行 `wsl --update` 和 `wsl --shutdown` 后重试。不要轻易把
`APP_HOST` 改为 `0.0.0.0`：当前 API 没有 HTTP 鉴权，这可能把服务暴露给局域网。

### 12.5 模型很慢或内存不足

- 不要以 30B 模型作为首次启动条件；
- 使用较小的本地 Chat 模型验证控制链路；
- 保留轻量 Embedding 模型；
- 或使用审核过的远端模型配置。

较小模型可能降低 NL2SQL 行为质量，但 SQL Guard、只读权限、资源限制和结果验证不会
因此放宽。

### 12.6 仓库位于 `/mnt/c` 时很慢

将仓库重新克隆到：

```text
~/Workspace/data-agent
```

可以在 Windows 文件资源管理器地址栏中通过以下路径访问：

```text
\\wsl$\Ubuntu\home\<linux-user>\Workspace\data-agent
```

不要在 Windows Git 和 WSL Git 之间交替维护同一个 working tree。

## 13. 重置

需要重建本地生成状态时：

```bash
task reset
task bootstrap
```

`task reset` 会清理可重建的本地数据库/索引状态，但不会删除受版本控制的 curated
Catalog 文件。

## 14. 安全边界

- 默认保持 `APP_HOST=127.0.0.1`；
- 不直接把 API、Ollama 或 MySQL 暴露到局域网/互联网；
- 不向模型或 API 请求传递数据库凭据；
- 不提交 `.env`；
- 不用管理员数据库账号运行查询；
- 不绕过 SQL Guard、EXPLAIN 或 verification；
- 当前实现是架构与受控 Harness 基线，不是已通过行为验收的 Product release。

如果需要部署给其他用户访问，应在新的明确授权范围内补充认证、授权、TLS、限流、
审计和部署边界，而不是直接改变本地监听地址。
