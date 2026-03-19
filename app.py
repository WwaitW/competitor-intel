"""
app.py — Intelix Streamlit 主界面
"""
import asyncio
import json
import sys
import os

# 将 competitor_intel 目录加入 Python 路径
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
from datetime import datetime

import config
from core.orchestrator import Orchestrator
from core.report import ReportGenerator
from core.matrix_report import MatrixReportGenerator
from core.storage import Storage
from core.knowledge_store import KnowledgeStore
from core.scheduler import CompetitorScheduler
from core.change_detector import ChangeDetector
from core.search_cache import SearchCache
from core.key_validator import validate_openrouter, validate_tavily
from core.exporters import NotionExporter, FeishuExporter
from core.idea_report import IdeaReportGenerator
from agents.idea_parser import IdeaParserAgent

# ─────────────────────────────────────────
# 页面配置
# ─────────────────────────────────────────
st.set_page_config(
    page_title="Intelix",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────
# 单例资源初始化
# ─────────────────────────────────────────
@st.cache_resource
def get_storage():
    return Storage()

@st.cache_resource
def get_knowledge_store():
    return KnowledgeStore()

@st.cache_resource
def get_scheduler():
    return CompetitorScheduler()

@st.cache_resource
def get_change_detector():
    return ChangeDetector()

storage         = get_storage()
knowledge_store = get_knowledge_store()
scheduler       = get_scheduler()
change_detector = get_change_detector()


# ─────────────────────────────────────────
# 产品文档辅助函数
# ─────────────────────────────────────────

def _make_our_product_ctx(name: str, doc: str) -> str:
    """
    将产品名 + 文档内容合并为传给 LLM 的上下文字符串。
    name 单独传时直接返回 name；有 doc 时追加文档正文（截断至 2000 字）。
    """
    name = (name or "").strip()
    doc  = (doc  or "").strip()
    if not name and not doc:
        return ""
    if not doc:
        return name
    header = f"{name}\n\n" if name else ""
    return header + f"【产品描述/文档摘要】\n{doc[:2000]}"


def _render_product_doc_input(key_prefix: str) -> tuple[str, str]:
    """
    渲染「我的产品信息」输入区，返回 (product_name, doc_text)。
    key_prefix 用于隔离不同 Tab 的 widget key。
    """
    col_name, _ = st.columns([3, 1])
    with col_name:
        product_name = st.text_input(
            "🏠 我方产品名称（可选）",
            placeholder="例如：我的笔记应用",
            help="填写后会生成针对性的竞争策略",
            key=f"{key_prefix}_product_name",
        )

    with st.expander("📄 粘贴/上传我的产品文档（可选，让分析更精准）", expanded=False):
        st.caption(
            "支持粘贴产品介绍、README、功能列表、定价页等任意文本，"
            "或上传 .txt / .md 文件。AI 会据此生成更有针对性的差异化建议。"
        )
        _tab_paste, _tab_upload = st.tabs(["✏️ 粘贴文本", "📁 上传文件"])

        with _tab_paste:
            pasted = st.text_area(
                "产品描述/文档内容",
                placeholder="粘贴你的产品介绍、核心功能、定价方案、README 等...",
                height=160,
                label_visibility="collapsed",
                key=f"{key_prefix}_doc_paste",
            )

        with _tab_upload:
            uploaded = st.file_uploader(
                "上传产品文档",
                type=["txt", "md"],
                label_visibility="collapsed",
                key=f"{key_prefix}_doc_upload",
            )
            if uploaded:
                try:
                    uploaded_text = uploaded.read().decode("utf-8", errors="ignore")
                    st.success(f"✅ 已读取「{uploaded.name}」（{len(uploaded_text)} 字符）")
                except Exception:
                    uploaded_text = ""
            else:
                uploaded_text = ""

        # 优先用上传内容，否则用粘贴
        doc_text = uploaded_text if uploaded_text else pasted

        if doc_text:
            st.caption(f"📝 已加载文档内容：{len(doc_text)} 字符（超出 2000 字将自动截断）")

    return product_name, doc_text

# ── session_state 键索引（统一管理，防止拼写错误）──────────────────────
# _SK_OR_VALID    = "_or_valid_result"      (bool, str) OpenRouter 验证结果
# _SK_OR_KEY      = "_validated_or_key"     str 上次验证的 OR Key
# _SK_TV_VALID    = "_tv_valid_result"      (bool, str) Tavily 验证结果
# _SK_TV_KEY      = "_validated_tv_key"     str 上次验证的 Tavily Key
# _SK_ONBOARDING  = "onboarding_dismissed"  bool 是否已跳过引导
# _SK_LOADED_RPT  = "loaded_report"         dict 当前展示的历史报告
# _SK_SHOW_LOADED = "show_loaded"           bool 是否展示历史报告区域
# _SK_LAST_ANALY  = "last_analysis"         dict 最近分析结果（下一步卡片数据源）
# _SK_BATCH_MD    = "batch_matrix_md"       str  批量对比矩阵 Markdown
# _SK_BATCH_RES   = "batch_results"         list 批量分析结果列表

# ─────────────────────────────────────────
# 侧边栏
# ─────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ 配置")

    openrouter_key = st.text_input(
        "OpenRouter API Key",
        value=config.OPENROUTER_API_KEY or "",
        type="password",
        help="在 openrouter.ai 免费注册获取",
    )
    tavily_key = st.text_input(
        "Tavily API Key（可选）",
        value=config.TAVILY_API_KEY or "",
        type="password",
        help="在 tavily.com 免费注册获取（每月1000次）；不填则自动使用 DuckDuckGo 免费搜索",
    )

    config.set_runtime("OPENROUTER_API_KEY", openrouter_key)
    config.set_runtime("TAVILY_API_KEY", tavily_key)

    # ── API Key 预检验证（#33）────────────────────────────────────────
    # Key 变化时自动清除上次验证缓存
    if st.session_state.get("_validated_or_key") != openrouter_key:
        st.session_state.pop("_or_valid_result", None)
    if st.session_state.get("_validated_tv_key") != tavily_key:
        st.session_state.pop("_tv_valid_result", None)

    _v_col1, _v_col2 = st.columns(2)
    with _v_col1:
        if openrouter_key and st.button("🔍 验证 OpenRouter", use_container_width=True):
            with st.spinner("验证中…"):
                ok, msg = validate_openrouter(openrouter_key)
            st.session_state["_or_valid_result"] = (ok, msg)
            st.session_state["_validated_or_key"] = openrouter_key
    with _v_col2:
        if tavily_key and st.button("🔍 验证 Tavily", use_container_width=True):
            with st.spinner("验证中…"):
                ok, msg = validate_tavily(tavily_key)
            st.session_state["_tv_valid_result"] = (ok, msg)
            st.session_state["_validated_tv_key"] = tavily_key

    # 显示验证结果
    if "_or_valid_result" in st.session_state:
        ok, msg = st.session_state["_or_valid_result"]
        if ok:
            st.success(f"OpenRouter ✅ {msg}")
        else:
            st.error(f"OpenRouter ❌ {msg}")
    if "_tv_valid_result" in st.session_state:
        ok, msg = st.session_state["_tv_valid_result"]
        if ok:
            st.success(f"Tavily ✅ {msg}")
        else:
            st.error(f"Tavily ❌ {msg}")

    # ── 邮件通知配置（可选）────────────────────────────────────────────
    email_configured = bool(config.NOTIFY_EMAIL_TO and config.NOTIFY_SMTP_USER and config.NOTIFY_SMTP_PASS)
    email_label = "📧 邮件通知  ✅" if email_configured else "📧 邮件通知（可选）"
    with st.expander(email_label, expanded=False):
        st.caption("配置后，竞品雷达检测到变更时将自动发邮件提醒，无需手动刷新页面。")
        notify_email_to = st.text_input(
            "接收通知邮箱",
            value=config.NOTIFY_EMAIL_TO or "",
            placeholder="your@email.com",
            key="notify_email_to",
        )
        notify_smtp_user = st.text_input(
            "SMTP 用户名（发件人）",
            value=config.NOTIFY_SMTP_USER or "",
            placeholder="your@gmail.com",
            key="notify_smtp_user",
        )
        notify_smtp_pass = st.text_input(
            "SMTP 密码",
            value=config.NOTIFY_SMTP_PASS or "",
            type="password",
            help="Gmail 用户：在 Google 账户安全设置中开启「应用专用密码」",
            key="notify_smtp_pass",
        )
        notify_smtp_host = st.text_input(
            "SMTP 服务器",
            value=config.NOTIFY_SMTP_HOST,   # 默认值已在 config.py 统一定义
            key="notify_smtp_host",
        )
        if notify_email_to:
            config.NOTIFY_EMAIL_TO = notify_email_to
        if notify_smtp_user:
            config.NOTIFY_SMTP_USER = notify_smtp_user
            config.NOTIFY_EMAIL_FROM = notify_smtp_user
        if notify_smtp_pass:
            config.NOTIFY_SMTP_PASS = notify_smtp_pass
        if notify_smtp_host:
            config.NOTIFY_SMTP_HOST = notify_smtp_host
        if notify_email_to and notify_smtp_user and notify_smtp_pass:
            st.success("✅ 邮件通知已配置，检测到变更时将自动发送")

    # ── Webhook 通知配置（#30）─────────────────────────────────────────
    _wh_configured = any([
        config.NOTIFY_DINGTALK_WEBHOOK,
        config.NOTIFY_FEISHU_WEBHOOK,
        config.NOTIFY_SLACK_WEBHOOK,
    ])
    wh_label = "🔔 Webhook 通知  ✅" if _wh_configured else "🔔 Webhook 通知（钉钉/飞书/Slack）"
    with st.expander(wh_label, expanded=False):
        st.caption("填写任意一个 Webhook URL，竞品变更时将自动推送消息到对应群。")

        wh_dingtalk = st.text_input(
            "钉钉机器人 Webhook",
            value=config.NOTIFY_DINGTALK_WEBHOOK or "",
            placeholder="https://oapi.dingtalk.com/robot/send?access_token=...",
            type="password",
            help="钉钉群 → 智能群助手 → 添加自定义机器人，安全关键词填「竞品雷达」",
            key="wh_dingtalk",
        )
        wh_feishu = st.text_input(
            "飞书机器人 Webhook",
            value=config.NOTIFY_FEISHU_WEBHOOK or "",
            placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/...",
            type="password",
            help="飞书群 → 设置 → 机器人 → 添加自定义机器人",
            key="wh_feishu",
        )
        wh_slack = st.text_input(
            "Slack Incoming Webhook",
            value=config.NOTIFY_SLACK_WEBHOOK or "",
            placeholder="https://hooks.slack.com/services/...",
            type="password",
            help="Slack 工作区 → 应用 → Incoming WebHooks → Add to Slack",
            key="wh_slack",
        )

        if wh_dingtalk:
            config.NOTIFY_DINGTALK_WEBHOOK = wh_dingtalk
        if wh_feishu:
            config.NOTIFY_FEISHU_WEBHOOK = wh_feishu
        if wh_slack:
            config.NOTIFY_SLACK_WEBHOOK = wh_slack

        configured_count = sum(bool(u) for u in [wh_dingtalk, wh_feishu, wh_slack])
        if configured_count:
            platforms = []
            if wh_dingtalk: platforms.append("钉钉")
            if wh_feishu:   platforms.append("飞书")
            if wh_slack:    platforms.append("Slack")
            st.success(f"✅ 已配置 {len(platforms)} 个平台：{'、'.join(platforms)}")

    # ── 报告导出配置（#26，Notion / 飞书文档）────────────────────────
    _export_configured = any([
        config.NOTION_TOKEN and config.NOTION_PARENT_PAGE_ID,
        config.FEISHU_APP_ID and config.FEISHU_APP_SECRET,
    ])
    export_label = "📤 导出配置（Notion / 飞书）  ✅" if _export_configured else "📤 导出配置（Notion / 飞书）"
    with st.expander(export_label, expanded=False):
        st.caption("配置后，分析完成时可一键将报告推送到 Notion 页面或飞书文档。")

        st.markdown("**Notion**")
        export_notion_token = st.text_input(
            "Integration Token",
            value=config.NOTION_TOKEN or "",
            placeholder="ntn_xxx 或 secret_xxx",
            type="password",
            help="notion.so/my-integrations → 新建 Integration → 复制 Token",
            key="export_notion_token",
        )
        export_notion_page = st.text_input(
            "父页面 ID",
            value=config.NOTION_PARENT_PAGE_ID or "",
            placeholder="32位ID或含横线UUID",
            help="打开 Notion 父页面，URL 末段即为页面 ID；并在该页面连接你的 Integration",
            key="export_notion_page",
        )

        st.markdown("**飞书文档**")
        export_fs_appid = st.text_input(
            "App ID",
            value=config.FEISHU_APP_ID or "",
            placeholder="cli_xxx",
            key="export_fs_appid",
        )
        export_fs_secret = st.text_input(
            "App Secret",
            value=config.FEISHU_APP_SECRET or "",
            type="password",
            help="飞书开放平台自建应用 → 凭证与基础信息",
            key="export_fs_secret",
        )
        export_fs_folder = st.text_input(
            "目标文件夹 Token（可选）",
            value=config.FEISHU_FOLDER_TOKEN or "",
            placeholder="留空则存放至应用根目录",
            key="export_fs_folder",
        )

        if export_notion_token:
            config.NOTION_TOKEN = export_notion_token
        if export_notion_page:
            config.NOTION_PARENT_PAGE_ID = export_notion_page
        if export_fs_appid:
            config.FEISHU_APP_ID = export_fs_appid
        if export_fs_secret:
            config.FEISHU_APP_SECRET = export_fs_secret
        if export_fs_folder:
            config.FEISHU_FOLDER_TOKEN = export_fs_folder

        ready_notion = bool(export_notion_token and export_notion_page)
        ready_feishu = bool(export_fs_appid and export_fs_secret)
        if ready_notion or ready_feishu:
            parts = []
            if ready_notion: parts.append("Notion")
            if ready_feishu: parts.append("飞书文档")
            st.success(f"✅ 已配置：{'、'.join(parts)}")

    model_label = st.selectbox(
        "选择 LLM 模型",
        options=list(config.AVAILABLE_MODELS.keys()),
        index=0,
    )
    selected_model = config.AVAILABLE_MODELS[model_label]

    st.divider()

    # ── 变更动态（未读徽章）──────────────────────────────────────────
    unread_count = change_detector.unread_count()
    radar_label = (
        f"📡 竞品雷达  🔴 {unread_count} 条新变更"
        if unread_count > 0
        else "📡 竞品雷达"
    )
    with st.expander(radar_label, expanded=unread_count > 0):
        changes = change_detector.list_unread(limit=10)
        if changes:
            if st.button("全部标为已读", key="mark_all_read"):
                change_detector.mark_all_read()
                st.rerun()
            for ch in changes:
                with st.container(border=True):
                    st.caption(f"🏷️ **{ch['competitor']}** · {ch['detected_at'][:16]}")
                    st.markdown(ch["summary"])
                    if st.button("标为已读", key=f"read_{ch['id']}"):
                        change_detector.mark_read(ch["id"])
                        st.rerun()
        else:
            st.caption("暂无新变更")

        # 监控列表概览
        jobs = scheduler.list_jobs()
        if jobs:
            st.divider()
            st.caption("**监控中的竞品**")
            for job in jobs:
                cols = st.columns([3, 1])
                cols[0].caption(
                    f"🔔 {job['competitor']}"
                    f"（每 {job['interval_hours']}h）"
                    f"\n下次：{job.get('next_run_at', '')[:16]}"
                )
                if cols[1].button("停止", key=f"stop_{job['competitor']}"):
                    scheduler.remove_job(job["competitor"])
                    st.rerun()

    st.divider()

    # ── 历史记录 ─────────────────────────────────────────────────────
    st.subheader("📂 历史记录")
    history = storage.list_recent(15)
    if history:
        for record in history:
            label = f"🔍 {record['competitor']}"
            if record.get("our_product"):
                label += f" vs {record['our_product']}"
            label += f"\n{record['created_at']}"
            if st.button(label, key=f"hist_{record['id']}", use_container_width=True):
                st.session_state["loaded_report"] = storage.get(record["id"])
                st.session_state["show_loaded"] = True
    else:
        st.caption("暂无历史记录")

    st.divider()

    # ── 搜索缓存统计（#27）──────────────────────────────────────────
    try:
        _cache = SearchCache()
        _stats = _cache.stats()
        if _stats["total"] > 0:
            st.caption(
                f"🗄️ 搜索缓存：{_stats['valid']} 条有效 / {_stats['total']} 条总计（TTL 12h）"
            )
            if _stats.get("oldest_valid_at"):
                st.caption(f"最早缓存：{_stats['oldest_valid_at']}")
        else:
            st.caption("🗄️ 搜索缓存：暂无缓存")
        if st.button("清除搜索缓存", use_container_width=True):
            _cache.clear()
            st.success("搜索缓存已清除")
            st.rerun()
    except Exception:
        pass

# ─────────────────────────────────────────
# 主区域
# ─────────────────────────────────────────
st.title("🔍 Intelix")
st.caption("输入竞品名称，自动生成可直接使用的竞品分析报告，支持定时监控变更")

# ══════════════════════════════════════════
# 首次使用引导（#32 Onboarding）
# 条件：OpenRouter Key 未配置 且 用户未手动跳过
# ══════════════════════════════════════════
_key_ready = bool(config.OPENROUTER_API_KEY)
_dismissed = st.session_state.get("onboarding_dismissed", False)

if not _key_ready and not _dismissed:
    with st.container(border=True):
        st.markdown("## 👋 欢迎使用 Intelix")
        st.markdown("只需 **2 分钟配置**，即可自动生成专业竞品分析报告。")

        st.markdown("---")

        # ── Step 1：OpenRouter（必填）──────────────────────────────
        st.markdown("### 第一步：获取 OpenRouter API Key（必填）")
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown(
                "OpenRouter 是统一的 AI 模型网关，支持 DeepSeek、Claude、GPT 等数十个模型。"
                "注册免费，部分模型永久免费。"
            )
        with c2:
            st.link_button(
                "🔗 去 OpenRouter 注册",
                "https://openrouter.ai/keys",
                use_container_width=True,
            )

        ob_key = st.text_input(
            "粘贴 OpenRouter API Key",
            type="password",
            placeholder="sk-or-v1-...",
            key="onboarding_openrouter_key",
        )

        st.markdown("---")

        # ── Step 2：Tavily（可选）──────────────────────────────────
        st.markdown("### 第二步：Tavily 搜索 Key（可选，推荐）")
        c3, c4 = st.columns([3, 1])
        with c3:
            st.markdown(
                "Tavily 提供高质量 AI 搜索，比 DuckDuckGo 结果更精准。"
                "免费套餐每月 **1,000 次**，足够日常使用。"
                "不填也能正常使用（自动切换 DuckDuckGo）。"
            )
        with c4:
            st.link_button(
                "🔗 去 Tavily 注册",
                "https://app.tavily.com/",
                use_container_width=True,
            )

        ob_tavily = st.text_input(
            "粘贴 Tavily API Key（可留空）",
            type="password",
            placeholder="tvly-...",
            key="onboarding_tavily_key",
        )

        st.markdown("---")

        # ── Step 3：完成 ──────────────────────────────────────────
        st.markdown("### 第三步：完成配置，开始分析")
        st.caption("配置保存在当前会话中，如需持久化请将 Key 写入项目根目录的 `.env` 文件。")

        btn_col1, btn_col2 = st.columns([2, 1])
        with btn_col1:
            if st.button(
                "🚀 完成配置，立即开始",
                type="primary",
                use_container_width=True,
                disabled=not ob_key.strip(),
            ):
                config.set_runtime("OPENROUTER_API_KEY", ob_key.strip())
                config.set_runtime("TAVILY_API_KEY", ob_tavily.strip())
                st.session_state["onboarding_dismissed"] = True
                st.rerun()
        with btn_col2:
            if st.button("跳过，稍后配置", use_container_width=True):
                st.session_state["onboarding_dismissed"] = True
                st.rerun()

    st.stop()   # 引导期间隐藏 Tab 主界面，避免混乱

# 显示历史报告（全局，Tab 外）
if st.session_state.get("show_loaded") and st.session_state.get("loaded_report"):
    record = st.session_state["loaded_report"]
    st.info(f"📖 查看历史报告：{record['competitor']} | {record['created_at']}")
    if st.button("✖ 关闭历史报告"):
        st.session_state["show_loaded"] = False
        st.rerun()
    st.markdown(record["report_md"])
    st.download_button(
        "⬇️ 下载 Markdown",
        data=record["report_md"],
        file_name=f"竞品分析_{record['competitor']}.md",
        mime="text/markdown",
    )
    st.stop()

# ─────────────────────────────────────────
# 辅助函数：下一步建议卡片（#35 / P2-⑫）
# ─────────────────────────────────────────

def _render_next_step_cards() -> None:
    """
    在「单竞品分析」Tab 顶部渲染下一步建议卡片。
    读取 session_state["last_analysis"]，若无数据或正在查看历史报告则不渲染。
    """
    _last = st.session_state.get("last_analysis")
    if not _last or st.session_state.get("show_loaded"):
        return

    _c        = _last["competitor"]
    _op       = _last["our_product"]
    _watching = _last["is_monitoring"]

    st.markdown(f"#### 💡 「{_c}」分析完成，建议下一步…")
    _n1, _n2, _n3, _n4 = st.columns(4)

    with _n1:
        with st.container(border=True):
            st.markdown("**📋 查看完整报告**")
            st.caption("点击下方按钮在历史记录中重新打开报告")
            if st.button("打开报告", key="next_open_report", use_container_width=True):
                history = storage.list_recent(1)
                if history:
                    st.session_state["loaded_report"] = storage.get(history[0]["id"])
                    st.session_state["show_loaded"] = True
                    st.rerun()

    with _n2:
        with st.container(border=True):
            if _watching:
                st.markdown("**🔔 监控已开启**")
                st.caption(f"系统将定期检测「{_c}」动态，变更出现时侧边栏「竞品雷达」会亮红点")
                if st.button("停止监控", key="next_stop_monitor", use_container_width=True):
                    scheduler.remove_job(_c)
                    _last["is_monitoring"] = False
                    st.rerun()
            else:
                st.markdown("**🔔 开启竞品监控**")
                st.caption(f"设置定时分析「{_c}」，自动发现定价调整、新功能等变化")
                if st.button("开启监控", key="next_start_monitor", use_container_width=True):
                    scheduler.add_job(_c, our_product=_op, interval_hours=168)
                    _last["is_monitoring"] = True
                    st.toast(f"🔔 已开启每周监控「{_c}」")
                    st.rerun()

    with _n3:
        with st.container(border=True):
            st.markdown("**📊 批量对比分析**")
            st.caption(f"将「{_c}」与其他竞品对比，生成横向矩阵，找出差异化机会")
            if st.button("去批量对比", key="next_batch", use_container_width=True):
                st.session_state["batch_competitors_prefill"] = _c
                st.info("请点击上方「📊 批量对比矩阵」Tab，将此竞品加入对比列表")

    with _n4:
        with st.container(border=True):
            st.markdown("**📝 补充内部情报**")
            st.caption("将渠道消息、内部观察写入知识库，让下次分析更精准")
            if st.button("去知识库", key="next_kb", use_container_width=True):
                st.session_state["kb_competitor_prefill"] = _c
                st.info("请点击上方「📚 知识库」Tab 添加手工备注")

    if st.button("✖ 收起建议", key="next_dismiss", use_container_width=False):
        st.session_state.pop("last_analysis", None)
        st.rerun()

    st.divider()


# ─────────────────────────────────────────
# Tab 切换：单竞品分析 / 批量对比 / 知识库
# ─────────────────────────────────────────
tab_single, tab_batch, tab_idea, tab_kb = st.tabs([
    "🎯 单竞品分析", "📊 批量对比矩阵", "💡 想法解析", "📚 知识库"
])

# ══════════════════════════════════════════
# Tab 1 — 单竞品分析（原有功能）
# ══════════════════════════════════════════
with tab_single:
    # 跳过 Onboarding 后仍未配置 Key 时的轻量提示
    if not config.OPENROUTER_API_KEY:
        st.warning(
            "⚠️ **OpenRouter API Key 未配置。** "
            "请在左侧侧边栏填写 Key，或点击下方按钮重新打开引导。",
            icon="🔑",
        )
        if st.button("📋 重新打开配置引导"):
            st.session_state["onboarding_dismissed"] = False
            st.rerun()
        st.divider()

    competitor = st.text_input(
        "🎯 竞品名称",
        placeholder="例如：Notion、Figma、Linear、飞书...",
        help="输入你想分析的竞品公司或产品名称",
        key="single_competitor",
    )

    single_product_name, single_doc_text = _render_product_doc_input("single")
    our_product = _make_our_product_ctx(single_product_name, single_doc_text)

    # 知识库历史数据提示
    if competitor and knowledge_store.has_prior_data(competitor):
        last_updated = knowledge_store.get_last_updated(competitor)
        st.info(
            f"📚 知识库：已有「{competitor}」的历史分析数据（{last_updated}），"
            "本次分析将自动对比变化。",
            icon="💡",
        )

    # 分析维度（展示用）
    st.multiselect(
        "分析维度",
        ["功能对比", "定价分析", "用户评价", "SWOT分析", "市场动态", "招聘信号"],
        default=["功能对比", "定价分析", "用户评价", "SWOT分析", "市场动态"],
        help="当前版本默认分析所有维度",
        disabled=True,
        key="single_dimensions",
    )

    # 监控频率选择
    monitor_after = False
    monitor_interval = 168
    interval_label = "每周"
    if competitor:
        is_monitoring = scheduler.is_monitoring(competitor)
        monitor_col1, monitor_col2 = st.columns([2, 1])
        with monitor_col1:
            monitor_after = st.toggle(
                f"🔔 分析完成后自动监控「{competitor}」",
                value=is_monitoring,
                help="开启后系统将定时重跑分析，发现变更时在左侧「竞品雷达」显示提醒",
                key="single_monitor_toggle",
            )
        with monitor_col2:
            interval_label = st.selectbox(
                "监控频率",
                ["每天", "每周", "每两周"],
                index=1,
                disabled=not monitor_after,
                key="single_interval",
            )
            monitor_interval = {"每天": 24, "每周": 168, "每两周": 336}[interval_label]

        if is_monitoring and not monitor_after:
            scheduler.remove_job(competitor)
            st.toast(f"已停止监控「{competitor}」")

    # ── 下一步建议卡片（#35）——已提取为 _render_next_step_cards() 函数
    _render_next_step_cards()

    start_btn = st.button(
        "🚀 开始分析",
        type="primary",
        disabled=not competitor,
        use_container_width=True,
        key="single_start",
    )

    if start_btn and competitor:
        if not config.OPENROUTER_API_KEY:
            st.error("❌ 请先在左侧填写 OpenRouter API Key")
            st.stop()

        # 轻量 Key 预检：复用侧边栏已有验证结果，避免每次重复请求
        _cached_ok, _cached_key = (
            st.session_state.get("_or_valid_result", (None, None))[0],
            st.session_state.get("_validated_or_key", ""),
        )
        if _cached_key != config.OPENROUTER_API_KEY or _cached_ok is None:
            with st.spinner("验证 API Key 中…"):
                _ok, _msg = validate_openrouter(config.OPENROUTER_API_KEY)
            st.session_state["_or_valid_result"] = (_ok, _msg)
            st.session_state["_validated_or_key"] = config.OPENROUTER_API_KEY
            if not _ok:
                st.error(f"❌ API Key 无效：{_msg}  请在左侧侧边栏重新检查。")
                st.stop()

        if not config.TAVILY_API_KEY:
            st.warning("⚠️ 未配置 Tavily API Key，将使用 DuckDuckGo 免费搜索")

        progress_container = st.container()
        report_container   = st.container()
        progress_messages  = []

        with progress_container:
            with st.status(f"🔄 正在分析「{competitor}」...", expanded=True) as status_box:
                log_area = st.empty()

                async def progress_callback(msg: str):
                    progress_messages.append(msg)
                    log_area.markdown("\n\n".join(f"- {m}" for m in progress_messages))

                async def run_analysis():
                    orchestrator = Orchestrator(model=selected_model)
                    prior_ctx = knowledge_store.get_prior_context(competitor)
                    return await orchestrator.run(
                        competitor=competitor,
                        our_product=our_product,
                        progress_callback=progress_callback,
                        prior_context=prior_ctx,
                    )

                try:
                    data = asyncio.run(run_analysis())
                    status_box.update(label="✅ 分析完成！", state="complete", expanded=False)
                except Exception as e:
                    status_box.update(label="❌ 分析失败，请查看下方提示", state="error")
                    _etype = type(e).__name__
                    _emsg  = str(e)
                    if "Authentication" in _etype or "401" in _emsg:
                        st.error("❌ **API Key 认证失败**：请在左侧侧边栏检查 OpenRouter Key 是否填写正确。")
                    elif "RateLimit" in _etype or "429" in _emsg:
                        st.error("❌ **调用频率超限（429）**：请稍等 30 秒后重试，或切换到其他模型。")
                    elif any(k in _etype for k in ("Connection", "Timeout", "URLError", "Network")):
                        st.error("❌ **网络连接失败**：请检查网络是否畅通，或使用 VPN/代理后重试。")
                    elif "InternalServer" in _etype or "500" in _emsg:
                        st.error("❌ **模型服务异常（500）**：OpenRouter 暂时不可用，请稍后重试。")
                    else:
                        st.error(f"❌ **分析失败**：{_emsg}")
                    with st.expander("🔧 技术详情（供排查）", expanded=False):
                        st.exception(e)
                    st.stop()

        report_md = ReportGenerator.generate(data)
        knowledge_store.extract_and_save(competitor, data)
        storage.save(
            competitor=competitor,
            our_product=our_product,
            model=selected_model,
            report_md=report_md,
            meta=data["meta"],
        )

        if monitor_after:
            scheduler.add_job(competitor, our_product=our_product, interval_hours=monitor_interval)
            st.toast(f"🔔 已开启监控「{competitor}」，{interval_label}自动检测变更")

        # 存入 session_state 供「下一步建议」卡片使用（#35）
        st.session_state["last_analysis"] = {
            "competitor": competitor,
            "our_product": our_product,
            "is_monitoring": monitor_after or scheduler.is_monitoring(competitor),
            "report_md": report_md,
        }

        with report_container:
            meta = data["meta"]
            st.success(
                f"✅ 分析完成 | 耗时 {meta['elapsed_seconds']}s | "
                f"Token: {meta['total_tokens']:,} | 成本: ${meta['estimated_cost_usd']}"
            )

            dl_col1, dl_col2 = st.columns(2)
            with dl_col1:
                st.download_button(
                    "⬇️ 下载 Markdown 报告",
                    data=report_md,
                    file_name=f"竞品分析_{competitor}_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
            with dl_col2:
                html_content = ReportGenerator.to_html(report_md)
                st.download_button(
                    "⬇️ 下载 HTML 报告",
                    data=html_content,
                    file_name=f"竞品分析_{competitor}_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                    mime="text/html",
                    use_container_width=True,
                )

            # ── 一键导出到 Notion / 飞书文档（#26）────────────────────
            _export_title = f"竞品分析 — {competitor} ({datetime.now().strftime('%Y-%m-%d')})"
            _notion_ready = bool(config.NOTION_TOKEN and config.NOTION_PARENT_PAGE_ID)
            _feishu_ready = bool(config.FEISHU_APP_ID and config.FEISHU_APP_SECRET)

            if _notion_ready or _feishu_ready:
                ex_cols = st.columns(2)
                if _notion_ready:
                    with ex_cols[0]:
                        if st.button("📤 导出到 Notion", use_container_width=True, key="export_notion_btn"):
                            with st.spinner("正在导出到 Notion…"):
                                try:
                                    page_url = NotionExporter(
                                        config.NOTION_TOKEN,
                                        config.NOTION_PARENT_PAGE_ID,
                                    ).export(_export_title, report_md)
                                    st.success(f"✅ 已导出到 Notion！")
                                    st.markdown(f"[🔗 打开 Notion 页面]({page_url})")
                                except Exception as ex:
                                    st.error(f"导出失败：{ex}")
                if _feishu_ready:
                    with ex_cols[1 if _notion_ready else 0]:
                        if st.button("📤 导出到飞书文档", use_container_width=True, key="export_feishu_btn"):
                            with st.spinner("正在导出到飞书文档…"):
                                try:
                                    doc_url = FeishuExporter(
                                        config.FEISHU_APP_ID,
                                        config.FEISHU_APP_SECRET,
                                        config.FEISHU_FOLDER_TOKEN,
                                    ).export(_export_title, report_md)
                                    st.success("✅ 已导出到飞书文档！")
                                    st.markdown(f"[🔗 打开飞书文档]({doc_url})")
                                except Exception as ex:
                                    st.error(f"导出失败：{ex}")
            else:
                st.caption("💡 在左侧「📤 导出配置」中填写 Notion / 飞书凭证，即可一键导出报告。")

            st.divider()
            st.markdown(report_md)

        st.rerun()

# ══════════════════════════════════════════
# Tab 2 — 批量对比矩阵（P5）
# ══════════════════════════════════════════
with tab_batch:
    st.subheader("📊 批量竞品对比矩阵")
    st.caption("同时分析多个竞品，自动生成横向对比矩阵。最多支持 5 个竞品并发分析。")

    batch_product_name, batch_doc_text = _render_product_doc_input("batch")
    batch_our_product = _make_our_product_ctx(batch_product_name, batch_doc_text)

    st.markdown("**竞品列表（每行一个，2～5 个）**")
    batch_input = st.text_area(
        "竞品列表",
        placeholder="Notion\nFigma\nLinear",
        height=130,
        label_visibility="collapsed",
        key="batch_competitors_input",
    )

    # 解析竞品列表
    batch_competitors = [
        c.strip() for c in batch_input.strip().splitlines()
        if c.strip()
    ][:5]  # 最多 5 个

    if batch_competitors:
        st.caption(
            f"将分析 {len(batch_competitors)} 个竞品：**{'、'.join(batch_competitors)}**"
            "（并发执行，耗时约为单竞品分析的 1.5~2 倍）"
        )

    batch_btn = st.button(
        "🚀 开始批量分析",
        type="primary",
        disabled=len(batch_competitors) < 2,
        use_container_width=True,
        key="batch_start",
    )

    if batch_btn and len(batch_competitors) >= 2:
        if not config.OPENROUTER_API_KEY:
            st.error("❌ 请先在左侧填写 OpenRouter API Key")
            st.stop()
        if not config.TAVILY_API_KEY:
            st.warning("⚠️ 未配置 Tavily API Key，将使用 DuckDuckGo 免费搜索")

        # ── 进度展示 ──────────────────────────────────────────────────
        batch_progress_msgs: list[str] = []

        with st.status(
            f"🔄 正在并发分析 {len(batch_competitors)} 个竞品...",
            expanded=True,
        ) as batch_status:
            batch_log_area = st.empty()

            async def batch_progress_callback(msg: str):
                batch_progress_msgs.append(msg)
                batch_log_area.markdown(
                    "\n\n".join(f"- {m}" for m in batch_progress_msgs[-30:])
                )

            async def run_batch_analysis():
                orch = Orchestrator(model=selected_model)
                prior_contexts = {
                    c: knowledge_store.get_prior_context(c)
                    for c in batch_competitors
                }
                return await orch.run_batch(
                    competitors=batch_competitors,
                    our_product=batch_our_product,
                    progress_callback=batch_progress_callback,
                    prior_contexts=prior_contexts,
                )

            try:
                batch_results = asyncio.run(run_batch_analysis())
                batch_status.update(label="✅ 批量分析完成！", state="complete", expanded=False)
            except Exception as e:
                batch_status.update(label=f"❌ 批量分析失败：{e}", state="error")
                st.exception(e)
                st.stop()

        # ── 保存各竞品知识库 & 历史 ──────────────────────────────────
        for result in batch_results:
            if not result.get("error"):
                try:
                    knowledge_store.extract_and_save(result["competitor"], result)
                    single_md = ReportGenerator.generate(result)
                    storage.save(
                        competitor=result["competitor"],
                        our_product=batch_our_product,
                        model=selected_model,
                        report_md=single_md,
                        meta=result["meta"],
                    )
                except Exception:
                    pass  # 单竞品存储失败不影响整批报告

        # ── 生成矩阵报告，存入 session_state，rerun 后展示 ──────────────
        matrix_md = MatrixReportGenerator.generate(
            batch_results,
            our_product=batch_our_product,
        )
        st.session_state["batch_matrix_md"] = matrix_md
        st.session_state["batch_results"] = batch_results
        st.rerun()

    # ── 展示上次批量分析结果（rerun 后从 state 读取）──────────────────
    if st.session_state.get("batch_matrix_md"):
        matrix_md = st.session_state["batch_matrix_md"]
        batch_results = st.session_state["batch_results"]

        total_tokens = sum(
            (r.get("meta") or {}).get("total_tokens", 0)
            for r in batch_results if not r.get("error")
        )
        total_cost = round(total_tokens / 1_000_000 * 0.15, 4)
        failed = sum(1 for r in batch_results if r.get("error"))
        n = len(batch_results)

        st.success(
            f"✅ 批量完成 | {n - failed}/{n} 成功 | "
            f"总 Token: {total_tokens:,} | 预估成本: ${total_cost}"
        )

        dl1, dl2, dl3 = st.columns([2, 2, 1])
        with dl1:
            st.download_button(
                "⬇️ 下载对比矩阵 Markdown",
                data=matrix_md,
                file_name=f"竞品对比矩阵_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
                use_container_width=True,
                key="dl_matrix_md",
            )
        with dl2:
            html_matrix = MatrixReportGenerator.to_html(matrix_md)
            st.download_button(
                "⬇️ 下载对比矩阵 HTML",
                data=html_matrix,
                file_name=f"竞品对比矩阵_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                use_container_width=True,
                key="dl_matrix_html",
            )
        with dl3:
            if st.button("✖ 清除结果", use_container_width=True, key="clear_batch"):
                del st.session_state["batch_matrix_md"]
                del st.session_state["batch_results"]
                st.rerun()

        st.divider()
        st.markdown(matrix_md)

        st.divider()
        st.subheader("各竞品完整报告")
        for result in batch_results:
            c = result["competitor"]
            if result.get("error"):
                with st.expander(f"❌ {c} — 分析失败"):
                    st.error(result["error"])
            else:
                with st.expander(f"📄 {c} — 点击展开完整报告"):
                    st.markdown(ReportGenerator.generate(result))

# ══════════════════════════════════════════
# Tab 3 — 想法解析（IdeaDiscovery）
# ══════════════════════════════════════════
with tab_idea:
    st.subheader("💡 想法解析 · 自动发现竞品")
    st.caption("描述你的产品想法，AI 自动解析核心要素、发现竞品，并生成以「市场验证 + 差异化机会」为重点的分析报告。")

    # ── Session State 初始化 ───────────────────────────────────────────
    for _k, _v in [
        ("_idea_state", "idle"),
        ("_idea_text", ""),
        ("_idea_our_product", ""),
        ("_idea_parse_result", None),
        ("_idea_confirmed_competitors", []),
        ("_idea_final_report", ""),
    ]:
        if _k not in st.session_state:
            st.session_state[_k] = _v

    _idea_state = st.session_state["_idea_state"]

    # ─────────────────────────────────────────
    # State: idle — 输入想法
    # ─────────────────────────────────────────
    if _idea_state == "idle":
        if not config.OPENROUTER_API_KEY:
            st.warning("⚠️ **OpenRouter API Key 未配置**，请在左侧侧边栏填写后再使用本功能。", icon="🔑")

        idea_text = st.text_area(
            "📝 描述你的产品/业务想法",
            placeholder="例如：我想做一个帮助独立开发者管理客户和项目的轻量 CRM 工具，\n专注小团队，和 Salesforce 这种企业级产品不同...",
            height=150,
            key="idea_input_text",
        )

        idea_product_name, idea_doc_text = _render_product_doc_input("idea")

        if st.button(
            "🔍 解析想法，发现竞品",
            type="primary",
            disabled=not idea_text.strip() or not config.OPENROUTER_API_KEY,
            use_container_width=True,
            key="idea_parse_btn",
        ):
            with st.spinner("💡 AI 正在解析你的想法..."):
                try:
                    parser = IdeaParserAgent(model=selected_model)
                    parse_result = asyncio.run(parser.run(idea_text.strip()))
                    st.session_state["_idea_text"] = idea_text.strip()
                    st.session_state["_idea_our_product"] = _make_our_product_ctx(
                        idea_product_name, idea_doc_text
                    )
                    st.session_state["_idea_parse_result"] = parse_result
                    st.session_state["_idea_state"] = "confirming"
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 解析失败：{e}")

    # ─────────────────────────────────────────
    # State: confirming — 确认解析结果 & 竞品列表
    # ─────────────────────────────────────────
    elif _idea_state == "confirming":
        result = st.session_state["_idea_parse_result"] or {}

        # 解析结果展示卡片
        with st.container(border=True):
            st.markdown(f"### {result.get('idea_summary', '你的想法')}")
            info_c1, info_c2, info_c3 = st.columns(3)
            with info_c1:
                st.markdown("**🎯 目标用户**")
                st.caption(result.get("target_users") or "—")
            with info_c2:
                st.markdown("**✨ 核心价值**")
                st.caption(result.get("core_value") or "—")
            with info_c3:
                st.markdown("**🔍 核心问题**")
                st.caption(result.get("key_problem") or "—")

            keywords = result.get("market_keywords", [])
            if keywords:
                st.markdown("**市场关键词**：" + "  ".join(f"`{k}`" for k in keywords))

        st.markdown("**发现的竞品（可编辑，每行一个，2~5 个）**")
        competitors_text = st.text_area(
            "竞品列表",
            value="\n".join(result.get("competitors", [])),
            height=130,
            label_visibility="collapsed",
            key="idea_competitors_edit",
        )

        col_confirm, col_reset = st.columns([3, 1])
        with col_confirm:
            if st.button(
                "✅ 确认，开始完整分析",
                type="primary",
                use_container_width=True,
                key="idea_confirm_btn",
            ):
                confirmed = [
                    c.strip()
                    for c in competitors_text.strip().splitlines()
                    if c.strip()
                ][:5]
                if len(confirmed) < 2:
                    st.error("至少需要 2 个竞品才能开始批量分析")
                else:
                    st.session_state["_idea_confirmed_competitors"] = confirmed
                    st.session_state["_idea_state"] = "analyzing"
                    st.rerun()
        with col_reset:
            if st.button("🔄 重新解析", use_container_width=True, key="idea_reset_btn"):
                st.session_state["_idea_state"] = "idle"
                st.rerun()

    # ─────────────────────────────────────────
    # State: analyzing — 批量分析中
    # ─────────────────────────────────────────
    elif _idea_state == "analyzing":
        confirmed_competitors = st.session_state["_idea_confirmed_competitors"]
        idea_context = st.session_state["_idea_parse_result"] or {}
        our_product = st.session_state.get("_idea_our_product", "")

        _idea_progress_msgs: list[str] = []

        with st.status(
            f"🔄 正在分析 {len(confirmed_competitors)} 个竞品...",
            expanded=True,
        ) as _idea_status:
            _idea_log_area = st.empty()

            async def _idea_progress_callback(msg: str):
                _idea_progress_msgs.append(msg)
                _idea_log_area.markdown(
                    "\n\n".join(f"- {m}" for m in _idea_progress_msgs[-30:])
                )

            async def _run_idea_analysis():
                orch = Orchestrator(model=selected_model)
                prior_contexts = {
                    c: knowledge_store.get_prior_context(c)
                    for c in confirmed_competitors
                }
                batch_results = await orch.run_batch(
                    competitors=confirmed_competitors,
                    our_product=our_product,
                    progress_callback=_idea_progress_callback,
                    prior_contexts=prior_contexts,
                )
                report_md = await IdeaReportGenerator.generate(
                    idea_context=idea_context,
                    batch_results=batch_results,
                    our_product=our_product,
                    model=selected_model,
                    progress_callback=_idea_progress_callback,
                )
                return batch_results, report_md

            try:
                _batch_results, _final_report = asyncio.run(_run_idea_analysis())
                _idea_status.update(label="✅ 分析完成！", state="complete", expanded=False)
            except Exception as e:
                _idea_status.update(label=f"❌ 分析失败：{e}", state="error")
                st.exception(e)
                st.stop()

        # 保存竞品知识库
        for _r in _batch_results:
            if not _r.get("error"):
                try:
                    knowledge_store.extract_and_save(_r["competitor"], _r)
                except Exception:
                    pass

        st.session_state["_idea_final_report"] = _final_report
        st.session_state["_idea_state"] = "done"
        st.rerun()

    # ─────────────────────────────────────────
    # State: done — 展示最终报告
    # ─────────────────────────────────────────
    elif _idea_state == "done":
        report_md = st.session_state.get("_idea_final_report", "")
        st.success("✅ 分析完成！以下是你的市场验证报告。")

        dl_c1, dl_c2, dl_c3 = st.columns([2, 2, 1])
        with dl_c1:
            st.download_button(
                "⬇️ 下载 Markdown 报告",
                data=report_md,
                file_name=f"想法解析报告_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
                use_container_width=True,
                key="idea_dl_md",
            )
        with dl_c2:
            from core.report import ReportGenerator as _RG
            html_content = _RG.to_html(report_md)
            st.download_button(
                "⬇️ 下载 HTML 报告",
                data=html_content,
                file_name=f"想法解析报告_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                use_container_width=True,
                key="idea_dl_html",
            )
        with dl_c3:
            if st.button("🔄 重新分析", use_container_width=True, key="idea_restart_btn"):
                for _k in ["_idea_state", "_idea_text", "_idea_our_product",
                           "_idea_parse_result", "_idea_confirmed_competitors", "_idea_final_report"]:
                    st.session_state.pop(_k, None)
                st.rerun()

        st.divider()
        st.markdown(report_md)


# ══════════════════════════════════════════
# Tab 4 — 知识库管理（#29 PM 手工编辑）
# ══════════════════════════════════════════
with tab_kb:
    st.subheader("📚 竞品知识库")
    st.caption("在这里为任意竞品补充内部情报、渠道信息、主观判断等 AI 无法搜到的内容，下次分析时将自动注入给 AI 参考。")

    # ── 竞品选择 ──────────────────────────────────────────────────────
    all_tracked = list(dict.fromkeys(
        knowledge_store.list_tracked_competitors() +
        knowledge_store.list_competitors_with_notes()
    ))

    kb_col1, kb_col2 = st.columns([2, 1])
    with kb_col1:
        kb_competitor_input = st.text_input(
            "竞品名称",
            placeholder="输入竞品名，或从右侧下拉选择",
            key="kb_competitor_input",
        )
    with kb_col2:
        kb_competitor_select = st.selectbox(
            "已追踪竞品",
            options=[""] + all_tracked,
            key="kb_competitor_select",
            label_visibility="visible",
        )

    # 文本框优先，否则用下拉
    kb_competitor = (kb_competitor_input.strip() or kb_competitor_select).strip()

    if not kb_competitor:
        st.info("👆 请先输入或选择一个竞品")
        st.stop()

    st.markdown(f"### {kb_competitor} — 知识库")

    # ── AI 自动事实（只读预览） ────────────────────────────────────────
    if knowledge_store.has_prior_data(kb_competitor):
        with st.expander("🤖 AI 分析摘要（只读，来自最近一次分析）", expanded=False):
            prior = knowledge_store.get_prior_context(kb_competitor)
            st.markdown(prior)

    # ── 现有手工备注列表 ──────────────────────────────────────────────
    notes = knowledge_store.get_manual_notes(kb_competitor)
    if notes:
        st.markdown("#### 手工备注")
        for note in notes:
            note_key = f"note_{note['id']}"
            with st.expander(
                f"📝 {note['title']}  *（{note['updated_at'][:10]}）*",
                expanded=False,
            ):
                # 编辑表单
                edit_title = st.text_input(
                    "标题", value=note["title"], key=f"edit_title_{note['id']}"
                )
                edit_content = st.text_area(
                    "内容", value=note["content"], height=120,
                    key=f"edit_content_{note['id']}"
                )
                c_save, c_del = st.columns([1, 1])
                with c_save:
                    if st.button("💾 保存修改", key=f"save_{note['id']}", use_container_width=True):
                        if edit_title.strip() and edit_content.strip():
                            knowledge_store.update_manual_note(
                                note["id"], edit_title, edit_content
                            )
                            st.success("已保存")
                            st.rerun()
                        else:
                            st.warning("标题和内容不能为空")
                with c_del:
                    if st.button("🗑️ 删除", key=f"del_{note['id']}", use_container_width=True,
                                 type="secondary"):
                        knowledge_store.delete_manual_note(note["id"])
                        st.success("已删除")
                        st.rerun()
    else:
        st.caption("暂无手工备注，在下方添加第一条。")

    # ── 新增备注表单 ───────────────────────────────────────────────────
    st.markdown("#### 添加手工备注")
    with st.form("add_note_form", clear_on_submit=True):
        new_title = st.text_input(
            "标题",
            placeholder="例如：内部渠道消息 / 展会观察 / 价格谈判记录",
            max_chars=80,
        )
        new_content = st.text_area(
            "内容",
            placeholder="在此记录任何 AI 无法从公开信息获取的内部判断、渠道情报或主观观察…",
            height=150,
        )
        submitted = st.form_submit_button("➕ 添加备注", use_container_width=True, type="primary")
        if submitted:
            if new_title.strip() and new_content.strip():
                knowledge_store.add_manual_note(kb_competitor, new_title, new_content)
                st.success(f"已为「{kb_competitor}」添加备注：{new_title}")
                st.rerun()
            else:
                st.warning("标题和内容不能为空")
