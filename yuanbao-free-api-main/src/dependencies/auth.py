from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from src.utils.common import generate_headers

bearer_scheme = HTTPBearer(auto_error=False)


async def get_authorized_headers(
    request: Request,
    authorization: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    if not authorization or not authorization.credentials:
        raise HTTPException(status_code=401, detail="need token")

    token = authorization.credentials

    content_type = request.headers.get("Content-Type", "")

    if "application/json" in content_type:
        data = await request.json()
    elif "multipart/form-data" in content_type:
        form = await request.form()
        data = dict(form)
    else:
        raise HTTPException(status_code=400, detail="Unsupported Content-Type")

    headers = generate_headers(data, token)
    return headers
