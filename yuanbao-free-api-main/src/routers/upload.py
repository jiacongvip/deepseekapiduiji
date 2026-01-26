import logging
from fastapi import APIRouter, Depends, HTTPException

from src.dependencies.auth import get_authorized_headers
from src.schemas.common import Media
from src.schemas.upload import UploadFileRequest
from src.services.upload.info import get_upload_info
from src.services.upload.uploader import upload_file_to_cos

router = APIRouter()


@router.post("/v1/upload", response_model=Media)
async def upload_file(
    request: UploadFileRequest,
    headers: dict = Depends(get_authorized_headers),
):
    try:
        upload_info = await get_upload_info(request.file.file_name, headers)
        logging.info("Upload info retrieved successfully")
        logging.debug(f"upload_info: {upload_info}")

        file_info = await upload_file_to_cos(
            request.file,
            upload_info,
            headers["User-Agent"],
        )
        logging.info("File uploaded successfully")
        logging.debug(f"File uploaded successfully: {file_info}")
        return file_info
    except Exception as e:
        logging.error(f"Error in upload_file: {e}")
        raise HTTPException(status_code=500, detail=str(e))
