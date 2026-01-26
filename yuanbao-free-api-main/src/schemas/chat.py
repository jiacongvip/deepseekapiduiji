from typing import List, Optional

from pydantic import BaseModel, field_validator

from src.const import MODEL_MAPPING
from src.schemas.common import Media


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    messages: List[Message]
    model: str
    agent_id: str
    chat_id: Optional[str] = None
    hy_source: str = "web"
    hy_user: str
    should_remove_conversation: bool = False
    multimedia: List[Media] = []

    @field_validator("messages")
    def check_messages_not_empty(cls, value):
        if not value:
            raise ValueError("messages cannot be an empty list")
        return value

    @field_validator("model")
    def validate_model(cls, value):
        if value not in MODEL_MAPPING:
            raise ValueError(f"model must be one of {list(MODEL_MAPPING.keys())}")
        return value


class YuanBaoChatCompletionRequest(BaseModel):
    agent_id: str
    chat_id: str
    prompt: str
    agent_id: str
    chat_model_id: str
    multimedia: List[Media] = []
    support_functions: Optional[List[str]]


class ChoiceDelta(BaseModel):
    role: str = "assistant"
    content: str = ""


class Choice(BaseModel):
    index: int = 0
    delta: ChoiceDelta
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[Choice]
