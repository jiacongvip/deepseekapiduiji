# SORA 视频生成 API 对接文档

本文档说明如何调用 SORA 视频生成接口。
本服务提供了两类接口：
1. **Chat 兼容接口**：适配 OpenAI 协议，可直接接入 NewAPI/OneAPI 等聚合系统，支持文生视频、图生视频。
2. **原生高级接口**：提供 SORA 完整的原生能力，包含文生/图生视频、角色创建、视频重绘（Remix）、进度查询等。

---

## 1. 服务信息

- **NewAPI 转发地址**: `http://8.137.117.8` (用于 Chat 兼容接口)
- **原生服务直连地址**: `http://8.137.117.8:8008` (用于高级接口)
- **鉴权方式**: Bearer Token
- **API Key**: `sk-L7PQGTjlRzjIRTHsqi3CqKYhB5z8iAguCKmIWla3kVUYLRGt` (示例 Key)

---

## 2. 视频生成 (Chat 兼容模式)

适用于对接 NewAPI 的常规场景。

### 2.1 文生视频 / 图生视频

**接口地址**: `http://8.137.117.8/v1/chat/completions`  
**Method**: `POST`

**请求示例 (图生视频):**

```bash
curl -X POST http://8.137.117.8/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-L7PQGTjlRzjIRTHsqi3CqKYhB5z8iAguCKmIWla3kVUYLRGt" \
  -d '{
    "model": "sora-2",
    "messages": [
      {
        "role": "user",
        "content": [
          { "type": "text", "text": "让画面动起来" },
          { "type": "image_url", "image_url": { "url": "https://example.com/image.jpg" } }
        ]
      }
    ]
  }'
```

**响应**: 返回包含 `任务ID` 的 JSON。

---

## 3. 原生高级接口 (Direct API)

以下接口建议直接调用 `http://8.137.117.8:8008`，以获得完整功能支持。

### 3.1 视频生成 (Generations)

原生接口支持所有参数透传，包括 `image_urls` (图生视频) 和 `characters` (多角色)。

- **URL**: `http://8.137.117.8:8008/v1/videos/generations`
- **Method**: `POST`

**请求参数:**

| 参数名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `model` | string | 是 | `sora-2` 或 `sora-2-pro` |
| `prompt` | string | 是 | 视频提示词 |
| `aspect_ratio` | string | 否 | 默认 `16:9`，支持 `9:16` 等 |
| `duration` | int | 否 | 默认 `10`，可选 `15`, `25` |
| `image_urls` | array | 否 | 图片 URL 列表，传此字段即为**图生视频** |
| `characters` | array | 否 | 角色列表，用于多角色客串 |

**请求示例 (文生视频):**

```bash
curl -X POST http://8.137.117.8:8008/v1/videos/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-L7PQGTjlRzjIRTHsqi3CqKYhB5z8iAguCKmIWla3kVUYLRGt" \
  -d '{
    "model": "sora-2",
    "prompt": "A cinematic drone shot of a futuristic city",
    "aspect_ratio": "16:9",
    "duration": 15
  }'
```

**请求示例 (图生视频):**

```bash
curl -X POST http://8.137.117.8:8008/v1/videos/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-L7PQGTjlRzjIRTHsqi3CqKYhB5z8iAguCKmIWla3kVUYLRGt" \
  -d '{
    "model": "sora-2",
    "prompt": "Animate this image",
    "image_urls": [
      "https://example.com/reference_image.jpg"
    ]
  }'
```

### 3.2 创建角色 (Create Character)

创建固定角色，用于后续视频生成中保持角色一致性。

- **URL**: `http://8.137.117.8:8008/v1/characters`
- **Method**: `POST`

**请求参数:**

| 参数名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `url` | string | 二选一 | 包含角色的视频 URL (不支持真人) |
| `from_task` | string | 二选一 | 已生成的视频任务 ID (支持真人) |
| `timestamps` | string | 是 | 角色出现的秒数范围，如 "0,3" |

**请求示例:**

```bash
curl -X POST http://8.137.117.8:8008/v1/characters \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-L7PQGTjlRzjIRTHsqi3CqKYhB5z8iAguCKmIWla3kVUYLRGt" \
  -d '{
    "url": "https://example.com/character_video.mp4",
    "timestamps": "0,3"
  }'
```

**响应:** 成功后通过查询接口获取角色结果。

### 3.3 重新编辑视频 (Remix Video)

对已生成的视频进行修改或扩展。

- **URL**: `http://8.137.117.8:8008/v1/videos/{video_id}/remix`
- **Method**: `POST`

**请求示例:**

```bash
# {video_id} 是原始视频的任务 ID 或 视频 ID
curl -X POST http://8.137.117.8:8008/v1/videos/{video_id}/remix \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-L7PQGTjlRzjIRTHsqi3CqKYhB5z8iAguCKmIWla3kVUYLRGt" \
  -d '{
    "model": "sora-2",
    "prompt": "将白天变成黑夜",
    "aspect_ratio": "16:9",
    "duration": 15
  }'
```

### 3.4 查询任务进度 (通用)

查询视频生成、角色创建、视频 Remix 的任务进度。

- **URL**: `http://8.137.117.8:8008/v1/videos/tasks/{task_id}`
- **Method**: `GET`

**请求示例:**

```bash
curl -X GET http://8.137.117.8:8008/v1/videos/tasks/e2f5c9d1-c6f6-13f5-4f20-da9552f214a9 \
  -H "Authorization: Bearer sk-L7PQGTjlRzjIRTHsqi3CqKYhB5z8iAguCKmIWla3kVUYLRGt"
```

**响应示例 (成功):**

```json
{
  "id": "...",
  "state": "succeeded",
  "data": {
    "videos": [
      {
        "url": "https://video-url.com/result.mp4"
      }
    ]
  },
  "progress": 100
}
```

### 3.5 使用角色生成视频 (多角色客串)

在 `v1/videos/generations` 中引用已创建的角色。

**原生接口请求示例:**

```bash
curl -X POST http://8.137.117.8:8008/v1/videos/generations \
  -d '{
    "model": "sora-2",
    "prompt": "@user1 在舞台上跳舞",
    "characters": [
      {
        "url": "https://character-video-url.mp4",
        "timestamps": "0,3"
      }
    ]
  }'
```
