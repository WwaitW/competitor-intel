@echo off
chcp 65001 >nul 2>&1
echo ==================================
echo   Intelix  启动中...
echo ==================================

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10 或以上版本
    echo   下载地址: https://www.python.org/downloads/
    echo   安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [OK] Python %PYTHON_VERSION%

:: 检查 .env 文件
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo.
        echo [提示] 已自动创建 .env 文件，请先填写 API Key：
        echo   1. 用记事本打开 .env 文件
        echo   2. 填写 OPENROUTER_API_KEY=你的密钥
        echo   3. 重新运行本脚本
        echo.
        echo   OpenRouter API Key 申请：https://openrouter.ai
        echo.
        notepad .env
        pause
        exit /b 0
    ) else (
        echo [错误] 未找到 .env 文件，请参考 README.md 完成配置
        pause
        exit /b 1
    )
)

:: 安装依赖
echo.
echo [1/2] 安装 Python 依赖...
python -m pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败，请检查网络或手动运行：
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

:: 启动应用
echo.
echo [2/2] 启动 Streamlit...
echo   访问地址: http://localhost:8501
echo   按 Ctrl+C 停止服务
echo.

python -m streamlit run app.py --server.headless true --browser.gatherUsageStats false --server.port 8501

pause
