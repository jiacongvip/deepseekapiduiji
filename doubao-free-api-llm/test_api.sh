#!/bin/bash
set -euo pipefail

pick_sessionid() {
  if [ -f session-cookies.json ]; then
    python3 -c 'import json; print(next(iter(json.load(open("session-cookies.json")))))'
    return 0
  fi
  if [ -f session-cookies-auto.json ]; then
    python3 -c 'import json; print(next(iter(json.load(open("session-cookies-auto.json")))))'
    return 0
  fi
  return 1
}

SESSIONID="${SESSIONID:-$(pick_sessionid)}"
if [ -z "${SESSIONID:-}" ]; then
  echo "❌ 未找到可用 sessionid：请先准备 session-cookies.json 或 session-cookies-auto.json"
  exit 1
fi

echo "=== 测试 Ping ==="
curl -s http://localhost:8000/ping
echo -e "\n\n=== 测试 Token 检查 ==="
curl -s -X POST http://localhost:8000/token/check \
  -H "Content-Type: application/json" \
  -d "{\"token\": \"$SESSIONID\"}" | python3 -m json.tool
echo -e "\n\n=== 测试 Chat (流式) ==="
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SESSIONID" \
  -d '{
    "model": "doubao",
    "messages": [
      {"role": "user", "content": "你好"}
    ],
    "stream": true
  }' | head -20
