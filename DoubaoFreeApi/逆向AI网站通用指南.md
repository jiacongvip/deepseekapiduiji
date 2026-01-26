# 逆向AI网站接口通用指南

基于豆包项目的实现经验，本文档总结了逆向 DeepSeek、Kimi、通义千问等AI网站的通用方法。

## 📋 目录

1. [通用逆向流程](#通用逆向流程)
2. [关键技术点](#关键技术点)
3. [各平台分析](#各平台分析)
4. [代码架构模板](#代码架构模板)
5. [实战步骤](#实战步骤)

---

## 通用逆向流程

### 🔄 五步逆向法

```
1. 抓包分析
   ↓
2. 参数提取
   ↓
3. 请求构造
   ↓
4. 响应解析
   ↓
5. 封装API
```

### 详细步骤

#### 第一步：抓包分析

```bash
# 工具选择
1. 浏览器开发者工具 (F12)
2. Charles / Fiddler（抓HTTPS）
3. mitmproxy（命令行抓包）
4. Wireshark（底层分析）
```

**操作流程**：
1. 打开目标网站（如 chat.deepseek.com）
2. 按 F12 打开开发者工具 → Network 标签
3. 勾选 "Preserve log"（保留日志）
4. 登录账号，发送一条消息
5. 找到关键的 API 请求（通常是 POST 请求，返回 SSE 流）

#### 第二步：参数提取

**需要提取的关键信息**：

| 类型 | 参数 | 位置 |
|------|------|------|
| 认证 | Cookie、Token | Headers |
| 设备 | device_id、ua | URL/Headers |
| 会话 | conversation_id | URL/Body |
| 追踪 | trace_id、request_id | Headers |
| 签名 | sign、timestamp | URL/Headers |

#### 第三步：请求构造

```python
# 通用请求模板
async def send_message(prompt: str, session: Session):
    url = "https://xxx.com/api/chat"
    
    headers = {
        "Cookie": session.cookie,
        "Authorization": f"Bearer {session.token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0...",
        "Origin": "https://xxx.com",
        "Referer": "https://xxx.com/chat"
    }
    
    body = {
        "prompt": prompt,
        "conversation_id": session.conversation_id,
        "model": "deepseek-chat",
        # ... 其他参数
    }
    
    async with aiohttp.ClientSession() as client:
        async with client.post(url, headers=headers, json=body) as resp:
            # 处理响应
            pass
```

#### 第四步：响应解析

**常见响应格式**：

```python
# 1. SSE 流式响应（最常见）
async for line in response.content:
    if line.startswith(b'data: '):
        data = json.loads(line[6:])
        # 处理数据

# 2. JSON 响应
data = await response.json()

# 3. 分块传输
async for chunk in response.content.iter_chunked(1024):
    # 处理分块
```

#### 第五步：封装API

```python
# FastAPI 封装
@app.post("/api/chat")
async def chat(request: ChatRequest):
    result = await send_message(request.prompt, session)
    return {"text": result.text, "references": result.refs}
```

---

## 关键技术点

### 1. Cookie/Token 获取

```python
# 方法一：手动抓取（简单但需定期更新）
session = {
    "cookie": "从浏览器复制",
    "token": "从请求头复制"
}

# 方法二：自动化登录（复杂但持久）
async def auto_login(username, password):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://xxx.com/login")
        await page.fill("#username", username)
        await page.fill("#password", password)
        await page.click("#login-btn")
        cookies = await page.context.cookies()
        return cookies

# 方法三：OAuth/API Key（如果平台提供）
headers = {"Authorization": f"Bearer {api_key}"}
```

### 2. SSE 流解析

```python
async def parse_sse(response):
    """通用SSE解析器"""
    buffer = ""
    
    async for chunk in response.content.iter_any():
        buffer += chunk.decode('utf-8', errors='replace')
        
        # 按双换行分割事件
        while '\n\n' in buffer:
            event, buffer = buffer.split('\n\n', 1)
            
            # 解析事件
            for line in event.split('\n'):
                if line.startswith('data: '):
                    data = line[6:]
                    if data == '[DONE]':
                        return
                    try:
                        yield json.loads(data)
                    except:
                        pass
```

### 3. 请求签名（如果有）

```python
import hashlib
import time

def generate_sign(params: dict, secret: str) -> str:
    """生成请求签名"""
    # 1. 参数排序
    sorted_params = sorted(params.items())
    
    # 2. 拼接字符串
    query_string = '&'.join([f"{k}={v}" for k, v in sorted_params])
    
    # 3. 加密
    sign_str = query_string + secret
    return hashlib.md5(sign_str.encode()).hexdigest()

# 使用
params = {
    "timestamp": int(time.time() * 1000),
    "nonce": str(uuid.uuid4()),
    # ... 其他参数
}
params["sign"] = generate_sign(params, SECRET_KEY)
```

### 4. 反爬处理

```python
# 1. 随机 User-Agent
import random
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36...",
    # ...
]
headers["User-Agent"] = random.choice(USER_AGENTS)

# 2. 请求间隔
import asyncio
await asyncio.sleep(random.uniform(1, 3))

# 3. 代理池
proxies = ["http://proxy1:8080", "http://proxy2:8080"]
proxy = random.choice(proxies)

# 4. Cookie 池
sessions = load_sessions_from_file()
session = random.choice(sessions)
```

---

## 各平台分析

### 🔵 DeepSeek

**网站**: https://chat.deepseek.com

**API端点**:
```
POST https://chat.deepseek.com/api/v0/chat/completions
```

**请求头**:
```python
headers = {
    "Authorization": "Bearer {token}",  # 登录后获取
    "Content-Type": "application/json",
    "Accept": "text/event-stream",
    "Origin": "https://chat.deepseek.com"
}
```

**请求体**:
```json
{
  "message": "你好",
  "stream": true,
  "model_preference": null,
  "model_class": "deepseek_chat",
  "temperature": 0
}
```

**特点**:
- 有官方API（需付费）
- 网页版有免费额度
- SSE流式响应
- 需要登录获取Token

**难度**: ⭐⭐（较简单）

---

### 🟣 Kimi (月之暗面)

**网站**: https://kimi.moonshot.cn

**API端点**:
```
POST https://kimi.moonshot.cn/api/chat/{chat_id}/completion/stream
```

**请求头**:
```python
headers = {
    "Authorization": "Bearer {access_token}",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Origin": "https://kimi.moonshot.cn",
    "Referer": "https://kimi.moonshot.cn/chat/{chat_id}"
}
```

**请求体**:
```json
{
  "messages": [{"role": "user", "content": "你好"}],
  "refs": [],
  "use_search": true
}
```

**特点**:
- 支持超长上下文（200K tokens）
- 有联网搜索功能
- 需要创建会话ID
- Token有时效性

**难度**: ⭐⭐⭐（中等）

**关键代码**:
```python
# 创建新会话
async def create_chat():
    url = "https://kimi.moonshot.cn/api/chat"
    resp = await client.post(url, headers=headers, json={"name": "新对话"})
    return resp.json()["id"]

# 发送消息
async def send_message(chat_id, content):
    url = f"https://kimi.moonshot.cn/api/chat/{chat_id}/completion/stream"
    body = {
        "messages": [{"role": "user", "content": content}],
        "use_search": True
    }
    async with client.post(url, headers=headers, json=body) as resp:
        async for line in resp.content:
            # 解析SSE
            pass
```

---

### 🟢 通义千问 (Qwen)

**网站**: https://tongyi.aliyun.com/qianwen

**API端点**:
```
POST https://qianwen.biz.aliyun.com/dialog/conversation
```

**特点**:
- 阿里系产品，有完善的签名机制
- 需要阿里云账号登录
- 有访问频率限制
- 支持多模态（图片理解）

**难度**: ⭐⭐⭐⭐（较难，有签名）

---

### 🔴 文心一言 (ERNIE Bot)

**网站**: https://yiyan.baidu.com

**特点**:
- 百度账号登录
- 有复杂的签名和加密机制
- 反爬较严格
- 需要处理验证码

**难度**: ⭐⭐⭐⭐⭐（困难）

---

### 🟡 智谱清言 (ChatGLM)

**网站**: https://chatglm.cn

**API端点**:
```
POST https://chatglm.cn/chatglm/backend-api/assistant/stream
```

**特点**:
- 有官方API（智谱AI开放平台）
- 网页版相对简单
- SSE流式响应

**难度**: ⭐⭐（较简单）

---

## 代码架构模板

### 项目结构

```
AI_Free_API/
├── app.py                    # FastAPI入口
├── config.py                 # 配置管理
├── session.json              # 会话配置
├── requirements.txt
│
├── src/
│   ├── api/                  # API路由
│   │   ├── router.py
│   │   └── endpoints/
│   │       ├── chat.py
│   │       └── file.py
│   │
│   ├── model/                # 数据模型
│   │   ├── request.py
│   │   └── response.py
│   │
│   ├── service/              # 核心服务
│   │   ├── base_service.py   # 基类
│   │   ├── deepseek.py
│   │   ├── kimi.py
│   │   └── qwen.py
│   │
│   ├── pool/                 # 会话池
│   │   ├── session_pool.py
│   │   └── fetcher.py
│   │
│   └── utils/                # 工具类
│       ├── sse_parser.py
│       ├── sign.py
│       └── anti_detect.py
│
└── tests/
    └── test_chat.py
```

### 基类设计

```python
# src/service/base_service.py
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Dict, Any

class BaseAIService(ABC):
    """AI服务基类"""
    
    def __init__(self, session: Dict[str, str]):
        self.session = session
        self.base_url = self.get_base_url()
    
    @abstractmethod
    def get_base_url(self) -> str:
        """获取API基础URL"""
        pass
    
    @abstractmethod
    def get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        pass
    
    @abstractmethod
    def build_request_body(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """构建请求体"""
        pass
    
    @abstractmethod
    async def parse_response(self, response) -> AsyncGenerator[Dict, None]:
        """解析响应"""
        pass
    
    async def chat(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """发送聊天请求"""
        url = f"{self.base_url}/chat/completions"
        headers = self.get_headers()
        body = self.build_request_body(prompt, **kwargs)
        
        texts = []
        references = []
        
        async with aiohttp.ClientSession() as client:
            async with client.post(url, headers=headers, json=body) as resp:
                async for data in self.parse_response(resp):
                    if "text" in data:
                        texts.append(data["text"])
                    if "references" in data:
                        references.extend(data["references"])
        
        return {
            "text": "".join(texts),
            "references": references
        }
```

### DeepSeek 实现示例

```python
# src/service/deepseek.py
from .base_service import BaseAIService

class DeepSeekService(BaseAIService):
    """DeepSeek服务"""
    
    def get_base_url(self) -> str:
        return "https://chat.deepseek.com/api/v0"
    
    def get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.session['token']}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Origin": "https://chat.deepseek.com",
            "User-Agent": "Mozilla/5.0..."
        }
    
    def build_request_body(self, prompt: str, **kwargs) -> Dict[str, Any]:
        return {
            "message": prompt,
            "stream": True,
            "model_class": kwargs.get("model", "deepseek_chat"),
            "temperature": kwargs.get("temperature", 0)
        }
    
    async def parse_response(self, response) -> AsyncGenerator[Dict, None]:
        async for line in response.content:
            line = line.decode('utf-8').strip()
            if line.startswith('data: '):
                data = line[6:]
                if data == '[DONE]':
                    break
                try:
                    obj = json.loads(data)
                    if "choices" in obj:
                        delta = obj["choices"][0].get("delta", {})
                        if "content" in delta:
                            yield {"text": delta["content"]}
                except:
                    pass
```

### Kimi 实现示例

```python
# src/service/kimi.py
from .base_service import BaseAIService

class KimiService(BaseAIService):
    """Kimi服务"""
    
    def __init__(self, session: Dict[str, str]):
        super().__init__(session)
        self.chat_id = session.get("chat_id")
    
    def get_base_url(self) -> str:
        return "https://kimi.moonshot.cn/api"
    
    def get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.session['access_token']}",
            "Content-Type": "application/json",
            "Origin": "https://kimi.moonshot.cn",
            "Referer": f"https://kimi.moonshot.cn/chat/{self.chat_id}"
        }
    
    def build_request_body(self, prompt: str, **kwargs) -> Dict[str, Any]:
        return {
            "messages": [{"role": "user", "content": prompt}],
            "refs": kwargs.get("refs", []),
            "use_search": kwargs.get("use_search", True)
        }
    
    async def create_chat(self) -> str:
        """创建新会话"""
        url = f"{self.base_url}/chat"
        headers = self.get_headers()
        
        async with aiohttp.ClientSession() as client:
            async with client.post(url, headers=headers, json={"name": "新对话"}) as resp:
                data = await resp.json()
                self.chat_id = data["id"]
                return self.chat_id
    
    async def chat(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """发送聊天请求"""
        if not self.chat_id:
            await self.create_chat()
        
        url = f"{self.base_url}/chat/{self.chat_id}/completion/stream"
        headers = self.get_headers()
        body = self.build_request_body(prompt, **kwargs)
        
        texts = []
        references = []
        
        async with aiohttp.ClientSession() as client:
            async with client.post(url, headers=headers, json=body) as resp:
                async for data in self.parse_response(resp):
                    if "text" in data:
                        texts.append(data["text"])
                    if "search_results" in data:
                        references.extend(data["search_results"])
        
        return {
            "text": "".join(texts),
            "references": references
        }
    
    async def parse_response(self, response) -> AsyncGenerator[Dict, None]:
        buffer = ""
        async for chunk in response.content.iter_any():
            buffer += chunk.decode('utf-8', errors='replace')
            
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip()
                
                if line.startswith('data: '):
                    data = line[6:]
                    try:
                        obj = json.loads(data)
                        event = obj.get("event")
                        
                        if event == "cmpl":
                            # 文本内容
                            text = obj.get("text", "")
                            if text:
                                yield {"text": text}
                        
                        elif event == "search_plus":
                            # 搜索结果
                            results = obj.get("msg", {}).get("search_results", [])
                            if results:
                                yield {"search_results": results}
                    except:
                        pass
```

---

## 实战步骤

### 步骤1：抓包分析

```bash
# 1. 打开目标网站
# 2. F12 打开开发者工具
# 3. Network 标签，勾选 Preserve log
# 4. 发送一条消息
# 5. 找到关键请求，通常是：
#    - POST 请求
#    - URL 包含 chat、completion、message 等
#    - Response 是 text/event-stream

# 6. 右键请求 → Copy → Copy as cURL
# 7. 分析 cURL 命令中的参数
```

### 步骤2：提取参数

```python
# 创建配置文件 session.json
{
    "deepseek": {
        "token": "从请求头Authorization提取",
        "cookie": "从请求头Cookie提取"
    },
    "kimi": {
        "access_token": "从请求头Authorization提取",
        "refresh_token": "从localStorage或Cookie提取",
        "chat_id": "从URL路径提取"
    }
}
```

### 步骤3：验证请求

```bash
# 使用curl测试
curl -X POST "https://chat.deepseek.com/api/v0/chat/completions" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "stream": true}'
```

### 步骤4：实现代码

```python
# 按照代码架构模板实现
# 1. 创建基类
# 2. 实现具体平台服务类
# 3. 封装FastAPI接口
# 4. 测试
```

### 步骤5：处理异常

```python
# 常见问题处理
class AIServiceError(Exception):
    pass

class TokenExpiredError(AIServiceError):
    pass

class RateLimitError(AIServiceError):
    pass

async def chat_with_retry(service, prompt, max_retries=3):
    for i in range(max_retries):
        try:
            return await service.chat(prompt)
        except TokenExpiredError:
            # 刷新Token
            await service.refresh_token()
        except RateLimitError:
            # 等待后重试
            await asyncio.sleep(60)
        except Exception as e:
            if i == max_retries - 1:
                raise
            await asyncio.sleep(2 ** i)
```

---

## 注意事项

### ⚠️ 法律与道德

1. **仅供学习研究**：逆向工程应仅用于个人学习，不得用于商业用途
2. **遵守服务条款**：使用前请阅读目标网站的服务条款
3. **合理使用**：控制请求频率，避免对服务造成压力
4. **保护隐私**：不要泄露自己或他人的账号信息

### 🔒 安全建议

1. **不要硬编码敏感信息**：使用配置文件或环境变量
2. **定期更新Token**：设置Token过期检测和自动刷新
3. **使用HTTPS**：确保所有请求使用安全连接
4. **日志脱敏**：日志中不要记录敏感信息

### 🚀 性能优化

1. **连接池复用**：使用aiohttp的连接池
2. **并发控制**：使用信号量限制并发数
3. **缓存机制**：缓存常用数据，减少重复请求
4. **异步处理**：使用async/await提高效率

---

## 总结

| 平台 | 难度 | 关键点 | 推荐指数 |
|------|------|--------|----------|
| DeepSeek | ⭐⭐ | Token认证 | ⭐⭐⭐⭐⭐ |
| Kimi | ⭐⭐⭐ | 会话管理+搜索 | ⭐⭐⭐⭐ |
| 智谱清言 | ⭐⭐ | 标准SSE | ⭐⭐⭐⭐ |
| 通义千问 | ⭐⭐⭐⭐ | 阿里签名 | ⭐⭐⭐ |
| 文心一言 | ⭐⭐⭐⭐⭐ | 复杂加密 | ⭐⭐ |

**建议入门顺序**：DeepSeek → 智谱清言 → Kimi → 通义千问

---

*文档版本: v1.0*
*更新时间: 2026-01-13*




