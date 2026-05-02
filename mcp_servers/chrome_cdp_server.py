"""Chrome CDP MCP Server

通过 chrome-cdp-skill 提供浏览器查询能力。
该服务为可选增强能力，不影响现有 CLS / Monitor 服务。
"""

import functools
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Chrome_CDP_MCP_Server")

mcp = FastMCP("ChromeCDP")


def log_tool_call(func):
    """记录工具调用日志。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        method_name = func.__name__
        logger.info("=" * 80)
        logger.info(f"调用方法: {method_name}")

        if kwargs:
            try:
                params_str = json.dumps(kwargs, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                params_str = str(kwargs)
            logger.info(f"参数信息:\n{params_str}")
        else:
            logger.info("参数信息: 无")

        try:
            result = func(*args, **kwargs)
            logger.info("返回状态: SUCCESS")
            logger.info("=" * 80)
            return result
        except Exception as e:
            logger.error("返回状态: ERROR")
            logger.error(f"错误信息: {e}")
            logger.error("=" * 80)
            raise

    return wrapper


def _resolve_script_path() -> Path:
    """解析 chrome-cdp-skill 脚本路径。"""
    script_path_env = os.getenv("CHROME_CDP_SCRIPT", "").strip()
    if script_path_env:
        script_path = Path(script_path_env)
        if script_path.exists():
            return script_path

    skill_dir = os.getenv("CHROME_CDP_SKILL_DIR", "").strip()
    if skill_dir:
        candidates = [
            Path(skill_dir) / "scripts" / "cdp.mjs",
            Path(skill_dir) / "skills" / "chrome-cdp" / "scripts" / "cdp.mjs",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

    # 本仓库下的默认候选路径（便于本地开发）
    local_candidates = [
        Path(__file__).resolve().parents[1] / "chrome-cdp-skill-main" / "skills" / "chrome-cdp" / "scripts" / "cdp.mjs",
        Path(__file__).resolve().parents[1] / "chrome-cdp-skill" / "skills" / "chrome-cdp" / "scripts" / "cdp.mjs",
    ]
    for candidate in local_candidates:
        if candidate.exists():
            return candidate

    msg = (
        "未找到 chrome-cdp-skill 脚本。"
        "请设置环境变量 CHROME_CDP_SCRIPT 或 CHROME_CDP_SKILL_DIR。"
    )
    raise RuntimeError(msg)


def _run_cdp(args: List[str], timeout: int = 60) -> Dict[str, Any]:
    """调用 chrome-cdp-skill 命令。"""
    script_path = _resolve_script_path()

    cmd = ["node", str(script_path), *args]
    logger.info(f"执行命令: {' '.join(cmd)}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        return {
            "ok": False,
            "error": "未找到 node 命令，请先安装 Node.js 22+ 并加入 PATH。",
            "detail": str(e),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "error": f"命令执行超时（{timeout}s）",
            "detail": str(e),
        }

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    return {
        "ok": proc.returncode == 0,
        "return_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


@mcp.tool()
@log_tool_call
def chrome_list_tabs() -> Dict[str, Any]:
    """列出当前可用标签页。"""
    return _run_cdp(["list"])


@mcp.tool()
@log_tool_call
def chrome_open(url: Optional[str] = None) -> Dict[str, Any]:
    """打开新标签页（可选 URL）。"""
    args = ["open"]
    if url:
        args.append(url)
    return _run_cdp(args)


@mcp.tool()
@log_tool_call
def chrome_snapshot(target: str) -> Dict[str, Any]:
    """获取目标页面语义快照（snap）。

    Args:
        target: 目标页 targetId 前缀（来自 chrome_list_tabs 输出）
    """
    return _run_cdp(["snap", target])


@mcp.tool()
@log_tool_call
def chrome_html(target: str, selector: Optional[str] = None) -> Dict[str, Any]:
    """获取页面 HTML（可选 CSS 选择器）。"""
    args = ["html", target]
    if selector:
        args.append(selector)
    return _run_cdp(args)


@mcp.tool()
@log_tool_call
def chrome_navigate(target: str, url: str) -> Dict[str, Any]:
    """导航到指定 URL。"""
    return _run_cdp(["nav", target, url])


@mcp.tool()
@log_tool_call
def chrome_click(target: str, selector: str) -> Dict[str, Any]:
    """点击目标页面元素（CSS 选择器）。"""
    return _run_cdp(["click", target, selector])


@mcp.tool()
@log_tool_call
def chrome_type(target: str, text: str) -> Dict[str, Any]:
    """在当前焦点输入文本。"""
    return _run_cdp(["type", target, text])


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8005, path="/mcp")
