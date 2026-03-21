# 系统库
import os
import sys
import time
import requests
import zipfile
import shutil
from pathlib import Path

# 项目内部库
from app.import_process.agent.state import ImportGraphState
from app.utils.task_utils import add_running_task, add_done_task
from app.conf.mineru_config import mineru_config
from app.core.logger import logger  # 统一日志工具

# MinerU配置（缓存配置信息）
MINERU_BASE_URL = mineru_config.base_url
MINERU_API_TOKEN = mineru_config.api_token

def node_pdf_to_md(state: ImportGraphState) -> ImportGraphState:
    """
    节点: PDF转Markdown (node_pdf_to_md)
    为什么叫这个名字: 核心任务是将 PDF 非结构化数据转换为 Markdown 结构化数据。
    未来要实现:
    1.进入日志和任务状态的设置
    2、进行参数校验 local_dir ->给默认值
    3、 调用 MinerU (magic-pdf) 工具进行pdf解析 返回一个下载文件地址 xx.zip url地址
    4. 下载zip包，解析和提取(local_dir
    5、把md_path地址进行复制，读取md文件内容 md_content赋值 将 PDF 转换成 Markdown 格式。
    3. 将结果保存到 state["md_content"]。
    """

    function_name = sys._getframe().f_code.co_name  # 当前帧 的name 就是函数名
    logger.info(f">>>[{function_name}]开始执行了，现在的状态为：{state} ")
    add_running_task(state['task_id'], function_name)


    try:
        # 步骤1：校验PDF路径和输出目录
        pdf_path_obj, output_dir_obj = step_1_validate_paths(state)

        # 步骤2：上传PDF至MinerU并轮询解析结果
        zip_url = step_2_upload_and_poll(pdf_path_obj, output_dir_obj)

        # 步骤3：下载ZIP包并提取MD文件
        md_path = step_3_download_and_extract(zip_url, output_dir_obj, pdf_path_obj.stem)


        # 更新工作流状态：记录MD文件路径和内容
        state["md_path"] = md_path
        logger.info(f"【{func_name}】MD文件生成成功，路径：{md_path}")

        # 读取MD文件内容，捕获异常仅警告不终止
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                state["md_content"] = f.read()
            logger.debug(f"【{func_name}】MD文件内容读取成功，内容长度：{len(state['md_content'])}字符")
        except Exception as e:
            logger.error(f"【{func_name}】读取MD文件内容失败：{str(e)}")

        logger.info(f"【{func_name}】节点执行完成，更新后工作流状态键：{list(state.keys())}")
    except Exception as e:
        #处理异常
        logger.error(f">>>[{function_name}]再使用minerU解析发生了异常，异常信息为:{e} ")
        raise #终止工作流
    finally:

        # 结束：记录节点运行状态
        add_done_task(state["task_id"], func_name)
        #4.结束节点的日志输出【节点+核心参数】 记录任务状态【哪个任务结束了】-> 给前端推送消息（埋点）
        logger.info(f">>>[{function_name}]执行结束了，现在的状态为：{state} ")
        add_done_task(state['task_id'], function_name)

    return state