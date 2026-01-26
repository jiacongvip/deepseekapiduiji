#!/bin/bash

# 自动获取参数脚本
# 使用方法: ./auto-fetch.sh "你的完整cookie字符串" "你的sessionid"

COOKIE="$1"
SESSIONID="$2"

if [ -z "$COOKIE" ] || [ -z "$SESSIONID" ]; then
  echo "使用方法: $0 <cookie> <sessionid>"
  exit 1
fi

echo "正在自动获取参数..."
RESULT=$(curl -s -X POST http://localhost:8000/token/auto-fetch \
  -H "Content-Type: application/json" \
  -d "{\"cookie\": \"$COOKIE\"}")

if echo "$RESULT" | grep -q '"success":true'; then
  echo "$RESULT" | python3 -c "
import sys, json
data = json.load(sys.stdin)['data']
config = {
    '$SESSIONID': data
}
with open('session-cookies.json', 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
print('✅ 自动获取成功！配置文件已更新')
print(f'device_id: {data[\"device_id\"]}')
print(f'web_id: {data[\"web_id\"]}')
print(f'room_id: {data[\"room_id\"]}')
" 
else
  echo "❌ 自动获取失败"
  echo "$RESULT"
  exit 1
fi
