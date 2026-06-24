<p align="center">
  <h1 align="center">🤖 nanoAgent</h1>
  <p align="center">
    轻量级 AI Agent —— 自动诊断与修复代码仓库
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
  <img src="https://img.shields.io/badge/stability-experimental-orange" alt="Stability" />
</p>

---

## 📖 简介

nanoAgent 是一个轻量级 AI Agent 原型，能够自动拉取 GitHub 仓库，分析代码结构，定位问题根因，
并在隔离环境中执行修复与验证。核心思路是 **让 LLM 自己动手** —— 给它工具，让它在一个可控的
循环里反复观察、思考、执行，直到任务完成。

与常见的"一次性问答"不同，nanoAgent 会：

- 🔍 主动探索仓库结构，搜索关键代码
- 🧪 复现测试失败，对比预期行为
- ✏️ 精准修改源码，而非弱化测试
- 🔄 遇到错误自动重试，上下文过长自动压缩
- 📋 最终提交一份结构化的修复报告

当前阶段：带工具使用的受控循环，支持运行持久化、缓存友好的 Prompt 设计，以及一层子 Agent 委托。

---

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| 🧠 **Tool-Use 循环** | LLM 请求工具 → 执行工具 → 结果回填 → 继续推理，直到任务完成 |
| 🔧 **丰富的内置工具** | 克隆仓库、文件读写、Grep 搜索、Shell 命令、代码编辑、任务管理 |
| 📦 **隔离执行环境** | 每次运行独立 venv，沙箱化的 HOME / TMPDIR / 缓存目录 |
| 🗜️ **多层上下文压缩** | 结果裁剪 → Snip → Micro → LLM 摘要 → 应急压缩，五层递进 |
| 🔄 **弹性错误恢复** | 瞬态故障指数退避重试、输出截断自动续写、无效工具调用主动纠正 |
| 🔌 **可扩展架构** | Hook 机制支持权限、审计、指标采集、技能注入等自定义扩展点 |
| 👥 **子 Agent 委托** | 支持同步/后台任务委派，最多 2 个并发只读子 Agent |
| 📋 **持久化任务管理** | 支持任务依赖（blocked_by）、生命周期追踪、与后台 Job 联动 |
| 📝 **结构化报告** | 每次运行生成 report.md，包含问题、根因、修改文件、验证摘要、残留风险 |
| 🎯 **按需技能激活** | 内置 Python / Node / Django / GitHub Actions 领域技能，模型自主决定何时激活 |

---

## 🚀 快速开始

### 前置要求

- Python ≥ 3.11
- DeepSeek API Key（[申请地址](https://platform.deepseek.com)）

### 安装

```bash
git clone <repo-url> && cd nanoAgent

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
```

编辑 `.env`：

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
```

### 运行

```bash
# 基本用法：诊断并修复一个仓库
python -m nano_agent.cli run https://github.com/user/repo \
  "修复 test_login 相关的测试失败"

# 允许写入和命令执行
python -m nano_agent.cli run https://github.com/user/repo \
  "重构 utils.py 中的异常处理" \
  --allow-write --allow-command

# 自定义步数和超时
python -m nano_agent.cli run https://github.com/user/repo \
  "运行完整测试套件，修复所有失败用例" \
  --max-steps 200 --background-idle-wait-timeout 120
```

运行结束后，终端会显示执行摘要，详细报告保存在 `.nano/runs/<run_id>/report.md`。

---

## 📁 项目结构

```
nano_agent/
├── agent.py              # 顶层入口，组装各类组件并启动循环
├── loop.py               # 核心 Tool-Use 循环引擎
├── cli.py                # Typer CLI 命令行入口
├── config.py             # AgentConfig——全局配置模型
├── models.py             # 数据模型：消息、响应、运行状态等
├── workspace.py          # 管理工作区隔离和运行摘要
├── tools/                # 运行时工具集
│   ├── base.py           #   RuntimeTool 抽象基类 + ToolRegistry
│   ├── clone_repo.py     #   仓库克隆
│   ├── list_files.py     #   目录浏览
│   ├── grep.py           #   代码搜索
│   ├── read_file.py      #   文件读取
│   ├── edit_file.py      #   文件编辑
│   ├── run_command.py    #   Shell 命令
│   ├── finish_run.py     #   终止协议
│   ├── todo.py           #   短生命周期清单
│   ├── activate_skill.py #   技能激活
│   ├── delegate_task.py  #   子 Agent 委托
│   └── tasks.py          #   持久化任务 CRUD
├── services/             # LLM 服务层
│   ├── llm.py            #   LLMClient Protocol + 测试用脚本客户端
│   ├── openai_compatible.py  # OpenAI 兼容客户端（DeepSeek）
│   ├── errors.py         #   错误分类与标准化
│   ├── retry.py          #   指数退避重试策略
│   └── registry.py       #   Provider 注册与工厂
├── hooks/                # 扩展点（Hook 机制）
│   ├── base.py           #   AgentHook Protocol
│   ├── permission.py     #   权限拦截
│   ├── console.py        #   终端进度展示
│   ├── llm_metrics.py    #   LLM 调用指标记录
│   ├── audit.py          #   工具调用审计
│   └── skill_activation.py   # 技能激活注入
├── context/              # 上下文压缩
│   ├── compactor.py      #   五层压缩管线 + 持久化存储
│   └── state.py          #   压缩状态构建器
├── subagents/            # 子 Agent 系统
│   ├── manager.py        #   子 Agent 创建与同步执行
│   ├── context.py        #   子 Agent 上下文构建
│   ├── models.py         #   子 Agent 数据模型
│   └── store.py          #   子 Agent 状态持久化
├── background/           # 后台作业调度
│   ├── supervisor.py     #   线程池调度器
│   ├── hook.py           #   完成通知 Hook
│   ├── cancellation.py   #   协作式取消
│   └── store.py          #   Job 快照持久化
├── tasks/                # 持久化任务管理
│   ├── service.py        #   任务生命周期服务
│   ├── store.py          #   任务文件存储
│   └── models.py         #   任务数据模型
├── prompts/              # Prompt 装配
│   ├── assembler.py      #   组装初始对话
│   └── templates/        #   Markdown 提示词模板
│       ├── core.md       #     稳定核心提示词（缓存友好）
│       └── repository_design.md  # 任务模板
├── skills/               # 领域知识技能
│   ├── registry.py       #   技能注册与发现
│   ├── session.py        #   技能激活会话
│   └── builtin/          #   内置技能（Python/Node/Django/GitHub Actions）
├── memory/               # 跨运行记忆
│   └── store.py          #   JSONL 记忆存储
├── runtime/              # 执行环境隔离
│   └── environment.py    #   虚拟环境创建与 PATH 管理
└── persistence/          # 文件持久化
    ├── message_store.py  #   消息流存储
    ├── config_store.py   #   配置快照
    ├── prompt_store.py   #   Prompt 元数据
    ├── report_store.py   #   报告渲染
    └── summary_store.py  #   运行摘要存储
```

---

## ⚙️ 高级配置

所有配置通过 `AgentConfig` 管理，CLI 参数会覆盖默认值。以下是关键配置项：

### 上下文与 Token

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `context_max_input_tokens` | 256,000 | 输入 token 预算上限 |
| `context_auto_compact_ratio` | 0.8 | 达到该比例时触发自动压缩 |
| `max_auto_compactions` | 3 | 单次运行最多自动压缩次数 |
| `tool_result_budget_chars` | 32,000 | 单轮工具结果字符预算 |
| `snip_keep_head` / `snip_keep_tail` | 8 / 32 | Snip 压缩保留的头/尾消息数 |

### 子 Agent

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `subagent_max_steps` | 50 | 子 Agent 最大循环步数 |
| `subagent_max_llm_calls` | 75 | 子 Agent LLM 调用预算 |
| `subagent_max_result_chars` | 16,000 | 子 Agent 回传结果上限 |
| `background_max_workers` | 2 | 后台子 Agent 最大并发数 |
| `background_max_jobs` | 8 | 同时存在的非终态 Job 上限 |

### 错误恢复

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `llm_max_transient_retries` | 4 | 瞬态故障最大重试次数 |
| `llm_retry_base_seconds` | 5.0 | 指数退避基础等待秒数 |
| `llm_retry_max_seconds` | 60.0 | 本地退避最大等待秒数 |
| `llm_max_continuations` | 2 | 输出截断后最大续写次数 |

完整配置参见 `nano_agent/config.py`。

---

## 🧪 开发

```bash
# 运行所有测试
pytest

# 运行单个测试文件
pytest tests/test_agent_loop.py

# 运行匹配关键词的测试
pytest -k "compaction"

# 代码检查
ruff check .
```

### 测试模式

测试使用 Mock LLM 客户端（如 `OneToolUseLLM`、`ScriptedMvpLLMClient`）来模拟确定性的
模型响应，无需实际 API 调用。测试文件与源码模块一一对应，放在 `tests/` 目录下。

### 运行产物

每次 run 的产物保存在 `.nano/runs/<run_id>/`：

```
.nano/runs/20240601120000/
├── summary.json              # 结构化运行摘要
├── messages.jsonl            # 完整对话协议流（追加写入）
├── promt.json                # 初始 Prompt 装配元数据
├── report.md                 # 结构化最终报告
├── llm_calls.jsonl           # LLM 调用详情（可选）
├── audit.jsonl               # 工具调用审计记录（可选）
├── context_checkpoint.json   # 最新活动上下文快照（可选）
├── compactions.jsonl         # 压缩事件记录
├── tasks/                    # 持久化任务快照
├── subagents/                # 子 Agent 执行产物
├── tool-results/             # 持久化的大型工具结果
└── transcripts/              # 压缩前的完整对话副本
```

---

## 🔄 核心工作流

```
用户请求 → Prompt 装配 → LLM 调用
                ↑            ↓
          上下文压缩     Tool Use?
                ↑         ↓ 是     否 → finish_run → report.md
          工具结果 ← 执行工具
                ↓
         消息历史追加 → 下一轮 LLM 调用
```

1. **Prompt 装配**：稳定核心提示词 + 技能目录 + 参考记忆 + 用户任务
2. **LLM 推理**：如果模型返回 `tool_use`，解析需要调用的工具和参数
3. **Hook 前置处理**：权限检查、审计记录
4. **工具执行**：在隔离环境中执行工具，捕获结果
5. **Hook 后置处理**：指标记录、进度刷新
6. **上下文压缩**：如果上下文接近 token 上限，逐层压缩
7. **结果回填**：工具结果注入对话历史，继续下一轮
8. **终止**：模型调用 `finish_run` 提交结构化报告

---

## 🎯 设计原则

- **证据驱动**：所有结论需有工具输出佐证，不凭空猜测
- **最小改动**：只修改根因相关的代码，不做无关重构
- **可验证**：每次修改后必须有测试或命令输出来验证
- **渐进降级**：上下文过长时逐层压缩，而非直接截断
- **弹性应对**：网络抖动、模型过载、输出截断等情况都有对应的恢复策略

---

## ⚠️ 当前局限

- 仅支持 DeepSeek 作为 LLM Provider（基于 OpenAI 兼容协议）
- 子 Agent 只允许一层委托（子 Agent 不可再创建子 Agent）
- Token 估算使用保守的字符比例，不使用真 tokenizer
- 缓存行为取决于 Provider 的具体实现
- 后台任务无进程重启恢复能力

---

## 📄 License

MIT
