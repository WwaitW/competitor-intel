<div align="center">

# 🔍 Intelix

**AI-powered competitive intelligence · 输入竞品名称，2~3 分钟自动生成完整竞品分析报告，或输入产品创意直接解析竞争格局**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.32%2B-red?logo=streamlit)](https://streamlit.io/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2%2B-green)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

[功能特性](#-功能特性) · [快速开始](#-快速开始) · [API Key 申请](#-api-key-申请教程) · [配置说明](#-配置说明) · [高级功能](#-高级功能) · [常见问题](#-常见问题)

</div>

---

## 📸 界面预览

| 单竞品分析 | 历史报告记录 |
|:---:|:---:|
| ![启动界面](docs/screenshots/startup_ok.png) | ![历史报告](docs/screenshots/history_report_ok.png) |

> 分析完成后自动生成包含公司概况、功能矩阵、SWOT 分析、战略建议的完整 Markdown/HTML 报告，支持一键下载。

---

## ✨ 功能特性

### 核心能力

- **🤖 5 Agent 协作分析**：研究员 → 分析师 → 产品经理 → 战略顾问 → 评估员，流水线自动完成
- **📡 4 维度数据采集**：官网信息 + 近期新闻 + 用户评价（G2/Capterra）+ 招聘信号，并发抓取
- **🔄 质量反思循环**：EvaluatorAgent 6 维度评分，评分 < 7 分自动补充搜索并重新分析
- **📊 批量对比矩阵**：一次输入最多 5 个竞品，并发分析后生成横向对比矩阵（含综合推荐行）
- **📚 增量知识积累**：SQLite 本地知识库，再次分析同一竞品时自动加载历史数据，重点关注变化
- **⏰ 定时监控推送**：开启后每天/每周自动重跑，通过邮件+钉钉/飞书/Slack 推送变更
- **💡 想法解析**：输入产品创意描述，自动拆解核心假设、识别潜在竞品、生成竞争力矩阵
- **🔑 API Key 预检验证**：配置 Key 后一键验证有效性，实时反馈
- **♻️ LLM 自动重试**：指数退避重试（2/4/8s），自动区分可重试错误（429/5xx）与不可重试错误（401/400）
- **🎯 智能引导与建议**：首次使用 Onboarding 引导；分析完成后显示下一步建议卡片（查看/监控/对比/知识库）

### 报告内容

| 章节 | 内容 |
|------|------|
| 📋 公司概况 | 成立时间、融资情况、员工规模、核心业务 |
| 💰 业务分析 | 融资历史、营收规模、近期重大事件 |
| ⚡ 功能矩阵 | 与我方产品的功能对比表格 |
| 💬 用户评价 | G2/Capterra 真实用户反馈与痛点 |
| 📈 市场动态 | 近 30~90 天新闻与招聘信号 |
| 🎯 SWOT 分析 | 含具体可执行的战略建议（3~5 条） |
| 🔗 参考来源 | 所有引用的原始链接，可点击溯源 |

### 与同类项目对比

| 能力 | 本项目 | GPT-Researcher | CrewAI 系列 | Crayon/Klue（商业） |
|------|:------:|:--------------:|:-----------:|:-------------------:|
| 专注竞品情报场景 | ✅ | ❌ | ⚠️ | ✅ |
| 招聘信号分析通道 | ✅ | ❌ | ❌ | ✅ $12K+/年 |
| 质量评分反思循环 | ✅ | ⚠️ | ⚠️ | ❌ |
| 增量分析/历史积累 | ✅ | ❌ | ❌ | ✅ 核心卖点 |
| 批量并发对比矩阵 | ✅ | ❌ | ⚠️ | ✅ |
| 定时监控+变更推送 | ✅ | ❌ | ❌ | ✅ 核心卖点 |
| 报告来源标注 | ✅ | ⚠️ | ❌ | ✅ |
| 一行命令启动 | ✅ | ❌ | ⚠️ | ❌ |
| 完全开源免费 | ✅ | ✅ | ✅ | ❌ |

---

## 🚀 快速开始

> 从零开始约需 **10 分钟**完成全部配置。

### 环境要求

| 软件 | 版本要求 | 检查命令 |
|------|---------|---------|
| Python | 3.10 或以上 | `python --version` |
| pip | 随 Python 安装 | `pip --version` |

**没有安装 Python？** 点击下载：
- [Python 官网下载](https://www.python.org/downloads/)（推荐 3.11 或 3.12）
- Windows 用户安装时 **务必勾选 "Add Python to PATH"**

---

### 第一步：下载项目

**方式 A：使用 git clone（推荐）**

```bash
git clone https://github.com/你的用户名/competitor-intel.git
cd competitor-intel
```

**方式 B：直接下载 ZIP**

1. 点击页面右上角绿色 **Code** 按钮 → **Download ZIP**
2. 解压到任意目录，在解压后的文件夹内打开终端

---

### 第二步：申请 API Key

本项目需要 **1 个必填 API Key** + **1 个可选 API Key**：

#### 必填：OpenRouter API Key

OpenRouter 是 AI 模型聚合平台，一个接口可以调用 DeepSeek、GPT、Claude 等所有主流模型。

1. 访问 [https://openrouter.ai](https://openrouter.ai) → 右上角 **Sign In** 注册/登录
2. 登录后点击右上角头像 → **Keys**
3. 点击 **Create Key** → 起个名字（如 `competitor-intel`）→ **Create**
4. 复制生成的密钥（格式为 `sk-or-v1-xxxxxxxx`），**只显示一次，请立即保存**

> 💡 **充值说明**：DeepSeek Chat V3 约 $0.001~0.003 每次分析（极低成本）。Gemini Flash 2.0 有免费额度，可先用来测试。

#### 可选：Tavily API Key（搜索质量更好）

Tavily 是专为 AI Agent 设计的搜索 API，效果优于免费的 DuckDuckGo。**不填也能用，系统会自动用 DuckDuckGo 兜底。**

1. 访问 [https://tavily.com](https://tavily.com) → 右上角 **Get Started** 注册
2. 注册后进入 Dashboard → 复制 API Key（格式为 `tvly-xxxxxxxx`）
3. 每月免费 **1000 次**搜索，通常足够日常使用

---

### 第三步：配置 API Key

```bash
# 从模板复制配置文件（Windows 用户用下一行）
cp .env.example .env

# Windows 用户：
copy .env.example .env
```

用任意文本编辑器打开 `.env` 文件，填入你的 API Key：

```env
# 必填：OpenRouter API Key
OPENROUTER_API_KEY=sk-or-v1-你的密钥

# 可选：Tavily 搜索（不填则用免费的 DuckDuckGo）
TAVILY_API_KEY=tvly-你的密钥
```

> ⚠️ **注意**：`.env` 文件包含私密密钥，**不要分享给他人，不要上传到 GitHub**（已在 `.gitignore` 中排除）。

---

### 第四步：安装依赖

```bash
pip install -r requirements.txt
```

> 如果安装缓慢，可以使用国内镜像：
> ```bash
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

---

### 第五步：启动应用

**方式 A：一键脚本（最简单）**

```bash
# macOS / Linux
chmod +x start.sh && ./start.sh

# Windows — 双击 start.bat 文件，或在命令行运行：
start.bat
```

**方式 B：手动命令**

```bash
python -m streamlit run app.py
```

启动成功后，浏览器会自动打开，或手动访问 **http://localhost:8501**

---

### 第六步：开始分析

1. 在页面**左侧边栏**填入 OpenRouter API Key（侧边栏 → 粘贴密钥）
2. 在主页面 **"单竞品分析"** 标签页，输入竞品名称（如 `Notion`、`Figma`）
3. 可选填写"我方产品名称"，让对比分析更有针对性
4. 点击 **"🔍 开始分析"** 按钮，等待 2~3 分钟即可

> 🎉 **完成！** 分析结果可直接下载为 `.md` 或 `.html` 格式。

---

## 🔑 API Key 申请教程

### OpenRouter 详细步骤（图文）

<details>
<summary>点击展开详细步骤</summary>

1. **注册账号**
   - 打开 [https://openrouter.ai](https://openrouter.ai)
   - 点击右上角 **Sign In** → 选择 Google 登录或邮箱注册

2. **创建 API Key**
   - 登录后，点击右上角头像
   - 在下拉菜单中选择 **Keys**
   - 点击右侧 **Create Key** 按钮
   - 在弹窗中输入名称（任意填写，如 `my-project`）
   - 点击 **Create** 确认

3. **复制密钥**
   - 密钥以 `sk-or-v1-` 开头
   - **只会显示一次**，请立即复制并保存到 `.env` 文件中

4. **充值（可选）**
   - 点击右上角头像 → **Credits** → 选择充值金额
   - 最低充值 $5，可分析约 1000~5000 次

</details>

### Tavily 详细步骤

<details>
<summary>点击展开详细步骤</summary>

1. 打开 [https://tavily.com](https://tavily.com)，点击 **Get Started** 注册
2. 填写邮箱和密码完成注册，可能需要邮箱验证
3. 登录后进入 **Dashboard**，在页面中找到 **API Key** 区域
4. 复制以 `tvly-` 开头的密钥，粘贴到 `.env` 文件的 `TAVILY_API_KEY=` 后面

</details>

---

## ⚙️ 配置说明

### 完整 .env 配置项

```env
# ── 必填 ──────────────────────────────────────
# OpenRouter API Key（用于 LLM 分析）
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxx

# ── 推荐填写 ─────────────────────────────────
# Tavily API Key（搜索质量更好，不填则用 DuckDuckGo）
TAVILY_API_KEY=tvly-xxxxxxxx

# ── 可选：邮件通知 ────────────────────────────
# 竞品雷达检测到变更时自动发邮件
NOTIFY_EMAIL_TO=your@email.com
NOTIFY_SMTP_HOST=smtp.gmail.com
NOTIFY_SMTP_PORT=587
NOTIFY_SMTP_USER=your@gmail.com
NOTIFY_SMTP_PASS=your_app_password  # Gmail 应用专用密码

# ── 可选：Webhook 通知 ────────────────────────
# 钉钉机器人 Webhook（群 → 智能群助手 → 添加机器人）
NOTIFY_DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
# 飞书机器人 Webhook
NOTIFY_FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
# Slack Incoming Webhook
NOTIFY_SLACK_WEBHOOK=https://hooks.slack.com/services/xxx

# ── 可选：报告导出 ────────────────────────────
# Notion 导出（需在 notion.so/my-integrations 创建 Integration）
NOTION_TOKEN=ntn_xxx
NOTION_PARENT_PAGE_ID=32位ID

# 飞书文档导出（需在飞书开放平台创建自建应用）
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_FOLDER_TOKEN=  # 可选，目标文件夹 token
```

### 在界面中切换模型

无需修改代码，在 Streamlit 左侧边栏直接切换：

| 模型 | 推荐度 | 成本估算 | 适用场景 |
|------|--------|---------|---------|
| DeepSeek Chat V3 | ⭐⭐⭐ **推荐** | ~$0.001/次 | 日常使用，性价比最高 |
| Gemini Flash 2.0 | ⭐⭐⭐ | **免费** | 测试阶段（有速率限制） |
| Claude Haiku 3.5 | ⭐⭐ | ~$0.003/次 | 需要稳定质量时 |
| Claude Sonnet 3.7 | ⭐⭐⭐ | ~$0.015/次 | 追求最佳质量时 |
| GPT-4o Mini | ⭐⭐ | ~$0.002/次 | 备选 |

### Gmail 邮件通知配置

如需开启变更邮件推送：

1. Google 账户 → 安全性 → 开启**两步验证**
2. 在安全设置中搜索"**应用专用密码**"
3. 设备选择"邮件"，生成一串 16 位密码
4. 将该密码填入 `.env` 的 `NOTIFY_SMTP_PASS`

**国内邮箱配置参考**：

| 邮箱 | SMTP_HOST | SMTP_PORT |
|------|-----------|-----------|
| QQ 邮箱 | smtp.qq.com | 587 |
| 163 邮箱 | smtp.163.com | 587 |
| 企业微信 | smtp.exmail.qq.com | 587 |

---

## 📁 项目结构

```
competitor_intel/
│
├── app.py                    # Streamlit 主界面（UI 入口）
├── config.py                 # 配置加载（读取 .env）
├── requirements.txt          # Python 依赖
├── .env.example              # 配置模板（可上传）
├── .env                      # 实际密钥（禁止上传！）
├── start.sh                  # macOS/Linux 一键启动
├── start.bat                 # Windows 一键启动
│
├── agents/                   # AI Agent（分析逻辑）
│   ├── researcher.py         # 研究员：4 类数据并发采集
│   ├── analyst.py            # 分析师：业务数据解读
│   ├── product.py            # 产品经理：功能对比矩阵
│   ├── strategist.py         # 战略顾问：SWOT + 建议
│   ├── evaluator.py          # 评估员：质量评分 + 反思循环
│   └── idea_parser.py        # 想法解析：创意拆解 + 竞品识别
│
├── tools/                    # 工具层（网络操作）
│   ├── web_search.py         # Tavily + DuckDuckGo 双后端搜索
│   ├── scraper.py            # Crawl4AI 网页爬取（可选）
│   └── app_store.py          # App Store / Google Play 评分采集
│
├── core/                     # 核心调度层
│   ├── orchestrator.py       # Agent 编排（单竞品 + 批量并发）
│   ├── graph.py              # LangGraph 图定义
│   ├── report.py             # 报告生成（Markdown + HTML）
│   ├── matrix_report.py      # 批量对比矩阵（含综合推荐行）
│   ├── idea_report.py        # 想法解析报告（矩阵 + LLM 综合）
│   ├── storage.py            # SQLite 历史记录
│   ├── knowledge_store.py    # 竞品知识库（增量分析 + 手工备注）
│   ├── scheduler.py          # APScheduler 定时监控
│   ├── change_detector.py    # 变更检测 + 通知推送
│   ├── search_cache.py       # 搜索结果缓存（TTL 12h）
│   ├── exporters.py          # Notion / 飞书文档导出
│   ├── llm_retry.py          # LLM 调用重试（指数退避）
│   ├── key_validator.py      # API Key 预验证
│   └── logger.py             # 统一日志配置
│
└── prompts/                  # LLM System Prompt 文件
    ├── researcher.txt
    ├── analyst.txt
    ├── product.txt
    ├── strategist.txt
    ├── evaluator.txt
    ├── idea_parser.txt       # 想法解析提示词
    └── idea_strategist.txt   # 想法战略综合提示词
```

---

## 🔧 高级功能

### 批量对比矩阵

1. 切换到 **"批量对比矩阵"** 标签页
2. 在文本框中每行输入一个竞品名称（最多 5 个）
3. 点击开始，系统并发分析所有竞品，自动生成横向对比矩阵

### 定时监控（竞品雷达）

1. 分析完成后，在报告下方开启 **"分析完成后自动监控"** 开关
2. 选择监控频率（每天 / 每周 / 每两周）
3. 配置通知方式（邮件或 Webhook），变更时自动收到推送

### 知识库管理

- 侧边栏 **"📚 知识库"** 标签：查看所有已分析竞品的摘要
- 可手动添加备注（如内部已知信息），下次分析时自动注入
- 再次分析同一竞品，AI 会聚焦于新变化而非重复历史

### 想法解析

1. 切换到 **"💡 想法解析"** 标签页
2. 输入你的产品创意描述（问题背景、目标用户、解决方案）
3. 点击开始，系统自动：
   - 拆解核心假设与关键前提
   - 识别 3~5 个潜在竞品并逐一分析
   - 生成竞争力矩阵（差异化维度对比）
   - 输出综合战略建议与可行动的下一步

### Notion / 飞书文档导出

分析完成后，在报告区域点击 **"📤 导出到 Notion"** 或 **"📤 导出到飞书文档"**。
需提前在侧边栏"📤 导出配置"区域填写对应的 Token/App 信息（见 `.env.example`）。

---

## ❓ 常见问题

<details>
<summary><strong>Q: 运行时报错 "ModuleNotFoundError: No module named 'xxx'"</strong></summary>

重新安装依赖：
```bash
pip install -r requirements.txt
```
如果仍然报错，尝试指定 Python 版本：
```bash
python3 -m pip install -r requirements.txt
```
</details>

<details>
<summary><strong>Q: 提示 "OpenRouter API Key 无效" 或 401 错误</strong></summary>

- 检查 `.env` 文件中 `OPENROUTER_API_KEY=` 后面的密钥是否完整（无多余空格）
- 确认密钥以 `sk-or-v1-` 开头
- 登录 [openrouter.ai](https://openrouter.ai) 确认账户状态正常
- 如果使用免费模型，确认没有超过速率限制
</details>

<details>
<summary><strong>Q: 分析速度很慢或超时</strong></summary>

- 搜索阶段依赖网络，国内可能较慢，请耐心等待（通常 2~5 分钟）
- 尝试切换到 **Gemini Flash 2.0（免费）** 模型，速度更快
- 确认 Tavily API Key 已填写（搜索速度比 DuckDuckGo 快得多）
</details>

<details>
<summary><strong>Q: 报错 "crawl4ai" 安装失败</strong></summary>

crawl4ai 是可选依赖，安装失败不影响主流程。忽略该报错即可，系统会自动降级使用搜索摘要。

如果想安装 crawl4ai，按官方文档单独安装：
```bash
pip install crawl4ai
playwright install chromium
```
</details>

<details>
<summary><strong>Q: 端口 8501 被占用</strong></summary>

指定其他端口：
```bash
python -m streamlit run app.py --server.port 8502
```
然后访问 http://localhost:8502
</details>

<details>
<summary><strong>Q: Windows 下启动脚本乱码</strong></summary>

1. 在命令提示符中执行 `chcp 65001` 切换编码
2. 或直接运行：`python -m streamlit run app.py`
</details>

<details>
<summary><strong>Q: 每次分析的费用大概是多少？</strong></summary>

以 DeepSeek Chat V3 为例：
- 单次竞品分析：约 **$0.001~0.003**（约 0.01~0.02 元人民币）
- 批量分析 5 个竞品：约 **$0.005~0.015**

使用 Gemini Flash 2.0 免费版：分析费用为 **$0**，但有速率限制。
</details>

---

## 🏗️ 技术架构

```
用户浏览器 (http://localhost:8501)
        │
  app.py（Streamlit UI 层 — 4 个 Tab）
        │
  orchestrator.py（Agent 编排层）
        │
  ┌─────┼─────────────────────┬──────────────┐
researcher analyst product strategist evaluator  idea_parser
  │                                              │
  tools/web_search.py                     idea_report.py
  ├── Tavily API（主路）
  └── DuckDuckGo（兜底）
        │
  core/（持久化 + 基础设施层）
  ├── knowledge_store.py → competitor_facts + manual_notes 表
  ├── storage.py         → analyses 表
  ├── search_cache.py    → search_cache 表（TTL 12h）
  ├── scheduler.py       → monitor_jobs 表
  ├── change_detector.py → change_logs 表 + 通知
  ├── llm_retry.py       → 指数退避重试
  ├── key_validator.py   → Key 预检
  └── exporters.py       → Notion / 飞书导出
```

**数据流**：用户输入 → 并发搜索 4 维度数据 → LLM 逐层分析 → 质量评分（不足则补充搜索）→ 生成报告 → 保存知识库

---

## 📋 版本记录

| 版本 | 主要内容 |
|------|---------|
| v4.0.0（当前） | 想法解析 Tab、Onboarding 引导、API Key 预验证、LLM 自动重试、分析后建议卡片、矩阵综合推荐行 |
| v3.0.0 | LLM 重试、搜索缓存、Notion/飞书导出、Webhook 通知、知识库手工备注、来源引用 |
| v2.0.0 | LangGraph 架构迁移、增量分析知识库、批量对比矩阵、定时监控、变更检测 |
| v1.0.0 | 基础 5 Agent 流水线、Tavily/DuckDuckGo 搜索、质量评分循环、历史记录 |

---

## 📄 License

[MIT License](LICENSE) — 自由使用、修改和分发，保留版权声明即可。

---

<div align="center">

如果这个项目对你有帮助，欢迎 ⭐ Star！

</div>
