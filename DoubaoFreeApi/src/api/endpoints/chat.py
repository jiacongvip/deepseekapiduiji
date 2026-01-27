from fastapi import APIRouter, Body, Query, HTTPException, Header
from fastapi.responses import StreamingResponse
from src.service import chat_completion, delete_conversation
from src.model.response import CompletionResponse, DeleteResponse
from src.model.request import CompletionRequest
from src.pool.session_pool import DoubaoSession
from typing import Optional
from loguru import logger
import json
import uuid
import time


router = APIRouter()


def create_openai_response(text: str, conv_id: str = "", model: str = "doubao-pro-4k", references: list = None):
    """创建 OpenAI 兼容的非流式响应"""
    message = {
        "role": "assistant",
        "content": text
    }
    
    # 如果有引用，添加到 message 中
    if references:
        message["references"] = references
    
    return {
        "id": f"chatcmpl-{conv_id or uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": len(text),
            "total_tokens": len(text)
        }
    }


def create_openai_stream_chunk(content: str, conv_id: str = "", model: str = "doubao-pro-4k", is_first: bool = False, is_done: bool = False, references: list = None):
    """创建 OpenAI 兼容的流式响应 chunk"""
    if is_done:
        delta = {}
        # 如果有引用，在结束时发送
        if references:
            delta["references"] = references
        return {
            "id": f"chatcmpl-{conv_id or uuid.uuid4()}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": "stop"
                }
            ]
        }
    
    delta = {"content": content}
    if is_first:
        delta["role"] = "assistant"
    
    return {
        "id": f"chatcmpl-{conv_id or uuid.uuid4()}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": None
            }
        ]
    }


@router.post("/completions")
async def api_completions(
    completion: CompletionRequest = Body(),
    authorization: Optional[str] = Header(None)
):
    """
    豆包聊天补全接口 - OpenAI 兼容格式
    支持流式和非流式响应
    """
    session_override = None
    if authorization:
        try:
            token_str = authorization.replace("Bearer ", "").strip()
            if token_str.startswith("{") and token_str.endswith("}"):
                session_data = json.loads(token_str)
                if "cookie" in session_data:
                    session_override = DoubaoSession(
                        cookie=session_data.get("cookie", ""),
                        device_id=session_data.get("device_id", "0"),
                        tea_uuid=session_data.get("tea_uuid", "0"),
                        web_id=session_data.get("web_id", "0"),
                        room_id=session_data.get("room_id", "0"),
                        x_flow_trace=session_data.get("x_flow_trace", "")
                    )
        except Exception as e:
            logger.warning(f"Failed to parse Authorization header as session config: {e}")

    # Convert OpenAI messages to prompt
    prompt = completion.prompt
    if not prompt and completion.messages:
        for msg in reversed(completion.messages):
            if msg.get("role") == "user":
                content = msg.get("content")
                # Handle multimodal content (list format)
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif isinstance(item, str):
                            text_parts.append(item)
                    prompt = "\n".join(text_parts)
                else:
                    prompt = content
                break
    
    if not prompt:
        raise HTTPException(status_code=400, detail="Field 'prompt' or 'messages' (with user content) is required")

    model = completion.model or "doubao-pro-4k"
    stream = completion.stream or False
    
    # 检查模型名是否包含 deep，启用深度思考
    use_deep_think = completion.use_deep_think or ("deep" in model.lower())
    
    logger.info(f"收到聊天请求: prompt长度={len(prompt)}, stream={stream}, model={model}, use_deep_think={use_deep_think}")

    if stream:
        # 流式响应
        async def generate_stream():
            try:
                text, imgs, refs, conv_id, msg_id, sec_id = await chat_completion(
                    prompt=prompt,
                    guest=completion.guest,
                    conversation_id=completion.conversation_id,
                    section_id=completion.section_id,
                    attachments=completion.attachments,
                    use_auto_cot=completion.use_auto_cot,
                    use_deep_think=use_deep_think,
                    session_override=session_override
                )
                
                logger.info(f"聊天完成: text长度={len(text) if text else 0}, 引用数={len(refs) if refs else 0}")
                
                if text:
                    # 发送第一个 chunk（包含 role）
                    first_chunk = create_openai_stream_chunk("", conv_id, model, is_first=True)
                    yield f"data: {json.dumps(first_chunk)}\n\n"
                    
                    # 分块发送内容（模拟流式效果）
                    chunk_size = 10  # 每次发送的字符数
                    for i in range(0, len(text), chunk_size):
                        chunk_text = text[i:i+chunk_size]
                        chunk = create_openai_stream_chunk(chunk_text, conv_id, model)
                        yield f"data: {json.dumps(chunk)}\n\n"
                    
                    # 发送结束 chunk（包含引用）
                    done_chunk = create_openai_stream_chunk("", conv_id, model, is_done=True, references=refs)
                    yield f"data: {json.dumps(done_chunk)}\n\n"
                else:
                    # 空响应
                    error_chunk = create_openai_stream_chunk("抱歉，未能获取到回复内容。", conv_id, model, is_first=True)
                    yield f"data: {json.dumps(error_chunk)}\n\n"
                    done_chunk = create_openai_stream_chunk("", conv_id, model, is_done=True)
                    yield f"data: {json.dumps(done_chunk)}\n\n"
                
                yield "data: [DONE]\n\n"
                
            except Exception as e:
                logger.error(f"流式响应错误: {e}", exc_info=True)
                error_response = {
                    "error": {
                        "message": str(e),
                        "type": "server_error",
                        "code": 500
                    }
                }
                yield f"data: {json.dumps(error_response)}\n\n"
        
        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            }
        )
    else:
        # 非流式响应
        try:
            text, imgs, refs, conv_id, msg_id, sec_id = await chat_completion(
                prompt=prompt,
                guest=completion.guest,
                conversation_id=completion.conversation_id,
                section_id=completion.section_id,
                attachments=completion.attachments,
                use_auto_cot=completion.use_auto_cot,
                use_deep_think=use_deep_think,
                session_override=session_override
            )
            
            logger.info(f"聊天完成: text长度={len(text) if text else 0}, 引用数={len(refs) if refs else 0}, conversation_id={conv_id}")
            
            if not text:
                text = "抱歉，未能获取到回复内容。"
            
            return create_openai_response(text, conv_id, model, references=refs)
            
        except Exception as e:
            logger.error(f"聊天请求处理失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))



@router.post("/delete", response_model=DeleteResponse)
async def api_delete(conversation_id: str = Query()):
    """
    删除聊天
    1. conversation_id 不存在也会提示成功
    2. 建议在聊天结束时都调用函数，避免创建过多对话
    """
    try:
        ok, msg = await delete_conversation(conversation_id)
        return DeleteResponse(
            ok=ok,
            msg=msg
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))