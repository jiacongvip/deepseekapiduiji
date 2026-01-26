from fastapi import APIRouter, Body, Query, HTTPException, Header
from src.service import chat_completion, delete_conversation
from src.model.response import CompletionResponse, DeleteResponse
from src.model.request import CompletionRequest
from src.pool.session_pool import DoubaoSession
from typing import Optional
from loguru import logger
import json


router = APIRouter()


@router.post("/completions", response_model=CompletionResponse)
async def api_completions(
    completion: CompletionRequest = Body(),
    authorization: Optional[str] = Header(None)
):
    """
    豆包聊天补全接口(目前仅支持文字消息e和图片消息)
    1. 如果是新聊天 conversation_id, section_id**不填**
    2. 如果沿用之前的聊天, 则沿用**第一次对话**返回的 conversation_id 和 section_id, 会话池会使用之前的参数
    3. 目前如果使用未登录账号，那么不支持上下文
    """
    session_override = None
    if authorization:
        try:
            # The gateway sends "Bearer <json_string>"
            token_str = authorization.replace("Bearer ", "").strip()
            # Basic validation to see if it looks like JSON
            if token_str.startswith("{") and token_str.endswith("}"):
                session_data = json.loads(token_str)
                # Ensure it has the critical cookie field
                if "cookie" in session_data:
                    # Construct DoubaoSession with defaults for missing fields
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

    # Compatibility logic: Convert OpenAI messages to prompt
    prompt = completion.prompt
    if not prompt and completion.messages:
        # Simple concatenation or taking the last user message
        # For simplicity, we'll take the content of the last message from user
        for msg in reversed(completion.messages):
            if msg.get("role") == "user":
                prompt = msg.get("content")
                break
    
    if not prompt:
        raise HTTPException(status_code=400, detail="Field 'prompt' or 'messages' (with user content) is required")

    try:
        text, imgs, conv_id, msg_id, sec_id = await chat_completion(
            prompt=prompt,
            guest=completion.guest,
            conversation_id=completion.conversation_id,
            section_id=completion.section_id,
            attachments=completion.attachments,
            use_auto_cot=completion.use_auto_cot,
            use_deep_think=completion.use_deep_think,
            session_override=session_override
        )
        return CompletionResponse(
            text=text, 
            img_urls=imgs, 
            conversation_id=conv_id, 
            messageg_id=msg_id, 
            section_id=sec_id
            )
    except Exception as e:
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