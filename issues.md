# Issues

## inspector: 大文件读取内存优化

`inspector.py:53` — `read_bytes()` 先把整个文件读入内存再切片，对大文件不必要。

应改为流式读取：

```python
with path.open("rb") as f:
    data = f.read(self.config.max_file_bytes)
```
