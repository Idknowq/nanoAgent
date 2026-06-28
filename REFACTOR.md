# asyncio Refactor Plan

## 目标

将 nanoAgent 从当前同步执行模型彻底重构为 `asyncio` 执行模型。本轮重构不考虑兼容旧同步接口，不保留同步 `run()`、`complete()`、`invoke()`、`ThreadPoolExecutor` 等生产路径。重构完成后，核心运行时应统一使用 async/await。

最终状态：

- `NanoAgent`、`AgentLoop`、LLM client、runtime tools、hooks、context compactor、task service、background supervisor、subagent manager 都使用异步接口。
- 新增功能默认基于 async 实现。
- 多 Agent 调度从线程池迁移为 `asyncio.Task`。
- 外部进程调用使用 `asyncio.create_subprocess_exec()`。
- HTTP/MCP 等网络能力使用异步 client。

## 当前进度

已完成：

- Step 1：核心接口已改为 async，包括 LLM client 协议、runtime tool 协议、hooks、context compactor、subagent manager、agent loop 和顶层 agent run 路径。
- Step 2：`AgentLoop` 已拆出单个 tool execution 边界，并保持 LLM、tool、hook、finalization、background idle wait 的协议顺序。
- Step 3：同一轮 LLM 返回的安全 tool batch 已支持可控并发，结果仍按原始 `tool_uses` 顺序写回。
- Step 4：`run_command` 已迁移到 `asyncio.create_subprocess_exec()`；`read_file`、`list_files`、`grep` 的阻塞文件 I/O 已通过 `asyncio.to_thread()` 移出 event loop。
- Step 5：hooks 已收敛到 `HookPipeline`，`AgentLoop` 不再直接遍历 hook list，hook 错误通知和注入消息顺序集中维护。
- Step 6：OpenAI-compatible provider 已迁移到 `AsyncOpenAI`，真实 LLM 网络调用不会阻塞 event loop。
- Step 7A：`clone_repo` 已迁移到 `asyncio.create_subprocess_exec()`，git clone 和元数据查询不再使用同步 `subprocess.run()`。

仍未完成：

- 执行环境准备中的外部进程仍需迁移到 asyncio subprocess。
- 持久化、task service、background supervisor 仍存在同步锁或线程池模型。
- MCP 尚未接入。

## 不可破坏的协议顺序

异步化不等于把所有步骤并发执行。以下顺序是 Agent 协议和当前语义的一部分，必须保留。

一次 Agent step 的顺序：

1. 检查取消信号。
2. 更新 `ToolContext.current_step`、`run.steps` 和当前可用工具列表。
3. 如进入 finalization step，先追加 finalization system message，并限制工具列表。
4. 执行上下文压缩管线。
5. 执行 `before_llm_call` hooks，按 hook 注册顺序逐个执行。
6. 调用 LLM。
7. 执行 `after_llm_call` hooks，按 hook 注册顺序逐个执行，并将其消息延迟到合适位置注入。
8. 追加 assistant message。
9. 根据 LLM stop reason 处理 end_turn、tool_use、max_tokens、content_filter 或 unknown。
10. 如有 tool calls，执行工具调用。
11. 追加 tool result messages。
12. 执行 `after_tool_call` hooks。
13. 追加延迟 hook messages。
14. 更新 `run.messages`，进入下一轮。

LLM 和工具之间的顺序：

- 必须先完成当前轮 LLM 调用，才能执行该轮工具调用。
- 必须将该轮工具结果写回消息流，下一轮 LLM 才能读取。
- 不允许在 LLM 调用未返回时预执行工具。
- 不允许在工具结果未写入消息流时开始下一轮 LLM。

hooks 顺序：

- 同一 hook 阶段内必须按注册顺序执行。
- `before_llm_call` 必须早于 LLM 调用。
- `after_llm_call` 必须晚于 LLM 调用，早于对应工具结果反馈完成后的下一轮 LLM。
- `before_tool_call` 必须早于对应工具执行。
- `after_tool_call` 必须晚于对应工具执行。
- hook 产生的消息注入位置必须保持当前协议语义，不得因并发而提前或乱序。

上下文压缩顺序：

- `tool_result_budget`、`snip_compact`、`micro_compact`、`compact_history` 是渐进式压缩管线，必须按顺序执行。
- `compact_history` 的多次 auto compact attempt 必须串行执行，因为后一次依赖前一次的输出和 token 估算。
- `reactive_compact` 只能在 LLM 抛出 `PROMPT_TOO_LONG` 后触发，不能提前并发执行。
- 压缩完成并保存 checkpoint 后，才能发起本轮 LLM 调用。

错误恢复顺序：

- transient retry 必须等待当前失败调用完成并记录错误后再重试。
- max_tokens continuation 必须先追加截断 assistant message 和 continuation system prompt，再发起 continuation LLM 调用。
- invalid response retry 必须先追加协议修正 system message，再重试。
- prompt_too_long reactive compaction 必须先完成压缩，再重试 LLM。

## 可以并发的边界

以下位置可以使用并发，但必须显式保持结果排序和状态一致性。

单轮多个工具调用：

- 同一个 LLM response 中包含多个 tool calls 时，可以并发执行多个工具。
- 并发前必须先完成所有 `before_tool_call` hooks，或为每个工具调用按 `before_tool_call -> tool execution -> after_tool_call` 的局部顺序执行。
- 回写到 `messages` 的 tool result 顺序必须与 LLM 返回的 `tool_uses` 顺序一致，而不是按完成时间排序。
- `run.tool_calls` 的记录顺序也应与 `tool_uses` 顺序一致。
- 如果工具之间存在隐式依赖或写冲突，应禁止并发或通过工具元数据降级为串行执行。
- `finish_run` 必须特殊处理：当它与其他工具同时出现时仍应返回协议错误，不能并发执行成部分成功。
- finalization step 中非 `finish_run` 工具必须直接拒绝，不参与并发调度。

后台多 Agent：

- 多个 subagent job 可以并发执行，每个 job 使用独立 `asyncio.Task`。
- 每个 subagent 必须拥有独立上下文、compactor、message store 和 cancellation token。
- job 状态更新、task 状态更新、事件队列写入必须通过异步锁串行化。

独立 I/O：

- 多个 MCP HTTP 请求、后台 job 查询、外部进程等待可以异步等待。
- 文件系统持久化如果仍使用同步原子写，应放入明确的异步边界中，避免阻塞核心 event loop。

## 当前同步边界

当前剩余需要重构的同步边界：

- `nano_agent/loop.py`：hook 调用逻辑仍分散在 loop 内，缺少统一 pipeline。
- `nano_agent/services/openai_compatible.py`：需要迁移或确认使用异步 OpenAI-compatible client。
- `nano_agent/tools/clone_repo.py`：使用 `subprocess.run`。
- `nano_agent/runtime/environment.py`：执行环境准备中存在同步子进程调用。
- `nano_agent/background/supervisor.py`：使用 `ThreadPoolExecutor`、`RLock` 和 `Condition`。
- `nano_agent/background/store.py` 与 `nano_agent/tasks/service.py`：使用线程锁保护状态。
- `nano_agent/persistence/` 与 compactor 持久化路径：仍以同步文件写入为主，需要明确 async 边界，同时保持原子写语义。

## 迁移原则

- 本次重构以 async 接口替代同步接口，不做同步兼容层。
- 每个阶段完成后，生产路径中对应模块不应继续调用旧同步方法。
- 不改变 tool call / tool result 消息协议。
- 不改变 `messages.jsonl`、`summary.json`、`report.md` 等运行产物格式。
- 并发必须由显式调度点控制，不能让 hooks、compaction、message append 和状态持久化自然竞态。
- 新增异步锁、事件和 task 管理时，必须明确谁拥有状态、谁负责关闭、谁负责取消。
- 文件写入仍需保持原子性；异步化不能降低崩溃恢复能力。

## Step 1：替换核心接口为 async

涉及模块：

- `nano_agent/services/llm.py`
- `nano_agent/tools/base.py`
- `nano_agent/hooks/base.py`
- `nano_agent/loop.py`
- 相关测试 fake 类

重构内容：

- 将 `LLMClient.complete()` 替换为 `async def complete(...) -> LLMResponse`。
- 将 `RuntimeTool.invoke()` 替换为 `async def invoke(...) -> ToolResult`。
- 将 `RuntimeTool.run()` 替换为 `async def run(...) -> ToolResult`。
- 将所有 hook 协议方法替换为 async 方法。
- 删除同步 helper 和同步默认实现，不使用 `asyncio.to_thread()` 作为长期兼容方案。
- 更新所有 fake LLM、fake tool、fake hook 为 async。

重构后的结果：

- 类型层面不再存在同步 LLM / tool / hook 协议。
- AgentLoop 后续只能通过 await 调用 LLM、工具和 hooks。
- 测试基础设施具备 async 版本。

## Step 2：重构 AgentLoop 为异步主循环

涉及模块：

- `nano_agent/loop.py`
- `nano_agent/agent.py`
- `tests/test_agent_loop.py`
- `tests/test_completion.py`
- `tests/test_audit_hook.py`
- `tests/test_console_hook.py`
- `tests/test_llm_metrics_hook.py`

重构内容：

- 将 `AgentLoop.run()` 改为 `async def run(...) -> RunSummary`。
- 将 `_call_llm_with_recovery()`、`_perform_llm_request()`、`_sleep()`、`_idle_wait()` 改为 async。
- 用 `await asyncio.sleep(...)` 替代阻塞 sleep。
- `idle_waiter` 改为 async callable。
- 保持 LLM 调用前后的 hooks 顺序。
- 保持 assistant message、tool result message、deferred hook messages 的追加顺序。
- 保持 finalization step 和 protocol correction 语义。

重构后的结果：

- Agent 主循环完全异步。
- LLM 重试、continuation、reactive compaction 和 tool execution 都运行在 async 流程中。
- 不再存在同步 AgentLoop 入口。

## Step 3：实现工具调用并发调度

涉及模块：

- `nano_agent/loop.py`
- `nano_agent/tools/base.py`
- `nano_agent/tools/finish_run.py`
- `tests/test_agent_loop.py`
- `tests/tools/test_base.py`

重构内容：

- 在 AgentLoop 中新增 tool batch 调度逻辑。
- 对同一轮 LLM 返回的多个 tool calls，按工具元数据判断是否允许并发。
- 新增工具元数据，例如：
  - `can_run_concurrently`
  - `conflict_group`
  - `requires_exclusive_execution`
- 默认策略应保守：读工具可并发，写工具、命令执行、仓库克隆、finish_run、delegate_task、task update 默认串行或按 conflict group 串行。
- 并发执行时，每个 tool call 内部保持：
  - `before_tool_call`
  - tool execution
  - `after_tool_call`
- 聚合结果时必须按原始 `tool_uses` 顺序写入 `run.tool_calls` 和 `messages`。
- 若任一工具抛出未捕获异常，应触发 `on_error` hooks，并取消同批仍在运行的工具任务。

重构后的结果：

- 单轮多个独立工具可以并发执行。
- 协议消息顺序保持稳定。
- 有副作用或有顺序依赖的工具不会被错误并发。

## Step 4：迁移工具内部阻塞 I/O

状态：已完成一部分。

涉及模块：

- `nano_agent/tools/read_file.py`
- `nano_agent/tools/list_files.py`
- `nano_agent/tools/grep.py`
- `nano_agent/tools/run_command.py`
- `tests/tools/test_read_file.py`
- `tests/tools/test_run_command.py`

重构内容：

- `run_command` 使用 `asyncio.create_subprocess_exec()`，保留进程组、timeout、stdout/stderr tail、exit code 和超时清理语义。
- `read_file`、`list_files`、`grep` 将同步文件 I/O 主体移入 `_run_sync()`，由 `asyncio.to_thread()` 调用。
- 保持 workspace containment、输入校验、权限级别和 `ToolResult` 格式不变。
- 增加 event loop 不被工具等待阻塞的测试。

重构后的结果：

- Step 3 的安全 tool batch 并发不再被 `run_command` 进程等待或只读文件工具的同步 I/O 长时间阻塞。
- 文件系统 I/O 仍保留同步实现，但同步成本被隔离到 thread boundary。
- 后续剩余工具迁移可以按同一模式处理。

剩余工作：

- `clone_repo` 仍需迁移到 asyncio subprocess。
- `runtime/environment.py` 中涉及外部命令或虚拟环境准备的路径仍需迁移。
- `edit_file`、task tools、delegate tools、activate skill、finish_run 等需要复查是否存在长时间同步 I/O，并按风险决定是否使用 `asyncio.to_thread()`。

## Step 5：抽取 HookPipeline

涉及模块：

- `nano_agent/hooks/base.py`
- `nano_agent/hooks/permission.py`
- `nano_agent/hooks/console.py`
- `nano_agent/hooks/llm_metrics.py`
- `nano_agent/hooks/registry.py`
- `nano_agent/loop.py`
- `tests/test_agent_loop.py`
- `tests/test_audit_hook.py`
- `tests/test_console_hook.py`
- `tests/test_llm_metrics_hook.py`
- `tests/test_permissions.py`

重构内容：

- 新增统一的 `HookPipeline`，封装：
  - `before_llm_call`
  - `after_llm_call`
  - `before_tool_call`
  - `after_tool_call`
  - `on_error`
- `AgentLoop` 不再直接遍历 `self.hooks`，只调用 pipeline。
- 明确 hook 注入消息语义：
  - `before_llm_call` 立即写入 conversation，影响本轮 LLM 输入。
  - `after_llm_call` 延迟到 assistant/tool 协议消息之后写入。
  - tool 前后 hook 消息按 LLM `tool_uses` 顺序收集和回填。
- 并发 tool batch 中，hook 仍保持串行和确定顺序：
  - before hooks 串行。
  - tool invoke 可并发。
  - after hooks 串行。
- `on_error` 按注册顺序执行；hook 自身错误不得覆盖原始业务异常，除非明确设计为 fatal。
- `PermissionDeniedError` 继续中断工具执行，被拒绝的 tool call 不进入 `tool.invoke()`。

重构后的结果：

- `AgentLoop` 更专注于 LLM、tool batch、compaction 和 finish 协议调度。
- hook 执行顺序、错误传播和注入消息位置集中在一个模块维护。
- 后续指标、权限、审计、MCP tracing 不需要继续扩张 loop 代码。

## Step 6：迁移 LLM provider 到真正异步网络调用

状态：已完成。

涉及模块：

- `nano_agent/services/openai_compatible.py`
- `nano_agent/services/registry.py`
- `nano_agent/services/retry.py`
- `tests/test_openai_compatible.py`
- `tests/test_llm_metrics_hook.py`

重构内容：

- OpenAI-compatible provider 改用 `AsyncOpenAI`。
- `complete()` 保持 async 协议，内部不再通过同步 client 阻塞 event loop。
- 错误归一化逻辑保持一致。
- transient retry 继续使用 async sleep。
- 确认 usage、tool call parsing、invalid response、max_tokens handling 与当前行为一致。
- 增加 provider 等待期间不阻塞 event loop 的测试。

重构后的结果：

- LLM 网络调用不阻塞 event loop。
- AgentLoop 可以在等待 LLM 时让出调度权。
- provider 层不再保留同步网络调用路径。

## Step 7：迁移剩余内置工具和运行环境准备

状态：进行中，Step 7A 已完成。

涉及模块：

- `nano_agent/tools/clone_repo.py`
- `nano_agent/tools/edit_file.py`
- `nano_agent/tools/tasks.py`
- `nano_agent/tools/delegate_task.py`
- `nano_agent/tools/activate_skill.py`
- `nano_agent/tools/finish_run.py`
- `nano_agent/runtime/environment.py`
- `tests/tools/`
- `tests/runtime/`

重构内容：

- `clone_repo` 使用 `asyncio.create_subprocess_exec()` 执行 git，并保留 timeout、stderr/stdout tail、工作区空目录约束和错误分类。已完成。
- `runtime/environment.py` 中需要执行外部命令的逻辑改为 async subprocess。
- 对文件写入、skill 读取、task 工具和 delegate 工具进行阻塞点审计：
  - 短文件 I/O 可暂时保留同步实现。
  - 可能长时间运行的文件 I/O 或目录遍历放入 `asyncio.to_thread()`。
  - 状态服务调用等到 task service 异步化后改为 await。
- 根据工具副作用复查并发元数据。

重构后的结果：

- 内置工具不会在长时间子进程或重 I/O 上阻塞 event loop。
- 工具权限、workspace containment、输入校验和 `ToolResult` 格式不变。
- 为 task service 和 background supervisor 的 async 化清理工具层依赖。

剩余工作：

- Step 7B：迁移 `runtime/environment.py` 中的同步外部命令。
- 审计 `edit_file`、`activate_skill`、task tools、delegate tools 和 `finish_run` 的阻塞点。

## Step 8：整理 ContextCompactor 和持久化异步边界

涉及模块：

- `nano_agent/context/compactor.py`
- `nano_agent/context/state.py`
- `nano_agent/persistence/message_store.py`
- `tests/test_context_compactor.py`

重构内容：

- 确认 `prepare()`、`compact_history()`、`reactive_compact()`、`_summarize()` 已走 async 调用路径。
- `prepare()` 内部严格保持顺序：
  - `tool_result_budget`
  - `snip_compact`
  - `micro_compact`
  - zero or more `compact_history`
  - save checkpoint
- `_summarize()` 调用异步 LLM client。
- `compact_history` attempts 串行执行。
- `reactive_compact` 只从 LLM prompt-too-long recovery 路径调用。
- transcript、checkpoint、tool result 持久化继续保持原子写。
- 如将同步持久化移出 event loop，必须保留临时文件加 `os.replace` 的原子模式。
- 不允许为了 async 化降低 tool result 落盘的完整性校验和恢复语义。

重构后的结果：

- 上下文压缩可以在 async AgentLoop 中顺序执行。
- 三层压缩和 LLM 摘要压缩不会被错误并发。
- prompt-too-long 恢复路径保持当前语义。
- 持久化阻塞点有明确边界，后续可统一迁移。

## Step 9：迁移持久化和 TaskService

涉及模块：

- `nano_agent/tasks/service.py`
- `nano_agent/tasks/store.py`
- `nano_agent/background/store.py`
- `nano_agent/persistence/json_io.py`
- `nano_agent/persistence/message_store.py`
- `nano_agent/persistence/report_store.py`
- `tests/test_tasks.py`
- `tests/test_persistence.py`

重构内容：

- 将 task service API 改为 async。
- 将 `RLock` 替换为 `asyncio.Lock`。
- task DAG 校验、状态转换、依赖解锁必须在同一把 async lock 下完成。
- store 写入继续保持原子性。
- message append、summary save、report save 等持久化方法按调用路径改为 async。

重构后的结果：

- task 和持久化层可以被 async supervisor、async tools 和 async AgentLoop 调用。
- 不再依赖线程锁。
- DAG 依赖和状态机语义保持不变。

## Step 10：多 Agent 调度迁移到 asyncio

涉及模块：

- `nano_agent/background/supervisor.py`
- `nano_agent/background/cancellation.py`
- `nano_agent/background/hook.py`
- `nano_agent/subagents/manager.py`
- `nano_agent/subagents/store.py`
- `nano_agent/tools/delegate_task.py`
- `tests/test_background_tasks.py`
- `tests/test_subagents.py`

重构内容：

- 删除 `ThreadPoolExecutor` 调度模型。
- `BackgroundJobSupervisor.submit()` 改为 async，并用 `asyncio.create_task()` 启动 subagent job。
- `_jobs`、`_tasks`、`_prepared`、`_tokens`、`_events` 等状态由 `asyncio.Lock` 保护。
- 完成通知使用 `asyncio.Condition` 或 `asyncio.Event`。
- `wait_for_completion()` 改为 async。
- `shutdown()` 改为 async，负责取消 active jobs 并 await 任务结束。
- `SubagentManager.run()` / `execute()` 改为 async。
- cancellation token 需要兼容 `asyncio.CancelledError`，保证取消时写入 job/task 终态。

重构后的结果：

- 多 Agent 运行由 event loop 统一调度。
- 主 Agent 等待后台完成不阻塞线程。
- job 状态、task 状态、事件投递和 observed 语义保持稳定。

## Step 11：顶层入口和资源生命周期复查

涉及模块：

- `nano_agent/agent.py`
- `nano_agent/cli.py`
- `nano_agent/__main__.py`
- `tests/test_persistence.py`
- 端到端测试

重构内容：

- 确认 `NanoAgent.run()`、CLI 入口和实验脚本已统一走 async 路径。
- 顶层异常处理、supervisor shutdown、report 保存、run summary 保存全部使用 await 或明确的 async boundary。
- 运行结束时确保 MCP client、subagent task、外部进程和后台资源被关闭。
- 删除任何为旧同步接口保留的生产入口。

重构后的结果：

- CLI 和生产入口走完整 async 路径。
- 顶层资源生命周期明确。
- 同步入口从生产代码中移除。

## Step 12：MCP 按 async-first 接入

涉及模块：

- `nano_agent/mcp/`（新增）
- `nano_agent/config.py`
- `nano_agent/tools/base.py`
- `nano_agent/agent.py`
- MCP 相关测试

重构内容：

- MCP HTTP transport 使用异步 HTTP client。
- MCP stdio transport 使用 `asyncio.create_subprocess_exec()`。
- MCP client 初始化、`tools/list`、`tools/call`、shutdown 全部 async。
- MCP tool adapter 实现 async `RuntimeTool.run()`。
- MCP 工具必须设置权限、并发元数据、workspace roots 和命名空间，避免绕过现有隔离与权限模型。

重构后的结果：

- MCP 不引入新的同步债务。
- MCP 工具可以参与 AgentLoop 的工具 batch 调度。
- stdio server 和 HTTP session 生命周期由 async 资源管理统一控制。

## Step 13：删除同步残留

涉及模块：

- 全部 `nano_agent/`
- 全部 `tests/`

重构内容：

- 删除同步 `complete()`、`invoke()`、`run()`、同步 hooks、同步 supervisor 等残留接口。
- 删除 `ThreadPoolExecutor`、`threading.RLock`、`threading.Condition` 在生产运行路径中的使用。
- 删除阻塞 `time.sleep`、`subprocess.run`、`subprocess.Popen` 在生产运行路径中的使用。
- 更新测试为 `pytest.mark.asyncio` 或项目选定的 async 测试方式。
- 更新 README 和开发文档中的运行模型描述。

重构后的结果：

- 项目核心运行时彻底 async 化。
- 同步实现不再作为内部兼容路径存在。
- 后续新功能可以直接依赖统一 async 架构。

## 验证策略

每个阶段至少验证：

- 对应模块单元测试。
- Agent loop 协议顺序测试。
- 工具 batch 并发测试，检查结果按 tool_use 顺序写回。
- hook 顺序测试。
- 上下文压缩顺序测试。
- LLM 错误恢复测试。
- 后台任务取消和完成通知测试。
- 持久化产物兼容性检查。

关键回归场景：

- LLM transient retry。
- invalid response 协议修正。
- `max_tokens` continuation。
- `prompt_too_long` reactive compaction。
- tool result budget 落盘和恢复路径。
- 同轮多个只读工具并发执行后按原始顺序写回。
- 同轮写工具或 exclusive 工具保持串行。
- `finish_run` 与其他工具同时出现时返回协议错误。
- 命令超时后的进程清理。
- subagent job 取消、失败、成功和 blocked 状态回写。
- task DAG 环检测、依赖阻塞和依赖完成后的自动解锁。

## 推荐执行顺序

1. 替换核心接口为 async。
2. 重构 AgentLoop 为异步主循环。
3. 实现工具调用并发调度。
4. 迁移工具内部阻塞 I/O。
5. 抽取 HookPipeline。
6. 迁移 LLM provider 到真正异步网络调用。
7. 迁移剩余内置工具和运行环境准备。
8. 整理 ContextCompactor 和持久化异步边界。
9. 迁移持久化和 TaskService。
10. 多 Agent 调度迁移到 asyncio。
11. 顶层入口和资源生命周期复查。
12. MCP 按 async-first 接入。
13. 删除同步残留。

不建议把“工具并发”和“多 Agent 迁移”放到同一步。工具并发属于单轮 LLM response 内的 batch 调度问题，多 Agent 迁移属于后台 job 生命周期和状态一致性问题，两个问题应分别验证。
