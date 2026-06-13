读多个文件时重复注入system prompt，可以设置stride

docker沙箱隔离

tool context和context

token hit rate

RateLimitHook 注入的系统消息是纯噪音：当前 run 产生了 ~15 条 "Tool 'X' has been called N consecutive times" 消息，每条 143 字符，累积消耗大量
token。这些消息在上下文窗口化之前就应该被抑制或合并