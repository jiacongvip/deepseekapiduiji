from pydantic import BaseModel


class File(BaseModel):
    file_name: str
    file_data: str
    file_type: str


class UploadFileRequest(BaseModel):
    agent_id: str
    hy_source: str = "web"
    hy_user: str
    file: File
