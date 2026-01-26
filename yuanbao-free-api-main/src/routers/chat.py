import logging

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.dependencies.auth import get_authorized_headers
from src.schemas.chat import ChatCompletionRequest, YuanBaoChatCompletionRequest
from src.services.chat.completion import create_completion_stream
from src.services.chat.conversation import create_conversation
from src.utils.chat import get_model_info, parse_messages

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    headers: dict = Depends(get_authorized_headers),
):
    try:
        if not request.chat_id:
            request.chat_id = await create_conversation(request.agent_id, headers)
            logging.info(f"Conversation created with chat_id: {request.chat_id}")

        prompt = parse_messages(request.messages)
        model_info = get_model_info(request.model)
        if not model_info:
            raise HTTPException(status_code=400, detail="invalid model")

        chat_request = YuanBaoChatCompletionRequest(
            agent_id=request.agent_id,
            chat_id=request.chat_id,
            prompt=prompt,
            chat_model_id=model_info["model"],
            multimedia=request.multimedia,
            support_functions=model_info.get("support_functions"),
        )

        generator = create_completion_stream(chat_request, headers, request.should_remove_conversation)
        logging.info(f"Streaming chat completion for chat_id: {request.chat_id}")
        return EventSourceResponse(generator, media_type="text/event-stream")
    except Exception as e:
        logging.error(f"Error in chat_completions: {e}")
        raise HTTPException(status_code=500, detail=str(e))
