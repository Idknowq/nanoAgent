# nanoAgent 开发流程

## 1. 项目定位

`nanoAgent` 是一个面向 AI Agent 岗位实习简历的学习型工程项目。项目不追求一开始做成大型完整平台，而是通过可运行的最小闭环，逐步展示对 Agent 机制的理解和工程化能力。

核心目标：

用户输入一个 GitHub 仓库地址，Agent 自动完成以下流程：

1. clone 仓库到隔离工作区。
2. 阅读 README 和关键配置文件。
3. 识别技术栈、包管理器、测试命令和项目结构。
4. 安装依赖。
5. 运行测试或基础检查。
6. 分析失败原因。
7. 生成修复建议或小范围 patch。
8. 等待用户 approve。
9. 执行修复。
10. 再次测试。
11. 输出结果摘要，并为后续 PR 流程预留接口。

MVP 阶段优先实现单 Agent 完整闭环。后续再逐步引入工具注册、权限管理、上下文压缩、任务系统、多 Agent 协同、记忆、技能、MCP 等机制。

## 2. 设计原则

### 2.1 先闭环，后抽象

MVP 的重点不是架构完整，而是证明 Agent 可以围绕真实仓库完成一次可验证的开发任务。不要过早设计复杂插件系统、多 Agent 调度系统或长期记忆系统。

建议顺序：

1. 先写死必要工具和流程。
2. 跑通 1 到 2 个可控测试仓库。
3. 再把重复逻辑抽象为工具、任务、权限和上下文模块。

### 2.2 所有关键行为可观测

Agent 的价值不只在于最终 patch，也在于它如何阅读、判断、执行和恢复。因此每个阶段都应该产生结构化记录。

至少记录：

- 当前任务阶段。
- 调用的工具。
- 工具输入摘要。
- 工具输出摘要。
- Agent 的判断依据。
- 是否需要用户授权。
- 最终状态：成功、失败、需要人工处理。

### 2.3 默认保守执行

涉及外部仓库、依赖安装、命令执行、文件修改、推送 PR 等操作时，默认采用保守策略。

MVP 阶段建议：

- clone 到临时工作区，不直接污染主项目目录。
- 只允许执行白名单命令。
- 文件修改前展示 patch。
- 用户 approve 后才写入。
- 不自动 push。
- 不处理高风险命令，例如删除系统文件、修改全局配置、执行未知脚本。

## 3. 推荐技术栈

考虑项目目标和迭代速度，建议优先使用 Python 实现。

推荐栈：

- Python 3.11+
- `typer` 或 `argparse`：命令行入口。
- `pydantic`：结构化任务状态、工具输入输出、配置。
- `gitpython` 或直接调用 `git` CLI：仓库操作。
- `subprocess`：命令执行工具。
- `rich`：终端输出和日志展示。
- `pytest`：自身项目测试。
- OpenAI / Anthropic / 本地模型 SDK：LLM 调用层，保持可替换。

初期不建议引入 Web UI。CLI 更适合作为 Agent 机制原型，工程成本低，行为更容易调试。

## 4. MVP 功能拆分

### 4.1 CLI 入口

目标：

```bash
nano-agent run https://github.com/example/repo
```

MVP 可支持参数：

```bash
nano-agent run <repo_url> --workdir .nano/workspaces --max-steps 20
```

输出内容：

- 仓库基本信息。
- 识别出的技术栈。
- 执行过的命令。
- 测试结果。
- 失败分析。
- 建议 patch。
- 是否等待用户确认。

### 4.2 工作区管理

职责：

- 为每个任务创建独立目录。
- clone 目标仓库。
- 记录当前 commit hash。
- 后续所有命令都限制在该工作区内执行。

建议目录：

```text
.nano/
  workspaces/
    <repo-name>-<timestamp>/
  runs/
    <run-id>.json
```

### 4.3 仓库理解

Agent 需要先读取有限但高价值的文件，而不是盲目扫描全仓库。

优先读取：

- `README.md`
- `package.json`
- `pyproject.toml`
- `requirements.txt`
- `pom.xml`
- `build.gradle`
- `Cargo.toml`
- `go.mod`
- `.github/workflows/*`

MVP 输出结构：

```json
{
  "language": "python",
  "package_manager": "pip",
  "install_command": "pip install -r requirements.txt",
  "test_command": "pytest",
  "confidence": "medium"
}
```

### 4.4 命令执行工具

MVP 阶段先实现一个通用 Shell 工具，但必须加限制。

限制策略：

- 只能在工作区内执行。
- 命令有超时时间。
- 捕获 stdout、stderr、exit code。
- 默认不允许交互式命令。
- 高风险命令进入拒绝或人工确认。

命令执行结果结构：

```json
{
  "command": "pytest",
  "exit_code": 1,
  "stdout_tail": "...",
  "stderr_tail": "...",
  "duration_seconds": 12.4
}
```

### 4.5 测试失败分析

失败分析不要求一次准确修复所有问题。MVP 要求 Agent 能做到：

1. 判断安装失败、测试失败、命令不存在、环境缺失等基本类别。
2. 提取关键错误信息。
3. 定位可能相关文件。
4. 给出小范围修改建议。

初期可以只支持典型 Python / Node.js 项目。

### 4.6 Patch 生成与审批

MVP 阶段建议先生成 unified diff，而不是直接改文件。

流程：

1. Agent 生成修复方案。
2. 展示变更摘要和 diff。
3. 用户输入 `y` 后执行。
4. 写入文件。
5. 再次运行测试。

注意：审批机制是简历亮点之一。即使实现简单，也能体现 Agent 权限管理意识。

## 5. MVP 开发顺序

### 阶段 0：项目骨架

目标：

- 初始化 Python 包结构。
- 建立 CLI。
- 建立基本配置和日志。
- 建立测试框架。

建议结构：

```text
nanoAgent/
  nano_agent/
    __init__.py
    cli.py
    agent.py
    config.py
    workspace.py
    tools/
      __init__.py
      shell.py
      git.py
    prompts/
      repo_analysis.md
      failure_analysis.md
      patch_plan.md
  tests/
  docs/
  pyproject.toml
  README.md
```

### 阶段 1：固定流程单 Agent

先不用复杂 planner，直接写一个确定性 pipeline：

1. clone repository。
2. inspect files。
3. infer stack。
4. install dependencies。
5. run tests。
6. ask LLM to analyze failure。
7. ask LLM to propose patch。
8. ask user approve。
9. apply patch。
10. rerun tests。

这一阶段的关键是端到端跑通。

### 阶段 2：工具接口抽象

当固定流程可运行后，再抽象工具层。

工具接口建议包含：

```python
class Tool:
    name: str
    description: str
    input_schema: type
    requires_approval: bool

    def run(self, input):
        ...
```

优先抽象：

- `clone_repo`
- `read_file`
- `list_files`
- `run_command`
- `apply_patch`
- `git_diff`

### 阶段 3：任务状态与 todo list

引入任务状态机，让 Agent 的执行过程可恢复、可展示。

任务状态示例：

```text
pending -> running -> waiting_approval -> running -> succeeded
pending -> running -> failed
```

todo item 示例：

```json
{
  "id": "run-tests",
  "title": "Run project tests",
  "status": "completed",
  "evidence": "pytest exited with code 1"
}
```

### 阶段 4：权限管理

从简单 approve 扩展为权限策略。

权限级别：

- `read`: 读取文件、列目录。
- `execute_safe`: 执行白名单命令。
- `execute_risky`: 安装依赖、运行项目脚本。
- `write`: 修改文件。
- `network`: clone、下载依赖。
- `publish`: push branch、create PR。

MVP 后优先实现：

- 工具级 `requires_approval`。
- 命令黑白名单。
- 用户一次性授权和单次授权。

### 阶段 5：上下文压缩

当仓库较大或命令输出较长时，引入上下文压缩。

压缩对象：

- README 摘要。
- 文件树摘要。
- 测试失败摘要。
- 已读文件摘要。
- 历史工具调用摘要。

压缩产物需要保留：

- 关键事实。
- 文件路径。
- 错误信息。
- 已执行动作。
- 当前假设。

### 阶段 6：Skill 机制

把不同技术栈的处理经验沉淀为 skill。

示例：

```text
skills/
  python.md
  node.md
  java-maven.md
  github-actions.md
```

Skill 内容可以包括：

- 常见项目文件。
- 安装命令判断规则。
- 测试命令判断规则。
- 常见失败模式。
- 修复建议模板。

### 阶段 7：Memory 机制

Memory 不应一开始做复杂。先做项目级短期记忆。

建议类型：

- `repo_memory`: 当前仓库已知事实。
- `run_memory`: 当前任务执行历史。
- `failure_memory`: 失败模式和修复尝试。
- `user_preference`: 用户授权偏好和输出偏好。

### 阶段 8：Subagent 与多 Agent

在单 Agent 可用后，再拆分角色。

候选 subagent：

- `RepoReaderAgent`: 阅读仓库，提炼结构和技术栈。
- `TestRunnerAgent`: 安装依赖并运行测试。
- `DebugAgent`: 分析失败原因。
- `PatchAgent`: 生成小范围 patch。
- `ReviewAgent`: 检查 patch 风险。

不要过早引入多 Agent。多 Agent 应该解决真实复杂度，而不是作为形式展示。

### 阶段 9：MCP 接入

MCP 应作为外部工具接入层，而不是 MVP 核心。

可接入方向：

- GitHub MCP：创建 issue、读取 PR、提交 PR。
- 文件系统 MCP：标准化文件访问。
- 浏览器 MCP：查看项目文档或 Web 测试页面。
- 数据库 MCP：未来支持数据库项目诊断。

## 6. Prompt 设计

MVP 至少需要三类 prompt。

### 6.1 仓库分析 Prompt

输入：

- README。
- 文件树。
- 关键配置文件内容。

输出：

- 技术栈。
- 安装命令。
- 测试命令。
- 置信度。
- 需要进一步读取的文件。

### 6.2 失败分析 Prompt

输入：

- 执行命令。
- exit code。
- stdout/stderr 摘要。
- 相关文件内容。

输出：

- 失败类别。
- 可能原因。
- 证据。
- 建议读取文件。
- 是否适合自动修复。

### 6.3 Patch 计划 Prompt

输入：

- 失败分析。
- 相关源文件。
- 项目约束。

输出：

- 修改目标。
- 影响范围。
- diff。
- 风险。
- 需要重新运行的验证命令。

## 7. 简历表达重点

项目实现过程中应刻意保留可展示的机制，而不是只写一个脚本。

可写入简历的点：

- 实现一个面向 GitHub 仓库自动诊断与修复的轻量级 AI Agent。
- 设计工具调用层，支持仓库 clone、文件读取、命令执行、patch 应用等工具。
- 实现命令执行权限控制和人工审批机制，降低自动修改代码的风险。
- 设计任务状态机和 todo list，记录 Agent 执行过程和中间判断。
- 通过上下文压缩管理 README、测试日志、文件树和工具调用历史。
- 支持按技术栈扩展 skill，提高不同项目类型下的诊断能力。
- 规划 subagent 架构，将仓库理解、测试执行、失败分析、patch 生成和审查拆分为独立角色。

## 8. 验收标准

MVP 完成时，至少满足：

1. 可以通过 CLI 输入 GitHub 仓库地址。
2. 可以 clone 到隔离工作区。
3. 可以读取 README 和配置文件。
4. 可以识别至少 Python 或 Node.js 其中一种技术栈。
5. 可以安装依赖并运行测试命令。
6. 可以捕获失败日志并生成结构化失败分析。
7. 可以生成小范围 patch 方案。
8. 修改文件前必须经过用户确认。
9. 修改后可以重新运行测试。
10. 可以输出完整 run summary。

进阶验收：

1. 对同一个失败任务可以保存和恢复状态。
2. 支持至少两个技术栈。
3. 支持工具注册表。
4. 支持权限策略配置。
5. 支持压缩长日志。
6. 支持一个简单 skill 文件。
7. 支持生成 PR 草稿说明。

## 9. 风险与取舍

### 9.1 不要把 PR 创建放进第一版

自动提 PR 听起来完整，但前置依赖较多，包括 GitHub token、分支管理、远程权限、提交规范和安全控制。MVP 阶段可以只生成 PR 描述和本地 diff。

### 9.2 不要一开始支持所有语言

建议先支持 Python，再支持 Node.js。多语言支持应该通过 skill 和规则逐步扩展。

### 9.3 不要过早做复杂 UI

CLI 更能突出 Agent 内部机制。等核心闭环稳定后，再考虑 Web dashboard 展示任务状态、工具调用和审批流。

### 9.4 不要让 LLM 直接决定所有命令

安装和测试命令可以由 LLM 建议，但最终执行前应经过规则校验。否则容易引入不可控命令执行风险。

## 10. 下一步开发建议

建议从以下最小任务开始：

1. 初始化 Python 项目结构。
2. 实现 `nano-agent run <repo_url>`。
3. 实现 workspace clone。
4. 实现 README 和文件树读取。
5. 用规则识别 Python 项目。
6. 执行 `pip install -r requirements.txt` 和 `pytest`。
7. 保存一次 run summary JSON。

完成以上内容后，再接入 LLM 做仓库分析和失败分析。这样可以避免一开始把所有问题都归因于 prompt，先保证工程执行链路可靠。
