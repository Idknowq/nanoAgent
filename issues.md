# Issues

## inspector: 大文件读取内存优化

`inspector.py:53` — `read_bytes()` 先把整个文件读入内存再切片，对大文件不必要。

应改为流式读取：

```python
with path.open("rb") as f:
    data = f.read(self.config.max_file_bytes)
```

cwd = context.workspace_path if context.workspace_path else self.cwd
检查safe_path机制

每次listfile都使用根目录作为起点，优化以省一次API

读多个文件时重复注入system prompt，可以设置stride

docker沙箱隔离