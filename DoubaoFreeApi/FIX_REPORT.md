# 豆包 Free API 修复报告

## 1. 问题背景
在部署和运行 `DoubaoFreeApi` 项目时，遇到了以下主要问题：
1.  **Python 版本兼容性问题**：原代码使用了 Python 3.10+ 的语法（如 `Type | None`），在 Python 3.9 环境下报错。
2.  **游客模式失效**：豆包加强了反爬虫机制（CAPTCHA），导致自动化的游客模式无法成功获取 Session。
3.  **API 接口变更**：
    *   旧接口 `/samantha/chat/completion` 返回 404。
    *   新接口 `/chat/completion` 的请求体结构发生了重大变化，旧的请求格式导致 500 系统错误 (`system error 710010702`).
    *   响应的 SSE（Server-Sent Events）流协议也发生了改变，事件类型由数字代码变更为具体的字符串（如 `STREAM_MSG_NOTIFY`）。

## 2. 解决方案

### 2.1 兼容性修复
*   **文件**：`src/model/request.py`, `src/model/response.py`, `src/pool/session_pool.py`
*   **修改**：将所有的类型注解 `A | B` 修改为 `Optional[A]` 或 `Union[A, B]`，以支持 Python 3.9。

### 2.2 登录模式变更（手动捕获）
由于自动游客模式不可用，我们切换到了“手动登录捕获”策略。
*   **文件**：`src/pool/fetcher.py`
    *   **修改**：增加了 `manual` 模式支持。在该模式下，浏览器以**有头模式**（Headless=False）启动，允许用户手动解决验证码并登录。
    *   **修改**：增加了对 `/chat/completion` 接口的监听，以捕获真实的请求头和参数。
*   **新文件**：`fetch_and_save_session.py`
    *   **功能**：一个专门的工具脚本，用于启动浏览器、引导用户登录、捕获 Session 并保存到 `session.json`。

### 2.3 核心服务重构 (API 协议适配)
这是本次修复的核心部分，针对豆包最新的 API 协议进行了完全重写。
*   **文件**：`src/service/doubao_service.py`
*   **修改详情**：
    1.  **URL 变更**：从 `https://www.doubao.com/samantha/chat/completion` 更新为 `https://www.doubao.com/chat/completion`。
    2.  **请求体 (Body) 重构**：
        *   废弃了旧的简单结构。
        *   采用了新的复杂嵌套结构，包含 `client_meta`, `messages` (内含 `content_block`), `option`, `ext` 等字段。
        *   模拟了真实的 `local_conversation_id` 和 `local_message_id` 生成逻辑。
    3.  **SSE 响应解析重写**：
        *   废弃了旧的 `event: 2001` 等数字事件解析。
        *   实现了对新事件的解析：
            *   `SSE_ACK`: 获取会话 ID。
            *   `STREAM_MSG_NOTIFY`: 获取消息元数据。
            *   `STREAM_CHUNK`: 获取流式文本内容（通过 `patch_op` 增量更新）。
            *   `SSE_REPLY_END`: 结束信号。

### 2.4 应用入口调整
*   **文件**：`app.py`
*   **修改**：启动时优先加载 `session.json` 文件，如果存在则直接使用其中的 Session，不再强制依赖失效的游客模式。

## 3. 使用说明

1.  **获取 Session**：
    运行 `python3 fetch_and_save_session.py`，在弹出的浏览器中登录豆包并发送一条消息。脚本会自动捕获凭证并保存。
2.  **启动服务**：
    运行 `python3 app.py`。
3.  **测试**：
    访问 `http://localhost:8000` 或通过 API 调用 `/api/completions`。

## 4. 遗留/待办
*   目前仅验证了**文本对话**功能。
*   图片生成和文件上传功能尚未针对新协议进行全面测试和适配。
