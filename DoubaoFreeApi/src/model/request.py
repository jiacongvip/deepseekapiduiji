from pydantic import BaseModel
from typing import Optional, List, Union, Any

class CompletionRequest(BaseModel):
    prompt: Optional[str] = None
    guest: bool = False
    attachments: list[dict] = []
    conversation_id: Optional[str] = None
    section_id: Optional[str] = None
    use_deep_think: bool = False
    use_auto_cot: bool = False
    
    # OpenAI compatibility fields
    messages: Optional[List[dict]] = None
    model: Optional[str] = None
    stream: Optional[bool] = False
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None


class AttachmentRequest(BaseModel):
    key: str
    name: str
    type: str
    file_review_state: int
    file_parse_state: int
    identifier: str
    option: Optional[dict] = None
    md5: Optional[str] = None
    size: Optional[int] = None


class UploadRequest(BaseModel):
    file_type: int
    file_name: str
    file_bytes: bytes