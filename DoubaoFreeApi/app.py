from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi import Request
from src.api.router import router
from src.pool import session_pool
import uvicorn


app = FastAPI(
    title="豆包API服务",
    description="轻量级豆包API代理服务",
    version="0.2.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="src/static"), name="static")
templates = Jinja2Templates(directory="src/templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.on_event("startup")
async def startup():
    # 尝试加载session.json，如果存在，说明已经获取了手动登录的session
    session_pool.load_from_file()
    
    if not session_pool.auth_sessions and not session_pool.guest_sessions:
        print("未找到会话配置，尝试获取游客Session...")
        try:
            await session_pool.fetch_guest_session(1)
            print("成功获取游客Session")
        except Exception as e:
            print(f"获取游客Session失败: {e}")
            print("服务将继续启动，但游客模式可能不可用。请尝试手动配置session.json")

app.include_router(router, prefix="/api")

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
