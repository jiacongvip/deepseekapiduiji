import json
import os
import random
import httpx
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from pydantic import BaseModel
from typing import Dict, List, Optional
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI API Gateway")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DEFAULT_CONFIG_FILE = os.path.join(BASE_DIR, "config.default.json")

def load_config():
    default_config = {}
    if os.path.exists(DEFAULT_CONFIG_FILE):
        try:
            with open(DEFAULT_CONFIG_FILE, "r") as f:
                default_config = json.load(f)
        except Exception as e:
            logger.error(f"Error loading default config: {e}")

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                user_config = json.load(f)

            if default_config:
                for key, val in default_config.items():
                    if key not in user_config:
                        user_config[key] = val
                        continue

                    user_service = user_config.get(key)
                    if not (isinstance(val, dict) and isinstance(user_service, dict) and "models" in val):
                        continue

                    if "models" not in user_service:
                        user_service["models"] = val["models"]
                        continue

                    if isinstance(user_service["models"], list):
                        existing_models = set(user_service["models"])
                        for model in val["models"]:
                            if model not in existing_models:
                                user_service["models"].append(model)

            return user_config
        except Exception as e:
            logger.error(f"Error loading config.json: {e}")
            
    # Fallback to default if config.json doesn't exist or failed to load
    if default_config:
        # Auto-create config.json from default if it doesn't exist
        if not os.path.exists(CONFIG_FILE):
            save_config(default_config)
        return default_config
            
    return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    config = load_config()
    return templates.TemplateResponse("index.html", {"request": request, "config": config})

@app.get("/api/config")
async def get_config():
    return load_config()

@app.post("/api/config")
async def update_config(config: Dict):
    try:
        save_config(config)
    except Exception as e:
        logger.exception(f"Error saving config.json: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save config: {e}")
    return {"status": "ok"}

@app.get("/api/env")
async def get_env_info():
    """Returns environment and config loading status for debugging"""
    config = load_config()
    
    # Mask secrets
    masked_config = {}
    for k, v in config.items():
        masked_config[k] = v.copy()
        token = v.get("token")
        if token:
            if isinstance(token, list):
                masked_config[k]["token"] = [f"{t[:5]}...{t[-5:]}" if isinstance(t, str) and len(t)>10 else "***" for t in token]
            elif isinstance(token, str):
                masked_config[k]["token"] = f"{token[:5]}...{token[-5:]}" if len(token)>10 else "***"
    
    return {
        "config_file_exists": os.path.exists(CONFIG_FILE),
        "default_config_exists": os.path.exists(DEFAULT_CONFIG_FILE),
        "loaded_config": masked_config,
        "env_vars": {k: "***" for k in os.environ if "TOKEN" in k}
    }

@app.get("/api/test/{service_key}")
async def test_service_connection(service_key: str):
    """Test connection to a specific service upstream with AUTH check"""
    config = load_config()
    if service_key not in config:
        raise HTTPException(status_code=404, detail="Service not found")
        
    service = config[service_key]
    url = service.get("url")
    token_config = service.get("token")
    
    # Pick a token to test
    selected_account = None
    if isinstance(token_config, list) and len(token_config) > 0:
        selected_account = token_config[0] # Test the first one
    elif isinstance(token_config, str) and token_config.strip():
        selected_account = token_config
        
    final_token = None
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Gateway-Test/1.0"
    }
    
    body = {}
    
    if selected_account:
        if isinstance(selected_account, dict):
             # Yuanbao style
             final_token = selected_account.get("hy_token") or selected_account.get("token")
             for k, v in selected_account.items():
                if k not in ["token", "hy_token"]:
                    body[k] = v
        else:
             final_token = selected_account

    if final_token:
        if service_key == "baidu" and (final_token.strip().startswith("{") or "BDUSS" in final_token):
             headers["Authorization"] = final_token
        else:
             headers["Authorization"] = f"Bearer {final_token}"
    
    # Try a simple chat completion (Dry Run)
    # We use a very short prompt to minimize cost/time
    target_url = f"{url}/v1/chat/completions"
    
    # Pick a model
    model = "gpt-3.5-turbo" # Default fallback
    if service.get("models"):
        model = service["models"][0]
    
    body["model"] = model
    body["messages"] = [{"role": "user", "content": "Hi"}]
    body["stream"] = False
    body["max_tokens"] = 1

    async with httpx.AsyncClient() as client:
        try:
            # First, try models endpoint (lighter) if it supports it, BUT many free-api might not auth it correctly.
            # So we go straight to chat completion to verify TOKEN.
            
            # Note: Some free APIs might be slow.
            resp = await client.post(target_url, json=body, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                return {
                    "status": "success",
                    "code": resp.status_code,
                    "url": url,
                    "message": "Auth Valid! (Chat Check Passed)"
                }
            else:
                # Try to read error
                try:
                    err_text = resp.text
                    # Truncate
                    if len(err_text) > 200: err_text = err_text[:200] + "..."
                except:
                    err_text = "Unknown error"
                    
                return {
                    "status": "error",
                    "code": resp.status_code,
                    "url": url,
                    "message": f"HTTP {resp.status_code}: {err_text}"
                }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Connection Error: {str(e)}",
                "url": url
            }

@app.get("/api/yuanbao/login/qrcode")
async def yuanbao_login_qrcode():
    """代理元宝服务的获取二维码接口"""
    config = load_config()
    if "yuanbao" not in config:
        raise HTTPException(status_code=404, detail="Yuanbao service not configured")
    
    # 假设元宝服务在 docker-compose 中的名称是 yuanbao-free-api，端口是 8003
    # 注意：这里的 url 应该是内部容器网络地址
    # config.json 中的 url 可能是外部地址，这里我们硬编码或推断内部地址
    # 更好的方式是 config.json 中存储 internal_url
    
    # 这里直接使用 docker-compose 中的 service name
    target_url = "http://yuanbao-free-api:8003/login/qrcode"
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(target_url, timeout=10)
            return resp.json()
        except Exception as e:
            logger.error(f"Proxy error: {e}")
            raise HTTPException(status_code=502, detail="Failed to connect to Yuanbao service")

@app.get("/api/yuanbao/login/status")
async def yuanbao_login_status(uuid: str):
    """代理元宝服务的检查状态接口"""
    target_url = f"http://yuanbao-free-api:8003/login/status?uuid={uuid}"
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(target_url, timeout=10)
            return resp.json()
        except Exception as e:
            logger.error(f"Proxy error: {e}")
            raise HTTPException(status_code=502, detail="Failed to connect to Yuanbao service")

@app.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Model is required")

    config = load_config()
    
    # 简单的路由逻辑：遍历配置，查找支持该 model 的服务
    # 或者如果 model 名字包含服务名，也可以作为 fallback
    target_service = None
    target_key = None
    
    # First pass: Exact match or Prefix match (explicitly configured models)
    for key, service in config.items():
        # 1. 精确匹配
        if model in service.get("models", []):
            target_service = service
            target_key = key
            break
        # 3. 前缀匹配配置的模型 (e.g. moonshot-v1-8k-search matches moonshot-v1-8k)
        for svc_model in service.get("models", []):
            if model.startswith(svc_model):
                target_service = service
                target_key = key
                break
        if target_service:
            break
            
    # Second pass: Fuzzy service name match (Only if no explicit match found)
    if not target_service:
        for key, service in config.items():
            # 2. 服务名匹配 (e.g. deepseek-chat matches deepseek)
            # CAUTION: This is dangerous if model name overlaps with service name but belongs to another service
            # e.g. DeepSeek-R1 contains 'deepseek' but might be configured for 'baidu'
            if key in model.lower():
                 # Double check if this model is explicitly configured in another service? 
                 # Too complex. Assuming explicit config is done in First Pass.
                 target_service = service
                 target_key = key
                 break
            
    # 如果没找到，尝试默认 fallback (例如 baidu 的 DeepSeek-R1)
    if not target_service:
        # 特殊处理 DeepSeek-R1 -> Baidu
        if model == "DeepSeek-R1" and "baidu" in config:
            target_service = config["baidu"]
            target_key = "baidu"
        else:
             # Default to first one or error? Let's error for now
             pass

    if not target_service:
        # Try to guess based on prefix
        for key in config:
            if model.startswith(key):
                target_service = config[key]
                target_key = key
                break
    
    if not target_service:
         raise HTTPException(status_code=404, detail=f"No service found for model: {model}")

    target_url = f"{target_service['url']}/v1/chat/completions"
        
    token_config = target_service.get("token")
    selected_account = None
    if isinstance(token_config, list):
        token_meta = f"list(len={len(token_config)})"
    elif isinstance(token_config, str):
        token_meta = "string(set)" if token_config.strip() else "string(empty)"
    elif token_config is None:
        token_meta = "none"
    else:
        token_meta = type(token_config).__name__
    logger.info(f"Token config for {target_key}: {token_meta}")

    # Support token rotation if it's a list
    if isinstance(token_config, list) and len(token_config) > 0:
        selected_account = random.choice(token_config)
    elif isinstance(token_config, str) and token_config.strip():
        # Single string token (non-empty)
        selected_account = token_config
    else:
        # Empty string, None, or empty list
        selected_account = None

    final_token = None
    
    if selected_account:
        if isinstance(selected_account, dict):
            # Yuanbao-style account object
            # Extract the auth token (usually hy_token for Yuanbao)
            final_token = selected_account.get("hy_token") or selected_account.get("token")
            
            # Inject other fields (hy_user, agent_id) into request body
            # This ensures the proxy receives the matching user/agent for the token
            for k, v in selected_account.items():
                if k not in ["token", "hy_token"]:
                    body[k] = v
        else:
            final_token = selected_account
    
    logger.info(f"Routing request for model {model} to {target_key} ({target_url})")

    if target_key == "qwen":
        if isinstance(body.get("max_tokens"), int) and body.get("max_tokens", 0) <= 0:
            body.pop("max_tokens", None)
        if isinstance(body.get("max_completion_tokens"), int) and body.get("max_completion_tokens", 0) <= 0:
            body.pop("max_completion_tokens", None)
        for k in [
            "stream_options",
            "response_format",
            "tools",
            "tool_choice",
            "functions",
            "function_call",
        ]:
            body.pop(k, None)

    try:
        message_count = len(body.get("messages") or [])
        roles = []
        for m in (body.get("messages") or [])[:6]:
            if isinstance(m, dict) and m.get("role"):
                roles.append(m.get("role"))
        logger.info(
            "Request body meta: "
            f"keys={sorted([k for k in body.keys() if isinstance(k, str)])} "
            f"stream={bool(body.get('stream'))} "
            f"max_tokens={body.get('max_tokens')} "
            f"messages={message_count} "
            f"roles={roles}"
        )
    except Exception:
        pass

    # 构建 Header
    # 只保留 Content-Type，其他 header 一律不转发，防止污染 upstream 请求
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }
    
    # 注入 Token
    if final_token:
        # 如果是 Baidu 且 token 是 JSON，或者看起来像 Cookie 字符串，直接传
        # 其他通常也是 Bearer Token
        # 为了兼容 Baidu 服务端的 load_cookies 逻辑 (JSON or Cookie String)
        if target_key == "baidu" and (final_token.strip().startswith("{") or "BDUSS" in final_token):
            headers["Authorization"] = final_token
        else:
            headers["Authorization"] = f"Bearer {final_token}"
    else:
        logger.warning(f"No token configured for service {target_key}. Request sent without Authorization header.")
    
    # 打印请求头用于调试（脱敏）
    debug_headers = headers.copy()
    if "Authorization" in debug_headers:
        debug_headers["Authorization"] = debug_headers["Authorization"][:10] + "..."
    logger.info(f"Request Headers: {debug_headers}")
    
    stream = bool(body.get("stream"))

    async def proxy_stream_sse():
        client = httpx.AsyncClient()
        try:
            async with client.stream("POST", target_url, json=body, headers=headers, timeout=120.0) as response:
                # Forward status code if error
                logger.info(f"Response Status: {response.status_code}")
                
                content_type = response.headers.get("Content-Type", "")
                
                # Check for upstream errors (Status >= 400 OR JSON response when expecting stream)
                # Many free-api wrappers return 200 OK with JSON body for errors
                if response.status_code >= 400 or "application/json" in content_type:
                    # We need to read the body to check if it's an error
                    # CAUTION: If it's a legitimate large JSON response (non-stream), reading it all might be slow, but usually fine for chat.
                    content = await response.aread()
                    text_content = content.decode('utf-8', errors='replace')
                    
                    is_error = False
                    if response.status_code >= 400:
                        is_error = True
                    else:
                        # Check if body contains "error" field
                        try:
                            json_body = json.loads(text_content)
                            if "error" in json_body or "code" in json_body and json_body.get("code") != 0:
                                # Loose check for error-like structure
                                # Standard OpenAI error is {"error": {...}}
                                if "error" in json_body:
                                    is_error = True
                        except:
                            pass
                            
                    if is_error:
                        logger.error(f"Upstream Error: {text_content}")
                        yield f"data: {json.dumps({'error': f'Upstream error {response.status_code}: {text_content}'})}\n\n"
                        return
                    else:
                        # It's a valid JSON response (maybe non-stream was requested or forced)
                        # Yield it as a single chunk if possible, or just write it
                        # Since we are in an async generator yielding bytes or strings...
                        # If we yield bytes, FastAPI handles it.
                        yield f"data: {text_content}\n\n"
                        return

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    # Ensure we forward SSE lines correctly
                    # Some upstream services might return raw JSON in chunks without "data: " prefix if not strict SSE
                    # But DoubaoFreeApi should be returning standard SSE.
                    
                    if line.startswith("data:") or line.startswith("event:") or line.startswith(":"):
                        yield f"{line}\n\n"
                    elif line.strip() == "[DONE]":
                        yield "data: [DONE]\n\n"
                    else:
                        # Fallback: wrap raw content in data
                        # Only if it looks like content
                        if line.strip():
                             yield f"data: {line}\n\n"
                             
        except Exception as e:
            logger.error(f"Proxy error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            await client.aclose()

    if not stream:
        async with httpx.AsyncClient() as non_stream_client:
            response = await non_stream_client.post(target_url, json=body, headers=headers, timeout=120.0)
            media_type = response.headers.get("Content-Type") or "application/json"
            return Response(content=response.content, status_code=response.status_code, media_type=media_type)

    return StreamingResponse(
        proxy_stream_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no", # Critical for Nginx/Baota
            "Content-Type": "text/event-stream",
        },
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8888, reload=True)
