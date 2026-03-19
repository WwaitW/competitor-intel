import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# 邮件通知配置（可选）
NOTIFY_EMAIL_TO   = os.getenv("NOTIFY_EMAIL_TO", "")    # 接收通知的邮箱
NOTIFY_EMAIL_FROM = os.getenv("NOTIFY_EMAIL_FROM", "")  # 发件人（通常与 SMTP 用户名相同）
NOTIFY_SMTP_HOST  = os.getenv("NOTIFY_SMTP_HOST", "smtp.gmail.com")
NOTIFY_SMTP_PORT  = int(os.getenv("NOTIFY_SMTP_PORT", "587"))
NOTIFY_SMTP_USER  = os.getenv("NOTIFY_SMTP_USER", "")
NOTIFY_SMTP_PASS  = os.getenv("NOTIFY_SMTP_PASS", "")

# Webhook 通知配置（#30，可选，填写对应平台 Webhook URL）
NOTIFY_DINGTALK_WEBHOOK = os.getenv("NOTIFY_DINGTALK_WEBHOOK", "")  # 钉钉自定义机器人 Webhook
NOTIFY_FEISHU_WEBHOOK   = os.getenv("NOTIFY_FEISHU_WEBHOOK", "")    # 飞书自定义机器人 Webhook
NOTIFY_SLACK_WEBHOOK    = os.getenv("NOTIFY_SLACK_WEBHOOK", "")     # Slack Incoming Webhook

# 报告导出配置（#26，可选）
# Notion：在 notion.so 创建 Integration 获取 Token，并将 Integration 共享给目标父页面
NOTION_TOKEN          = os.getenv("NOTION_TOKEN", "")           # ntn_xxx / secret_xxx
NOTION_PARENT_PAGE_ID = os.getenv("NOTION_PARENT_PAGE_ID", "")  # 父页面 32 位 ID 或含横线 UUID

# 飞书文档：在飞书开放平台创建自建应用，赋予 docx:document (write) 权限
FEISHU_APP_ID       = os.getenv("FEISHU_APP_ID", "")        # cli_xxx
FEISHU_APP_SECRET   = os.getenv("FEISHU_APP_SECRET", "")    # 应用密钥
FEISHU_FOLDER_TOKEN = os.getenv("FEISHU_FOLDER_TOKEN", "")  # 可选，导出目标文件夹 token

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

AVAILABLE_MODELS = {
    "DeepSeek Chat V3 (推荐·低成本)": "deepseek/deepseek-chat-v3-0324",
    "Gemini Flash 2.0 (免费)": "google/gemini-2.0-flash-exp:free",
    "Claude Haiku 3.5 (低成本)": "anthropic/claude-3.5-haiku",
    "Claude Sonnet 3.7": "anthropic/claude-3.7-sonnet",
    "GPT-4o Mini": "openai/gpt-4o-mini",
}

DEFAULT_MODEL = "deepseek/deepseek-chat-v3-0324"

DB_PATH = os.path.join(os.path.dirname(__file__), "history.db")

# 用户评价平台搜索域名白名单（#P2-⑭）
# 可在 .env 中用逗号分隔覆盖，也可直接在此处追加新平台
_review_domains_env = os.getenv("REVIEW_PLATFORM_DOMAINS", "")
REVIEW_PLATFORM_DOMAINS: list[str] = (
    [d.strip() for d in _review_domains_env.split(",") if d.strip()]
    if _review_domains_env
    else [
        "g2.com", "capterra.com", "trustradius.com",
        "producthunt.com", "getapp.com", "gartner.com",
    ]
)


def set_runtime(env_name: str, value: str) -> None:
    """
    运行时覆盖配置变量（#P3-⑱）。
    同步写入 os.environ 和 config 模块本身，统一两处赋值。
    value 为空字符串时不做任何操作（避免覆盖 .env 中已配置的值）。
    """
    if not value:
        return
    import os as _os, sys as _sys
    _os.environ[env_name] = value
    _module = _sys.modules[__name__]
    if hasattr(_module, env_name):
        setattr(_module, env_name, value)
