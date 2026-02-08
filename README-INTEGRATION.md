# AI API 整合平台

本项目整合了多个大模型逆向 API，通过 Docker Compose 统一管理。

## 服务列表与端口映射

| 服务名称 | 原始项目 | 本地端口 | 原始端口 | 备注 |
|---|---|---|---|---|
| **DeepSeek** | DeepSeek-Free-API | `8001` | 8000 | DeepSeek 免费 API |
| **GLM** | GLM-Free-API | `8002` | 8000 | 智谱 GLM 免费 API |
| **Kimi** | Kimi-Free-API | `8003` | 8000 | 月之暗面 Kimi 免费 API |
| **Qwen** | Qwen-Free-API | `8004` | 8000 | 通义千问 Qwen 免费 API |
| **Doubao** | doubao-free-api-llm | `8005` | 8000 | 字节跳动豆包免费 API |
| **Yuanbao** | yuanbao-free-api | `8006` | 8003 | 腾讯元宝免费 API |
| **Baidu** | BaiDu-AI-main | `8007` | 8000 | 百度 AI (基于网页版逆向) |
| **Jimeng** | jimeng-api | `5100` | 5100 | 即梦AI 图像/视频生成 API |

## 快速开始

### 前置要求
- 安装 [Docker](https://www.docker.com/products/docker-desktop) 和 Docker Compose。

### 配置说明
部分服务需要配置 Cookie 或 Token 才能正常工作：

- **Baidu**: 需要在 `BaiDu-AI-main/cookie.txt` 中填入 JSON 格式的 Cookie，或者在 `docker-compose.yml` 中配置 `BAIDU_COOKIE` 环境变量。

### 启动服务

在当前目录下运行：

```bash
docker-compose up -d --build
```

### 停止服务

```bash
docker-compose down
```

## 调用示例

### 通用调用 (OpenAI 格式)
大部分服务（包括 DeepSeek, GLM, Kimi, Qwen, Doubao, Yuanbao）都支持 OpenAI 格式的调用。

以 DeepSeek 为例：
```bash
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer any_token" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

### 百度 AI 调用 (封装版)
这也是 OpenAI 兼容格式：
```bash
curl http://localhost:8007/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "DeepSeek-R1",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

## 注意事项
- 确保本地没有其他服务占用 8001-8007 端口。
- 百度 AI 的逆向接口较为不稳定，可能会因为 Cookie 过期或风控而失效。
