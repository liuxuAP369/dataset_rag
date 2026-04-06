# 导入基础库：系统、路径、类型注解（类型注解提升代码可读性和可维护性）
import os
import sys
from typing import List, Dict, Any, Tuple

from attr.validators import max_len
from onnxruntime.transformers.models.longformer.benchmark_longformer import find_onnx_model
# 导入Milvus客户端（向量数据库核心操作）、数据类型枚举（定义集合Schema）
from pymilvus import MilvusClient, DataType
# 导入LangChain消息类（标准化大模型对话消息格式）
from langchain_core.messages import SystemMessage, HumanMessage

from app.conf.milvus_config import milvus_config
# 导入自定义模块：
# 1. 流程状态载体：ImportGraphState为LangGraph流程的统一状态管理对象
from app.import_process.agent.state import ImportGraphState
# 2. Milvus工具：获取单例Milvus客户端，实现连接复用
from app.clients.milvus_utils import get_milvus_client
# 3. 大模型工具：获取大模型客户端，统一模型调用入口
from app.lm.lm_utils import get_llm_client
# 4. 向量工具：BGE-M3模型实例、向量生成方法（稠密+稀疏向量）
from app.lm.embedding_utils import get_bge_m3_ef, generate_embeddings
# 5. 稀疏向量工具：归一化处理，保证向量长度为1，提升检索准确性
from app.utils.normalize_sparse_vector import normalize_sparse_vector
# 6. 任务工具：更新任务运行状态，用于任务监控和管理
from app.utils.task_utils import add_running_task, add_done_task
# 7. 日志工具：项目统一日志入口，分级输出（info/warning/error）
from app.core.logger import logger
# 8. 提示词工具：加载本地prompt模板，实现提示词与代码解耦
from app.core.load_prompt import load_prompt

from app.utils.escape_milvus_string_utils import escape_milvus_string

# --- 配置参数 (Configuration) ---
# 大模型识别商品名称的上下文切片数：取前5个切片，避免上下文过长导致大模型输入超限
DEFAULT_ITEM_NAME_CHUNK_K = 5
# 单个切片内容截断长度：防止单切片内容过长，占满大模型上下文
SINGLE_CHUNK_CONTENT_MAX_LEN = 800
# 大模型上下文总字符数上限：适配主流大模型输入限制，默认2500
CONTEXT_TOTAL_MAX_CHARS = 2500




"""
  主要目标：
     1. 录用文本大模型识别当前chunks对应的item_name！用于区分不同的文档
     2. 使用嵌入式模型，将item_name生成向量存储到向量数据库 
     3. 修改state[chunks] -> chunk {title parent_title part file_title content item_name => 每个赋值 }
  实现步骤：
     1. 校验和取值 （file_title,chunks）
     2. 构建上下文环境  chunks -> top 5 -> 拼接成context文本 
     3. 调用模型，拼接提示词，识别chunks对应item_name
     4. 修改state chunks -》 item_name 
     5. item_name生成向量（稠密/稀疏）
     6. 存储向量到向量数据库 kb_item_name (id / file_title / item_name / 稠密 和 稀疏)
 """



def step_1_get_chunks(state):
    """
    获取chunks和file_title
    :param state:
    :return:
    """
    chunks = state.get('chunks')
    file_title = state.get('file_title')

    if not chunks:
        raise ValueError("chunks没有值，无法继续进行，抛出异常处理！")
    if not file_title:
        # file_title没有值！
        # md_path中获取文件名即可
        file_title = os.path.basename(state.get('md_path'))
        logger.info(f"file_title缺失，获取md_path进行截取！{file_title}")
        state['file_title'] = file_title
    return chunks, file_title



def node_item_name_recognition(state: ImportGraphState) -> ImportGraphState:
    """
       节点: 主体识别 (node_item_name_recognition)
       为什么叫这个名字: 识别文档核心描述的物品/商品名称 (Item Name)。
       未来要实现:
       1. 取文档前几段内容。
       2. 调用 LLM 识别这篇文档讲的是什么东西 (如: "Fluke 17B+ 万用表")。
       3. 存入 state["item_name"] 用于后续数据幂等性清理。
       """
    # 1. 进入的日志和任务状态的配置
    function_name = sys._getframe().f_code.co_name
    logger.info(f">>> [{function_name}]开始执行了！现在的状态为：{state}")
    add_running_task(state['task_id'], function_name)

    try:
        # 1. 验和取值 （file_title,chunks）
        # 获取前置的材料！ file_title = 为了兜底，没有item_name
        chunks, file_title = step_1_get_chunks(state)
        # 2. 构建上下文环境  chunks -> top 5 -> 拼接成context文本
        context = step_2_build_context(chunks)
        # 3. 调用模型，拼接提示词，识别chunks对应item_name
        item_name = step_3_call_llm(context, file_title)
        # 4. 修改state chunks -》 item_name -> chunks [{title parent_title context part item_name [没有值]}]
        step_4_update_chunks_and_state(state, item_name, chunks)
        # 5. item_name生成向量（稠密/稀疏）
        dense_vector, sparse_vector = step_5_generate_embeddings(item_name)
        # 6. 将向量存储到向量数据库 kb_item_name (id / file_title / item_name / 稠密 和 稀疏)
        step_6_save_to_vector_db(file_title, item_name, dense_vector, sparse_vector)
    except Exception as e:
        # 处理异常
        logger.error(f">>> [{function_name}]主体识别发生了异常，异常信息：{e}")
        raise  # 终止工作流
    finally:
        # 6. 结束的日志和任务状态的配置
        logger.info(f">>> [{function_name}]开始结束了！现在的状态为：{state}")
        add_done_task(state['task_id'], function_name)
    return state