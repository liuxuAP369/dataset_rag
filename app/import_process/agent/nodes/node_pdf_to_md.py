# 系统库
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

import requests

# 项目内部库
from app.conf.mineru_config import mineru_config
from app.core.logger import logger  # 统一日志工具
from app.import_process.agent.state import ImportGraphState, create_default_state
from app.utils.path_util import PROJECT_ROOT
from app.utils.task_utils import add_done_task, add_running_task


"""
    node_pdf_to_md 整体思路解析
     目标：解析pdf生成md content
     参数： state [is_pdf_read_enabled = True | pdf_path = xxx.pdf | local_dir = output ]
     返回： state [md_path = 地址 | md_content = 内容 ]

     todoList
     1、日志和任务状态
     2. step_1_validate_paths 路径校验
     3. step_2_upload_and_poll 上传pdf到 minerU
     4. step_3_download_and_extract 下载和解压
     5. 日志和任务状态 return state

    step_1_validate_paths
         参数：state pdf_path = xxx.pdf | local_dir = output
         返回： pdf_path_obj Path  local_dir_obj Path
             1. 非空校验
             2. 文件校验 pdf_path_obj 没有抛异常 local_dir_obj 没有给与默认
             3. 返回完成可用的Path对象即可

     step_2_upload_and_poll
         参数：pdf对应Path  pdf_path_obj
         返回：str zip url地址
         1. 进行申请，获取要上传文件的地址
         2. 进行文件上传 session | requests.put
         3. 轮询获取返回结果 zip_url  （确定一个最大等待时间 1页pdf 1s 间隔时间3 错误码 200 -》 500能容忍）
         4. 返回地址即可

      step_3_download_and_extract
         参数：zip_url , out_dir_obj , 原文件名 path.stem
         返回：解压后的.md的str地址
         1. zip下载 get    output / stem_result.zip
         2. 检查解压的文件夹地址  output / stem
         3. 检查解压的文件夹进行防重复处理
         4. 进行解压 zipFile  extractall(解压的目标文件夹)
         5. 考虑文件名字 原文件件名 还是 full 还是其他
         6. 重命名处理
         7. 路径转成字符串 获取绝对路径最终返回即可！
"""

MINERU_MODEL_VERSION = "vlm"
HTTP_REQUEST_TIMEOUT_SECONDS = 60
POLL_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 3


def _start_pdf_to_md_task(state: ImportGraphState, function_name: str) -> None:
    """记录节点开始执行。"""
    logger.info(f">>>[{function_name}]开始执行了，现在的状态为：{state} ")
    add_running_task(state["task_id"], function_name)



def _finish_pdf_to_md_task(state: ImportGraphState, function_name: str) -> None:
    """记录节点结束执行。"""
    logger.info(f">>> [{function_name}]执行结束了，现在的状态为：{state}")
    add_done_task(state["task_id"], function_name)



def _build_mineru_headers() -> dict[str, str]:
    """构造 MinerU 接口请求头。"""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {mineru_config.api_key}",
    }



def _request_upload_target(pdf_path_obj: Path, headers: dict[str, str]) -> tuple[str, str]:
    """申请 MinerU 上传地址和批次 ID。"""
    request_url = f"{mineru_config.base_url}/file-urls/batch"
    request_data = {
        "files": [{"name": pdf_path_obj.name}],
        "model_version": MINERU_MODEL_VERSION,
    }
    response = requests.post(
        request_url,
        headers=headers,
        json=request_data,
        timeout=HTTP_REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        logger.error("[step_2_upload_and_poll]请求minerU解析接口失败，请检查输入文件路径是否正确！！")
        raise RuntimeError("[step_2_upload_and_poll]请求minerU解析接口失败，请检查输入文件路径是否正确！！")

    response_data = response.json()
    if response_data["code"] != 0:
        logger.error("[step_2_upload_and_poll]请求minerU解析接口失败，请检查输入文件路径是否正确！！")
        raise RuntimeError("[step_2_upload_and_poll]请求minerU解析接口失败，请检查输入文件路径是否正确！！")

    upload_url = response_data["data"]["file_urls"][0]
    batch_id = response_data["data"]["batch_id"]
    return upload_url, batch_id



def _upload_pdf_file(upload_url: str, pdf_path_obj: Path) -> None:
    """上传 PDF 文件到 MinerU 提供的临时地址。"""
    http_session = requests.Session()
    http_session.trust_env = False  # 1.禁止走代理 2.复用请求对象

    try:
        file_data = pdf_path_obj.read_bytes()
        upload_response = http_session.put(
            upload_url,
            data=file_data,
            timeout=HTTP_REQUEST_TIMEOUT_SECONDS,
        )
        if upload_response.status_code != 200:
            raise RuntimeError("[step_2_upload_and_poll]上传文件到minerU失败，请检查输入文件路径是否正确！！")
    except Exception as exc:
        logger.error("[step_2_upload_and_poll]上传文件到minerU失败，请检查输入文件路径是否正确！！")
        raise RuntimeError("[step_2_upload_and_poll]上传文件到minerU失败，请检查输入文件路径是否正确！！") from exc
    finally:
        http_session.close()



def _poll_extract_result(batch_id: str, headers: dict[str, str]) -> str:
    """轮询 MinerU 解析结果，直到拿到 ZIP 下载地址。"""
    result_url = f"{mineru_config.base_url}/extract-results/batch/{batch_id}"
    start_time = time.time()

    while True:
        if time.time() - start_time > POLL_TIMEOUT_SECONDS:
            logger.error("[step_2_upload_and_poll]请求minerU解析接口超时！！")
            raise TimeoutError("[step_2_upload_and_poll]请求minerU解析接口超时 ！！")

        response = requests.get(
            result_url,
            headers=headers,
            timeout=HTTP_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            if 500 <= response.status_code < 600:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            raise RuntimeError(
                f"[step_2_upload_and_poll]请求minerU解析接口失败，返回的状态码{response.status_code}！！"
            )

        json_data = response.json()
        if json_data["code"] != 0:
            raise RuntimeError(
                f"[step_2_upload_and_poll]请求minerU解析接口失败，返回的错误:{json_data['code']}信息{json_data['msg']}！！"
            )

        extract_result = json_data["data"]["extract_result"][0]
        if extract_result["state"] == "done":
            full_zip_url = extract_result["full_zip_url"]
            logger.info(f"已经完成pdf的解析，耗时：{time.time() - start_time}s,解析结果：{full_zip_url}")
            return full_zip_url

        time.sleep(POLL_INTERVAL_SECONDS)



def _download_zip_file(zip_url: str, zip_save_path: Path) -> None:
    """下载 MinerU 解析结果 ZIP 文件到本地。"""
    response = requests.get(zip_url, timeout=HTTP_REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 200:
        logger.error("[step_3_download_and_extract]下载文件失败，请检查输入文件路径是否正确！！")
        raise RuntimeError("[step_3_download_and_extract]下载文件失败，请检查输入文件路径是否正确！！")

    zip_save_path.write_bytes(response.content)
    logger.info(f"[step_3_download_and_extract]下载文件成功，保存位置：{zip_save_path}")



def _prepare_extract_target_dir(extract_target_dir: Path) -> None:
    """准备解压目录；若旧目录存在则先清空。"""
    if extract_target_dir.exists():
        shutil.rmtree(extract_target_dir)
    extract_target_dir.mkdir(parents=True, exist_ok=True)



def _extract_zip_file(zip_save_path: Path, extract_target_dir: Path) -> None:
    """将 ZIP 文件解压到目标目录。"""
    with zipfile.ZipFile(zip_save_path, "r") as zip_file_object:
        zip_file_object.extractall(extract_target_dir)



def _select_target_markdown(md_file_list: list[Path], stem: str) -> Path:
    """按既定优先级选择目标 Markdown 文件。"""
    for md_file in md_file_list:
        if md_file.name == f"{stem}.md":
            return md_file

    for md_file in md_file_list:
        if md_file.name.lower() == "full.md":
            return md_file

    return md_file_list[0]



def _rename_markdown_if_needed(target_md_file: Path, stem: str) -> Path:
    """必要时将目标 Markdown 重命名为原 PDF 文件名。"""
    if target_md_file.stem == stem:
        return target_md_file
    return target_md_file.rename(target_md_file.with_name(f"{stem}.md"))



def _validate_pdf_input(pdf_path_obj: Path) -> None:
    """校验输入路径必须是存在的 PDF 文件。"""
    if not pdf_path_obj.exists():
        logger.error("[step_1_validate_paths]检查发现pdf_path不存在，请检查输入文件路径是否正确！！")
        raise FileNotFoundError("[step_1_validate_paths]检查发现pdf_path不存在，请检查输入文件路径是否正确！！")

    if not pdf_path_obj.is_file():
        logger.error("[step_1_validate_paths]检查发现pdf_path不是文件，无法继续解析！！")
        raise ValueError("[step_1_validate_paths]检查发现pdf_path不是文件，无法继续解析！！")

    if pdf_path_obj.suffix.lower() != ".pdf":
        logger.error("[step_1_validate_paths]检查发现输入文件不是pdf格式，无法继续解析！！")
        raise ValueError("[step_1_validate_paths]检查发现输入文件不是pdf格式，无法继续解析！！")



def _ensure_local_dir(local_dir_obj: Path) -> None:
    """确保输出目录存在。"""
    if local_dir_obj.exists() and not local_dir_obj.is_dir():
        logger.error("[step_1_validate_paths]检查发现local_dir不是文件夹，无法继续解析！！")
        raise ValueError("[step_1_validate_paths]检查发现local_dir不是文件夹，无法继续解析！！")

    if not local_dir_obj.exists():
        logger.info("[step_1_validate_paths]检查发现local_dir不存在，主动创建对应的文件夹！！！")
        local_dir_obj.mkdir(parents=True, exist_ok=True)



def _read_markdown_content(md_path: str) -> str:
    """读取 Markdown 内容。"""
    return Path(md_path).read_text(encoding="utf-8")



def _write_markdown_result(state: ImportGraphState, md_path: str, local_dir_obj: Path) -> None:
    """将 Markdown 路径、目录与内容写回状态。"""
    state["md_path"] = md_path
    state["local_dir"] = str(local_dir_obj)
    state["md_content"] = _read_markdown_content(md_path)



def step_1_validate_paths(state: ImportGraphState) -> tuple[Path, Path]:
    """
    进行路径校验！ pdf_path失效 直接异常处理!
                local_dir 没有，给与默认值
    :param state:
    :return:
    """
    logger.debug(">>> [step_1_validate_paths] pdf转md，开始进行文件路径校验！！")
    pdf_path = state["pdf_path"]
    local_dir = state["local_dir"] or (PROJECT_ROOT / "output")

    if not pdf_path:
        logger.error("step_1_validate_paths 发现没有输入文件，无法继续解析！！")
        raise ValueError("step_1_validate_paths 检查发现没有输入文件，无法继续解析！！")

    pdf_path_obj = Path(pdf_path)
    local_dir_obj = Path(local_dir)

    if not state["local_dir"]:
        logger.info(f"step_1_validate_paths 检查发现local_dir没有赋值，给与默认值：{local_dir_obj}！")

    _validate_pdf_input(pdf_path_obj)
    _ensure_local_dir(local_dir_obj)
    return pdf_path_obj, local_dir_obj



def step_2_upload_and_poll(pdf_path_obj: Path) -> str:
    """
    将pdf文件使用minerU解析，并且获取md对应的下载的url地址！！
    :param pdf_path_obj: 上传解析pdf文件的 path对象
    :return: str -> url , minerU解析后md文件zip压缩包的下载地址
    """
    headers = _build_mineru_headers()
    upload_url, batch_id = _request_upload_target(pdf_path_obj, headers)
    _upload_pdf_file(upload_url, pdf_path_obj)
    return _poll_extract_result(batch_id, headers)



def step_3_download_and_extract(zip_url: str, local_dir_obj: Path, stem: str) -> str:
    """
    下载指定的md.zip文件，并且解压，返回解压后的md文件的地址！
    :param zip_url:  要下载的地址
    :param local_dir_obj: 存储的文件夹
    :param stem: pdf的文件名字
    :return: 返回md文件的地址
    """
    zip_save_path = local_dir_obj / f"{stem}_result.zip"
    _download_zip_file(zip_url, zip_save_path)

    extract_target_dir = local_dir_obj / stem
    _prepare_extract_target_dir(extract_target_dir)
    _extract_zip_file(zip_save_path, extract_target_dir)

    md_file_list = list(extract_target_dir.rglob("*.md"))
    if not md_file_list:
        logger.error("[step_3_download_and_extract]没有找到md文件，请检查输入文件路径是否正确！！")
        raise RuntimeError("[step_3_download_and_extract]没有找到md文件，请检查输入文件路径是否正确！！")

    target_md_file = _select_target_markdown(md_file_list, stem)
    target_md_file = _rename_markdown_if_needed(target_md_file, stem)

    final_md_str_path = str(target_md_file.resolve())
    logger.info(f"[step_3_download_and_extract]完成md解压，最终存储md路径为：{final_md_str_path}")
    return final_md_str_path



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
    function_name = sys._getframe().f_code.co_name
    _start_pdf_to_md_task(state, function_name)

    try:
        pdf_path_obj, local_dir_obj = step_1_validate_paths(state)
        zip_url = step_2_upload_and_poll(pdf_path_obj)
        md_path = step_3_download_and_extract(zip_url, local_dir_obj, pdf_path_obj.stem)
        _write_markdown_result(state, md_path, local_dir_obj)
        return state
    except Exception as exc:
        logger.error(f">>> [{function_name}]使用minerU解析发生了异常，异常信息：{exc}")
        raise
    finally:
        _finish_pdf_to_md_task(state, function_name)


if __name__ == "__main__":
    # 单元测试：验证PDF转MD全流程
    logger.info("===== 开始node_pdf_to_md节点单元测试 =====")
    logger.info(f"测试获取根地址：{PROJECT_ROOT}")

    test_pdf_name = os.path.join("doc", "hak180产品安全手册.pdf")
    test_pdf_path = os.path.join(PROJECT_ROOT, test_pdf_name)

    # 构造测试状态
    test_state = create_default_state(
        task_id="test_pdf2md_task_001",
        pdf_path=test_pdf_path,
        local_dir=os.path.join(PROJECT_ROOT, "output")
    )

    node_pdf_to_md(test_state)

    logger.info("===== 结束node_pdf_to_md节点单元测试 =====")
