#!/bin/bash
cd "$(dirname "$0")"

# 检查 docker 命令是否存在
if ! command -v docker &> /dev/null; then
    echo "错误: 未找到 docker 命令，请先安装 Docker。"
    exit 1
fi

echo "正在构建 SoraNewApi 镜像..."
docker build -t sora-newapi .

# 停止旧容器
if docker ps -a --format '{{.Names}}' | grep -q "^sora-newapi$"; then
    echo "停止旧容器..."
    docker rm -f sora-newapi
fi

echo "启动新容器 (端口 8008)..."
docker run -d \
  --name sora-newapi \
  --restart always \
  -p 8008:8010 \
  -e SORA_BASE_URL="https://duomiapi.com" \
  -e SORA_TOKEN="EAT7NMc6op6DnfCdaXNbW2dYdW" \
  sora-newapi

echo "启动成功！"
echo "日志查看: docker logs -f sora-newapi"
