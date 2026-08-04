import re
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

def safe_name(s: str) -> str:
    # 简单做下文件名安全处理
    return re.sub(r'[\\/:*?"<>|]+', '_', s)

def build_page_url_from_template(tmpl: str, vid: str) -> str:
    """
    通用页面 URL 构造：
    - 若模板中包含 '{}'，用 template.format(vid)
    - 若模板中包含 '{id}'，用 template.format(id=vid)
    - 否则，默认直接拼接在后面：tmpl + vid
    """
    if '{}' in tmpl:
        return tmpl.format(vid)
    if '{id}' in tmpl:
        return tmpl.format(id=vid)
    # 没有占位符，就简单拼接
    if tmpl.endswith('/') or tmpl.endswith('?') or tmpl.endswith('&'):
        return tmpl + vid
    return tmpl + vid

def extract_page_title(html: str, page_url: str) -> str | None:
    """
    尽量从 HTML 里提取一个合适的视频标题：
    - 优先 meta og:title / twitter:title
    - 其次脚本里的 "name": "xxx"
    - 最后用 <title>，顺便去掉类似 "- XXX.com" 的站点后缀
    """
    soup = BeautifulSoup(html, "lxml")

    # 1) og:title / twitter:title
    og = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if og and og.get("content"):
        title = og["content"].strip()
        if title:
            return title

    # 2) JSON 里的 "name": "xxx"
    m = re.search(r'"name"\s*:\s*"([^"]+)"', html)
    if m:
        raw = m.group(1)
        try:
            title = json.loads(f'"{raw}"').strip()
        except Exception:
            title = raw.strip()
        if title:
            return title

    # 3) <title>
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        # 去掉常见站点后缀： "- XXX.com ..." 或 "| XXX"
        title = re.sub(r'\s*[-|]\s*[^-|\r\n]*$', '', title)
        return title or None

    return None

# ===================== Referer 自动注入工具 =====================
def get_referer_for_url(url: str) -> str:
    """从任意 URL 提取根域名作为 Referer，如 https://cn.example.com/"""
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/"
    return ""


def request_with_referer(session, method: str, url: str,
                         page_url: str | None = None, **kwargs):
    """
    发送 HTTP 请求时自动注入 Referer，按优先级试探：
      ① 不设 Referer
      ② 页面 URL 根域名（page_url 提供时）
      ③ 目标 URL 根域名

    遇到 403/404/412 时自动降级，其他 4xx 直接返回。
    """
    # 构造候选列表
    candidates = [""]  # ① 不设 Referer
    if page_url:
        page_root = get_referer_for_url(page_url)
        if page_root and page_root not in candidates:
            candidates.append(page_root)  # ② 页面根域名
    url_root = get_referer_for_url(url)
    if url_root and url_root not in candidates:
        candidates.append(url_root)  # ③ 目标根域名

    last_exception = None
    for referer in candidates:
        headers = dict(kwargs.get("headers", {}))
        if referer:
            headers["Referer"] = referer
        try:
            resp = session.request(method, url, headers=headers, **kwargs)
            if resp.status_code < 400:
                # 成功
                return resp
            if resp.status_code in (403, 404, 412):
                last_exception = Exception(f"HTTP {resp.status_code} with Referer={referer}")
                continue
            # 其他 4xx（如 400/401/405）：直接返回，不重试
            return resp
        except Exception as e:
            last_exception = e
            continue

    raise last_exception or Exception("所有 Referer 策略均失败")


# ===================== STEP 0 - HTML 中提取 m3u8 =====================
def normalize_m3u8_url(raw_url: str, page_url: str) -> str:
    r"""
    通用 m3u8 URL 规范化：
    - 处理 JSON 转义（https:\/\/...、\/ 等）
    - 支持 //host/path 协议相对地址
    - 其余按相对路径拼到 page_url 上
    """
    s = (raw_url or "").strip()

    # 1) 尝试按 JSON 字符串反转义（处理 \"、\/、\uXXXX 等）
    try:
        s = json.loads(f'"{s}"')
    except Exception:
        # 不是严格 JSON，就简单把 '\/' → '/'
        s = s.replace('\\/', '/')

    s = s.strip()

    # 2) 协议相对地址：//host/path
    if s.startswith("//"):
        base_scheme = urlparse(page_url).scheme or "https"
        s = f"{base_scheme}:{s}"

    # 3) 已经是绝对 http(s)
    if s.startswith("http://") or s.startswith("https://"):
        return s

    # 4) 其余当作相对路径
    return urljoin(page_url, s)