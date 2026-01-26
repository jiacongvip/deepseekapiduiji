from pydantic import BaseModel
from typing import Optional

class CompletionRequest(BaseModel):
    prompt: str
    guest: bool
    attachments: list[dict] = []
    conversation_id: Optional[str] = None
    section_id: Optional[str] = None
    use_deep_think: bool = False
    use_auto_cot: bool = False


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