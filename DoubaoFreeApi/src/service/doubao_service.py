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
    session_override: DoubaoSession = None
):
    # 获取会话配置
    if session_override:
        session = session_override
    else:
        session = session_pool.get_session(conversation_id, guest)
        
    if not session:
        raise HTTPException(status_code=404, detail=f"会话配置不存在,请检查 session.config 文件或提供有效的 Token")
    
    # Extract fp from cookie
    fp = ""
    if session.cookie:
        for part in session.cookie.split('; '):
            if part.startswith('s_v_web_id='):
                fp = part.split('=')[1]
                break
    
    # ------ PARAMS -------
    params = "&".join([
        "aid=497858",
        f"device_id={session.device_id}",
        "device_platform=web",
        "language=zh",
        "pc_version=2.23.2",
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
    
    # ------ URL -------
    url = "https://www.doubao.com/chat/completion?" + params
    
    # ------ BODY -------
    # New structure based on capture
    local_conv_id = f"local_{int(uuid.uuid4().int % 10000000000000000)}"
    
    body = {
        "client_meta": {
            "local_conversation_id": local_conv_id,
            "conversation_id": conversation_id if conversation_id and conversation_id != "0" else "",
            "bot_id": "7338286299411103781", # Default Doubao bot ID
            "last_section_id": section_id if section_id else "",
            "last_message_index": None
        },
        "messages": [
            {
                "local_message_id": str(uuid.uuid4()),
                "content_block": [
                    {
                        "block_type": 10000,
                        "content": {
                            "text_block": {
                                "text": prompt,
                                "icon_url": "",
                                "icon_url_dark": "",
                                "summary": ""
                            },
                            "pc_event_block": ""
                        },
                        "block_id": str(uuid.uuid4()),
                        "parent_id": "",
                        "meta_info": [],
                        "append_fields": []
                    }
                ],
                "message_status": 0
            }
        ],
        "option": {
            "send_message_scene": "",
            "create_time_ms": int(time.time() * 1000),
            "collect_id": "",
            "is_audio": False,
            "answer_with_suggest": False,
            "tts_switch": False,
            "need_deep_think": 1 if use_deep_think else 0,
            "click_clear_context": False,
            "from_suggest": False,
            "is_regen": False,
            "is_replace": False,
            "disable_sse_cache": False,
            "select_text_action": "",
            "resend_for_regen": False,
            "scene_type": 0,
            "unique_key": str(uuid.uuid4()),
            "start_seq": 0,
            "need_create_conversation": True,
            "conversation_init_option": {
                "need_ack_conversation": True
            },
            "regen_query_id": [],
            "edit_query_id": [],
            "regen_instruction": "",
            "no_replace_for_regen": False,
            "message_from": 0,
            "shared_app_name": "",
            "sse_recv_event_options": {
                "support_chunk_delta": True
            },
            "is_ai_playground": False
        },
        "ext": {
            "conversation_init_option": "{\"need_ack_conversation\":true}",
            "fp": fp,
            "use_deep_think": "1" if use_deep_think else "0",
            "commerce_credit_config_enable": "0",
            "sub_conv_firstmet_type": "1"
        }
    }
    
    # Handle attachments (simplified, might need more work if attachments are used)
    # The capture showed complex structure, but for text chat this should be enough.
    
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
                try:
                    # 下一次会话需要同一个session
                    text, image_urls, conversation_id, message_id, section_id = await handle_sse(response)
                    if conversation_id:
                        session_pool.set_session(conversation_id, session)
                    return text, image_urls, conversation_id, message_id, section_id
                except LimitedException:
                    session_pool.del_session(session)
                    raise HTTPException(status_code=500, detail=f"游客限制5次会话已用完，请重使用新Session")
    except Exception as e:
        raise Exception(f"豆包API请求失败: {str(e)}")


async def handle_sse(response: aiohttp.ClientResponse):
    """处理SSE流响应 (New Protocol)"""
    buffer = ""
    conversation_id = ""
    message_id = ""
    section_id = ""
    texts = []
    image_urls = []
    
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
        
        while '\n\n' in buffer:
            evt, buffer = buffer.split('\n\n', 1)
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
            
            # Fallback: if no event type but has data, treat as message/chunk
            if not event_type and data_str:
                event_type = "implicit_message"
            
            if not event_type or not data_str:
                continue
            
            try:
                data = json.loads(data_str)
                
                if event_type == "SSE_ACK":
                    # Initial Ack
                    ack_meta = data.get("ack_client_meta", {})
                    conversation_id = ack_meta.get("conversation_id")
                    section_id = ack_meta.get("section_id")
                    logger.debug(f"SSE_ACK: conv_id={conversation_id}, sec_id={section_id}")
                    
                elif event_type == "STREAM_MSG_NOTIFY":
                    # Start of message?
                    meta = data.get("meta", {})
                    if not conversation_id:
                        conversation_id = meta.get("conversation_id")
                    if not section_id:
                        section_id = meta.get("section_id")
                    message_id = meta.get("message_id")
                    
                    content = data.get("content", {})
                    blocks = content.get("content_block", [])
                    for block in blocks:
                        text_block = block.get("content", {}).get("text_block", {})
                        if text := text_block.get("text"):
                            texts.append(text)
                            
                elif event_type == "STREAM_CHUNK":
                    # Patch updates
                    patch_ops = data.get("patch_op", [])
                    for op in patch_ops:
                        patch_type = op.get("patch_type") # 1 usually
                        patch_value = op.get("patch_value", {})
                        
                        # Handle text updates
                        if "content_block" in patch_value:
                            for block in patch_value["content_block"]:
                                text_block = block.get("content", {}).get("text_block", {})
                                if text := text_block.get("text"):
                                    texts.append(text)
                                # 修复：处理只有 text_block 且为空的情况（可能包含在其他字段里）或直接是文本
                        
                        # Handle tts_content as a fallback for text (Observed in logs: patch_value={"tts_content":"想"})
                        if "tts_content" in patch_value:
                            tts_text = patch_value["tts_content"]
                            # Doubao tts_content often contains the *entire* sentence accumulated so far, or just a chunk.
                            # The log showed single chars: "想", "做", "数字"...
                            # But sometimes it might be accumulated.
                            # Given the logs showed distinct single chars, we append them.
                            # But we need to be careful not to duplicate if content_block also fired.
                            
                            # Log to see what's happening
                            logger.debug(f"TTS Content found: {tts_text}")
                            
                            if tts_text:
                                texts.append(tts_text)

                elif event_type == "FULL_MSG_NOTIFY":
                    # Full message content in one go
                    message = data.get("message", {})
                    
                    # 优先使用 content_block 如果存在（解析后的）
                    if "content_block" in message:
                        content_blocks = message.get("content_block", [])
                        for block in content_blocks:
                             text_block = block.get("content", {}).get("text_block", {})
                             if text := text_block.get("text"):
                                 texts.append(text)
                    else:
                        # 否则尝试解析 content 字符串
                        content_str = message.get("content", "")
                        if content_str:
                             try:
                                 # Try to parse content as JSON list of blocks
                                 content_blocks = json.loads(content_str)
                                 if isinstance(content_blocks, list):
                                     for block in content_blocks:
                                         text_block = block.get("content", {}).get("text_block", {})
                                         if text := text_block.get("text"):
                                             texts.append(text)
                                 else:
                                     # Fallback if not list
                                     texts.append(str(content_str))
                             except:
                                 # Fallback if not JSON
                                 # Clean up potential JSON artifacts if it was a failed parse but still meaningful
                                 texts.append(str(content_str))

                elif event_type == "message" or event_type == "implicit_message":
                    # Some responses use simple 'message' event for full content or delta
                    # This is a fallback based on observation of similar APIs
                    try:
                        # Try to parse as JSON first
                        if isinstance(data, dict):
                             content = data.get("content", "")
                             if content and isinstance(content, str):
                                 texts.append(content)
                        elif isinstance(data, str):
                             texts.append(data)
                    except:
                        # If data is just a string
                        if isinstance(data_str, str):
                            texts.append(data_str)
                
                elif event_type == "SSE_REPLY_END":
                    # End of reply
                    logger.debug("SSE_REPLY_END received")
                    # break # Don't break here, wait for stream to close naturally or next event
                    
            except Exception as e:
                logger.warning(f"Error parsing event {event_type}: {e}")
                continue

    text = "".join(texts)
    logger.debug(f"SSE流结束: 获取到文本长度={len(text)}")
    return text, image_urls, conversation_id, message_id, section_id


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
