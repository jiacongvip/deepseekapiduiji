import json
import os
import random
import asyncio
import time
import httpx
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from pydantic import BaseModel
from typing import Dict, List, Optional
from datetime import datetime, timezone
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

def _now_iso_utc():
    return datetime.now(timezone.utc).isoformat()

def _select_service_for_model(config: Dict, model: str):
    target_service = None
    target_key = None

    # First pass: Exact match or Prefix match (explicitly configured models)
    for key, service in (config or {}).items():
        if model in service.get("models", []):
            target_service = service
            target_key = key
            break
        for svc_model in service.get("models", []):
            if isinstance(svc_model, str) and model.startswith(svc_model):
                target_service = service
                target_key = key
                break
        if target_service:
            break

    # Second pass: Fuzzy service name match (Only if no explicit match found)
    if not target_service:
        for key, service in (config or {}).items():
            if isinstance(key, str) and key in model.lower():
                target_service = service
                target_key = key
                break

    # Special fallback: DeepSeek-R1 -> Baidu (legacy)
    if not target_service and model == "DeepSeek-R1" and "baidu" in (config or {}):
        target_service = config["baidu"]
        target_key = "baidu"

    # Last fallback: Guess based on prefix of service key
    if not target_service:
        for key in (config or {}):
            if isinstance(key, str) and model.startswith(key):
                target_service = config[key]
                target_key = key
                break

    return target_key, target_service

async def _probe_upstream(
    client: httpx.AsyncClient,
    service_key: str,
    service: Dict,
    *,
    timeout: float = 10.0,
    token_strategy: str = "first",
    user_agent: str = "Gateway-Monitor/1.0",
):
    """
    Minimal upstream probe (auth + basic endpoint).
    Returns a dict compatible with /api/test response, plus latency_ms/model/checked_at.
    """
    started = time.monotonic()
    url = (service or {}).get("url")
    if not url:
        return {
            "status": "error",
            "code": 0,
            "url": url,
            "message": "No upstream url configured",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "checked_at": _now_iso_utc(),
        }

    token_config = (service or {}).get("token")
    selected_account = None
    if isinstance(token_config, list) and len(token_config) > 0:
        selected_account = token_config[0] if token_strategy == "first" else random.choice(token_config)
    elif isinstance(token_config, str) and token_config.strip():
        selected_account = token_config

    # Jimeng uses token management endpoints rather than chat completions
    if service_key == "jimeng":
        final_token = None
        if selected_account:
            if isinstance(selected_account, dict):
                final_token = selected_account.get("token") or selected_account.get("hy_token")
            else:
                final_token = selected_account

        headers = {
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        }

        if not final_token:
            latency_ms = int((time.monotonic() - started) * 1000)
            return {
                "status": "error",
                "code": 0,
                "url": url,
                "probe": "/token/check",
                "message": "No token configured",
                "latency_ms": latency_ms,
                "checked_at": _now_iso_utc(),
            }

        try:
            resp = await client.post(
                f"{url}/token/check",
                json={"token": final_token},
                headers=headers,
                timeout=timeout,
            )
            latency_ms = int((time.monotonic() - started) * 1000)

            if resp.status_code != 200:
                err_text = ""
                try:
                    err_text = resp.text or ""
                except Exception:
                    err_text = "Unknown error"
                if len(err_text) > 200:
                    err_text = err_text[:200] + "..."
                return {
                    "status": "error",
                    "code": resp.status_code,
                    "url": url,
                    "probe": "/token/check",
                    "message": f"HTTP {resp.status_code}: {err_text}" if err_text else f"HTTP {resp.status_code}",
                    "latency_ms": latency_ms,
                    "checked_at": _now_iso_utc(),
                }

            live = None
            try:
                live = (resp.json() or {}).get("live")
            except Exception:
                live = None

            if live is True:
                return {
                    "status": "success",
                    "code": resp.status_code,
                    "url": url,
                    "probe": "/token/check",
                    "message": "Token live",
                    "latency_ms": latency_ms,
                    "checked_at": _now_iso_utc(),
                }

            return {
                "status": "error",
                "code": resp.status_code,
                "url": url,
                "probe": "/token/check",
                "message": "Token not live" if live is False else f"Unexpected response: {resp.text[:200]}",
                "latency_ms": latency_ms,
                "checked_at": _now_iso_utc(),
            }

        except Exception as e:
            latency_ms = int((time.monotonic() - started) * 1000)
            return {
                "status": "error",
                "code": 0,
                "url": url,
                "probe": "/token/check",
                "message": f"Connection Error: {str(e)}",
                "latency_ms": latency_ms,
                "checked_at": _now_iso_utc(),
            }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": user_agent,
    }
    body = {}

    final_token = None
    if selected_account:
        if isinstance(selected_account, dict):
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
    
    target_url = f"{url}/v1/chat/completions"

    model = "gpt-3.5-turbo"
    if isinstance(service.get("models"), list) and service["models"]:
        model = service["models"][0]

    body["model"] = model
    body["messages"] = [{"role": "user", "content": "Hi"}]
    body["stream"] = False
    body["max_tokens"] = 1

    try:
        resp = await client.post(target_url, json=body, headers=headers, timeout=timeout)
        latency_ms = int((time.monotonic() - started) * 1000)

        if resp.status_code == 200:
            return {
                "status": "success",
                "code": resp.status_code,
                "url": url,
                "model": model,
                "message": "Auth Valid! (Chat Check Passed)",
                "latency_ms": latency_ms,
                "checked_at": _now_iso_utc(),
            }

        err_text = ""
        try:
            err_text = resp.text or ""
        except Exception:
            err_text = "Unknown error"
        if len(err_text) > 200:
            err_text = err_text[:200] + "..."

        return {
            "status": "error",
            "code": resp.status_code,
            "url": url,
            "model": model,
            "message": f"HTTP {resp.status_code}: {err_text}" if err_text else f"HTTP {resp.status_code}",
            "latency_ms": latency_ms,
            "checked_at": _now_iso_utc(),
        }
    except Exception as e:
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            "status": "error",
            "code": 0,
            "url": url,
            "model": model,
            "message": f"Connection Error: {str(e)}",
            "latency_ms": latency_ms,
            "checked_at": _now_iso_utc(),
        }

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
    async with httpx.AsyncClient() as client:
        return await _probe_upstream(
            client,
            service_key,
            service,
            timeout=10.0,
            token_strategy="first",
            user_agent="Gateway-Test/1.0",
        )

@app.get("/api/monitor")
async def monitor_services(timeout: float = 10.0):
    """Run a probe against all configured upstream services and return a summary."""
    config = load_config()
    keys = list(config.keys())
    checked_at = _now_iso_utc()

    async with httpx.AsyncClient() as client:
        tasks = [
            _probe_upstream(
                client,
                key,
                config[key],
                timeout=timeout,
                token_strategy="first",
                user_agent="Gateway-Monitor/1.0",
            )
            for key in keys
        ]
        results_list = await asyncio.gather(*tasks)

    results = {k: v for k, v in zip(keys, results_list)}
    ok = sum(1 for v in results.values() if v.get("status") == "success")
    fail = len(results) - ok

    return {
        "checked_at": checked_at,
        "timeout": timeout,
        "summary": {"total": len(results), "ok": ok, "fail": fail},
        "results": results,
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
    
    target_key, target_service = _select_service_for_model(config, model)
    
    if not target_service:
         raise HTTPException(status_code=404, detail=f"No service found for model: {model}")

    if target_key == "jimeng":
        raise HTTPException(
            status_code=400,
            detail="Jimeng is an image/video service. Use /v1/images/generations or /v1/videos/generations.",
        )

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
                             # CAUTION: If the upstream sends partial JSON or raw text, we might be breaking it by wrapping in data:
                             # But for standard SSE, newlines should be handled.
                             # If line is just "}", it might be part of a previous JSON.
                             # But aiter_lines() splits by newline.
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
            # Add CORS headers specifically for the stream response just in case
            "Access-Control-Allow-Origin": "*",
        },
    )

def _build_upstream_headers(
    target_key: str,
    target_service: Dict,
    body: Optional[Dict] = None,
    *,
    content_type: str = "application/json",
):
    token_config = (target_service or {}).get("token")

    selected_account = None
    if isinstance(token_config, list) and len(token_config) > 0:
        selected_account = random.choice(token_config)
    elif isinstance(token_config, str) and token_config.strip():
        selected_account = token_config

    final_token = None
    if selected_account:
        if isinstance(selected_account, dict):
            final_token = selected_account.get("hy_token") or selected_account.get("token")
            if isinstance(body, dict):
                for k, v in selected_account.items():
                    if k not in ["token", "hy_token"]:
                        body[k] = v
        else:
            final_token = selected_account

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }
    if content_type:
        headers["Content-Type"] = content_type

    if final_token:
        if target_key == "baidu" and (final_token.strip().startswith("{") or "BDUSS" in final_token):
            headers["Authorization"] = final_token
        else:
            headers["Authorization"] = f"Bearer {final_token}"
    else:
        logger.warning(f"No token configured for service {target_key}. Request sent without Authorization header.")

    return headers

@app.post("/v1/images/generations")
async def proxy_images_generations(request: Request):
    """OpenAI-compatible image generation (Jimeng)"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    config = load_config()
    model = body.get("model")

    target_key = None
    target_service = None
    if model:
        target_key, target_service = _select_service_for_model(config, model)

    if not target_service:
        if "jimeng" in config:
            target_key = "jimeng"
            target_service = config["jimeng"]
            if not model:
                # Keep behaviour aligned with Jimeng upstream defaults
                body["model"] = "jimeng-4.5"
                model = body["model"]
        else:
            raise HTTPException(status_code=404, detail=f"No service found for model: {model or '(missing model)'}")

    target_url = f"{target_service['url']}/v1/images/generations"
    headers = _build_upstream_headers(target_key, target_service, body, content_type="application/json")
    logger.info(f"Routing image generation model={model} to {target_key} ({target_url})")

    async with httpx.AsyncClient() as client:
        response = await client.post(target_url, json=body, headers=headers, timeout=1800.0)
        media_type = response.headers.get("Content-Type") or "application/json"
        return Response(content=response.content, status_code=response.status_code, media_type=media_type)

@app.post("/v1/images/compositions")
async def proxy_images_compositions(request: Request):
    """OpenAI-compatible image composition (Jimeng). Supports JSON and multipart."""
    content_type = request.headers.get("Content-Type") or ""
    is_json = "application/json" in content_type.lower()

    config = load_config()
    target_key = None
    target_service = None
    body_json = None
    model = None

    if is_json:
        try:
            body_json = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        if isinstance(body_json, dict):
            model = body_json.get("model")
            if model:
                target_key, target_service = _select_service_for_model(config, model)

    if not target_service:
        if "jimeng" in config:
            target_key = "jimeng"
            target_service = config["jimeng"]
        else:
            raise HTTPException(status_code=404, detail="Jimeng service not configured")

    target_url = f"{target_service['url']}/v1/images/compositions"
    headers = _build_upstream_headers(
        target_key,
        target_service,
        body_json if is_json else None,
        content_type=content_type or ("application/json" if is_json else "application/octet-stream"),
    )
    logger.info(f"Routing image composition model={model or '-'} to {target_key} ({target_url})")

    async with httpx.AsyncClient() as client:
        if is_json:
            resp = await client.post(target_url, json=body_json, headers=headers, timeout=1800.0)
        else:
            raw = await request.body()
            resp = await client.post(target_url, content=raw, headers=headers, timeout=1800.0)
        media_type = resp.headers.get("Content-Type") or "application/json"
        return Response(content=resp.content, status_code=resp.status_code, media_type=media_type)

@app.post("/v1/videos/generations")
async def proxy_videos_generations(request: Request):
    """OpenAI-compatible video generation (Jimeng). Supports JSON and multipart."""
    content_type = request.headers.get("Content-Type") or ""
    is_json = "application/json" in content_type.lower()

    config = load_config()
    target_key = None
    target_service = None
    body_json = None
    model = None

    if is_json:
        try:
            body_json = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        if isinstance(body_json, dict):
            model = body_json.get("model")
            if model:
                target_key, target_service = _select_service_for_model(config, model)

    if not target_service:
        if "jimeng" in config:
            target_key = "jimeng"
            target_service = config["jimeng"]
        else:
            raise HTTPException(status_code=404, detail="Jimeng service not configured")

    target_url = f"{target_service['url']}/v1/videos/generations"
    headers = _build_upstream_headers(
        target_key,
        target_service,
        body_json if is_json else None,
        content_type=content_type or ("application/json" if is_json else "application/octet-stream"),
    )
    logger.info(f"Routing video generation model={model or '-'} to {target_key} ({target_url})")

    async with httpx.AsyncClient() as client:
        if is_json:
            resp = await client.post(target_url, json=body_json, headers=headers, timeout=1800.0)
        else:
            raw = await request.body()
            resp = await client.post(target_url, content=raw, headers=headers, timeout=1800.0)
        media_type = resp.headers.get("Content-Type") or "application/json"
        return Response(content=resp.content, status_code=resp.status_code, media_type=media_type)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8888, reload=True)
