# MCP Servers

为 AIOps 智能诊断提供日志查询和监控数据工具。

## 📚 服务列表

### CLS Server (`cls_server.py`)
**日志查询服务** - 端口 8003

**核心工具：**
- `get_current_timestamp` - 获取当前时间戳
- `get_topic_info_by_name` - 查询日志主题
- `search_log` - 日志搜索
- `search_service_logs` - 服务日志查询（支持级别筛选）
- `analyze_log_pattern` - 日志模式分析

**AIOps 只读工具（防腐墙示例）：**
- `get_error_logs` - 设备异常日志查询（代理上游 HTTP，带脱敏/裁剪/摘要）

### Monitor Server (`monitor_server.py`)
**监控数据服务** - 端口 8004

**核心工具：**
- `query_cpu_metrics` - CPU 使用率查询
- `query_memory_metrics` - 内存使用查询
- `query_process_list` - 进程列表
- `search_historical_tickets` - 历史工单查询
- `get_service_info` / `list_all_services` - 服务信息

**AIOps 只读工具（防腐墙示例）：**
- `get_scada_status` - 设备 SCADA 状态查询（代理上游 HTTP，输出结构化特征）

### Chrome CDP Server (`chrome_cdp_server.py`)
**浏览器查询服务（可选）** - 端口 8005

基于 `chrome-cdp-skill` 提供浏览器标签页查询和页面交互能力。

**核心工具：**
- `chrome_list_tabs` - 列出当前标签页
- `chrome_snapshot` - 获取页面语义快照
- `chrome_html` - 获取页面 HTML（可选选择器）
- `chrome_navigate` - 页面导航
- `chrome_click` / `chrome_type` - 基础交互

## 🚀 快速开始

### 安装依赖
```bash
pip install fastmcp
```

### 启动服务

**方式一：使用 Makefile（推荐）**
```bash
make mcp-start   # 启动所有 MCP 服务
make mcp-stop    # 停止所有 MCP 服务
make mcp-status  # 查看服务状态
```

**方式二：手动启动**
```bash
python mcp_servers/cls_server.py
python mcp_servers/monitor_server.py
python mcp_servers/chrome_cdp_server.py
```

### Chrome CDP 可选配置

在启动 `chrome_cdp_server.py` 前，请先安装 Node.js 22+，并准备 `chrome-cdp-skill`。

可通过以下环境变量指定脚本路径（二选一）：

- `CHROME_CDP_SCRIPT`：直接指向 `scripts/cdp.mjs`
- `CHROME_CDP_SKILL_DIR`：指向 `chrome-cdp-skill` 根目录

示例：

```bash
export CHROME_CDP_SKILL_DIR=/path/to/chrome-cdp-skill
python mcp_servers/chrome_cdp_server.py
```

应用侧默认不会启用 Chrome MCP。若需启用，请在环境变量中设置：

```bash
MCP_CHROME_ENABLED=true
MCP_CHROME_URL=http://localhost:8005/mcp
```

## 💡 使用示例

### AIOps 诊断场景

```
用户: data-sync-service 出现告警，请排查

Agent 自动执行:
1. list_all_services() → 查看所有服务状态
2. get_service_info("data-sync-service") → 获取服务详情
3. query_cpu_metrics("data-sync-service") → CPU 趋势分析
4. search_service_logs("data-sync-service", level="error") → 错误日志
5. analyze_log_pattern("data-sync-service") → 日志模式分析
6. search_historical_tickets(service_name="data-sync-service") → 历史工单
7. 综合分析 → 生成诊断报告和修复建议
```

### 工具参数示例

**查询 CPU 指标：**
```python
query_cpu_metrics(
    service_name="data-sync-service",
    start_time="2024-02-14 02:00:00",
    interval="1m"
)
```

**搜索错误日志：**
```python
search_service_logs(
    service_name="data-sync-service",
    log_level="error",
    keyword="timeout",
    limit=100
)
```

**搜索历史工单：**
```python
search_historical_tickets(
    service_name="data-sync-service",
    issue_type="cpu",
    limit=10
)
```

## 🔧 高级配置

### 接入真实 API

当前返回模拟数据。接入真实 API 步骤：

#### AIOps（SCADA / 日志）HTTP 代理配置

这两类工具的上游真实调用被封装在 MCP Server 内部，Agent 侧只依赖稳定的工具名/参数/返回结构。

**SCADA：`get_scada_status`（Monitor Server）**

- `SCADA_HTTP_BASE_URL`：上游基础地址，例如 `http://scada-gateway.internal:8080`
- `SCADA_STATUS_PATH`：接口路径（默认 `/scada/status`）
- `SCADA_HTTP_TOKEN`：可选，Bearer Token
- `SCADA_HTTP_TIMEOUT_S`：可选，默认 `5`
- `SCADA_HTTP_RETRIES`：可选，默认 `2`

未配置 `SCADA_HTTP_BASE_URL` 时，工具会返回 `source=mock` 的模拟数据，便于本地演示与联调。

**日志：`get_error_logs`（CLS Server）**

- `LOG_HTTP_BASE_URL`：上游基础地址，例如 `http://log-search.internal:8081`
- `LOG_SEARCH_PATH`：接口路径（默认 `/logs/search`）
- `LOG_HTTP_TOKEN`：可选，Bearer Token
- `LOG_HTTP_TIMEOUT_S`：可选，默认 `6`
- `LOG_HTTP_RETRIES`：可选，默认 `2`

未配置 `LOG_HTTP_BASE_URL` 时，工具会返回 `source=mock` 的模拟数据。

**腾讯云 CLS：**
```bash
# 安装 SDK
pip install tencentcloud-sdk-python

# 配置环境变量
export TENCENTCLOUD_SECRET_ID="your-id"
export TENCENTCLOUD_SECRET_KEY="your-key"

# 在 cls_server.py 中集成
from tencentcloud.cls.v20201016 import cls_client
```

**其他监控系统：**
- Prometheus
- Grafana
- 云监控（腾讯云/阿里云/AWS）
- 自建监控平台

### 自定义 Mock 数据

修改各 Server 文件中的数据生成逻辑，模拟实际场景。

## 📚 参考资料

- [FastMCP 文档](https://github.com/jlowin/fastmcp)
- [MCP 协议](https://modelcontextprotocol.io/)
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
- [主项目 README](../README.md)

---

**注意**: 当前版本返回模拟数据，生产环境需配置真实 API。
