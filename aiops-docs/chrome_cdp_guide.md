# Chrome CDP 浏览器工具使用指南

## 概述

Chrome CDP（Chrome DevTools Protocol）工具允许 AIOps 助手操控浏览器，实现网页信息抓取、自动化操作等功能。

## 可用工具

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `chrome_list_tabs` | 列出所有已打开的浏览器标签页 | 无 |
| `chrome_open` | 打开新标签页 | `url`（可选） |
| `chrome_navigate` | 将指定标签页导航到新 URL | `target`（targetId前缀）, `url` |
| `chrome_snapshot` | 获取页面语义快照（无障碍树） | `target`（targetId前缀） |
| `chrome_html` | 获取页面完整 HTML | `target`, `selector`（可选CSS选择器） |
| `chrome_click` | 点击页面元素 | `target`, `selector`（CSS选择器） |
| `chrome_type` | 在焦点元素中输入文本 | `target`, `text` |

## 重要规则

### 1. targetId 的获取

`chrome_navigate`、`chrome_snapshot`、`chrome_click`、`chrome_html`、`chrome_type` 都需要 `target` 参数，该参数是标签页 ID 的前缀（一般为 8 位十六进制字符串，如 `16102206`）。

获取 targetId 的两种方式：
- **方式一**（推荐）：使用 `chrome_open(url)` 打开新标签页，返回结果中的 `stdout` 包含新标签页的 targetId 前缀
- **方式二**：使用 `chrome_list_tabs()` 获取所有标签页列表及其 targetId 前缀

### 2. 标准操作流程

**打开新网页并抓取内容：**
```
1. chrome_open("https://目标网址") → 获得 targetId
2. chrome_snapshot(targetId) → 获取页面语义快照
3. 解析快照中的文字内容
```

**在已有标签页中操作：**
```
1. chrome_list_tabs() → 获得所有标签页的 targetId
2. chrome_navigate(targetId, "https://目标网址") → 导航到目标页面
3. chrome_snapshot(targetId) → 获取页面内容
```

### 3. chrome_snapshot 的特点

- 返回的是页面的**语义快照**（类似无障碍树），不是原始 HTML
- 包含所有可见文字、链接、按钮等元素的结构化信息
- 快照中的标签如 `[link]`、`[StaticText]`、`[heading]`、`[textbox]` 等
- 对于提取页面关键信息（标题、排名、数据等）非常有效
- 如果快照内容不够，可以再使用 `chrome_html` 获取完整 HTML

### 4. 常见网页的 URL

**哔哩哔哩：**
- 首页：`https://www.bilibili.com/`
- 热搜/排行榜：`https://www.bilibili.com/v/popular/rank/all`
- 动态（登录用户的关注动态）：`https://t.bilibili.com/`
- 用户空间动态（需要用户ID）：`https://space.bilibili.com/<用户ID>/dynamic`

**其他：**
- 微博热搜：`https://weibo.com/hot/search`
- 知乎热榜：`https://www.zhihu.com/hot`

**重要：永远不要编造 URL！如果不知道某个页面的确切 URL，先使用 chrome_list_tabs 查看已打开的标签页，或者使用搜索引擎查找正确的 URL。**

## 示例：获取 B 站排行榜前 5 名

```
步骤1: 使用 chrome_list_tabs() 获取已有标签页列表
步骤2: 选择一个标签页的 targetId，使用 chrome_navigate(targetId, "https://www.bilibili.com/v/popular/rank/all") 导航到排行榜
步骤3: 使用 chrome_snapshot(targetId) 获取页面快照
步骤4: 从快照中提取排名 1-5 的标题、UP主和播放量数据
```
