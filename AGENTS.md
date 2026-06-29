# Repository Guidelines

## 项目简介

本项目是一个轻量级 Coding Agent，用于面向真实代码仓库执行诊断、修复、验证和结果汇报。整体架构围绕 Agent loop 展开：LLM 产生工具调用，运行时执行工具并回填结果，直到提交结构化完成报告。

核心运行时已经完成 `asyncio` 异步化：`NanoAgent.run()`、`AgentLoop.run()`、LLM client、runtime tool、hook、context compactor、task service、background supervisor 和 subagent manager 均使用 async 接口。多 Agent 调度已从 `ThreadPoolExecutor` 迁移为 `asyncio.Task`，后台通知、取消、finish_run active-job 检查和 delegate tools 均通过 async 路径协作。新增运行时能力应沿用 async-first 设计，不再新增同步生产入口。

主要模块职责如下：

- `tools/`：定义运行时工具体系，包括文件读取、搜索、编辑、命令执行、仓库克隆、任务委派和运行结束报告等工具。
- `tasks/`：维护持久化任务状态，支持任务创建、查询、更新、依赖关系和状态流转。
- `context/`：负责上下文状态管理和压缩，包括工具结果持久化、消息裁剪和摘要压缩。
- `services/`：封装 LLM 客户端、错误归一化、重试策略和 provider 注册。
- `prompts/`：负责系统提示词、用户任务、skill 元数据和上下文信息的组装。
- `hooks/`：提供 LLM 调用和工具执行前后的扩展点，用于审计、权限控制、指标采集和上下文注入。
- `background/` 与 `subagents/`：支持后台子 Agent 并行执行、状态持久化、取消和结果回传。
- `persistence/`：管理运行过程中的消息、配置、报告、摘要和其他持久化产物。
- `skills/` 与 `memory/`：提供可按需加载的能力说明和历史偏好/经验注入。

测试位于 `tests/`，文档位于 `README.md`、`README_zh.md` 和 `docs/`。运行产物写入 `.nano/`，不得提交。

## 环境

使用项目虚拟环境中的 Python 3.13。默认所有开发、测试和脚本执行都应基于该虚拟环境。

## 开发方向

后续主要开发方向是接入 MCP。先搭建通用 MCP 基础设施，再接入 GitHub 等具体 MCP server。MCP 开发记录、阶段计划和验收要求统一维护在 `MCP.md`。

MCP 功能必须基于 async-first 设计：stdio transport 使用 `asyncio.create_subprocess_exec()`，HTTP transport 使用异步 HTTP client，client 初始化、`tools/list`、`tools/call` 和 shutdown 全部使用 async 生命周期管理。MCP tool adapter 应实现 async `RuntimeTool.run()`，并接入现有权限、workspace containment、并发元数据、审计 hook 和工具命名空间机制，避免绕过当前隔离与审计模型。

新增功能默认基于 async 实现，不再新增同步生产入口。除非有明确理由，不应新增 `ThreadPoolExecutor`、同步 subprocess、阻塞 sleep 或新的同步兼容 wrapper。

每次 MCP 相关开发完成后更新 `MCP.md` 文档。

## 代码风格

保持现有代码风格，优先做小范围、可验证的修改。代码应保持高内聚、低耦合和模块化，新增能力应放入职责匹配的模块中，避免把不同层级的逻辑混在同一个类或函数里。具体可参考skill:$karpathy-guidelines。

使用 4 空格缩进、Python 类型标注，并遵守当前项目的命名习惯和约定。新增测试应放在与被测模块对应的位置。

新增类必须包含明确的作用说明。类中的成员变量应添加简短注释，说明其用途或维护的状态。每个函数都必须有功能说明，说明该函数负责什么，不写空泛或重复代码本身的注释。

修改工具、上下文压缩、持久化、任务状态、后台调度或权限相关逻辑时，应补充有针对性的测试，并保持消息协议和运行产物的兼容性。

## 对话要求

交流应简洁、务实，优先说明结论、依据和下一步。不要使用夸张或情绪化表达。

每次开始修改文件或代码前，必须先向用户确认修改范围和意图；用户明确确认后再执行修改。
