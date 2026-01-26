import logging

from fastapi import FastAPI

from src.routers import chat, upload, login

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="YuanBao API Proxy", version="1.0.0")

app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(login.router)

if __name__ == "__main__":
    import uvicorn
    import os

    port = int(os.environ.get("PORT", 8003))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
