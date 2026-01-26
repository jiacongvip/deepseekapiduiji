import json
import random
import secrets
import time
import os
import sys
import hmac
import logging
from base64 import b64encode
from hashlib import md5 as md5_hash, sha256 as sha256_hash
from urllib.parse import quote
from time import gmtime, strftime
from contextlib import asynccontextmanager

import requests
import bs4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 全局状态
class GlobalState:
    cookies: Dict[str, str] = {}
    user_token: Optional[str] = None
    lid: Optional[str] = None

state = GlobalState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    state.cookies = load_cookies()
    if not state.cookies:
        logger.warning("No cookies found! Please configure cookie.txt or BAIDU_COOKIE env var.")
    else:
        state.user_token, state.lid = get_token_lid()
        if state.user_token:
            logger.info("Successfully initialized Baidu AI token")
        else:
            logger.error("Failed to initialize Baidu AI token")
    yield
    # Shutdown logic (if any)

app = FastAPI(title="Baidu AI Proxy", version="1.0.0", lifespan=lifespan)

class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    model: Optional[str] = "DeepSeek-R1"
    stream: Optional[bool] = True
    session_id: Optional[str] = ""

def parse_cookie_string(cookie_str):
    parsed_cookies = {}
    for item in cookie_str.split(';'):
        if '=' in item:
            name, value = item.strip().split('=', 1)
            parsed_cookies[name] = value
    return parsed_cookies

def load_cookies():
    # 优先从环境变量读取
    env_cookie = os.environ.get("BAIDU_COOKIE")
    if env_cookie:
        logger.info("Loading cookies from environment variable")
        try:
            return json.loads(env_cookie)
        except json.JSONDecodeError:
            return parse_cookie_string(env_cookie)
            
    if os.path.exists("cookie.txt"):
        logger.info("Loading cookies from cookie.txt")
        with open("cookie.txt", "r", encoding="utf-8") as f:
            cookie_content = f.read().strip()
            if cookie_content.startswith('{'):
                try:
                    return json.loads(cookie_content)
                except json.JSONDecodeError:
                    return parse_cookie_string(cookie_content)
            else:
                return parse_cookie_string(cookie_content)
    return {}

def get_token_lid_for_cookies(cookies_dict):
    """Helper to get token/lid for arbitrary cookies"""
    url = "https://chat.baidu.com/search?isShowHello=1"
    headers = {
        "Host": "chat.baidu.com",
        "Connection": "keep-alive",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Referer": "https://cn.bing.com/",
    }
    try:
        res = requests.get(url, headers=headers, cookies=cookies_dict)
        soup = bs4.BeautifulSoup(res.text, "lxml")
        data_script = soup.find("script", attrs={"type":"application/json","name":"aiTabFrameBaseData"})
        if not data_script:
            logger.error("Failed to find aiTabFrameBaseData script for custom cookies")
            return None, None
            
        data = json.loads(data_script.string)
        if not data.get("userInfo", {}).get("isUserLogin"):
            logger.error("Cookie expired or not logged in for custom cookies")
            return None, None
            
        token = data["token"]
        lid = data["lid"]
        return token, lid
    except Exception as e:
        logger.error(f"Error getting token/lid for custom cookies: {e}")
        return None, None

def get_token_lid():
    url = "https://chat.baidu.com/search?isShowHello=1"
    headers = {
        "Host": "chat.baidu.com",
        "Connection": "keep-alive",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Referer": "https://cn.bing.com/",
    }
    try:
        res = requests.get(url, headers=headers, cookies=state.cookies)
        soup = bs4.BeautifulSoup(res.text, "lxml")
        data_script = soup.find("script", attrs={"type":"application/json","name":"aiTabFrameBaseData"})
        if not data_script:
            logger.error("Failed to find aiTabFrameBaseData script")
            return None, None
            
        data = json.loads(data_script.string)
        if not data.get("userInfo", {}).get("isUserLogin"):
            logger.error("Cookie expired or not logged in")
            return None, None
            
        token = data["token"]
        lid = data["lid"]
        return token, lid
    except Exception as e:
        logger.error(f"Error getting token/lid: {e}")
        return None, None

def md5(s):
    return md5_hash(s.encode()).hexdigest()

def get_tk(token, query, lid):
    p1 = token
    p2 = md5(query)
    p3 = str(int(time.time() * 1000))
    p4 = lid
    tk = b64encode(f"{p1}|{p2}|{p3}|{p4}".encode("utf-8")).decode("utf-8") + "-" + p4 + "-3"
    return tk

def get_anti_ext(query):
    inputT = len(query)*1000 + random.randint(-10*len(query), len(query)*20+300)
    ck1 = random.randint(79, 246)
    ck9 = random.randint(281, 1025)
    ck10 = random.randint(847, 926)
    return {
        "inputT": inputT,
        "ck1": ck1,
        "ck9": ck9,
        "ck10": ck10,
    }

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest, req: Request):
    # 鉴权
    auth_header = req.headers.get("Authorization")
    cookies_to_use = state.cookies
    
    if auth_header and auth_header.startswith("Bearer "):
        token_str = auth_header.split("Bearer ")[1].strip()
        if token_str:
            try:
                if token_str.startswith("{"):
                    cookies_to_use = json.loads(token_str)
                # If looks like cookie string
                elif "BDUSS" in token_str or "=" in token_str:
                    cookies_to_use = parse_cookie_string(token_str)
            except:
                pass
    
    if not cookies_to_use:
         raise HTTPException(status_code=500, detail="Cookies not configured. Provide via Authorization header or server config.")
    
    # Need to get token/lid for these specific cookies if they changed or if global token is missing
    # For simplicity, if cookies changed from global, we re-fetch token/lid. 
    # NOTE: This might be slow if done per request. In a real app, cache this.
    
    # Check if we need to refresh token (if using global cookies)
    current_token = state.user_token
    current_lid = state.lid
    
    # If using custom cookies, we MUST fetch new token/lid
    if cookies_to_use != state.cookies:
         # This is a bit inefficient for every request but necessary for statelessness
         # We could cache based on cookie hash
         # For now, let's just fetch it.
         # Re-implement get_token_lid logic here or modify the function to accept cookies
         current_token, current_lid = get_token_lid_for_cookies(cookies_to_use)
         if not current_token:
              raise HTTPException(status_code=401, detail="Invalid cookies provided in Authorization header")
    else:
        # Using global cookies
        if not current_token:
            state.user_token, state.lid = get_token_lid()
            current_token = state.user_token
            current_lid = state.lid
            if not current_token:
                raise HTTPException(status_code=401, detail="Failed to refresh server-side token")

    # Extract query from messages (simple concatenation for now, or just take the last user message)
    query = "你好"
    for msg in reversed(request.messages):
        if msg['role'] == 'user':
            query = msg['content']
            break
            
    # Prepare request params
    session_id = request.session_id or ""
    sa = 'bkb'
    anti_ext = get_anti_ext(query)
    str_anti_ext = json.dumps(anti_ext)
    
    url = "https://chat.baidu.com/aichat/api/conversation"
    headers = {
        "Host": "chat.baidu.com",
        "Connection": "keep-alive",
        "X-Chat-Message": f"query:{quote(query)},anti_ext:{quote(str_anti_ext)},enter_type:chat_url,re_rank:1,modelName:{request.model}",
        "isDeepseek": "1",
        "source": "pc_csaitab",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0",
        "accept": "text/event-stream",
        "Content-Type": "application/json",
        "landingPageSwitch": "",
        "Origin": "https://chat.baidu.com",
        "Referer": "https://chat.baidu.com/search?extParams=%7B%22enter_type%22%3A%22chat_url%22%7D&isShowHello=1",
    }
    
    data = {
        "message": {
            "inputMethod": "chat_search",
            "isRebuild": False,
            "content": {
                "query": "",
                "agentInfo": {
                    "agent_id": [""],
                    "params": "{\"agt_rk\":1,\"agt_sess_cnt\":1}"
                },
                "qtype": 0,
                "aitab_ct": ""
            },
            "searchInfo": {
                "srcid": "",
                "order": "",
                "tplname": "",
                "dqaKey": "",
                "re_rank": "1",
                "ori_lid": session_id,
                "sa": sa,
                "enter_type": "chat_url",
                "chatParams": {
                    "setype": "csaitab",
                    "chat_samples": "WISE_NEW_CSAITAB",
                    "chat_token": get_tk(current_token, query, current_lid),
                    "scene": ""
                },
                "blockCmpt": [],
                "usedModel": {
                    "modelName": request.model,
                    "modelFunction": {
                        "internetSearch": "1",
                        "deepSearch": "0"
                    }
                },
                "landingPageSwitch": "",
                "landingPage": "aitab",
                "out_enter_type": "",
                "showMindMap": False,
                 "isInnovate": 2,
                "applid": "",
                "a_lid": "",
            },
            "from": "",
            "source": "pc_csaitab",
            "query": [
                {
                    "type": "TEXT",
                    "data": {
                        "text": {
                            "query": query,
                            "text_type": ""
                        }
                    }
                }
            ],
             "anti_ext": anti_ext
        },
        "setype": "csaitab",
        "rank": 1
    }

    if request.stream:
        return StreamingResponse(
            generate_stream(url, headers, data, session_id, cookies_to_use),
            media_type="text/event-stream"
        )
    else:
        # For non-streaming, we collect the stream and return a single response
        # implementation omitted for brevity, forcing stream for now or just using the stream generator to collect
        full_response = ""
        async for chunk in generate_stream(url, headers, data, session_id, cookies_to_use):
            # Parse OpenAI chunk format back to content
            # This is complex because we are wrapping it. 
            # Simplified: just return the stream generator even if stream=False is requested (not ideal but works for many clients)
             pass
        return StreamingResponse(
            generate_stream(url, headers, data, session_id, cookies_to_use),
            media_type="text/event-stream"
        )

async def generate_stream(url, headers, data, session_id, cookies_dict):
    try:
        # Use a session for connection pooling
        with requests.Session() as s:
            logger.info(f"Sending request to Baidu: {url}")
            res = s.post(url, headers=headers, cookies=cookies_dict, json=data, stream=True)
            logger.info(f"Baidu response status: {res.status_code}")
            
            # OpenAI compatible stream start
            yield f"data: {json.dumps({'id': 'chatcmpl-' + secrets.token_hex(12), 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': data['message']['searchInfo']['usedModel']['modelName'], 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': ''}, 'finish_reason': None}]})}\n\n"

            status = 0
            references = []
            
            for line in res.iter_lines():
                if line:
                    res_line = line.decode("utf-8")
                    logger.debug(f"Received line: {res_line}") # Debug logging
                    
                    # More robust parsing: ignore status check if we see data directly
                    if res_line.startswith("event:"):
                        event = res_line[6:].strip()
                        if event == "message":
                            status = 1
                    elif res_line.startswith("data:"):
                        # Accept data even if status is not 1 (fallback)
                        content_data = res_line[5:].strip()
                        try:
                            mdata = json.loads(content_data)
                            
                            # Check if finished
                            msg_data = mdata.get('data', {}).get('message', {}).get('content', {}).get('generator', {}).get('data', {})
                            
                            # Extract references if available
                            if 'referenceList' in msg_data:
                                references = msg_data['referenceList']

                            if msg_data.get('status') == 'finished':
                                break
                                
                            component = mdata.get('data', {}).get('message', {}).get('content', {}).get('generator', {}).get('component')
                            
                            text_chunk = ""
                            reasoning_chunk = ""
                            
                            if component == 'thinkingSteps':
                                reasoning_chunk = ''.join(msg_data.get('reasoningContentArr', []))
                                if reasoning_chunk:
                                     # For now, append newlines to separate reasoning steps if needed, or just send raw
                                     text_chunk = f"{reasoning_chunk}\n" 

                            elif component == 'markdown-yiyan':
                                text_chunk = msg_data.get('value', '')
                            
                            if text_chunk:
                                chunk_payload = {
                                    "id": "chatcmpl-" + secrets.token_hex(12),
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": data['message']['searchInfo']['usedModel']['modelName'],
                                    "choices": [
                                        {
                                            "index": 0,
                                            "delta": {
                                                "content": text_chunk
                                            },
                                            "finish_reason": None
                                        }
                                    ]
                                }
                                yield f"data: {json.dumps(chunk_payload)}\n\n"
                                
                        except Exception as e:
                            logger.error(f"Error parsing line: {e} | Line: {res_line}")
                            continue
            
            # Send collected references at the end
            if references:
                ref_text = "\n\n**引用来源:**\n"
                for i, ref in enumerate(references, 1):
                    title = ref.get('text', '未知标题')
                    url = ref.get('url', '#')
                    source = ref.get('source', '') or ref.get('author_name', '')
                    ref_text += f"{i}. [{title}]({url}) {source}\n"
                
                chunk_payload = {
                    "id": "chatcmpl-" + secrets.token_hex(12),
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": data['message']['searchInfo']['usedModel']['modelName'],
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": ref_text
                            },
                            "finish_reason": None
                        }
                    ]
                }
                yield f"data: {json.dumps(chunk_payload)}\n\n"

            # End of stream
            yield f"data: {json.dumps({'id': 'chatcmpl-' + secrets.token_hex(12), 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': data['message']['searchInfo']['usedModel']['modelName'], 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
            yield "data: [DONE]\n\n"
            
    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
