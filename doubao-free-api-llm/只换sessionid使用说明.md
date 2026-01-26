# 只换 `sessionid` 的使用说明（doubao-free-api-llm）

目标：后续你只需要获取/更换新的 `sessionid`，就能在本项目里继续聊天（UI 或 API），不用每次都重新抓整套 Cookie/参数。

## 结论（一句话）

- **可以只换 `sessionid` 使用**：前提是你本地保留一份“可用的完整模板 Cookie”（通常来自任意一个能正常聊天的账号/浏览器环境）。

## 原理（你现在的“浏览器替换法”在服务端复刻）

你之前的做法是：用 B 账号登录，然后把 A 的 `sessionid`（ssid）替换到 B 浏览器里就能用。

项目现在等价做了这件事：

- 准备一份 **模板 Cookie**（完整 Cookie，含 `s_v_web_id`、`passport_csrf_token`、`ttcid`、`odin_tt` 等）
- 你只提供一个新的 `sessionid`
- 服务端发请求时：**用模板 Cookie 当底座，只替换 `sessionid` / `sessionid_ss`**

## 文件说明

- `doubao-free-api-llm/session-cookies-auto.json`
  - 放“完整模板 Cookie +（可选）真实参数”的地方
  - 项目会优先把这里当成模板来源
- `doubao-free-api-llm/session-cookies.json`
  - 你日常只改这个：只放 `sessionid=...` 即可
  - 示例：
    ```json
    {
      "<sessionid>": {
        "cookie": "sessionid=<sessionid>"
      }
    }
    ```

## 一次性准备：放一个“模板 Cookie”（只需要做一次）

1) 从浏览器里复制一个**能正常聊天**的完整 Cookie（随便哪个账号都行）
2) 写入 `doubao-free-api-llm/session-cookies-auto.json`，格式如下（字段可多不可少，最关键是 `cookie` 必须是完整的）：
   ```json
   {
     "__template__": {
       "cookie": "hook_slardar_session_id=...; s_v_web_id=verify_...; passport_csrf_token=...; ...; sessionid=...; sessionid_ss=...; ...",
       "device_id": "7xxxxxxxxxxxxxxx",
       "tea_uuid": "7xxxxxxxxxxxxxxx",
       "web_id": "7xxxxxxxxxxxxxxx",
       "room_id": "xxxxxxxxxxxxxxxx",
       "x_flow_trace": "04-<32hex>-<16hex>-01"
     }
   }
   ```

说明：
- `__template__` 是可选的；如果没有该 key，程序会自动从已有配置里挑一个“非 sessionid-only 的 cookie”当模板。
- 如果你不填 `device_id/web_id/x_flow_trace/room_id`，程序会尽量从模板或生成值兜底，但**推荐填上**（更稳）。

## 日常使用：只换 `sessionid`

你有 2 种方式：

### 方式 A：改配置文件（适合部署/接口）

1) 编辑 `doubao-free-api-llm/session-cookies.json`，把 key 和 `cookie` 里的 `sessionid` 换成你的新值
2) 重启服务（因为配置会缓存到内存）

### 方式 B：直接在网页里输入（适合本地快速测试）

1) 打开：`http://localhost:<端口>/chat`
2) 右上角输入 `sessionid`（会存到浏览器 `localStorage`）
3) 发送消息即可

## 启动 / 重启

在 `doubao-free-api-llm` 目录执行：

```bash
npm run build
SERVER_PORT=8001 npm start
```

端口被占用（`EADDRINUSE`）：

```bash
lsof -i :8001 -sTCP:LISTEN -n -P
kill -9 <PID>
```

## API 调用（OpenAI 风格）

接口：`POST /v1/chat/completions`

关键点：
- `Authorization: Bearer <sessionid>`
- `stream: true/false` 都支持

示例（非流式）：

```bash
curl -s http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <sessionid>' \
  -d '{
    "model":"doubao",
    "messages":[{"role":"user","content":"你好"}],
    "stream":false
  }'
```

## 引用来源（搜索引用）展示

当豆包返回搜索引用时：

- 非流式：会在 `choices[0].message.references` 返回引用数组
- 流式：会在最后一个 chunk 的 `choices[0].delta.references` 返回引用数组

前端页面会自动把引用渲染成“参考来源”列表。

## 常见问题

### 1) `710022002 block / 当前服务访问频繁`

这通常是风控触发（cookie/参数不一致或模板过期）。

处理方式（按优先级）：
1) 更新 `session-cookies-auto.json` 的模板 Cookie（重新从浏览器复制一份“能聊的完整 cookie”替换掉）
2) 确认模板里存在 `s_v_web_id=verify_...`（它会被用来生成请求参数 `fp`，缺了容易触发风控）
3) 如果你刚改了 `session-cookies*.json`，记得重启服务让缓存刷新

### 2) 访问 `favicon.ico` 一直提示“请纠正”

已在代码里返回 `204`，正常情况下不会再刷这个日志（`doubao-free-api-llm/src/api/routes/index.ts`）。

---

如果你愿意把“你浏览器里确定能聊的那份完整 cookie + 对应参数（device_id/web_id/x_flow_trace/room_id）”按上述格式填进 `session-cookies-auto.json`，后面就基本只需要换 `sessionid` 了。

