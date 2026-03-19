"""
exporters.py — 一键导出到 Notion / 飞书文档（#26）

NotionExporter : Markdown → Notion Page（Notion API v1，仅用 stdlib urllib）
FeishuExporter : Markdown → 飞书 docx（飞书 docx API v1，仅用 stdlib urllib）

使用方法：
    exporter = NotionExporter(token, parent_page_id)
    url = exporter.export("竞品分析 — Notion", report_md)

    exporter = FeishuExporter(app_id, app_secret, folder_token)
    url = exporter.export("竞品分析 — Notion", report_md)
"""
import json
import re
import urllib.request
import urllib.error


# ══════════════════════════════════════════════════════════════
# Notion 导出器
# ══════════════════════════════════════════════════════════════

class NotionExporter:
    """将 Markdown 报告导出为 Notion 页面"""

    API_BASE = "https://api.notion.com/v1"
    _NOTION_LANGS = {
        "python", "javascript", "typescript", "java", "c", "cpp", "c++", "csharp",
        "go", "rust", "sql", "bash", "shell", "json", "html", "css", "markdown",
        "plain text",
    }

    def __init__(self, token: str, parent_page_id: str):
        self.token = token.strip()
        self.parent_page_id = self._normalize_page_id(parent_page_id.strip())

    # ── 公开接口 ──────────────────────────────────────────────

    def export(self, title: str, markdown: str) -> str:
        """导出 Markdown 为 Notion 页面，返回页面公开 URL"""
        blocks = self._md_to_blocks(markdown)
        # Notion 每次最多 100 个子 block
        page_id = self._create_page(title, blocks[:100])
        for i in range(100, len(blocks), 100):
            self._append_blocks(page_id, blocks[i : i + 100])
        clean = page_id.replace("-", "")
        return f"https://www.notion.so/{clean}"

    # ── 内部：API 请求 ─────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }

    def _request(self, method: str, path: str, body: dict = None) -> dict:
        url = f"{self.API_BASE}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8")
            raise RuntimeError(f"Notion API {e.code}: {err[:400]}")

    def _create_page(self, title: str, blocks: list) -> str:
        resp = self._request(
            "POST",
            "/pages",
            {
                "parent": {"type": "page_id", "page_id": self.parent_page_id},
                "properties": {
                    "title": {
                        "title": [{"type": "text", "text": {"content": title[:2000]}}]
                    }
                },
                "children": blocks,
            },
        )
        return resp["id"]

    def _append_blocks(self, page_id: str, blocks: list):
        self._request("PATCH", f"/blocks/{page_id}/children", {"children": blocks})

    # ── 内部：Markdown → Notion blocks ────────────────────────

    def _md_to_blocks(self, markdown: str) -> list:
        blocks = []
        lines = markdown.split("\n")
        in_code = False
        code_lines: list[str] = []
        code_lang = "plain text"

        for line in lines:
            # ── code fence ────────────────────────────────────
            if line.startswith("```"):
                if not in_code:
                    in_code = True
                    lang = line[3:].strip().lower() or "plain text"
                    code_lang = lang if lang in self._NOTION_LANGS else "plain text"
                    code_lines = []
                else:
                    in_code = False
                    code_content = "\n".join(code_lines)
                    # 超过 Notion rich_text 2000 字符上限时，追加截断提示
                    if len(code_content) > 2000:
                        code_content = (
                            code_content[:1960]
                            + "\n\n…（内容过长已截断，完整代码请查看 Markdown 原报告）"
                        )
                    blocks.append({
                        "type": "code",
                        "code": {
                            "rich_text": [{
                                "type": "text",
                                "text": {"content": code_content},
                            }],
                            "language": code_lang,
                        },
                    })
                continue

            if in_code:
                code_lines.append(line)
                continue

            # ── headings ──────────────────────────────────────
            if line.startswith("### "):
                blocks.append(_notion_heading(3, line[4:]))
            elif line.startswith("## "):
                blocks.append(_notion_heading(2, line[3:]))
            elif line.startswith("# "):
                blocks.append(_notion_heading(1, line[2:]))
            # ── divider ───────────────────────────────────────
            elif line.strip() in ("---", "***", "___"):
                blocks.append({"type": "divider", "divider": {}})
            # ── bullet list ───────────────────────────────────
            elif re.match(r"^[-*+] ", line):
                blocks.append({
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": _inline(line[2:])},
                })
            # ── numbered list ─────────────────────────────────
            elif re.match(r"^\d+\. ", line):
                text = re.sub(r"^\d+\. ", "", line)
                blocks.append({
                    "type": "numbered_list_item",
                    "numbered_list_item": {"rich_text": _inline(text)},
                })
            # ── empty line ────────────────────────────────────
            elif not line.strip():
                pass  # Notion 自动处理空白间距
            # ── paragraph ─────────────────────────────────────
            else:
                blocks.append({
                    "type": "paragraph",
                    "paragraph": {"rich_text": _inline(line)},
                })

        return blocks

    @staticmethod
    def _normalize_page_id(pid: str) -> str:
        """将 32 位无横线 ID 转为标准 UUID 格式"""
        clean = pid.replace("-", "")
        if len(clean) == 32:
            return f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"
        return pid  # 已是标准格式，或用户传入的 URL 末段（保持原样）


def _notion_heading(level: int, text: str) -> dict:
    key = f"heading_{level}"
    return {"type": key, key: {"rich_text": _inline(text.strip())}}


def _inline(text: str) -> list:
    """Markdown 内联文本 → Notion rich_text（简化：去除格式标记，保留纯文字）"""
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)
    clean = re.sub(r"`(.+?)`", r"\1", clean)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)  # [text](url) → text
    clean = clean.strip()
    return [{"type": "text", "text": {"content": clean[:2000]}}]


# ══════════════════════════════════════════════════════════════
# 飞书文档导出器
# ══════════════════════════════════════════════════════════════

class FeishuExporter:
    """将 Markdown 报告导出为飞书文档（docx API v1）"""

    API_BASE = "https://open.feishu.cn"

    def __init__(self, app_id: str, app_secret: str, folder_token: str = ""):
        self.app_id = app_id.strip()
        self.app_secret = app_secret.strip()
        self.folder_token = folder_token.strip()

    # ── 公开接口 ──────────────────────────────────────────────

    def export(self, title: str, markdown: str) -> str:
        """导出 Markdown 为飞书文档，返回文档 URL"""
        token = self._get_token()
        doc_id = self._create_document(token, title)
        blocks = self._md_to_blocks(markdown)
        # 飞书每批最多 50 个子块
        for i in range(0, len(blocks), 50):
            self._append_blocks(token, doc_id, blocks[i : i + 50])
        return f"https://docs.feishu.cn/docx/{doc_id}"

    # ── 内部：API 请求 ─────────────────────────────────────────

    def _post(self, path: str, body: dict, token: str = "") -> dict:
        url = f"{self.API_BASE}{path}"
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8")
            raise RuntimeError(f"飞书 API {e.code}: {err[:400]}")

    def _get_token(self) -> str:
        """获取 tenant_access_token"""
        resp = self._post(
            "/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": self.app_id, "app_secret": self.app_secret},
        )
        if resp.get("code") != 0:
            raise RuntimeError(f"飞书授权失败（code={resp.get('code')}）: {resp.get('msg')}")
        return resp["tenant_access_token"]

    def _create_document(self, token: str, title: str) -> str:
        """创建飞书文档，返回 document_id"""
        body: dict = {"title": title[:200]}
        if self.folder_token:
            body["folder_token"] = self.folder_token
        resp = self._post("/open-apis/docx/v1/documents", body, token=token)
        if resp.get("code") != 0:
            raise RuntimeError(f"飞书创建文档失败（code={resp.get('code')}）: {resp.get('msg')}")
        return resp["data"]["document"]["document_id"]

    def _append_blocks(self, token: str, doc_id: str, blocks: list):
        """向文档根块追加子块"""
        path = f"/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children"
        resp = self._post(path, {"children": blocks}, token=token)
        if resp.get("code") != 0:
            raise RuntimeError(f"飞书追加块失败（code={resp.get('code')}）: {resp.get('msg')}")

    # ── 内部：Markdown → 飞书 blocks ──────────────────────────

    def _md_to_blocks(self, markdown: str) -> list:
        blocks = []
        lines = markdown.split("\n")
        in_code = False
        code_lines: list[str] = []
        code_lang = ""

        for line in lines:
            # ── code fence ────────────────────────────────────
            if line.startswith("```"):
                if not in_code:
                    in_code = True
                    code_lang = line[3:].strip()
                    code_lines = []
                else:
                    in_code = False
                    blocks.append(_feishu_code("\n".join(code_lines)))
                continue

            if in_code:
                code_lines.append(line)
                continue

            # ── headings ──────────────────────────────────────
            if line.startswith("### "):
                blocks.append(_feishu_heading(line[4:], 3))
            elif line.startswith("## "):
                blocks.append(_feishu_heading(line[3:], 2))
            elif line.startswith("# "):
                blocks.append(_feishu_heading(line[2:], 1))
            # ── divider ───────────────────────────────────────
            elif line.strip() in ("---", "***", "___"):
                blocks.append({"block_type": 22})  # divider
            # ── bullet list ───────────────────────────────────
            elif re.match(r"^[-*+] ", line):
                blocks.append(_feishu_bullet(line[2:]))
            # ── numbered list ─────────────────────────────────
            elif re.match(r"^\d+\. ", line):
                text = re.sub(r"^\d+\. ", "", line)
                blocks.append(_feishu_ordered(text))
            # ── empty line ────────────────────────────────────
            elif not line.strip():
                pass
            # ── paragraph ─────────────────────────────────────
            else:
                blocks.append(_feishu_paragraph(line))

        return blocks


# ── 飞书 block 构建辅助函数 ────────────────────────────────────

# 飞书 block_type：2=paragraph, 3=h1, 4=h2, 5=h3, 12=bullet, 13=ordered, 14=code, 22=divider
_FEISHU_HEADING_TYPES = {1: 3, 2: 4, 3: 5}
_FEISHU_HEADING_KEYS  = {1: "heading1", 2: "heading2", 3: "heading3"}


def _clean(text: str) -> str:
    """去除基础 Markdown 格式，返回纯文本"""
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"`(.+?)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    return t.strip()


def _feishu_text_elem(content: str) -> dict:
    return {"text_run": {"content": content[:2000]}}


def _feishu_paragraph(text: str) -> dict:
    return {
        "block_type": 2,
        "text": {"elements": [_feishu_text_elem(_clean(text))], "style": {}},
    }


def _feishu_heading(text: str, level: int) -> dict:
    bt = _FEISHU_HEADING_TYPES.get(level, 3)
    key = _FEISHU_HEADING_KEYS.get(level, "heading1")
    return {
        "block_type": bt,
        key: {"elements": [_feishu_text_elem(_clean(text))], "style": {}},
    }


def _feishu_bullet(text: str) -> dict:
    return {
        "block_type": 12,
        "bullet": {"elements": [_feishu_text_elem(_clean(text))], "style": {}},
    }


def _feishu_ordered(text: str) -> dict:
    return {
        "block_type": 13,
        "ordered": {"elements": [_feishu_text_elem(_clean(text))], "style": {}},
    }


def _feishu_code(code: str) -> dict:
    # 超过飞书代码块限制时追加截断提示
    if len(code) > 5000:
        code = code[:4960] + "\n\n…（内容过长已截断，完整代码请查看 Markdown 原报告）"
    return {
        "block_type": 14,
        "code": {
            "elements": [_feishu_text_elem(code[:5000])],
            "style": {"language": 1},  # 1 = PlainText
        },
    }
