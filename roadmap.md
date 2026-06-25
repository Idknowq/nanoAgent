# nanoAgent Development Roadmap

> 自动生成于 2026-06-25，按优先级排列。每个小点约 10-15 分钟完成。

## 一、MCP 接入 (Model Context Protocol)

- [x] **1.1** MCP 客户端基础框架 — 实现 `nano_agent/mcp/client.py`，支持 stdio 传输，连接 MCP server 并完成 initialize 握手 ✅ 2026-06-25
- [x] **1.2** MCP 工具发现与注册 — 从 MCP server 拉取 tool list，转换为 `RuntimeTool` 注册到 ToolRegistry ✅ 2026-06-25
- [ ] **1.3** MCP 资源/提示模板支持 — 支持 `resources/list` 和 `prompts/list`，注入到 Agent 上下文
- [ ] **1.4** MCP 配置管理 — 在 `AgentConfig` 中添加 `mcp_servers` 字段，支持多 server 配置

## 二、记忆系统增强

- [x] **2.1** 记忆更新工具 — 实现 `memory_update` 工具，允许 Agent 在运行中写入/更新记忆 ✅ 2026-06-25
- [ ] **2.2** 记忆删除与过期 — 支持记忆的 TTL 过期和手动删除
- [ ] **2.3** 记忆搜索增强 — 支持模糊匹配、全文搜索（当前仅 namespace + tag 精确过滤）
- [ ] **2.4** 跨运行记忆持久化 — 确保 failure/repo 记忆在运行间可靠传递，优化记忆注入格式

## 三、Web 工具

- [x] **3.1** web_search 工具 — 基于 HTTP 搜索 API，返回结构化搜索结果 ✅ 2026-06-25
- [ ] **3.2** web_fetch 工具 — 抓取 URL 内容并转为文本/markdown
- [ ] **3.3** Web 工具安全策略 — URL 白名单/黑名单、内容大小限制、超时控制

## 四、Thinking/推理模式支持

- [ ] **4.1** AgentMessage 扩展 — 添加 `reasoning_content` 字段，支持回传 thinking tokens
- [ ] **4.2** LLM 响应解析 — 在 `OpenAICompatibleLLMClient` 中解析并保存 `reasoning_content`
- [ ] **4.3** Thinking 配置与测试 — 在 `AgentConfig` 中启用 `llm_thinking_enabled`，端到端验证

## 五、沙箱与安全隔离

- [ ] **5.1** Docker 沙箱管理器 — 实现 `nano_agent/sandbox/docker.py`，支持在容器中执行命令
- [ ] **5.2** 沙箱配置集成 — `AgentConfig` 中添加 `sandbox` 配置项（image, network, volume mounts）
- [ ] **5.3** 沙箱与 runtime 环境统一 — 将当前 venv 隔离迁移到 Docker 沙箱内执行

## 六、性能与成本优化

- [ ] **6.1** 子 Agent 上下文预热 — 子 Agent 复用主 Agent 的 stable prefix，提高缓存命中率（issues.md 中缓存仅 42.8%）
- [ ] **6.2** 真实 token 计数 — 集成 tiktoken 或 provider tokenizer API，替换当前的 3 chars/token 估算
- [ ] **6.3** 智能压缩策略 — 基于消息重要性而非固定阈值进行裁剪
- [ ] **6.4** LLM 请求合并 — 减少无意义的小请求（如连续的空 tool_use 轮次）

## 七、工具系统增强

- [ ] **7.1** 工具审批缓存 — 同类型工具调用在同一次运行中记住用户审批决定
- [ ] **7.2** 并行工具执行 — 支持无依赖的工具调用并发执行，减少 round-trip
- [ ] **7.3** 工具超时与重试 — 每个工具独立的超时和重试策略
- [ ] **7.4** 工具调用审计增强 — 记录更多调用上下文（调用栈、前置条件判断等）

## 八、更多内置 Skill

- [ ] **8.1** `rust-repository` skill — Rust 项目诊断：cargo check/clippy/test 工作流
- [ ] **8.2** `go-repository` skill — Go 项目诊断：go build/vet/test 工作流
- [ ] **8.3** `generic-ci` skill — 通用 CI/CD 诊断：读取 CI 日志、定位失败原因

## 九、对话恢复与断点续传

- [ ] **9.1** 对话检查点保存 — 定期保存完整的对话状态快照
- [ ] **9.2** 对话恢复入口 — CLI 支持 `--resume <run_id>` 从检查点恢复
- [ ] **9.3** 恢复后状态验证 — 恢复后验证 workspace、git 状态一致性

## 十、CLI 与开发体验

- [ ] **10.1** 更丰富的 CLI 输出 — 彩色输出、spinner、步骤摘要表格
- [ ] **10.2** 交互模式 — 支持 `/approve`, `/deny`, `/skip` 等运行时交互命令
- [ ] **10.3** 配置文件支持 — `nano-agent.toml` 或 `.nano-agent.json` 项目级配置
- [ ] **10.4** 配置预设 (profiles) — 预设 `safe`/`thorough`/`quick` 等配置组合

## 十一、代码质量与测试

- [ ] **11.1** 补充 tools 模块测试 — `activate_skill`, `delegate_task`, `todo` 工具缺少独立测试
- [ ] **11.2** 补充集成测试 — Agent 端到端场景测试（clone → diagnose → fix → report）
- [ ] **11.3** 代码类型检查 — 在 CI 中添加 mypy/pyright 严格模式检查
- [ ] **11.4** 测试覆盖率报告 — 添加 pytest-cov，CI 中展示覆盖率变化

## 十二、文档与示例

- [ ] **12.1** API 文档 — 使用 mkdocs 或 sphinx 生成模块文档
- [ ] **12.2** 示例工作流 — 补充 `examples/` 目录，包含典型诊断/修复场景
- [ ] **12.3** 配置参考文档 — 完整列出所有 `AgentConfig` 字段及用途
