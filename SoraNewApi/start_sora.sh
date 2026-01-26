#!/bin/bash
cd "$(dirname "$0")"

# 尝试所有可能的 python3.10 路径（宝塔、CentOS、Ubuntu 常见位置）
POSSIBLE_PATHS=(
    "/usr/local/bin/python3.10"
    "/usr/bin/python3.10"
    "/usr/local/python3/bin/python3.10"
    "/usr/local/python3/bin/python3"
    "/www/server/python_manager/versions/3.10.0/bin/python3"
)

PY_EXEC=""

# 1. 优先找明确的 3.10
for path in "${POSSIBLE_PATHS[@]}"; do
    if [ -f "$path" ]; then
        PY_EXEC="$path"
        break
    fi
done

# 2. 如果没找到，尝试 which python3.10
if [ -z "$PY_EXEC" ]; then
    PY_EXEC=$(which python3.10 2>/dev/null)
fi

# 3. 如果还没找到，那就只能报错了
# 绝对不能回退到 python3，因为你的默认 python3 是 3.6，肯定跑不起来
if [ -z "$PY_EXEC" ]; then
    echo "严重错误：未找到 Python 3.10！"
    echo "你的默认 python3 是 3.6 (不支持 asyncio.run)，必须使用 Python 3.7+。"
    echo "请确认你服务器上 python3.10 到底装在哪了？或者用宝塔安装一个 Python 3.10。"
    exit 1
fi

echo "使用 Python 解析器: $PY_EXEC"

# 安装依赖
$PY_EXEC -m pip install -r requirements.txt >/dev/null 2>&1

# 环境变量
export SORA_BASE_URL="https://duomiapi.com"
export SORA_TOKEN="EAT7NMc6op6DnfCdaXNbW2dYdW"

# 杀旧进程
pid=$(ps aux | grep "uvicorn app:app" | grep "port 8010" | awk '{print $2}')
if [ -n "$pid" ]; then
    kill -9 $pid
fi

# 启动
nohup $PY_EXEC -m uvicorn app:app --host 0.0.0.0 --port 8010 > run.log 2>&1 &
echo "启动成功！日志文件: run.log"
