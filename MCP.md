# MCP Development Plan

## 目标

为 nanoAgent 接入 Model Context Protocol（MCP），先建立通用 MCP 基础设施，再接入 GitHub 等具体 MCP server。MCP 应作为现有 runtime tool 体系的外部工具来源，不应绕过 AgentLoop、权限、审计、workspace containment、并发调度和 tool result 消息协议。

本阶段优先接入 stdio transport，后续再扩展 HTTP transport。stdio 版本用于验证 MCP lifecycle、tool discovery、tool adapter、权限分级和测试闭环；HTTP 版本用于支持 remote MCP server、OAuth/PAT header、session 管理和流式响应。

## 设计原则

- async-first：不新增同步生产入口，不使用同步 subprocess、阻塞 sleep 或新的同步兼容 wrapper。
- transport 与 tool adapter 分离：stdio、HTTP 只负责 JSON-RPC 传输，MCP tool adapter 负责映射到 `RuntimeTool`。
- MCP server 必须使用命名空间，避免与内置工具或其他 MCP server 冲突，例如 `github.search_issues`。
- MCP 工具必须接入现有权限、审计、workspace containment 和并发元数据机制。
- GitHub token、OAuth token、header 等敏感信息不得进入 LLM 上下文、日志、tool result 或 report。
- 第一版应使用 mock MCP server 做稳定测试，再接入真实 GitHub MCP server。

## 开发顺序

1. 补 MCP 配置模型和生命周期设计，不接 GitHub 业务。
2. 实现 stdio transport：async subprocess、JSON-RPC request/response、超时、shutdown。
3. 实现 `initialize` 和 `tools/list`，把 MCP tools 映射成 nanoAgent tool definitions。
4. 实现 `tools/call` adapter，并接入现有 `RuntimeTool.run()`。
5. 加权限分级和 namespace。
6. 用一个最小 mock MCP server 做测试，不先依赖真实 GitHub。
7. 再接 GitHub MCP server，先启用只读 toolset。
8. 最后补 HTTP remote MCP 和 GitHub PAT/OAuth 配置。

## 第一阶段：通用 MCP 基础设施

涉及模块预计包括：

- `nano_agent/mcp/`：MCP client、transport、JSON-RPC message、session、tool adapter。
- `nano_agent/config.py` 或配置相关模块：MCP server 配置。
- `nano_agent/tools/base.py` 或工具注册路径：接入 MCP tool definitions。
- `nano_agent/agent.py` 或运行时初始化路径：管理 MCP session 生命周期。
- `tests/`：mock MCP server、transport、tool adapter、权限和 shutdown 测试。

基础设施应提供：

- `MCPServerConfig`：描述 server 名称、transport、命令/URL、环境变量、headers、启用 toolsets。
- `MCPTransport`：统一 async 传输接口。
- `StdioMCPTransport`：使用 `asyncio.create_subprocess_exec()` 启动和关闭本地 MCP server。
- `HttpMCPTransport`：后续使用异步 HTTP client 支持 remote MCP。
- `MCPClientSession`：负责 `initialize`、`tools/list`、`tools/call` 和 shutdown。
- `MCPToolAdapter`：把 MCP tool 包装为 nanoAgent `RuntimeTool`。
- `MCPToolRegistry`：按 server namespace 注册 MCP tools。

## 开发记录

### Step 1：MCP 配置模型和生命周期设计

状态：已完成。

本步只建立 MCP server 的配置表达和后续生命周期边界，不接入 GitHub 业务、不启动 stdio subprocess、不注册 MCP tools。

已完成内容：

- 新增 `nano_agent/mcp/`，定义 `MCPTransportType` 和 `MCPServerConfig`。
- `AgentConfig` 新增 `mcp_servers`，默认空 tuple，不改变现有运行行为。
- stdio server 配置要求 `command`，禁止 `url`。
- HTTP server 配置要求 `url`，禁止 `command`。
- server `name` 作为工具命名空间，只允许字母、数字、下划线和连字符。

后续生命周期边界：

1. `configured`
2. `disabled` 或 `session_created`
3. `initialized`
4. `tools_discovered`
5. `shutdown`

下一步进入 stdio transport，实现 async subprocess、JSON-RPC request/response、超时和 shutdown。

### Step 2：stdio transport

状态：已完成。

本步只实现 MCP stdio 传输层，不实现 `initialize`、`tools/list`、`tools/call` 语义封装，不接入 GitHub MCP server，也不注册 runtime tools。

已完成内容：

- 新增 JSON-RPC request、response 和 error 模型。
- 新增 `StdioMCPTransport`，使用 `asyncio.create_subprocess_exec()` 启动本地 MCP server。
- 支持按行写入 JSON-RPC request，并从 stdout 读取单行 JSON-RPC response。
- 支持请求超时、server 提前退出、非法 JSON、非法 JSON-RPC response 和 response id 不匹配的错误分类。
- `shutdown()` 支持重复调用，并按 close stdin、wait、terminate、kill 的顺序清理子进程。
- 使用最小 mock MCP server 覆盖 stdio request/response、timeout、closed server、invalid JSON、mismatched id 和 shutdown。

下一步进入 MCP client session，实现 `initialize` 和 `tools/list`，把 MCP tools 映射成 nanoAgent tool definitions。

### Step 3：initialize 和 tools/list

状态：已完成。

本步实现 MCP session 层的初始化和工具发现，只读取 MCP server 已暴露的工具清单，不实现 GitHub API 调用、不 hardcode GitHub 工具、不执行 MCP tools，也不注册 runtime tools。

已完成内容：

- 新增 `MCPClientSession`，负责启动 transport、发送 `initialize`、发送 `tools/list` 和关闭 transport。
- `initialize` 成功后发送 `notifications/initialized`，保持真实 MCP server 兼容性。
- session 层负责递增 JSON-RPC request id，transport 仍只负责发送和接收。
- 新增 `MCPInitializeResult`，保存协商协议版本、serverInfo、capabilities 和原始 initialize result。
- 新增 `MCPToolDefinition`，将远端 MCP tool 映射为 nanoAgent namespaced tool definition。
- 工具名使用 `<server>.<remote_tool>`，例如 `github.search_issues`。
- 远端 tool name 必须是 namespace-safe 名称；非法名称作为 MCP protocol error 处理，不做静默修正。
- JSON-RPC error 会转换为 session 层 `MCPRemoteError`。
- 使用 mock MCP server 覆盖 initialize、tools/list、未初始化调用、远端错误、非法工具名和 request id 递增。

下一步进入 `tools/call` adapter，将 MCP tool 调用接入 async `RuntimeTool.run()`。

### Step 4：tools/call adapter

状态：已完成。

本步实现 MCP tool 执行桥接，但仍不接入默认 `ToolRegistry`、不改 AgentLoop、不写 GitHub API 调用、不 hardcode GitHub 工具。

已完成内容：

- `MCPClientSession` 新增 `call_tool()`，通过 JSON-RPC `tools/call` 调用远端 MCP tool。
- `tools/call` 发送给 MCP server 的名称使用远端 tool name，例如 `search_issues`，不发送 `github.search_issues`。
- 新增 `MCPToolCallResult`，保存 MCP content blocks、`isError` 和原始 result。
- 新增 `MCPToolAdapter`，把一个 `MCPToolDefinition` 包装为 nanoAgent `RuntimeTool`。
- adapter 使用 namespaced tool name，例如 `github.search_issues`，并继承 MCP `inputSchema`。
- MCP tool 成功结果转换为 `ToolResult(success=True)`。
- MCP `isError=true` 转换为 `mcp_tool_error`。
- JSON-RPC remote error、protocol error 和 transport error 会转换为对应 `ToolResult.failure`。
- 使用 mock MCP server 覆盖远端 tool 调用、错误结果、JSON-RPC error、未初始化调用和 namespace 不匹配。

下一步进入权限分级、namespace 策略、并发元数据和 registry 接入。

### Step 5：namespace、权限元数据和 registry 接入

状态：已完成。

本步只把已发现的 MCP tool definitions 包装成 nanoAgent `ToolRegistry` 可管理的 runtime tools，不自动接入默认工具注册表、不改 AgentLoop、不接真实 GitHub MCP server。

已完成内容：

- 新增 `build_mcp_tool_registry()`，将 `MCPToolDefinition` 列表转换为 `MCPToolAdapter` 并注册进 `ToolRegistry`。
- MCP tool 使用 namespaced 工具名，例如 `github.search_issues`。
- 复用 `ToolRegistry` 的重复名称检测，避免 MCP tool 或内置工具命名冲突被静默覆盖。
- MCP adapter 默认元数据保持保守只读策略：`approval_level=READ`、`category=mcp`、`is_mutating=False`、`requires_workspace=False`。
- MCP adapter 默认允许并发：`can_run_concurrently=True`，并使用 `mcp:<server_name>` 作为 conflict group。
- 测试覆盖 registry 注册、重复名称拒绝、`ToolRegistry.specs()` 元数据和 `selected()` 行为。

下一步使用最小 mock MCP server 做更接近真实运行的集成测试，然后再接 GitHub MCP server 只读 toolset。

### Step 6：mock MCP server 集成测试

状态：已完成。

本步使用最小 mock MCP server 验证完整 stdio MCP tool lifecycle，不接真实 GitHub MCP server、不读取 token、不改 AgentLoop 自动挂载。

已完成内容：

- 新增端到端集成测试，覆盖 `MCPServerConfig`、`StdioMCPTransport`、`MCPClientSession.initialize()`、`notifications/initialized`、`tools/list`、`build_mcp_tool_registry()`、`MCPToolAdapter.invoke()` 和 `tools/call`。
- mock server 要求收到 `notifications/initialized` 后才允许 `tools/list` 和 `tools/call`，贴近真实 MCP server 生命周期。
- 集成测试确认 registry 能暴露 `mock.search_issues`，并能通过 adapter 得到 `ToolResult(success=True)`。
- 集成测试确认 MCP tool spec 保留 `category=mcp`、`approval_level=READ`、`can_run_concurrently=True` 和 `mcp:<server>` conflict group。

下一步接入 GitHub MCP server，先使用 stdio 模式和只读 toolset 做 smoke test。

### Step 7：GitHub MCP server stdio smoke

状态：已完成。

本步接入 GitHub 官方 MCP server 的 Docker stdio 运行方式，只做默认跳过的 smoke test，不接 HTTP remote MCP、不改 AgentLoop 自动挂载、不开放写操作。

已完成内容：

- 新增 GitHub MCP stdio 配置 helper，从 `.env` / 环境读取 Docker image、token、toolsets 和 read-only 开关。
- helper 使用 Docker `-e GITHUB_PERSONAL_ACCESS_TOKEN` 从父进程环境传递 token，不把 token 明文写入 `MCPServerConfig.env`。
- `.env.example` 记录 `GITHUB_MCP_DOCKER_IMAGE`、`GITHUB_PERSONAL_ACCESS_TOKEN`、`GITHUB_TOOLSETS` 和 `GITHUB_READ_ONLY`。
- 新增默认跳过的 smoke test：仅当 `RUN_GITHUB_MCP_SMOKE=1`、`GITHUB_PERSONAL_ACCESS_TOKEN` 存在且 Docker 可用时运行。
- smoke test 覆盖 GitHub MCP server 启动、`initialize`、`tools/list` 和 `build_mcp_tool_registry()`。

运行真实 GitHub MCP smoke：

```bash
. .venv/bin/activate
# Edit .env and set GITHUB_PERSONAL_ACCESS_TOKEN first.
RUN_GITHUB_MCP_SMOKE=1 .venv/bin/python -m pytest -q tests/test_github_mcp_smoke.py
```

下一步补 HTTP remote MCP 和 GitHub PAT/OAuth 配置。

## GitHub MCP 接入策略

GitHub 是第一个具体 MCP provider，但不应把 GitHub 逻辑写死到 MCP 核心层。GitHub 接入应建立在通用 MCP 基础设施之上。

第一版 GitHub 接入建议：

- 使用 stdio 模式运行本地 GitHub MCP server。
- 默认启用只读能力，优先覆盖 repo、issue、pull request、Actions 查询类工具。
- 写操作默认需要权限确认，并通过权限分级标记为非并发或 exclusive。
- 高风险操作默认禁用或需要显式 allowlist。
- token 只通过环境变量或安全配置引用传递给 MCP server，不写入持久化产物。

后续 HTTP 版本再支持：

- GitHub remote MCP endpoint。
- PAT 或 OAuth header 注入。
- session id、协议版本 header、SSE/streamable response、断线重连和 session 失效恢复。

## 验收标准

- MCP 基础设施不引入新的同步生产路径。
- stdio server 生命周期可被 async 创建、调用、超时处理和关闭。
- `initialize`、`tools/list`、`tools/call` 有单元测试覆盖。
- MCP tool result 能按现有 tool result 消息协议回填。
- MCP 工具可以被现有 hook、permission 和 audit 路径观察或拦截。
- 命名空间冲突、工具调用失败、server 退出、超时和 shutdown 清理均有测试覆盖。
- GitHub 接入先通过只读工具完成 smoke test，再逐步开放写能力。
