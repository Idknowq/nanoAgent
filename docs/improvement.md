## config调优
  - DeepSeek V4 官方支持 1M 上下文，但没有直接使用满 1M。当前 Agent 会累积工具协议、测试日志和重复观察，256K 能降低 context degradation，同时足以覆盖 SWE-bench Lite 的多数
    仓库修复任务。

  - Thinking 暂时关闭。V4 默认开启，但当前 AgentMessage 没有保存并回传 reasoning_content，多轮工具调用可能收到 400。要开启 thinking，需要先完善消息协议。
  - 未启用 JSON Output。当前 Agent 使用 function calling 和结构化 finish_run，再叠加 response_format=json_object 没有实际收益，还存在空响应和提示词必须包含 JSON 指令等限
    制。

  - snip_compact_ratio 调至 1.0，避免原实现先在 50% 阈值删除中间历史，再执行自动摘要。
  - 测试命令超时提高到 600 秒，适配 SWE-bench 中安装依赖、项目构建和完整测试执行。
  - 补充了 DeepSeek prompt_cache_hit_tokens 用量统计。
  - 500/503/529 和 insufficient_system_resource 现在作为可重试过载处理；400/402/422 作为不可重试请求错误处理。