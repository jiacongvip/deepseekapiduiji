from typing import Dict

import httpx

UPLOAD_URL = "https://yuanbao.tencent.com/api/resource/genUploadInfo"

DEFAULT_TIMEOUT = 60


class GetUploadInfoError(Exception):
    pass


async def get_upload_info(file_name: str, headers: Dict[str, str], timeout: int = DEFAULT_TIMEOUT) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                UPLOAD_URL,
                json={"fileName": file_name, "docFrom": "localDoc", "docOpenId": ""},
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()

    except Exception as e:
        raise GetUploadInfoError(e)
