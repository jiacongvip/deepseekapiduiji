from pydantic import BaseModel
import uuid
from typing import Optional


class CompletionResponse(BaseModel):
    text: str
    img_urls: list[str]
    conversation_id: str
    messageg_id: str
    section_id: str
    
    
class UploadResponse(BaseModel):
    key: str
    name: str
    type: str
    file_review_state: int
    file_parse_state: int
    identifier: str
    option: Optional[dict] = None
    md5: Optional[str] = None
    size: Optional[int] = None
    

class ImageResponse(BaseModel):
    key: str
    name: str
    option: dict
    type: str = "vlm_image"
    file_review_state: int = 3
    file_parse_state: int = 3
    identifier: str = str(uuid.uuid1())


class FileResponse(BaseModel):
    key: str
    name: str
    md5: str
    size: int
    type: str = "file"
    file_review_state: int = 1
    file_parse_state: int = 3
    identifier: str = str(uuid.uuid1())
    

class DeleteResponse(BaseModel):
    ok: bool
    msg: str