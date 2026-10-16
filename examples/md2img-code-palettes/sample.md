# 代码配色预览

同一段 Python 示例，比较注释、关键字、字符串、数字与普通变量的辨识度。

```python
from dataclasses import dataclass

# 筛选高分项目，并生成一条消息
@dataclass
class Project:
    name: str
    score: float = 0.0


def summarize(items: list[Project]) -> str:
    threshold = 85.5
    selected = [
        item.name for item in items
        if item.score >= threshold
    ]
    if not selected:
        return "暂无符合条件的项目"
    return f"已选 {len(selected)} 项：" + ", ".join(selected)


projects = [Project("Hatsume", 96.0)]
print(summarize(projects))
```

行内代码：`threshold = 85.5` · 浅色卡片 / Python
