<p align="center">
  <h1 align="center">🤖 nanoAgent</h1>
  <p align="center">
    轻量级异步 Coding Agent，用于诊断、修复代码仓库并接入外部工具。
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B%20%7C%20CI%203.13-blue?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
  <img src="https://img.shields.io/badge/stability-experimental-orange" alt="Stability" />
</p>

---

## 📖 项目简介

nanoAgent 是一个实验性 Coding Agent。它可以克隆 Git 仓库，探索代码，调用工具定位问题，执行小范围修复，验证结果，并生成结构化运行报告。

当前核心运行时已经完成 async 化：LLM 调用、工具、Hook、子进程、任务状态、后台子 Agent 和 MCP session 均通过 async 接口协作。

## ✨ 核心特性

| 特性 | 说明 |
| --- | --- |
| 🧠 Tool-use 循环 | LLM 请求工具，nanoAgent 执行工具，并按原始顺序回填结果。 |
| 🔧 内置工具 | 仓库、文件、搜索、命令、编辑、任务和子 Agent 委派工具。 |
| ⚡ 异步运行时 | LLM 调用、工具、Hook、子进程、任务状态、子 Agent 和 MCP session 均走 async 接口。 |
| 📦 隔离运行 | 每次运行拥有独立 workspace 和 run-local 执行环境。 |
| 🗜️ 上下文压缩 | 长任务通过多层压缩控制模型输入预算。 |
| 👥 后台子 Agent | 只读子 Agent 以有界 `asyncio.Task` 后台 Job 运行。 |
| 🌐 MCP 接入 | 可选 MCP runtime，并内置 GitHub MCP provider。 |
| 📝 运行产物 | 报告、消息、指标、审计、任务和子 Agent 产物保存到 `.nano/runs/<run_id>/`。 |

## 🚀 快速开始

```bash
git clone <repo-url> && cd nanoAgent

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

cp .env.example .env
```

编辑 `.env`：

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

运行：

```bash
nano-agent run https://github.com/user/repo \
  "修复 test_login.py 中失败的测试" \
  --allow-write --allow-command
```

最终报告会写入 `.nano/runs/<run_id>/report.md`。

## 🌐 GitHub MCP

GitHub MCP 是可选功能，默认关闭。启用前配置：

```env
GITHUB_MCP_DOCKER_IMAGE=ghcr.io/github/github-mcp-server
GITHUB_PERSONAL_ACCESS_TOKEN=your_github_personal_access_token
GITHUB_TOOLSETS=context,repos,issues,pull_requests
GITHUB_READ_ONLY=1
```

然后运行：

```bash
nano-agent run https://github.com/user/repo \
  "修改代码前先搜索相关 GitHub issue" \
  --mcp-github
```

## 📚 文档

- [快速开始](docs/getting-started.md)
- [架构说明](docs/architecture.md)
- [MCP 接入](docs/mcp.md)
- [安全模型](docs/security.md)
- [开发指南](docs/development.md)

英文文档：[README.md](README.md)

## ⚠️ 当前限制

- 内置 LLM provider 目前只有 DeepSeek。
- 子 Agent 只允许一层委派。
- CLI 当前只暴露 GitHub MCP provider。
- Token 估算使用保守字符比例，不使用 provider tokenizer。
- 后台 Job 暂不支持进程重启恢复。

## 📄 License

MIT
