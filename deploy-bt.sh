#!/bin/bash

# 宝塔部署脚本 (AI API Gateway)

show_help() {
    echo "用法: bash deploy-bt.sh [--update] [--force] [--branch <name>]"
    echo ""
    echo "参数:"
    echo "  --update        先更新代码(支持 git pull / submodule)，再构建启动"
    echo "  --force         更新时强制覆盖本地改动(会备份关键配置后 reset)"
    echo "  --branch <name> 指定更新的分支(默认当前分支/或 origin/HEAD)"
    echo "  -h, --help      显示帮助"
    echo ""
    echo "说明:"
    echo "  不带任何参数时，行为与原脚本保持一致(仅重建并启动)。"
}

UPDATE_CODE=0
FORCE_UPDATE=0
UPDATE_BRANCH=""

while [ $# -gt 0 ]; do
    case "$1" in
        --update)
            UPDATE_CODE=1
            shift
            ;;
        --force)
            FORCE_UPDATE=1
            shift
            ;;
        --branch)
            UPDATE_BRANCH="${2:-}"
            if [ -z "$UPDATE_BRANCH" ]; then
                echo "❌ --branch 需要一个分支名"
                exit 1
            fi
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "❌ 未知参数: $1"
            show_help
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "      AI API Gateway 宝塔一键部署脚本      "
echo "=========================================="

# 确保在脚本所在目录执行
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ 未检测到 Docker，请先在宝塔面板 -> 软件商店 安装 Docker 管理器。"
    exit 1
fi

# 检查 Docker Compose 是否安装
COMPOSE_CMD=""
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    echo "⚠️ 未检测到 docker-compose / docker compose，正在尝试安装 docker-compose..."
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    if command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
        echo "✅ docker-compose 安装成功。"
    else
        echo "❌ docker-compose 安装失败，请手动安装或在宝塔软件商店修复 Docker。"
        exit 1
    fi
fi

update_code() {
    if [ "$UPDATE_CODE" -ne 1 ]; then
        return 0
    fi

    if ! command -v git &> /dev/null; then
        echo "⚠️ 未检测到 git，跳过代码更新。"
        return 0
    fi

    if [ ! -d ".git" ]; then
        echo "⚠️ 当前目录不是 git 仓库(没有 .git)，跳过代码更新。"
        echo "   如果你是用 release.zip 方式部署，请先上传/解压最新代码后再执行本脚本。"
        return 0
    fi

    echo "🔄 开始更新代码..."

    # 备份关键配置，避免更新覆盖 Token/Cookie
    BACKUP_DIR="/tmp/ai-gateway-backup-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$BACKUP_DIR"

    if [ -f "gateway/config.json" ]; then
        cp -a "gateway/config.json" "$BACKUP_DIR/config.json" 2>/dev/null
    fi
    if [ -f "BaiDu-AI-main/cookie.txt" ]; then
        cp -a "BaiDu-AI-main/cookie.txt" "$BACKUP_DIR/cookie.txt" 2>/dev/null
    fi

    # 获取默认分支
    DEFAULT_BRANCH="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@')"
    if [ -z "$DEFAULT_BRANCH" ]; then
        DEFAULT_BRANCH="main"
    fi

    CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
    if [ -z "$CURRENT_BRANCH" ] || [ "$CURRENT_BRANCH" = "HEAD" ]; then
        CURRENT_BRANCH="$DEFAULT_BRANCH"
    fi

    TARGET_BRANCH="$CURRENT_BRANCH"
    if [ -n "$UPDATE_BRANCH" ]; then
        TARGET_BRANCH="$UPDATE_BRANCH"
    fi

    git fetch --all --prune

    if [ "$FORCE_UPDATE" -eq 1 ]; then
        echo "⚠️ 使用 --force：将强制覆盖本地改动(已备份关键配置到 $BACKUP_DIR)"
        # 尝试切换到目标分支（若不存在则创建跟踪分支）
        if ! git checkout "$TARGET_BRANCH" 2>/dev/null; then
            git checkout -B "$TARGET_BRANCH" "origin/$TARGET_BRANCH" 2>/dev/null || true
        fi
        git reset --hard "origin/$TARGET_BRANCH" || git reset --hard
    else
        # 如果仅改了关键配置文件(保存 Token/Cookie)，自动临时还原后再更新，避免影响一键更新体验
        CHANGED_TRACKED="$( (git diff --name-only; git diff --cached --name-only) 2>/dev/null | sort -u )"
        SAFE_CHANGED=1
        if [ -n "$CHANGED_TRACKED" ]; then
            while IFS= read -r f; do
                [ -z "$f" ] && continue
                if [ "$f" != "gateway/config.json" ] && [ "$f" != "BaiDu-AI-main/cookie.txt" ]; then
                    SAFE_CHANGED=0
                    break
                fi
            done <<EOF
$CHANGED_TRACKED
EOF
        fi

        if [ "$SAFE_CHANGED" -eq 1 ] && [ -n "$CHANGED_TRACKED" ]; then
            echo "ℹ️ 检测到仅关键配置文件有改动，将自动临时还原以完成更新(更新后会恢复配置)。"
            git checkout -- gateway/config.json 2>/dev/null || true
            git checkout -- BaiDu-AI-main/cookie.txt 2>/dev/null || true
        elif [ "$SAFE_CHANGED" -eq 0 ]; then
            echo "⚠️ 检测到除配置文件外还有本地改动，已跳过自动更新。"
            echo "   如需强制覆盖，请执行：bash deploy-bt.sh --update --force"
            exit 1
        fi

        if ! git pull --ff-only origin "$TARGET_BRANCH"; then
            echo "❌ git pull 失败。你可以尝试：bash deploy-bt.sh --update --force"
            exit 1
        fi
    fi

    # 更新子模块(如有)
    git submodule sync --recursive 2>/dev/null || true
    git submodule update --init --recursive 2>/dev/null || true

    # 恢复关键配置
    if [ -f "$BACKUP_DIR/config.json" ]; then
        cp -a "$BACKUP_DIR/config.json" "gateway/config.json" 2>/dev/null
    fi
    if [ -f "$BACKUP_DIR/cookie.txt" ]; then
        cp -a "$BACKUP_DIR/cookie.txt" "BaiDu-AI-main/cookie.txt" 2>/dev/null
    fi

    echo "✅ 代码更新完成。"
}

update_code

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
$COMPOSE_CMD down 2>/dev/null

# 构建并启动
$COMPOSE_CMD up -d --build

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
