# nanoAgent 架构指南

## 总览：三层结构

```
┌─────────────────────────────────────────────────────┐
│  入口层：cli.py                                      │
│  解析命令行 → 组装 config → 启动 NanoAgent            │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│  编排层：agent.py + loop.py                          │
│  NanoAgent 准备工具和上下文 → AgentLoop 驱动 LLM 循环 │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│  执行层：tools/ + services/llm.py                    │
│  LLM 返回 tool_use → ToolRegistry 查找 → 工具执行    │
└─────────────────────────────────────────────────────┘
```

---

## 一、数据模型（models.py）— 全部是值对象，不包含行为

这些类只定义"数据长什么样"，字段自带校验和序列化。不依赖项目内任何其他模块。

```
RunStatus (StrEnum)         运行状态：pending → running → succeeded/failed
ApprovalLevel (StrEnum)     权限等级：read < execute_safe < execute_risky < write < network < publish

AgentMessage (BaseModel)    LLM 对话中的一条消息，有 role + content + tool_call_id
ToolUseRequest (BaseModel)  LLM 要求调用工具的请求，有 id + name + input
LLMResponse (BaseModel)     LLM 一轮响应的完整结果：文本 + 工具请求列表 + stop_reason
ToolCallRecord (BaseModel)  一次工具调用的审计记录：工具名、输入输出摘要、耗时、权限、成败
RunSummary (BaseModel)      一次运行的完整快照：id + 仓库 + 状态 + tool_calls + messages
```

**注意**：`TodoStatus` 和 `TodoItem` 不在 models.py 中，它们属于 `tools/todo.py` 的私有类型。

---

## 二、配置（config.py）— 全局运行参数

```
AgentConfig (BaseModel)
  workspace_root           工作区父目录，默认 .nano/workspaces
  runs_root                run 摘要保存目录，默认 .nano/runs
  max_steps                最大循环轮数，默认 20
  command_timeout_seconds  单命令超时，默认 120
  auto_approve             是否跳过人工确认，默认 False
  max_file_bytes           单文件最大读取字节，默认 128000
  stdout_tail_chars        stdout 截断保留字符数，默认 16000
  stderr_tail_chars        stderr 截断保留字符数，默认 16000
```

---

## 三、工具系统（tools/）— 核心执行能力

### 3.1 抽象层（tools/base.py）

```
ToolResult (BaseModel)      工具执行结果：success + summary + data
ToolSpec (BaseModel)        工具的"名片"：name + description + approval_level + input_schema
RuntimeTool (ABC)           所有工具的抽象基类，子类必须实现 run(input_data) → ToolResult
ToolRegistry                工具注册表：register() 注册、get(name) 查找、specs() 导出元数据列表
```

### 3.2 BashTool（tools/bash.py）

```
BashTool (RuntimeTool)      name="bash", approval_level=EXECUTE_RISKY
  ├─ cwd: Path              命令执行目录
  └─ run({"command": "..."}) → subprocess.run(["bash", "-lc", command])
      返回 ToolResult(success, summary, data={exit_code, stdout_tail, stderr_tail, ...})
```

系统唯一的**外部执行工具**，有真实的 shell 副作用。

### 3.3 TodoWriteTool（tools/todo.py）

```
TodoWriteTool (RuntimeTool)  name="todo_write", approval_level=READ
  ├─ self.todos: TodoList   内部自治的状态存储（外部不可见）
  └─ run({action, title, id, evidence}) → 操作 TodoList，返回当前快照

TodoList                    TodoWriteTool 的内部数据管理（不是工具，不对外暴露）
  ├─ add / start / complete / fail / skip
  └─ 通过 todo-1, todo-2... 自增 id

TodoStatus (StrEnum)        PENDING / RUNNING / COMPLETED / FAILED / SKIPPED
TodoItem (BaseModel)        id + title + status + evidence
```

关键设计：`TodoItem`、`TodoStatus`、`TodoList` 全部是 `tools/todo.py` 的**私有实现**，不污染全局 `models.py`。`TodoWriteTool.__init__` 无参，内部自己 new TodoList。

`TodoWriteTool` 和 `BashTool` 地位完全平等——都实现 `RuntimeTool`，都通过 `ToolRegistry` 注册，调用记录统一写入 `RunSummary.tool_calls`。

---

## 四、LLM 服务层（services/llm.py）

```
LLMClient (Protocol)            接口协议：complete(messages, tools) → LLMResponse
                                    ↑
                    ┌───────────────┴───────────────┐
                    │                               │
ScriptedMvpLLMClient            StubLLMClient
确定性脚本，按 step 计数         空响应，直接 end_turn
step=1: clone 仓库              未配置真实模型时使用
step=2: 扫描关键文件
step=3: end_turn
```

---

## 五、循环引擎（loop.py）— 系统心跳

```
AgentLoop(config, llm, tools)
  │
  └─ run(run, initial_messages) → RunSummary
       │
       for _ in range(max_steps):
         1. llm.complete(messages, tools.specs())  → LLMResponse
         2. 如果有 content，追加 assistant 消息
         3. stop_reason="end_turn" → run.status=SUCCEEDED，返回
         4. stop_reason="tool_use" → 遍历 tool_uses：
            a. ToolRegistry.get(name) → RuntimeTool
            b. tool.run(input) → ToolResult
            c. 生成 ToolCallRecord → run.tool_calls
            d. 追加 role="tool" 消息 → messages
         5. 超限 → run.status=FAILED，返回
```

---

## 六、编排器（agent.py）— 装配工

```
NanoAgent(config, llm?)
  │
  └─ run(repo_url) → RunSummary
       1. WorkspaceManager.create_run(repo_url)    → RunSummary（生成 run_id）
       2. WorkspaceManager.next_workspace_path()   → .nano/workspaces/<repo>-<run_id>
       3. llm = 用户传入 or ScriptedMvpLLMClient()
       4. ToolRegistry([BashTool(...), TodoWriteTool()])
       5. AgentLoop(config, llm, tools)
       6. loop.run(run, initial_messages)
       7. WorkspaceManager.save_run_summary(run)   → .nano/runs/<run_id>.json
```

---

## 七、工作区管理（workspace.py）

```
WorkspaceManager(config)
  ├─ create_run(repo_url)           → 生成带时间戳 run_id 的 RunSummary
  ├─ next_workspace_path(url, id)   → 计算路径，确保父目录存在
  ├─ save_run_summary(run)          → 写入 JSON 文件
  └─ _repo_name_from_url(url)       → URL 尾部提取安全目录名
```

不涉及 git 操作。clone 由 LLM 通过 BashTool 执行。

---

## 八、预埋模块（当前未被运行时调用）

```
context/compressor.py     ContextCompressor   → 头尾截断，后续替换为 LLM 摘要
memory/store.py           InMemoryStore       → 进程内记忆增删查
                          JsonlMemoryStore    → JSONL 持久化（占位）
permissions/policy.py     PermissionPolicy    → 按 ApprovalLevel 判断是否需审批
skills/registry.py        SkillRegistry       → 从目录加载 .md Skill
```

---

## 九、完整调用链路（从 CLI 到 JSON 落盘）

```
$ nano-agent run https://github.com/foo/bar
│
│  ┌──────────────────────────────────────────────────────┐
│  │ cli.py                                               │
│  │   AgentConfig(workspace_root=.nano/workspaces, ...)  │
│  │   NanoAgent(config).run("https://github.com/foo/bar")│
│  └──────────────────────────┬───────────────────────────┘
│                             │
│  ┌──────────────────────────▼───────────────────────────┐
│  │ agent.py: NanoAgent.run()                            │
│  │                                                      │
│  │  1. WorkspaceManager.create_run(repo_url)            │
│  │     └─ RunSummary(run_id="20240610...", repo_url=..) │
│  │                                                      │
│  │  2. WorkspaceManager.next_workspace_path()           │
│  │     └─ .nano/workspaces/bar-20240610...              │
│  │                                                      │
│  │  3. ScriptedMvpLLMClient(repo_url)  ← 脚本 LLM      │
│  │                                                      │
│  │  4. ToolRegistry([                                   │
│  │       BashTool(config, cwd=workspace_path),          │
│  │       TodoWriteTool(),           ← 无参，自治        │
│  │     ])                                               │
│  │                                                      │
│  │  5. AgentLoop(config, llm, tools)                    │
│  │     └─ loop.run(run, initial_messages)               │
│  └──────────────────────────┬───────────────────────────┘
│                             │
│  ┌──────────────────────────▼───────────────────────────┐
│  │ loop.py: AgentLoop.run()                             │
│  │                                                      │
│  │  messages = [system_prompt, user_message]            │
│  │                                                      │
│  │  ┌── for step in range(max_steps): ──────────────┐   │
│  │  │                                                │   │
│  │  │  llm.complete(messages, tools.specs())         │   │
│  │  │       │                                        │   │
│  │  │       ├─ stop_reason="tool_use"                │   │
│  │  │       │   tool_uses: [                          │   │
│  │  │       │     {id:"toolu_1", name:"bash",        │   │
│  │  │       │      input:{command:"git clone ..."}}  │   │
│  │  │       │   ]                                     │   │
│  │  │       │                                         │   │
│  │  │       │   for each tool_use:                    │   │
│  │  │       │     tool = ToolRegistry.get("bash")    │   │
│  │  │       │     result = tool.run(input)            │   │
│  │  │       │       │                                │   │
│  │  │       │       ▼ BashTool.run({"command":...})  │   │
│  │  │       │         └─ subprocess.run(["bash",     │   │
│  │  │       │              "-lc", command], cwd=...) │   │
│  │  │       │         └─ ToolResult(success=..,      │   │
│  │  │       │              summary="exit_code=0",    │   │
│  │  │       │              data={exit_code,stdout..})│   │
│  │  │       │                                         │   │
│  │  │       │     记录 ToolCallRecord → run.tool_calls│   │
│  │  │       │     追加 tool 消息 → messages           │   │
│  │  │       │                                         │   │
│  │  │       ├─ stop_reason="end_turn"                │   │
│  │  │       │   → run.status = SUCCEEDED             │   │
│  │  │       │   → return run                          │   │
│  │  │                                                │   │
│  │  └────────────────────────────────────────────────┘   │
│  └──────────────────────────┬───────────────────────────┘
│                             │
│  ┌──────────────────────────▼───────────────────────────┐
│  │ agent.py: 回到 NanoAgent.run()                       │
│  │                                                      │
│  │  WorkspaceManager.save_run_summary(run)              │
│  │    └─ .nano/runs/20240610....json                    │
│  │       {                                              │
│  │         "run_id": "...",                             │
│  │         "repo_url": "...",                           │
│  │         "status": "succeeded",                       │
│  │         "tool_calls": [                              │
│  │           {"tool_name":"bash", "success":true, ...}  │
│  │         ],                                           │
│  │         "messages": [...],                           │
│  │         "notes": [],                                 │
│  │         "artifacts": {}                              │
│  │       }                                              │
│  └──────────────────────────────────────────────────────┘
│
│  cli.py: console.print_json(run_summary)
│
▼  终端输出 JSON 摘要
```

---

## 十、类关系速查

| 类 | 位置 | 谁创建/持有它 | 依赖 |
|---|---|---|---|
| AgentConfig | config.py | cli.py 解析参数 | 无 |
| RunStatus | models.py | —（枚举） | 无 |
| ApprovalLevel | models.py | —（枚举） | 无 |
| AgentMessage | models.py | agent.py, loop.py 构造 | 无 |
| ToolUseRequest | models.py | LLM 客户端构造 | 无 |
| LLMResponse | models.py | LLMClient.complete() 返回 | ToolUseRequest |
| ToolCallRecord | models.py | AgentLoop 工具执行后 | ApprovalLevel |
| RunSummary | models.py | WorkspaceManager.create_run() | ToolCallRecord, AgentMessage |
| ToolResult | tools/base.py | RuntimeTool.run() 返回 | 无 |
| ToolSpec | tools/base.py | ToolRegistry.specs() | ApprovalLevel |
| RuntimeTool | tools/base.py | 工具开发者继承 | ToolResult |
| ToolRegistry | tools/base.py | NanoAgent.run() | RuntimeTool, ToolSpec |
| BashTool | tools/bash.py | NanoAgent.run() | AgentConfig, RuntimeTool |
| TodoWriteTool | tools/todo.py | NanoAgent.run() | RuntimeTool, TodoList |
| TodoList | tools/todo.py | TodoWriteTool.\_\_init\_\_() | TodoItem, TodoStatus |
| TodoItem | tools/todo.py | TodoList.add() | TodoStatus |
| TodoStatus | tools/todo.py | —（枚举） | 无 |
| LLMClient | services/llm.py | —（Protocol） | AgentMessage, ToolSpec, LLMResponse |
| ScriptedMvpLLMClient | services/llm.py | NanoAgent.run() | AgentMessage, ToolSpec, LLMResponse |
| StubLLMClient | services/llm.py | 测试/备用 | AgentMessage, ToolSpec, LLMResponse |
| AgentLoop | loop.py | NanoAgent.run() | AgentConfig, LLMClient, ToolRegistry |
| NanoAgent | agent.py | cli.py | 几乎所有 |
| WorkspaceManager | workspace.py | NanoAgent.\_\_init\_\_() | AgentConfig, RunSummary |
