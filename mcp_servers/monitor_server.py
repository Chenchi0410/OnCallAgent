"""智能运维监控 MCP Server

本地实现的监控服务 MCP Server，提供：
- 监控数据查询（CPU、内存、磁盘、网络等）
- 进程信息查询
- 历史工单查询
- 服务信息查询

用于支持运维 Agent 的故障排查场景。
"""

import logging
import functools
import json
import os
import random
import time
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from fastmcp import FastMCP
import httpx

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Monitor_MCP_Server")

mcp = FastMCP("Monitor")


def log_tool_call(func):
    """装饰器：记录工具调用的日志，包括方法名、参数和返回状态"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        method_name = func.__name__

        # 记录调用信息
        logger.info(f"=" * 80)
        logger.info(f"调用方法: {method_name}")

        # 记录参数（排除self等）
        if kwargs:
            # 使用 json.dumps 格式化参数，处理可能的序列化错误
            try:
                params_str = json.dumps(kwargs, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                params_str = str(kwargs)
            logger.info(f"参数信息:\n{params_str}")
        else:
            logger.info("参数信息: 无")

        # 执行方法
        try:
            result = func(*args, **kwargs)

            # 记录返回状态
            logger.info(f"返回状态: SUCCESS")

            # 记录返回结果摘要（避免日志过长）
            if isinstance(result, dict):
                summary = {k: v if not isinstance(v, (list, dict)) else f"<{type(v).__name__} with {len(v)} items>"
                          for k, v in list(result.items())[:5]}
                logger.info(f"返回结果摘要: {json.dumps(summary, ensure_ascii=False)}")
            else:
                logger.info(f"返回结果: {result}")

            logger.info(f"=" * 80)
            return result

        except Exception as e:
            # 记录错误状态
            logger.error(f"返回状态: ERROR")
            logger.error(f"错误信息: {str(e)}")
            logger.error(f"=" * 80)
            raise

    return wrapper


# ============================================================
# 辅助函数
# ============================================================

def parse_time_or_default(time_str: Optional[str], default_offset_hours: int = 0) -> datetime:
    """解析时间字符串或返回默认时间。

    Args:
        time_str: 时间字符串（格式：YYYY-MM-DD HH:MM:SS）
        default_offset_hours: 默认时间偏移（小时）

    Returns:
        datetime: 解析后的时间对象
    """
    if time_str:
        try:
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    # 返回默认时间（当前时间 + 偏移）
    return datetime.now() + timedelta(hours=default_offset_hours)


def generate_time_series(base_time: datetime, minutes_offset: int, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """生成时间序列字符串。

    Args:
        base_time: 基准时间
        minutes_offset: 分钟偏移量
        format_str: 时间格式字符串

    Returns:
        str: 格式化的时间字符串
    """
    result_time = base_time + timedelta(minutes=minutes_offset)
    return result_time.strftime(format_str)


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value if value is not None and value != "" else default


def _sanitize_scada_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    forbidden_keys = {
        "token",
        "access_token",
        "password",
        "secret",
        "api_key",
        "gps",
        "location",
        "coordinates",
    }
    sanitized: Dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in forbidden_keys:
            continue
        sanitized[key] = value
    return sanitized


def _http_post_json(
    url: str,
    json_body: Dict[str, Any],
    headers: Dict[str, str],
    timeout_s: float,
    max_retries: int,
) -> Dict[str, Any]:
    last_error: str | None = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(url, json=json_body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    return data
                return {"data": data}
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_error = f"network_error: {e}"
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 400 <= status < 500:
                return {
                    "success": False,
                    "error": {
                        "type": "upstream_http_4xx",
                        "status": status,
                        "message": e.response.text[:800],
                        "retryable": False,
                    },
                }
            last_error = f"upstream_http_{status}: {e.response.text[:200]}"
        except Exception as e:
            last_error = f"unexpected_error: {e}"

        if attempt < max_retries:
            time.sleep(0.3 * (2**attempt))

    return {
        "success": False,
        "error": {
            "type": "upstream_unavailable",
            "message": (last_error or "unknown")[:800],
            "retryable": True,
        },
    }


@mcp.tool()
@log_tool_call
def get_scada_status(
    device_id: str,
    metrics: List[str],
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    interval: str = "1m",
    limit_points: int = 60,
) -> Dict[str, Any]:
    """查询设备的 SCADA 状态（通过 HTTP 代理上游系统）。

    该工具体现 MCP 作为“防腐墙”的价值：
    - 参数校验与默认时间窗
    - 弱网重试/超时
    - 返回结构化特征（避免把原始大报文塞进上下文）
    - 脱敏裁剪敏感字段

    Args:
        device_id: 井号/设备号（必填）
        metrics: 指标名列表（必填），例如 ["pressure", "load", "current"]
        start_time: 开始时间（可选，格式 "YYYY-MM-DD HH:MM:SS"；默认当前时间-30分钟）
        end_time: 结束时间（可选，格式 "YYYY-MM-DD HH:MM:SS"；默认当前时间）
        interval: 聚合粒度（可选），例如 "1m"/"5m"/"1h"
        limit_points: 每个指标最大点数（可选，默认 60）

    Returns:
        Dict: 结构化状态特征
            - success: 是否成功
            - device_id, metrics, time_range, interval
            - features: 每个指标的统计特征（min/max/avg/last、是否突变等）
            - raw_trace_id: 原始数据追踪 ID（用于审计/复查）
            - source: "http" 或 "mock"
    """
    if not device_id or not device_id.strip():
        return {
            "success": False,
            "error": {"type": "invalid_params", "message": "device_id 不能为空", "retryable": False},
        }

    metrics = [m.strip() for m in metrics if isinstance(m, str) and m.strip()]
    if not metrics:
        return {
            "success": False,
            "error": {"type": "invalid_params", "message": "metrics 不能为空", "retryable": False},
        }

    end_dt = parse_time_or_default(end_time, default_offset_hours=0)
    start_dt = parse_time_or_default(start_time, default_offset_hours=0)
    if start_time is None:
        start_dt = end_dt - timedelta(minutes=30)

    if start_dt > end_dt:
        return {
            "success": False,
            "error": {
                "type": "invalid_params",
                "message": "start_time 不能晚于 end_time",
                "retryable": False,
            },
        }

    trace_id = f"scada_{uuid.uuid4().hex[:12]}"

    base_url = _env("SCADA_HTTP_BASE_URL", "")
    path = _env("SCADA_STATUS_PATH", "/scada/status")
    token = _env("SCADA_HTTP_TOKEN", "")
    timeout_s = float(_env("SCADA_HTTP_TIMEOUT_S", "5"))
    max_retries = int(_env("SCADA_HTTP_RETRIES", "2"))

    time_range = {
        "start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
    }

    if base_url:
        url = base_url.rstrip("/") + path
        headers: Dict[str, str] = {"x-trace-id": trace_id}
        if token:
            headers["authorization"] = f"Bearer {token}"

        payload = {
            "device_id": device_id,
            "metrics": metrics,
            "time_range": time_range,
            "interval": interval,
            "limit_points": limit_points,
        }

        upstream = _http_post_json(
            url=url,
            json_body=payload,
            headers=headers,
            timeout_s=timeout_s,
            max_retries=max_retries,
        )

        if upstream.get("success") is False and "error" in upstream:
            upstream["device_id"] = device_id
            upstream["metrics"] = metrics
            upstream["time_range"] = time_range
            upstream["raw_trace_id"] = trace_id
            upstream["source"] = "http"
            return upstream

        raw_data = upstream.get("data", upstream)
        raw_data = raw_data if isinstance(raw_data, dict) else {"data": raw_data}
        raw_data = _sanitize_scada_payload(raw_data)

        features: Dict[str, Any] = {}
        points_by_metric = raw_data.get("points") or raw_data.get("data_points") or {}
        if isinstance(points_by_metric, dict):
            for metric in metrics:
                points = points_by_metric.get(metric)
                if not isinstance(points, list):
                    continue
                values = [p.get("value") for p in points if isinstance(p, dict) and isinstance(p.get("value"), (int, float))]
                if not values:
                    continue
                values_sorted = sorted(values)
                last_value = values[-1]
                features[metric] = {
                    "count": len(values),
                    "min": float(values_sorted[0]),
                    "max": float(values_sorted[-1]),
                    "avg": float(round(sum(values) / len(values), 4)),
                    "last": float(last_value),
                }

        return {
            "success": True,
            "device_id": device_id,
            "metrics": metrics,
            "time_range": time_range,
            "interval": interval,
            "features": features,
            "raw_trace_id": trace_id,
            "source": "http",
        }

    features: Dict[str, Any] = {}
    for metric in metrics:
        base = 10.0 + random.uniform(-1, 1)
        last = base + random.uniform(0, 20)
        features[metric] = {
            "count": min(limit_points, 30),
            "min": round(min(base, last), 3),
            "max": round(max(base, last), 3),
            "avg": round((base + last) / 2.0, 3),
            "last": round(last, 3),
        }

    return {
        "success": True,
        "device_id": device_id,
        "metrics": metrics,
        "time_range": time_range,
        "interval": interval,
        "features": features,
        "raw_trace_id": trace_id,
        "source": "mock",
    }





# ============================================================
# 监控数据查询工具
# ============================================================

@mcp.tool()
@log_tool_call
def query_cpu_metrics(
    service_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    interval: str = "1m"
) -> Dict[str, Any]:
    """查询服务的 CPU 使用率监控数据。

    Args:
        service_name: 服务名称（必填）
            示例: "data-sync-service"
        
        start_time: 开始时间（可选，字符串类型）
            格式: "YYYY-MM-DD HH:MM:SS"
            示例: "2026-02-14 10:00:00"
            默认值: 如果不传，默认为当前时间的1小时前
            注意: 必须使用字符串格式，而非时间戳
        
        end_time: 结束时间（可选，字符串类型）
            格式: "YYYY-MM-DD HH:MM:SS"
            示例: "2026-02-14 11:00:00"
            默认值: 如果不传，默认为当前时间
            注意: 必须使用字符串格式，而非时间戳
        
        interval: 数据聚合间隔（可选）
            可选值: "1m" (1分钟), "5m" (5分钟), "1h" (1小时)
            默认值: "1m"
            说明: 控制数据点的时间间隔

    Returns:
        Dict: CPU 监控数据
            - service_name: 服务名称
            - metric_name: 指标名称 (cpu_usage_percent)
            - interval: 数据聚合间隔
            - data_points: 数据点列表，每个点包含:
                * timestamp: 时间点（格式: HH:MM）
                * value: CPU 使用率百分比
            - statistics: 统计信息
                * average: 平均值
                * max: 最大值
                * min: 最小值
            - alert: 告警信息（如有）
                * triggered: 是否触发告警
                * threshold: 告警阈值
                * message: 告警消息
    
    使用示例:
        # 示例1: 使用默认时间（最近1小时）
        query_cpu_metrics(service_name="data-sync-service")
        
        # 示例2: 指定时间范围
        query_cpu_metrics(
            service_name="data-sync-service",
            start_time="2026-02-14 10:00:00",
            end_time="2026-02-14 11:00:00",
            interval="5m"
        )
        
        # 示例3: 只指定开始时间（结束时间自动为当前时间）
        query_cpu_metrics(
            service_name="data-sync-service",
            start_time="2026-02-14 10:00:00"
        )
    """
    # 解析时间参数
    start_dt = parse_time_or_default(start_time, default_offset_hours=-1)
    end_dt = parse_time_or_default(end_time, default_offset_hours=0)
    
    # 解析间隔时间（interval: 1m, 5m, 1h 等）
    interval_minutes = 1  # 默认 1 分钟
    if interval.endswith('m'):
        interval_minutes = int(interval[:-1])
    elif interval.endswith('h'):
        interval_minutes = int(interval[:-1]) * 60

    # 动态生成 CPU 使用率数据：从低到高逐渐增长
    data_points = []
    current_time = start_dt
    time_index = 0

    # 初始 CPU 使用率（10%）
    base_cpu = 10.0

    while current_time <= end_dt:
        # CPU 使用率逐渐升高的算法：
        # - 前几个数据点保持在 10% 左右
        # - 然后开始快速上升
        # - 最终达到 95% 左右

        if time_index < 3:
            # 初始阶段：10% 左右波动
            cpu_value = base_cpu + (time_index * 0.5)
        else:
            # 上升阶段：使用指数增长模型
            growth_factor = (time_index - 2) * 8.5
            cpu_value = min(base_cpu + growth_factor, 96.0)

        # 添加一些随机波动（±2%）
        cpu_value = round(cpu_value + random.uniform(-2, 2), 1)
        cpu_value = max(0, min(100, cpu_value))  # 确保在 0-100 范围内

        data_point = {
            "timestamp": current_time.strftime("%H:%M"),
            "value": cpu_value,
            "process_id": "pid-12345"
        }

        data_points.append(data_point)

        # 下一个时间点
        current_time += timedelta(minutes=interval_minutes)
        time_index += 1

    # 计算统计信息
    if data_points:
        values = [d["value"] for d in data_points]
        avg_value = round(sum(values) / len(values), 2)
        max_value = max(values)
        min_value = min(values)

        # 检测是否有 CPU 突增（超过 80%）
        spike_detected = max_value > 80.0

        return {
            "service_name": service_name,
            "metric_name": "cpu_usage_percent",
            "interval": interval,
            "data_points": data_points,
            "statistics": {
                "avg": avg_value,
                "max": max_value,
                "min": min_value,
                "p95": round(sorted(values)[int(len(values) * 0.95)] if len(values) > 1 else max_value, 2),
                "spike_detected": spike_detected
            },
            "alert_info": {
                "triggered": spike_detected,
                "threshold": 80.0,
                "message": "CPU 使用率持续超过 80% 阈值" if spike_detected else "CPU 使用率正常"
            }
        }
    else:
        return {
            "service_name": service_name,
            "metric_name": "cpu_usage_percent",
            "interval": interval,
            "data_points": [],
            "statistics": {},
        }


@mcp.tool()
@log_tool_call
def query_memory_metrics(
    service_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    interval: str = "1m"
) -> Dict[str, Any]:
    """查询服务的内存使用监控数据。

    Args:
        service_name: 服务名称（必填）
            示例: "data-sync-service"
        
        start_time: 开始时间（可选，字符串类型）
            格式: "YYYY-MM-DD HH:MM:SS"
            示例: "2026-02-14 10:00:00"
            默认值: 如果不传，默认为当前时间的1小时前
            注意: 必须使用字符串格式，而非时间戳
        
        end_time: 结束时间（可选，字符串类型）
            格式: "YYYY-MM-DD HH:MM:SS"
            示例: "2026-02-14 11:00:00"
            默认值: 如果不传，默认为当前时间
            注意: 必须使用字符串格式，而非时间戳
        
        interval: 数据聚合间隔（可选）
            可选值: "1m" (1分钟), "5m" (5分钟), "1h" (1小时)
            默认值: "1m"

    Returns:
        Dict: 内存监控数据
            - service_name: 服务名称
            - metric_name: 指标名称 (memory_usage_percent)
            - interval: 数据聚合间隔
            - data_points: 数据点列表，每个点包含:
                * timestamp: 时间点（格式: HH:MM）
                * value: 内存使用率百分比
                * used_gb: 已使用内存（GB）
                * total_gb: 总内存（GB）
            - statistics: 统计信息
                * average: 平均值
                * max: 最大值
                * min: 最小值
            - alert: 告警信息（如有）
                * triggered: 是否触发告警
                * threshold: 告警阈值
                * message: 告警消息
    
    使用示例:
        # 示例1: 使用默认时间（最近1小时）
        query_memory_metrics(service_name="data-sync-service")
        
        # 示例2: 指定时间范围
        query_memory_metrics(
            service_name="data-sync-service",
            start_time="2026-02-14 10:00:00",
            end_time="2026-02-14 11:00:00",
            interval="5m"
        )
    """
    # 解析时间参数
    start_dt = parse_time_or_default(start_time, default_offset_hours=-1)
    end_dt = parse_time_or_default(end_time, default_offset_hours=0)
    
    # 解析间隔时间（interval: 1m, 5m, 1h 等）
    interval_minutes = 1  # 默认 1 分钟
    if interval.endswith('m'):
        interval_minutes = int(interval[:-1])
    elif interval.endswith('h'):
        interval_minutes = int(interval[:-1]) * 60
    
    # 动态生成内存使用率数据：从低到高逐渐增长
    data_points = []
    current_time = start_dt
    time_index = 0
    
    # 初始内存使用率（30%）
    base_memory = 30.0
    total_gb = 8.0  # 总内存 8GB
    
    while current_time <= end_dt:
        # 内存使用率逐渐升高的算法：
        # - 前几个数据点保持在 30% 左右
        # - 然后开始逐步上升
        # - 最终达到 85% 左右
        
        if time_index < 3:
            # 初始阶段：30% 左右波动
            memory_value = base_memory + (time_index * 1.0)
        else:
            # 上升阶段：使用线性增长模型（内存增长比 CPU 慢）
            growth_factor = (time_index - 2) * 5.5
            memory_value = min(base_memory + growth_factor, 85.0)
        
        # 添加一些随机波动（±1%）
        memory_value = round(memory_value + random.uniform(-1, 1), 1)
        memory_value = max(0, min(100, memory_value))  # 确保在 0-100 范围内
        
        # 计算已使用内存（GB）
        used_gb = round((memory_value / 100.0) * total_gb, 2)
        
        data_point = {
            "timestamp": current_time.strftime("%H:%M"),
            "value": memory_value,
            "used_gb": used_gb,
            "total_gb": total_gb
        }
        
        data_points.append(data_point)
        
        # 下一个时间点
        current_time += timedelta(minutes=interval_minutes)
        time_index += 1
    
    # 计算统计信息
    if data_points:
        values = [d["value"] for d in data_points]
        avg_value = round(sum(values) / len(values), 2)
        max_value = max(values)
        min_value = min(values)
        
        # 检测是否有内存压力（超过 70%）
        memory_pressure = max_value > 70.0
        
        return {
            "service_name": service_name,
            "metric_name": "memory_usage_percent",
            "interval": interval,
            "data_points": data_points,
            "statistics": {
                "avg": avg_value,
                "max": max_value,
                "min": min_value,
                "p95": round(sorted(values)[int(len(values) * 0.95)] if len(values) > 1 else max_value, 2),
                "memory_pressure": memory_pressure
            },
            "alert_info": {
                "triggered": memory_pressure,
                "threshold": 70.0,
                "message": "内存使用率超过 70% 阈值，存在内存压力" if memory_pressure else "内存使用率正常"
            }
        }
    else:
        return {
            "service_name": service_name,
            "metric_name": "memory_usage_percent",
            "interval": interval,
            "data_points": [],
            "statistics": {},
            "error": "时间范围无效或没有生成数据点"
        }




if __name__ == "__main__":
    # 使用 streamable-http 模式，运行在 8004 端口
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8004, path="/mcp")
