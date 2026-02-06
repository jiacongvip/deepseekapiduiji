from src.pool.session_pool import session_pool, DoubaoSession
from requests_aws4auth import AWS4Auth
from fastapi import HTTPException
from loguru import logger
import aiohttp
import httpx
import json
import uuid
import hashlib
import binascii
import os
import time

async def chat_completion(
    prompt: str, 
    guest: bool,
    section_id: str = None, 
    conversation_id: str = None, 
    attachments: list[dict] = [], 
    use_auto_cot: bool = False, 
    use_deep_think: bool = False,
    session_override: DoubaoSession = None,
    stream: bool = False
):
    # 获取会话配置
    if session_override:
        session = session_override
    else:
        session = session_pool.get_session(conversation_id, guest)
        
    if not session:
        raise HTTPException(status_code=404, detail=f"会话配置不存在,请检查 session.config 文件或提供有效的 Token")
    
    # ------ PARAMS -------
    # 从 cookie 中提取 fp (s_v_web_id)
    fp = ""
    if session.cookie and "s_v_web_id=" in session.cookie:
        try:
            fp = session.cookie.split("s_v_web_id=")[1].split(";")[0]
        except:
            pass
    
    params_list = [
        "aid=497858",
        f"device_id={session.device_id}",
        "device_platform=web",
        "language=zh",
        "pc_version=3.1.2",
        "pkg_type=release_version",
        "real_aid=497858",
        "samantha_web=1",
        f"tea_uuid={session.tea_uuid}",
        "use-olympus-account=1",
        "version_code=20800",
        f"web_id={session.web_id}"
    ]
    
    # 添加 fp 参数（如果存在）
    if fp:
        params_list.insert(4, f"fp={fp}")
    
    # 添加 region 和 sys_region
    params_list.append("region=CN")
    params_list.append("sys_region=CN")
    
    params = "&".join(params_list)
    
    # ------ URL ------- 使用旧协议端点（支持搜索引用）
    url = "https://www.doubao.com/samantha/chat/completion?" + params
    
    # ------ BODY ------- 旧协议格式
    body = {
        "completion_option": {
            "is_regen": False,
            "with_suggest": False,
            "need_create_conversation": conversation_id is None,
            "launch_stage": 1,
            "use_auto_cot": use_auto_cot,
            "use_deep_think": use_deep_think
        },
        "conversation_id": "0" if conversation_id is None else conversation_id,
        "messages": [
            {
                "content": json.dumps({"text": prompt}),
                "content_type": 2001,
                "attachments": attachments,
                "references": []
            }
        ]
    }
    
    if section_id is not None:
        body["section_id"] = section_id
    
    # 如果是登录账户，添加 local 字段
    if not guest:
        body["local_conversation_id"] = f"local_{int(uuid.uuid4().int % 10000000000000000)}" 
        body["local_message_id"] = str(uuid.uuid4())
    
    # ------ HEADERS -------
    headers = {
        'content-type': 'application/json',
        'accept': 'text/event-stream',
        'agw-js-conv': 'str',
        'cookie': session.cookie,
        'origin': "https://www.doubao.com",
        'referer': f"https://www.doubao.com/chat/{session.room_id}",
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0',
        "x-flow-trace": session.x_flow_trace
    }
    try:
        async with aiohttp.ClientSession() as aio_session:
            async with aio_session.post(url=url, headers=headers, json=body) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"豆包API对话补全失败: {response.status}, 详情: {error_text}")
                
                if stream:
                    return handle_sse_stream(response, session, conversation_id)
                else:
                    try:
                        # 下一次会话需要同一个session
                        text, image_urls, references, conversation_id, message_id, section_id = await handle_sse(response)
                        if conversation_id:
                            session_pool.set_session(conversation_id, session)
                        return text, image_urls, references, conversation_id, message_id, section_id
                    except LimitedException:
                        session_pool.del_session(session)
                        raise HTTPException(status_code=500, detail=f"游客限制5次会话已用完，请重使用新Session")
    except Exception as e:
        # If we are in stream mode, we might have already yielded some chunks.
        # But here we are setting up the generator or handling non-stream error.
        raise Exception(f"豆包API请求失败: {str(e)}")


async def handle_sse_stream(response: aiohttp.ClientResponse, session: DoubaoSession, initial_conversation_id: str):
    """
    Generator for OpenAI-compatible SSE stream.
    Yields string chunks in format: 'data: {...}\n\n'
    """
    buffer = ""
    conversation_id = initial_conversation_id
    message_id = ""
    section_id = ""
    
    # We need to track if we've sent the role chunk
    role_sent = False
    
    try:
        async for chunk in response.content.iter_chunked(1024):
            buffer += chunk.decode('utf-8', errors='replace')
            
            while '\n\n' in buffer:
                evt, buffer = buffer.split('\n\n', 1)
                lines = evt.strip().split('\n')
                
                event_type = ""
                data_str = ""
                
                for line in lines:
                    if line.startswith("event: "):
                        event_type = line[7:].strip()
                    elif line.startswith("data: "):
                        data_str = line[6:].strip()
                
                if not event_type and data_str:
                    event_type = "implicit_message"
                
                if not event_type or not data_str:
                    continue
                
                try:
                    data = json.loads(data_str)
                    
                    if event_type == "SSE_ACK":
                        ack_meta = data.get("ack_client_meta", {})
                        conversation_id = ack_meta.get("conversation_id")
                        if conversation_id:
                            session_pool.set_session(conversation_id, session)
                            
                    elif event_type in ["STREAM_CHUNK", "STREAM_MSG_NOTIFY", "message", "implicit_message", "FULL_MSG_NOTIFY"]:
                        new_text = ""
                        
                        if event_type == "STREAM_CHUNK":
                            patch_ops = data.get("patch_op", [])
                            for op in patch_ops:
                                patch_value = op.get("patch_value", {})
                                if "content_block" in patch_value:
                                    for block in patch_value["content_block"]:
                                        text_block = block.get("content", {}).get("text_block", {})
                                        if text := text_block.get("text"):
                                            new_text += text
                                if "tts_content" in patch_value:
                                    tts_text = patch_value["tts_content"]
                                    if tts_text:
                                        # Simple deduplication heuristic: if tts equals what we just extracted from block, ignore
                                        # Otherwise append. This is tricky without full state.
                                        # For now, just append if we haven't extracted anything yet from this op
                                        # Or rely on tts_content being the source of truth for text.
                                        # Let's prioritize tts_content as it seemed more reliable in logs
                                        if not new_text: 
                                            new_text = tts_text
                                        elif new_text != tts_text:
                                            # If different, maybe it's a sequence? 
                                            # Safest is to use tts_content if available and non-empty
                                            new_text = tts_text

                        elif event_type == "STREAM_MSG_NOTIFY":
                             # Usually initial full message or update
                             content = data.get("content", {})
                             blocks = content.get("content_block", [])
                             for block in blocks:
                                 text_block = block.get("content", {}).get("text_block", {})
                                 if text := text_block.get("text"):
                                     new_text += text
                        
                        elif event_type == "FULL_MSG_NOTIFY":
                             # For stream mode, FULL_MSG might be redundant if we already streamed chunks
                             # But if it's the *only* thing we got, we should send it.
                             # To avoid duplication, maybe we ignore it if we already sent chunks?
                             # Let's assume FULL_MSG_NOTIFY comes at the end or for short messages.
                             # We can send it.
                             message = data.get("message", {})
                             content_str = message.get("content", "")
                             # Parse logic similar to handle_sse...
                             # For simplicity, let's skip FULL_MSG_NOTIFY in stream mode to avoid massive duplication
                             # UNLESS we haven't sent anything yet?
                             pass 

                        elif event_type in ["message", "implicit_message"]:
                             # ... extraction logic ...
                             if isinstance(data, dict):
                                 content = data.get("content", "")
                                 if isinstance(content, str): new_text = content
                             elif isinstance(data, str):
                                 new_text = data

                        if new_text:
                            if not role_sent:
                                # Send role chunk first
                                yield f"data: {json.dumps({'id': 'chatcmpl-' + str(uuid.uuid4()), 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'doubao-pro-4k', 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"
                                role_sent = True
                            
                            # Send content chunk
                            chunk_resp = {
                                "id": f"chatcmpl-{uuid.uuid4()}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": "doubao-pro-4k",
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": new_text},
                                        "finish_reason": None
                                    }
                                ]
                            }
                            yield f"data: {json.dumps(chunk_resp)}\n\n"

                    elif event_type == "SSE_REPLY_END":
                        # Stream finished
                        yield f"data: {json.dumps({'id': 'chatcmpl-' + str(uuid.uuid4()), 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'doubao-pro-4k', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                except Exception as e:
                    logger.error(f"Stream parse error: {e}")
                    continue
    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


async def handle_sse(response: aiohttp.ClientResponse):
    """处理SSE流响应 - 支持新旧两种协议格式"""
    buffer = ""
    conversation_id = ""
    message_id = ""
    section_id = ""
    texts = []
    image_urls = []
    references = []  # 引用来源列表
    reference_urls = set()
    is_end = False
    
    def _normalize_url(url: str) -> str:
        if not isinstance(url, str):
            return ""
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        return url

    def _is_probable_source_url(url: str) -> bool:
        if not url:
            return False
        if not (url.startswith("http://") or url.startswith("https://")):
            return False
        lowered = url.lower()
        if any(
            lowered.endswith(ext)
            for ext in (
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".webp",
                ".svg",
                ".ico",
                ".css",
                ".js",
                ".mp3",
                ".mp4",
                ".m4a",
                ".wav",
            )
        ):
            return False
        if any(
            host in lowered
            for host in (
                "byteimg.com",
                "bytednsdoc.com",
                "zijieapi.com",
                "bytedanceapi.com",
                "snssdk.com",
            )
        ):
            return False
        return True

    def add_reference_from_text_card(text_card: dict):
        """从 text_card/引用对象中提取引用信息（兼容豆包改版字段）"""
        if not isinstance(text_card, dict):
            return

        url = _normalize_url(
            text_card.get("url")
            or text_card.get("link")
            or text_card.get("href")
            or text_card.get("jump_url")
            or ""
        )
        if not _is_probable_source_url(url):
            return
        if url in reference_urls:
            return

        index = (
            text_card.get("index")
            if text_card.get("index") is not None
            else text_card.get("original_doc_rank")
        )
        if index is None:
            index = text_card.get("rank")

        ref_data = {
            "title": text_card.get("title")
            or text_card.get("name")
            or text_card.get("site_title")
            or "",
            "url": url,
            "snippet": text_card.get("snippet")
            or text_card.get("summary")
            or text_card.get("desc")
            or text_card.get("description")
            or "",
            "index": index,
            "sitename": text_card.get("sitename")
            or text_card.get("site_name")
            or text_card.get("source")
            or "",
            "publish_time": text_card.get("publish_time")
            or text_card.get("publish_time_second")
            or text_card.get("publish_time_ms")
            or "",
        }

        reference_urls.add(url)
        references.append(ref_data)
        logger.debug(f"添加引用: {ref_data.get('title', '')[:30]}... -> {url[:50]}...")

    def extract_search_results(search_result: dict):
        """从搜索结果中提取引用"""
        if not isinstance(search_result, dict):
            return

        candidates = []
        for key in ("results", "items", "docs", "sources", "cards"):
            val = search_result.get(key)
            if isinstance(val, list) and val:
                candidates.extend(val)

        for result in candidates:
            if isinstance(result, dict):
                for nested_key in ("text_card", "card", "doc", "source", "reference"):
                    nested_val = result.get(nested_key)
                    if isinstance(nested_val, dict):
                        add_reference_from_text_card(nested_val)
                add_reference_from_text_card(result)

        if candidates:
            summary = search_result.get("summary", "")
            queries = search_result.get("queries", [])
            if summary or queries:
                logger.info(f"搜索引用: {summary}, 关键词: {queries}")

    def _maybe_extract_from_json_string(value: str, depth: int):
        if not isinstance(value, str):
            return
        if depth > 12:
            return
        s = value.strip()
        if len(s) < 2 or len(s) > 200000:
            return
        if ("url" not in s and "text_card" not in s and "reference" not in s and "http" not in s):
            return
        if not ((s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))):
            return
        try:
            obj = json.loads(s)
        except Exception:
            return
        _extract_references_deep(obj, depth + 1)

    def _extract_references_deep(obj, depth: int = 0):
        """兜底：深度遍历提取引用（适配豆包字段/结构改动）"""
        if depth > 12:
            return
        if isinstance(obj, dict):
            add_reference_from_text_card(obj)

            for key in ("text_card", "card", "doc", "source", "reference", "ref"):
                nested = obj.get(key)
                if isinstance(nested, dict):
                    add_reference_from_text_card(nested)

            for list_key in (
                "search_references",
                "references",
                "reference_list",
                "citation_list",
                "citations",
                "sources",
                "source_list",
                "results",
                "items",
                "docs",
                "cards",
            ):
                nested_list = obj.get(list_key)
                if isinstance(nested_list, list):
                    for item in nested_list:
                        _extract_references_deep(item, depth + 1)

            for v in obj.values():
                if isinstance(v, (dict, list)):
                    _extract_references_deep(v, depth + 1)
                elif isinstance(v, str):
                    _maybe_extract_from_json_string(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _extract_references_deep(item, depth + 1)
    
    async for chunk in response.content.iter_chunked(1024):
        buffer += chunk.decode('utf-8', errors='replace')
        
        # 游客限制判断
        if "tourist conversation reach limited" in buffer:
            raise LimitedException()
        
        if 'event: gateway-error' in buffer:
            error_match = buffer.find('data: {')
            if error_match != -1:
                try:
                    error_data = json.loads(buffer[error_match + 6:].split('\n')[0])
                    raise Exception(f"服务器返回网关错误: {error_data.get('code')} - {error_data.get('message')}")
                except Exception as e:
                    raise Exception(f"服务器返回网关错误: {buffer}")
        
        # 处理 SSE 事件（按行分割）
        while '\n' in buffer:
            # 找到完整的一行或一个事件块
            if '\n\n' in buffer:
                evt, buffer = buffer.split('\n\n', 1)
            elif buffer.endswith('\n'):
                evt = buffer.rstrip('\n')
                buffer = ""
            else:
                # 等待更多数据
                break
            
            lines = evt.strip().split('\n')
            
            # Debug: print every event
            logger.debug(f"Raw SSE Event: {lines}")
            
            event_type = ""
            data_str = ""
            
            for line in lines:
                if line.startswith("event: "):
                    event_type = line[7:].strip()
                elif line.startswith("data: "):
                    data_str = line[6:].strip()
            
            if not data_str:
                continue
            
            try:
                data = json.loads(data_str)
                # 新协议/改版时引用结构变化较多：只要 payload 中出现 url/refs 相关字段就做一次深度提取
                if any(k in data_str for k in ("\"url\"", "text_card", "reference", "references", "search_references")):
                    _extract_references_deep(data)
                
                # ========== 旧协议格式 (event_type 为数字) ==========
                # 格式: data: {"event_type": 2001, "event_data": "{...}"}
                if "event_type" in data and isinstance(data.get("event_type"), int):
                    raw_event_type = data.get("event_type")
                    event_data_str = data.get("event_data", "")
                    
                    logger.debug(f"旧协议 event_type={raw_event_type}, has_event_data={bool(event_data_str)}")
                    
                    # 错误检查
                    if data.get("code"):
                        raise Exception(f"豆包返回错误: {data.get('code')} - {data.get('message')}")
                    
                    # event_type == 2002: 开始，获取 conversation_id
                    if raw_event_type == 2002:
                        try:
                            start_result = json.loads(event_data_str) if event_data_str else {}
                            if start_result.get("conversation_id"):
                                conversation_id = start_result["conversation_id"]
                                logger.debug(f"旧协议 2002: conversation_id={conversation_id}")
                        except:
                            pass
                        continue
                    
                    # event_type == 2003: 结束
                    if raw_event_type == 2003:
                        is_end = True
                        logger.debug("旧协议 2003: 流结束")
                        continue
                    
                    # event_type == 2005: 错误
                    if raw_event_type == 2005:
                        try:
                            error_result = json.loads(event_data_str) if event_data_str else {}
                            if error_result.get("code"):
                                error_msg = error_result.get("error_detail", {}).get("message") or error_result.get("message") or "未知错误"
                                logger.warning(f"旧协议 2005 错误: {error_msg}")
                                raise Exception(f"豆包服务器错误: {error_msg}")
                        except json.JSONDecodeError:
                            pass
                        continue
                    
                    # event_type == 2001: 消息内容
                    if raw_event_type == 2001:
                        try:
                            result = json.loads(event_data_str) if event_data_str else {}
                            if any(k in event_data_str for k in ("\"url\"", "text_card", "reference", "references", "search_references")):
                                _extract_references_deep(result)
                            
                            # 检查是否结束
                            if result.get("is_finish"):
                                is_end = True
                                logger.debug("旧协议 2001: is_finish=True, 流结束")
                            
                            # 获取 conversation_id
                            if not conversation_id and result.get("conversation_id"):
                                conversation_id = result["conversation_id"]
                            
                            # 提取消息内容
                            message = result.get("message", {})
                            if message:
                                content_type = message.get("content_type")
                                
                                # 文字消息: 10000, 2001, 2008
                                if content_type in [10000, 2001, 2008, None]:
                                    content = message.get("content")
                                    if content:
                                        try:
                                            if isinstance(content, str):
                                                content_data = json.loads(content)
                                            else:
                                                content_data = content
                                            
                                            # 提取文本
                                            content_text = content_data.get("text", "")
                                            if content_text:
                                                texts.append(content_text)
                                                logger.debug(f"旧协议提取文本: {content_text[:50]}... (长度: {len(content_text)})")
                                            
                                            # 提取搜索引用 search_references
                                            search_refs = content_data.get('search_references', [])
                                            if search_refs:
                                                logger.info(f"发现搜索引用: {len(search_refs)}个")
                                                for ref_item in search_refs:
                                                    text_card = ref_item.get('text_card', {})
                                                    add_reference_from_text_card(text_card)
                                            
                                            # 兼容：从 extra_info 提取引用
                                            extra_info = content_data.get('extra_info', {})
                                            if isinstance(extra_info, dict):
                                                search_results = extra_info.get('search_query_result_block', {}).get('results', [])
                                                for sr in search_results:
                                                    text_card = sr.get('text_card', {})
                                                    add_reference_from_text_card(text_card)
                                                    
                                        except json.JSONDecodeError:
                                            if isinstance(content, str) and content:
                                                texts.append(content)
                                                logger.debug(f"旧协议直接使用content: {content[:50]}...")
                                
                                # 搜索结果消息: 10025
                                elif content_type == 10025:
                                    try:
                                        search_result = json.loads(message.get('content', '{}'))
                                        extract_search_results(search_result)
                                    except:
                                        pass
                                
                                # 从 content_block 中提取搜索引用
                                content_blocks = message.get('content_block', [])
                                for block in content_blocks:
                                    if block.get('block_type') == 10025:
                                        block_content = block.get('content', {})
                                        search_result = block_content.get('search_query_result_block', {})
                                        extract_search_results(search_result)
                                    else:
                                        _extract_references_deep(block)
                                        
                        except json.JSONDecodeError as e:
                            logger.warning(f"旧协议解析 event_data 失败: {e}")
                        continue
                    
                    # 其他 event_type 跳过
                    logger.debug(f"旧协议跳过 event_type: {raw_event_type}")
                    continue
                
                # ========== 新协议格式 (event 为字符串) ==========
                # 格式: event: STREAM_CHUNK\ndata: {...}
                if not event_type and data_str:
                    event_type = "implicit_message"
                
                if event_type == "SSE_ACK":
                    ack_meta = data.get("ack_client_meta", {})
                    conversation_id = ack_meta.get("conversation_id", conversation_id)
                    section_id = ack_meta.get("section_id", section_id)
                    logger.debug(f"新协议 SSE_ACK: conv_id={conversation_id}, sec_id={section_id}")
                    
                elif event_type == "STREAM_MSG_NOTIFY":
                    meta = data.get("meta", {})
                    if not conversation_id:
                        conversation_id = meta.get("conversation_id")
                    if not section_id:
                        section_id = meta.get("section_id")
                    message_id = meta.get("message_id")
                    logger.debug(f"新协议 STREAM_MSG_NOTIFY: conv_id={conversation_id}, sec_id={section_id}")
                    
                    content = data.get("content", {})
                    blocks = content.get("content_block", [])
                    for block in blocks:
                        text_block = block.get("content", {}).get("text_block", {})
                        if text := text_block.get("text"):
                            texts.append(text)
                            logger.debug(f"新协议从 STREAM_MSG_NOTIFY 提取: {text[:50]}...")
                        if block.get("block_type") == 10025:
                            block_content = block.get("content", {})
                            search_result = (
                                block_content.get("search_query_result_block")
                                or block_content.get("search_result_block")
                                or {}
                            )
                            extract_search_results(search_result)
                        else:
                            _extract_references_deep(block)
                            
                elif event_type == "STREAM_CHUNK":
                    patch_ops = data.get("patch_op", [])
                    for op in patch_ops:
                        patch_value = op.get("patch_value", {})
                        chunk_text = ""
                        
                        if "content_block" in patch_value:
                            for block in patch_value["content_block"]:
                                # 提取文本
                                text_block = block.get("content", {}).get("text_block", {})
                                if text := text_block.get("text"):
                                    chunk_text = text
                                
                                # 提取搜索引用 (block_type: 10025)
                                if block.get('block_type') == 10025:
                                    block_content = block.get('content', {})
                                    search_result = (
                                        block_content.get("search_query_result_block")
                                        or block_content.get("search_result_block")
                                        or {}
                                    )
                                    extract_search_results(search_result)
                                else:
                                    _extract_references_deep(block)
                        
                        _extract_references_deep(patch_value)
                        
                        if "tts_content" in patch_value:
                            tts_text = patch_value["tts_content"]
                            if not chunk_text and tts_text:
                                chunk_text = tts_text
                            elif chunk_text and tts_text and len(tts_text) > len(chunk_text):
                                chunk_text = tts_text
                        
                        if chunk_text:
                            texts.append(chunk_text)
                            logger.debug(f"新协议从 STREAM_CHUNK 提取: {chunk_text[:50]}...")

                elif event_type == "FULL_MSG_NOTIFY":
                    message = data.get("message", {})
                    if "content_block" in message:
                        for block in message.get("content_block", []):
                            text_block = block.get("content", {}).get("text_block", {})
                            if text := text_block.get("text"):
                                texts.append(text)
                            if block.get("block_type") == 10025:
                                block_content = block.get("content", {})
                                search_result = (
                                    block_content.get("search_query_result_block")
                                    or block_content.get("search_result_block")
                                    or {}
                                )
                                extract_search_results(search_result)
                            else:
                                _extract_references_deep(block)
                    else:
                        content_str = message.get("content", "")
                        if content_str:
                            try:
                                content_blocks = json.loads(content_str)
                                if isinstance(content_blocks, list):
                                    for block in content_blocks:
                                        text_block = block.get("content", {}).get("text_block", {})
                                        if text := text_block.get("text"):
                                            texts.append(text)
                                        _extract_references_deep(block)
                                else:
                                    texts.append(str(content_str))
                            except:
                                texts.append(str(content_str))
                    _extract_references_deep(message)

                elif event_type in ["message", "implicit_message"]:
                    if isinstance(data, dict):
                        content = data.get("content", "")
                        if content and isinstance(content, str):
                            texts.append(content)
                    elif isinstance(data, str):
                        texts.append(data)
                
                elif event_type == "SSE_REPLY_END":
                    is_end = True
                    logger.debug("新协议 SSE_REPLY_END: 流结束")
                    
            except json.JSONDecodeError as e:
                logger.warning(f"JSON解析失败: {e}, data: {data_str[:100] if data_str else 'empty'}")
                continue
            except Exception as e:
                logger.warning(f"处理事件失败 {event_type}: {e}")
                continue

    text = "".join(texts)
    logger.info(f"SSE流结束: 文本长度={len(text)}, 片段数={len(texts)}, 引用数={len(references)}, conv_id={conversation_id}, sec_id={section_id}")
    if text:
        logger.debug(f"文本预览: {text[:200]}...")
    else:
        logger.warning("警告: 解析后文本为空!")
        logger.warning(f"收到的片段: {texts}")
    if references:
        logger.info(f"引用列表: {[r.get('title', '')[:20] for r in references]}")
    return text, image_urls, references, conversation_id, message_id, section_id


async def upload_file(file_type: int, file_name: str, file_data: bytes):
    """
    上传文件到豆包服务器，返回附件信息
    总体流程为：
    1. 通过 prepare-upload 拿到 AWS 凭证
    2. 通过 apply-upload 提交文件元信息
    3. 通过 upload 上传文件数据
    4. 通过 commit-upload 确认上传
    """
    # 生成文件与用户无关，随机挑一个session
    session = session_pool.get_session()
    logger.debug(f"开始上传文件: {file_name}, 类型: {file_type}, 大小: {len(file_data)} 字节")
    # ------ HEADERS -------
    DEFAULT_HEADERS = {
        'content-type': 'application/json',
        'cookie': session.cookie,
        'origin': "www.doubao.com",
        'referer': "https://www.doubao.com/chat/",
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36'
    }
    # ------ PARAMS -------
    params = "&".join([
        "aid=497858",
        f"device_id={session.device_id}",
        "device_platform=web",
        "language=zh",
        "pc_version=2.20.0",
        "pkg_type=release_version",
        "real_aid=497858",
        "region=CN",
        "samantha_web=1",
        "sys_region=CN",
        f"tea_uuid={session.tea_uuid}",
        "use-olympus-account=1",
        "version_code=20800",
        f"web_id={session.web_id}"
    ])
    # 由于 AWS4Auth 不支持 Aiohttp, 所以采用异步库 HTTPX
    async with httpx.AsyncClient() as client:
        # PREPARE UPLOAD
        prepare_url = "https://www.doubao.com/alice/resource/prepare_upload?" + params
        prepare_payload = {
            "resource_type": file_type,  # 文档类型 1;图片类型 2; 
            "scene_id": "5",
            "tenant_id": "5"
        }
        resp = await client.post(url=prepare_url, headers=DEFAULT_HEADERS, json=prepare_payload)
        prepare_data = resp.json()
        upload_info = prepare_data.get("data", {})
        
        # APPLY UPLOAD
        service_id = upload_info.get("service_id")
        session_token = upload_info.get("upload_auth_token", {}).get("session_token")
        access_key = upload_info.get("upload_auth_token", {}).get("access_key")
        secret_key = upload_info.get("upload_auth_token", {}).get("secret_key")
        file_size = len(file_data)
        if not '.' in file_name:
            raise HTTPException(status_code=500, detail="文件名格式错误，注意附带后缀名")
        file_ext = os.path.splitext(file_name)[1]
        apply_url = f"https://imagex.bytedanceapi.com/?Action=ApplyImageUpload&Version=2018-08-01&ServiceId={service_id}&NeedFallback=true&FileSize={file_size}&FileExtension={file_ext}"
        
        # 构建 AWS4Auth
        auth = AWS4Auth(access_key, secret_key, 'cn-north-1', "imagex", session_token=session_token)
        applu_request = client.build_request(
            method="GET",
            url=apply_url,
            headers={
                "origin": "https://www.doubao.com",
                "reference": "https://www.doubao.com",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                }
            )
        auth.__call__(applu_request) 
        resp = await client.send(applu_request)
        data = resp.json()
        upload_address = data.get("Result", {}).get("UploadAddress", {})
        if not (infos := upload_address.get("StoreInfos", [])):
            raise HTTPException(status_code=500, detail="Apply Upload 返回 StoreInfos列表为空")
        store_info = infos[0]
        store_url = store_info.get("StoreUri")
        store_auth = store_info.get("Auth")
        session_key = upload_address.get("SessionKey")
        
        # UPLOAD
        upload_url = f"https://tos-d-x-hl.snssdk.com/upload/v1/{store_url}"
        crc32 = format(binascii.crc32(file_data) & 0xFFFFFFFF, '08x')
        upload_headers = {
            "authorization": store_auth,
            "origin": "https://www.doubao.com",
            "reference": "https://www.doubao.com",
            "host": "tos-d-x-hl.snssdk.com",
            "content-type": "application/octet-stream",
            "content-disposition": 'attachment; filename="undefined"',
            "content-crc32": crc32
        }
        resp = await client.post(upload_url, content=file_data, headers=upload_headers)
        data = resp.json()
        if not (msg := data.get("message")) == "Success":
            raise HTTPException(status_code=500, detail=f"上传消息失败 {msg}")
        
        # COMMIT UPLOAD
        commit_url = f"https://imagex.bytedanceapi.com/?Action=CommitImageUpload&Version=2018-08-01&ServiceId={service_id}"
        commit_payload = {"SessionKey": session_key}
        commit_headers = {
            "origin": "https://www.doubao.com",
            "referer": "https://www.doubao.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        }
        
        # AWS4AUTH
        commit_request = client.build_request(
            method="POST",
            url=commit_url,
            headers=commit_headers,
            json=commit_payload
        )
        auth.__call__(commit_request)
        resp = await client.send(commit_request)
        data = resp.json()
        if not (results := data.get("Result", {}).get("PluginResult", [])):
            raise HTTPException(status_code=500, detail="Commit Upload 返回 PluginResult 为空")
        result = results[0]
        
        # 返回结果
        from src.model.response import FileResponse, ImageResponse
        if file_type == 1:
            return FileResponse(
                key=result.get("ImageUri"),
                name=file_name,
                md5=result.get("ImageMd5") or hashlib.md5(file_data).hexdigest(),
                size=result.get("ImageSize")
            )
        elif file_type == 2:
            return ImageResponse(
                key=result.get("ImageUri"),
                name=file_name,
                option={
                    "height": result.get("ImageHeight"),
                    "width": result.get("ImageWidth")
                }
            )


async def delete_conversation(conversation_id: str) -> tuple[bool, str]:
    # 获取会话配置
    session = session_pool.get_session(conversation_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话配置不存在:, 会话ID: {conversation_id}")
    
    # ------ URL -------
    params = "&".join([
        "aid=497858",
        f"device_id={session.device_id}",
        "device_platform=web",
        "language=zh",
        "pc_version=2.20.0",
        "pkg_type=release_version",
        "real_aid=497858",
        "region=CN",
        "samantha_web=1",
        "sys_region=CN",
        f"tea_uuid={session.tea_uuid}",
        "use-olympus-account=1",
        "version_code=20800",
        f"web_id={session.web_id}",
    ])
    url = "https://www.doubao.com/samantha/thread/delete?" + params
    
    # ------ BODY -------
    body = {"conversation_id": conversation_id}
    
    # ------ HEADERS -------
    headers = {
        "cookie": session.cookie,
        "origin": "https://www.doubao.com",
        "referer": "https://www.doubao.com/chat/" + conversation_id,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0"
    }
    
    try:
        async with aiohttp.ClientSession() as aio_session:
            async with aio_session.post(url, headers=headers, json=body) as response:
                if response.status != 200:
                    return False, f"请求状态错误: {response.status}"
        return True, ""
    except Exception as e:
        return False, f"请求失败: {str(e)}"


class LimitedException(Exception):
    pass


__all__ = [
    "chat_completion",
    "upload_file",
    "delete_conversation"
] 
