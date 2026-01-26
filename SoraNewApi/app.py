import os
from typing import Dict, Any

import httpx
from fastapi import FastAPI, Body, HTTPException, Request
from fastapi.responses import HTMLResponse

from sora_client import SoraClient


def get_sora_client() -> SoraClient:
    base_url = os.getenv("SORA_BASE_URL", "https://duomiapi.com")
    token = os.getenv("SORA_TOKEN", "")
    return SoraClient(base_url=base_url, token=token)


app = FastAPI(title="SORA NewAPI Adapter")


HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>SORA 视频测试</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; margin: 0; padding: 20px; background: #f3f4f6; }
    .container { max-width: 900px; margin: 0 auto; background: #ffffff; padding: 20px 24px 32px; border-radius: 8px; box-shadow: 0 10px 30px rgba(15,23,42,0.1); }
    h1 { margin: 0 0 4px; font-size: 22px; }
    .subtitle { margin: 0 0 16px; color: #6b7280; font-size: 13px; }
    label { display: block; margin: 10px 0 4px; font-size: 13px; color: #374151; }
    input[type="text"], textarea, select { width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 6px; border: 1px solid #d1d5db; font-size: 14px; outline: none; }
    input[type="text"]:focus, textarea:focus, select:focus { border-color: #2563eb; box-shadow: 0 0 0 1px rgba(37,99,235,0.2); }
    textarea { min-height: 70px; resize: vertical; }
    .row { display: flex; gap: 12px; }
    .row > div { flex: 1; }
    button { cursor: pointer; border: none; border-radius: 6px; padding: 8px 16px; font-size: 14px; font-weight: 500; }
    .btn-primary { background: #2563eb; color: #ffffff; }
    .btn-primary:hover { background: #1d4ed8; }
    .btn-secondary { background: #e5e7eb; color: #374151; }
    .btn-secondary:hover { background: #d1d5db; }
    .actions { margin-top: 16px; display: flex; gap: 10px; align-items: center; }
    .status { margin-top: 16px; font-size: 13px; color: #4b5563; white-space: pre-wrap; background: #f9fafb; border-radius: 6px; padding: 10px; max-height: 260px; overflow: auto; }
    .video-wrapper { margin-top: 16px; }
    .tag { display: inline-block; padding: 2px 6px; font-size: 11px; border-radius: 9999px; margin-left: 8px; background: #eef2ff; color: #4f46e5; }
    .hint { font-size: 11px; color: #9ca3af; margin-top: 2px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>SORA 视频生成测试</h1>
    <p class="subtitle">在这里直接输入提示词，调用 /v1/videos/generations 接口进行测试。</p>

    <label>模型(model)</label>
    <input id="model" type="text" value="sora-2">
    <div class="hint">可选: sora-2, sora-2-pro</div>

    <label>提示词(prompt)</label>
    <textarea id="prompt">The car moves forward at a high speed</textarea>

    <div class="row">
      <div>
        <label>宽高比(aspect_ratio)</label>
        <select id="aspect_ratio">
          <option value="16:9" selected>16:9</option>
          <option value="9:16">9:16</option>
        </select>
      </div>
      <div>
        <label>时长(duration)</label>
        <select id="duration">
          <option value="10">10</option>
          <option value="15" selected>15</option>
          <option value="25">25</option>
        </select>
      </div>
    </div>

    <label>参考图(image_urls[0])</label>
    <input id="image_url" type="text" placeholder="可选，公网可访问的图片链接">

    <label>多角色字符(JSON，可选)</label>
    <textarea id="characters" placeholder='例如: [{"url":"https://xxx.com/role.mp4","timestamps":"0,3"}]'></textarea>
    <div class="hint">留空则不传 characters 字段。</div>

    <div class="actions">
      <button class="btn-primary" onclick="createTask()">创建视频生成任务</button>
      <button class="btn-secondary" onclick="pollTask()">查询任务进度</button>
      <span class="tag" id="task_tag">当前任务: 无</span>
    </div>

    <div class="status" id="status_box"></div>

    <div class="video-wrapper" id="video_box"></div>
  </div>

  <script>
    let currentTaskId = "";

    function appendStatus(text) {
      const box = document.getElementById("status_box");
      const time = new Date().toLocaleTimeString();
      box.textContent += "[" + time + "] " + text + "\\n";
      box.scrollTop = box.scrollHeight;
    }

    function updateTaskTag() {
      const tag = document.getElementById("task_tag");
      if (currentTaskId) {
        tag.textContent = "当前任务: " + currentTaskId;
      } else {
        tag.textContent = "当前任务: 无";
      }
    }

    async function createTask() {
      const model = document.getElementById("model").value.trim() || "sora-2";
      const prompt = document.getElementById("prompt").value.trim();
      const aspect = document.getElementById("aspect_ratio").value;
      const duration = parseInt(document.getElementById("duration").value, 10);
      const imageUrl = document.getElementById("image_url").value.trim();
      const charactersRaw = document.getElementById("characters").value.trim();

      if (!prompt) {
        alert("提示词不能为空");
        return;
      }

      const payload = { model, prompt, aspect_ratio: aspect, duration: duration };

      if (imageUrl) {
        payload.image_urls = [imageUrl];
      }

      if (charactersRaw) {
        try {
          const parsed = JSON.parse(charactersRaw);
          payload.characters = parsed;
        } catch (e) {
          alert("characters 字段不是合法 JSON");
          return;
        }
      }

      appendStatus("发送创建任务请求: " + JSON.stringify(payload));

      try {
        const res = await fetch("/v1/videos/generations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        appendStatus("返回: " + JSON.stringify(data));
        if (data && data.id) {
          currentTaskId = data.id;
          updateTaskTag();
        }
      } catch (e) {
        appendStatus("请求失败: " + e);
      }
    }

    async function pollTask() {
      if (!currentTaskId) {
        alert("当前没有任务 ID，请先创建任务");
        return;
      }

      appendStatus("查询任务进度: " + currentTaskId);

      try {
        const res = await fetch("/v1/videos/tasks/" + encodeURIComponent(currentTaskId));
        const data = await res.json().catch(() => ({}));
        appendStatus("进度返回: " + JSON.stringify(data));

        const box = document.getElementById("video_box");
        box.innerHTML = "";
        if (data && data.data && data.data.videos && data.data.videos.length > 0) {
          const url = data.data.videos[0].url;
          if (url) {
            const a = document.createElement("a");
            a.href = url;
            a.target = "_blank";
            a.textContent = "打开生成视频";
            box.appendChild(a);

            const video = document.createElement("video");
            video.src = url;
            video.controls = true;
            video.style.marginTop = "10px";
            video.style.maxWidth = "100%";
            box.appendChild(video);
          }
        }
      } catch (e) {
        appendStatus("查询失败: " + e);
      }
    }

    updateTaskTag();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


@app.post("/v1/videos/generations")
async def create_video_task(payload: Dict[str, Any] = Body(...)):
    client = get_sora_client()
    try:
        data = await client.create_video_task(payload)
        return data
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/v1/characters")
async def create_character_task(payload: Dict[str, Any] = Body(...)):
    client = get_sora_client()
    try:
        data = await client.create_character_task(payload)
        return data
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/v1/videos/tasks/{task_id}")
async def get_task(task_id: str):
    client = get_sora_client()
    try:
        data = await client.get_task(task_id)
        return data
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/v1/videos/{video_id}/remix")
async def remix_video(video_id: str, payload: Dict[str, Any] = Body(...)):
    client = get_sora_client()
    try:
        data = await client.remix_video(video_id, payload)
        return data
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# 伪装接口：拦截 NewAPI 发来的聊天请求，转发给 SORA 视频生成
@app.post("/v1/chat/completions")
async def fake_chat_completions(request: Request):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # 1. 提取 Prompt 和 Image URLs
    messages = body.get("messages", [])
    prompt = ""
    image_urls = []

    # 取最后一条 user 消息作为 prompt
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                prompt = content
            elif isinstance(content, list):
                # 处理多模态格式 (GPT-4 Vision)
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            prompt += item.get("text", "")
                        elif item.get("type") == "image_url":
                            url_obj = item.get("image_url", {})
                            if isinstance(url_obj, dict):
                                url = url_obj.get("url", "")
                                if url:
                                    image_urls.append(url)
                            elif isinstance(url_obj, str):
                                # 兼容部分非标准格式
                                image_urls.append(url_obj)
            break
    
    if not prompt and not image_urls:
        # 如果没找到，尝试取第一条
        if messages:
            content = messages[0].get("content", "")
            if isinstance(content, str):
                prompt = content
    
    if not prompt and not image_urls:
        raise HTTPException(status_code=400, detail="No prompt or image found in messages")

    # 2. 提取 Model (可选)
    model = body.get("model", "sora-2")

    # 3. 构造 SORA 请求
    # 这里默认写死一些参数，或者你可以从 prompt 里解析
    sora_payload = {
        "model": model if "sora" in model else "sora-2",
        "prompt": prompt,
        "aspect_ratio": "16:9",
        "duration": 15
    }
    
    if image_urls:
        sora_payload["image_urls"] = image_urls

    client = get_sora_client()
    try:
        # 调用 SORA 接口
        # 注意：SORA 接口通常是异步任务，返回 id
        sora_data = await client.create_video_task(sora_payload)
        
        # 4. 构造 OpenAI 格式的返回
        # 把 SORA 返回的任务 ID 放在 content 里返回给用户
        task_id = sora_data.get("id", "unknown_id")
        
        # 如果需要，这里可以构造一个包含 task_id 的假回复
        # 或者如果你想做更高级的，可以在这里轮询直到任务完成（不推荐，会超时）
        # 这里直接返回任务 ID，告诉用户任务已创建
        
        content = f"视频生成任务已创建。任务ID: {task_id}\n请使用查询接口查询进度。"
        
        return {
            "id": f"chatcmpl-{task_id}",
            "object": "chat.completion",
            "created": 1234567890,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": len(prompt),
                "completion_tokens": len(content),
                "total_tokens": len(prompt) + len(content)
            }
        }

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"SORA Error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8010, reload=False)
