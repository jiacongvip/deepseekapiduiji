from pydantic import BaseModel


class Media(BaseModel):
    type: str
    docType: str
    url: str
    fileName: str
    size: int
    width: int
    height: int
