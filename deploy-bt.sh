#!/bin/bash

# 宝塔部署脚本 (AI API Gateway)

echo "=========================================="
echo "      AI API Gateway 宝塔一键部署脚本      "
echo "=========================================="

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ 未检测到 Docker，请先在宝塔面板 -> 软件商店 安装 Docker 管理器。"
    exit 1
fi

# 检查 Docker Compose 是否安装
if ! command -v docker-compose &> /dev/null; then
    echo "⚠️ 未检测到 docker-compose，正在尝试安装..."
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    if ! command -v docker-compose &> /dev/null; then
        echo "❌ docker-compose 安装失败，请手动安装或在宝塔软件商店修复 Docker。"
        exit 1
    fi
    echo "✅ docker-compose 安装成功。"
fi

echo "🚀 开始构建并启动服务..."

# 创建必要的目录和权限
chmod -R 755 .
chmod +x auto-fetch.sh 2>/dev/null

# 确保 gateway/config.json 存在，避免 Docker 自动将其创建为目录
if [ -d "gateway/config.json" ]; then
    echo "⚠️ 检测到 gateway/config.json 是个目录（可能是之前的错误挂载导致），正在删除..."
    rm -rf gateway/config.json
fi

if [ ! -f "gateway/config.json" ]; then
    echo "⚠️ 检测到 gateway/config.json 不存在，正在从默认配置创建..."
    if [ -f "gateway/config.default.json" ]; then
        cp gateway/config.default.json gateway/config.json
        echo "✅ 已创建初始配置文件 gateway/config.json"
    else
        echo "{}" > gateway/config.json
        echo "⚠️ 未找到默认配置文件，已创建空配置。"
    fi
fi

# 停止旧容器（如果有）
docker-compose down 2>/dev/null

# 构建并启动
docker-compose up -d --build

if [ $? -eq 0 ]; then
    echo "=========================================="
    echo "✅ 部署成功！"
    echo "------------------------------------------"
    echo "管理后台地址: http://服务器IP:8888"
    echo "统一API接口:  http://服务器IP:8888/v1/chat/completions"
    echo "------------------------------------------"
    echo "注意：请确保在宝塔面板 -> 安全 中放行 [8888] 端口。"
    echo "如果需要外网访问，请在防火墙中放行相应端口。"
    echo "=========================================="
else
    echo "❌ 部署失败，请检查上方错误日志。"
fi
