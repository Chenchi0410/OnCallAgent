"""
Executor 节点：执行单个步骤
基于 LangGraph 官方教程实现
"""

import json
from typing import Dict, Any, Sequence
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_qwq import ChatQwen
from langgraph.prebuilt import ToolNode
from loguru import logger

from app.config import config
from app.tools import get_current_time, retrieve_knowledge
from app.agent.mcp_client import get_mcp_client_with_retry
from .state import PlanExecuteState


MAX_TOOL_CALLS_PER_STEP = 2


def _serialize_tool_args(args: Any) -> str:
    """将 tool args 序列化为稳定字符串，用于去重键。"""
    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return str(args)


def _dedupe_and_limit_tool_calls(tool_calls: Sequence[Any]) -> list[Any]:
    """同名同参去重，并限制单步最大工具调用数。"""
    deduped: list[Any] = []
    seen_keys: set[str] = set()

    for tool_call in tool_calls:
        name = tool_call.get("name", "")
        args = tool_call.get("args", {})
        dedupe_key = f"{name}:{_serialize_tool_args(args)}"

        if dedupe_key in seen_keys:
            continue

        seen_keys.add(dedupe_key)
        deduped.append(tool_call)

    return deduped[:MAX_TOOL_CALLS_PER_STEP]


async def executor(state: PlanExecuteState) -> Dict[str, Any]:
    """
    执行节点：执行计划中的下一个步骤
    
    使用 LangGraph 的 ToolNode 自动处理工具调用
    """
    logger.info("=== Executor：执行步骤 ===")

    plan = state.get("plan", [])

    # 如果计划为空，不执行
    if not plan:
        logger.info("计划为空，跳过执行")
        return {}

    # 取出第一个步骤
    task = plan[0]
    logger.info(f"当前任务: {task}")

    try:
        # 获取本地工具
        local_tools = [
            get_current_time,
            retrieve_knowledge
        ]

        # 获取 MCP 工具
        mcp_client = await get_mcp_client_with_retry()
        mcp_tools = await mcp_client.get_tools()
        logger.info(f"可用工具数量: 本地 {len(local_tools)} + MCP {len(mcp_tools)}")

        # 合并所有工具
        all_tools = local_tools + mcp_tools

        # 创建 LLM（绑定工具）
        llm = ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            temperature=0
        )
        llm_with_tools = llm.bind_tools(all_tools)

        # 创建工具节点（自动执行工具调用）
        tool_node = ToolNode(all_tools)

        # 获取上一步的执行结果，作为当前步骤的上下文
        past_steps = state.get("past_steps", [])
        prev_context = ""
        if past_steps:
            last_step, last_result = past_steps[-1]
            # 截取上一步结果的关键信息（不超过 2000 字符）
            result_preview = last_result[:2000] if len(last_result) > 2000 else last_result
            prev_context = f"\n\n## 上一步的执行结果\n上一步任务: {last_step}\n上一步结果: {result_preview}"

        # 构建消息
        messages = [
            SystemMessage(content="""你是一个能力强大的助手，负责执行具体的任务步骤。

你可以使用各种工具来完成任务。对于每个步骤：
1. 理解步骤的目标
2. 选择合适的工具，如果已经指定了工具，则使用指定的工具
3. 调用工具获取信息
4. 返回执行结果

## 关键规则

- **数据提取而非总结**：当使用 chrome_snapshot 或 chrome_html 获取网页内容后，你必须从返回的原始数据中**逐条提取**相关信息（如标题、排名、数据），直接列出提取到的具体内容
- **传递原始关键数据**：如果步骤要求"提取"或"获取"信息，你的响应中必须包含提取到的具体数据，而不是简单地说"已获取到页面内容"
- 如果工具调用失败，请说明失败原因
- 不要编造数据，只返回实际获取的信息
- 专注于当前步骤，不要考虑其他任务

浏览器工具（chrome_*）使用注意事项：
- chrome_open(url) 会打开新标签页并返回 targetId。如果上一步已通过 chrome_open 获得 targetId，直接使用该 targetId，无需再次 list_tabs
- chrome_snapshot(target) 的 target 参数从上一步结果中获取（如 targetId: 81462CB3），不要编造
- chrome_navigate(target, url) 中的 target 必须是有效的标签页 targetId，不能编造"""),
            HumanMessage(content=f"请执行以下任务: {task}{prev_context}")
        ]

        # 第一步：LLM 决定是否调用工具
        llm_response = await llm_with_tools.ainvoke(messages)
        logger.info(f"LLM 响应类型: {type(llm_response)}")

        # 第二步：如果有工具调用，执行工具
        if hasattr(llm_response, "tool_calls") and llm_response.tool_calls:
            original_count = len(llm_response.tool_calls)
            filtered_tool_calls = _dedupe_and_limit_tool_calls(llm_response.tool_calls)
            filtered_count = len(filtered_tool_calls)
            logger.info(f"检测到 {original_count} 个工具调用，过滤后执行 {filtered_count} 个")

            if filtered_count < original_count:
                logger.warning(
                    "工具调用已做去重/限流: 原始={}, 过滤后={}, 上限={}",
                    original_count,
                    filtered_count,
                    MAX_TOOL_CALLS_PER_STEP,
                )

            if hasattr(llm_response, "model_copy"):
                llm_response = llm_response.model_copy(update={"tool_calls": filtered_tool_calls})
            elif hasattr(llm_response, "copy"):
                llm_response = llm_response.copy(update={"tool_calls": filtered_tool_calls})
            
            # 使用 ToolNode 自动执行工具
            messages.append(llm_response)
            tool_messages = await tool_node.ainvoke({"messages": messages})

            # 判断是否为数据提取类步骤：快照、html、提取、获取页面内容等
            is_extraction_step = any(kw in task for kw in ["快照", "snapshot", "提取", "html", "获取页面"])

            if is_extraction_step:
                # 数据提取步骤：直接使用工具原始输出，不经过 LLM 二次合成
                raw_results: list[str] = []
                for tm in tool_messages.get("messages", []):
                    content = getattr(tm, "content", str(tm))
                    if isinstance(content, str):
                        raw_results.append(content)
                    else:
                        raw_results.append(str(content))
                result = "\n\n".join(raw_results)
                logger.info(f"数据提取步骤，直接返回工具原始输出，长度: {len(result)}")
            else:
                # 第三步：将工具结果返回给 LLM 生成最终答案
                messages.extend(tool_messages["messages"])
                final_response = await llm_with_tools.ainvoke(messages)
                result = final_response.content if hasattr(final_response, 'content') else str(final_response)
        else:
            # 没有工具调用，直接使用 LLM 的输出
            logger.info("LLM 未调用工具，直接返回结果")
            result = llm_response.content if hasattr(llm_response, 'content') else str(llm_response)

        logger.info(f"步骤执行完成，结果长度: {len(result)}")

        # 返回更新：移除已执行的步骤，添加执行历史
        return {
            "plan": plan[1:],  # 移除第一个步骤
            "past_steps": [(task, result)],  # 使用 operator.add 追加
        }

    except Exception as e:
        logger.error(f"执行步骤失败: {e}", exc_info=True)
        return {
            "plan": plan[1:],
            "past_steps": [(task, f"执行失败: {str(e)}")],
        }
