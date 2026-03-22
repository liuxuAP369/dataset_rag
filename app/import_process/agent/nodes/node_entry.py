import sys
from pathlib import Path

from app.core.logger import logger
from app.import_process.agent.state import ImportGraphState
from app.utils.task_utils import add_running_task, add_done_task


def _start_entry_task(state: ImportGraphState, function_name: str) -> None:
    """记录入口节点开始执行。"""
    logger.info(f">>>[{function_name}]开始执行了，现在的状态为：{state} ")
    add_running_task(state["task_id"], function_name)


def _finish_entry_task(state: ImportGraphState, function_name: str) -> None:
    """记录入口节点结束执行。"""
    logger.info(f">>>[{function_name}]执行结束了，现在的状态为：{state} ")
    add_done_task(state["task_id"], function_name)


def _get_local_file_path(state: ImportGraphState, function_name: str) -> str:
    """获取并校验输入文件路径。"""
    local_file_path = state["local_file_path"]
    if not local_file_path:
        logger.error(f"[{function_name}]检查发现没有输入文件，无法解析")
        return ""
    return local_file_path


def _write_file_title(state: ImportGraphState, local_file_path: str) -> None:
    """将文件标题写回状态，供后续节点兜底使用。"""
    state["file_title"] = Path(local_file_path).stem


def _apply_file_route(state: ImportGraphState, local_file_path: str, function_name: str) -> None:
    """根据文件类型设置入口节点的路由状态。"""
    file_suffix = Path(local_file_path).suffix.lower()

    if file_suffix == ".md":
        state["is_md_read_enabled"] = True
        state["is_pdf_read_enabled"] = False
        state["md_path"] = local_file_path
        return

    if file_suffix == ".pdf":
        state["is_pdf_read_enabled"] = True
        state["is_md_read_enabled"] = False
        state["pdf_path"] = local_file_path
        return

    logger.error(f"[{function_name}]文件格式非md或者pdf，无法解析")


def node_entry(state: ImportGraphState) -> ImportGraphState:
    """
    节点: 入口节点 (node_entry)
    作用:
    1. 记录节点开始/结束日志和任务状态
    2. 校验输入文件路径
    3. 根据输入文件类型设置路由标记
    4. 回写 file_title，供后续节点兜底使用
    """
    function_name = sys._getframe().f_code.co_name
    _start_entry_task(state, function_name)

    try:
        local_file_path = _get_local_file_path(state, function_name)
        if not local_file_path:
            return state

        _write_file_title(state, local_file_path)
        _apply_file_route(state, local_file_path, function_name)
        return state
    finally:
        _finish_entry_task(state, function_name)
