#!/bin/bash
# Intelix — 一键启动脚本（macOS / Linux）

set -e

echo "=================================="
echo "  Intelix  启动中..."
echo "=================================="

# 检查 Python 版本
PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "[错误] 未检测到 Python，请先安装 Python 3.10 或以上版本"
    echo "  下载地址: https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[OK] Python $PYTHON_VERSION"

# 检查 .env 文件
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo ""
        echo "[提示] 已自动创建 .env 文件，请先填写 API Key 再启动："
        echo "  1. 用文本编辑器打开 .env 文件"
        echo "  2. 填写 OPENROUTER_API_KEY=你的密钥"
        echo "  3. 重新运行本脚本"
        echo ""
        echo "  OpenRouter API Key 申请：https://openrouter.ai"
        exit 0
    else
        echo "[错误] 未找到 .env 文件，请参考 README.md 完成配置"
        exit 1
    fi
fi

# 检查 OPENROUTER_API_KEY 是否已填写
if grep -q "your_openrouter_api_key_here" .env 2>/dev/null; then
    echo ""
    echo "[提示] 请先在 .env 文件中填写真实的 OPENROUTER_API_KEY"
    echo "  申请地址：https://openrouter.ai"
    exit 0
fi

# 安装依赖
echo ""
echo "[1/2] 安装 Python 依赖..."
$PYTHON_CMD -m pip install -r requirements.txt -q

# 启动应用
echo ""
echo "[2/2] 启动 Streamlit..."
echo "  访问地址: http://localhost:8501"
echo "  按 Ctrl+C 停止服务"
echo ""

$PYTHON_CMD -m streamlit run app.py \
    --server.headless true \
    --browser.gatherUsageStats false \
    --server.port 8501
