# page_parser.py

import re
import logging
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from core.utils import normalize_m3u8_url, extract_page_title, request_with_referer
from core.debug_utils import DebugRecorder   # 为了类型注解

def extract_m3u8_from_html(html: str, page_url: str, debug: DebugRecorder | None = None) -> str | None:
    """
    从 HTML 中尽可能通用地提取 m3u8 地址（仅取第一条）：
    1. 正则捕获显式 http(s)://...m3u8（含转义）
    2. 标签 src/href 中的 m3u8
    3. script 中的 url / videoUrl / playUrl / src 等字段
    """
    # 1) 直接正则扫整页（这里抓到的可能是已转义或未转义的 URL，都统一交给 normalize）
    m = re.search(r'https?://[^\s\'"]+\.m3u8[^\s\'"]*', html)
    if m:
        url = normalize_m3u8_url(m.group(0), page_url)
        if debug:
            debug.note(f"HTML 正则直接捕获 m3u8: {url}")
        return url

    soup = BeautifulSoup(html, "lxml")

    # 2) 常见标签中的 src/href
    for tag in soup.find_all(["source", "video", "a", "link"]):
        for attr in ("src", "href", "data-src"):
            raw = tag.get(attr)
            if not raw:
                continue
            if ".m3u8" in raw:
                real = normalize_m3u8_url(raw, page_url)
                if debug:
                    debug.note(f"HTML 标签捕获 m3u8: {real}")
                return real

    # 3) script 文本中常见字段
    for script in soup.find_all("script"):
        if not script.string:
            continue
        text = script.string

        # 3.1 按字段名匹配 JSON："videoUrl":"xxx.m3u8"
        for key in ("url", "videoUrl", "playUrl", "src"):
            pattern = rf'"{key}"\s*:\s*"(.*?)"'
            m = re.search(pattern, text)
            if m and ".m3u8" in m.group(1):
                raw_url = m.group(1)
                full = normalize_m3u8_url(raw_url, page_url)
                if debug:
                    debug.note(f"script JSON 字段 {key} 捕获 m3u8: {full}")
                return full

        # 3.2 兜底：任何字符串里的 xxx.m3u8（绝对 / 相对 / 转义 全交给 normalize 处理）
        m = re.search(r'["\']([^"\']+\.m3u8[^"\']*)["\']', text)
        if m:
            raw = m.group(1)
            url = normalize_m3u8_url(raw, page_url)
            if debug:
                debug.note(f"script 文本中捕获 m3u8（兜底匹配）: {url}")
            return url

    if debug:
        debug.note("未在静态 HTML 中找到 m3u8")
    return None

async def get_m3u8_url_smart(page_url: str, session: requests.Session,
                             debug: DebugRecorder | None = None) -> tuple[str | None, str | None]:
    """
    先用 requests + HTML 静态解析；
    若失败，再用 Playwright 回退。
    额外返回一个尽量推断出的页面标题，用于自动命名。
    """
    page_title = None

    try:
        res = request_with_referer(session, "GET", page_url, page_url=page_url, verify=False, timeout=20)
        status = res.status_code
        res.encoding = res.apparent_encoding
        html = res.text

        if debug:
            debug.save_text("01_page_requests.html", html)
            debug.note(f"requests 访问页面状态码: {status}")

        if status != 200:
            print(f"❌ 页面访问失败：HTTP {status}")
            logging.error(f"页面访问失败：{page_url} HTTP {status}")
            session._page_url = page_url
            return None, None

        # 先提标题
        page_title = extract_page_title(html, page_url)

        # 再找 m3u8
        m3u8_url = extract_m3u8_from_html(html, page_url, debug)
        if m3u8_url:
            print("✅ HTML 中已找到 m3u8，不用执行 Playwright！")
            logging.info("HTML 中已找到 m3u8，不用执行 Playwright！")
            session._page_url = page_url
            return m3u8_url, page_title

        print("ℹ️ 静态 HTML 未找到 m3u8，可能在 JS 动态加载或 iframe 中，准备使用 Playwright")
        logging.info("静态 HTML 未找到 m3u8，准备使用 Playwright")

        session._page_url = page_url

    except Exception as e:
        logging.error("页面直读失败", exc_info=True)
        if debug:
            debug.note(f"requests 访问页面异常：{e}")
        session._page_url = page_url

    # 回退：Playwright 只帮你找 m3u8，标题沿用上面静态 HTML 提取到的（可能为 None）
    try:
        m3u8_url = await get_m3u8_url_playwright(page_url, debug)
    except Exception as e:
        logging.error(f"Playwright 回退失败：{e}")
        if debug:
            debug.note(f"Playwright 回退失败：{e}")
        m3u8_url = None
    return m3u8_url, page_title


async def get_m3u8_url_playwright(page_url: str, debug: DebugRecorder | None = None) -> str | None:
    async with async_playwright() as p:
        print(f"🕵️ 使用 Playwright 打开页面：{page_url}")
        logging.info(f"🕵️ 使用 Playwright 打开页面：{page_url}")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        found_url = None
        all_m3u8_requests = []

        async def handle_response(resp):
            nonlocal found_url
            try:
                url = resp.url
                if ".m3u8" in url:
                    all_m3u8_requests.append(url)
                    if not found_url:
                        found_url = url
                # debug: 保存含有 m3u8 字样的 JSON 响应
                if debug and debug.enabled:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct or "javascript" in ct or "text" in ct:
                        try:
                            text = await resp.text()
                            if any(x in text for x in ("m3u8", "videoUrl", "playUrl")):
                                fname = f"02_resp_{re.sub(r'[^0-9a-zA-Z]', '_', url[-50:])}.txt"
                                debug.save_text(fname, text)
                        except Exception:
                            pass
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            await page.goto(page_url, timeout=60000)
            await page.wait_for_timeout(5000)
        except Exception as e:
            print(f"❌ Playwright 打开页面失败：{e}")
            logging.error("Playwright 打开页面失败", exc_info=True)
            if debug:
                debug.note(f"Playwright 打开页面失败：{e}")
            await browser.close()
            return None

        # 1) 看网络请求中是否有 m3u8
        if found_url:
            print(f"✅ Playwright 响应中捕获 m3u8: {found_url}")
            logging.info(f"✅ Playwright 响应中捕获 m3u8: {found_url}")
            if debug:
                debug.note(f"Playwright 网络中捕获 m3u8: {found_url}")
            await browser.close()
            return found_url

        # 2) 遍历 frame HTML 做正则
        all_html = []
        for frame in page.frames:
            try:
                content = await frame.content()
                all_html.append(f"===== FRAME {frame.url} =====\n{content}\n\n")
                match = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', content)
                if match:
                    url = match.group(1)
                    print(f"✅ Playwright HTML 中找到 m3u8: {url}")
                    logging.info(f"✅ Playwright HTML 中找到 m3u8: {url}")
                    if debug:
                        debug.note(f"Playwright frame HTML 中捕获 m3u8: {url}")
                        debug.save_text("02_playwright_frames.html", "\n".join(all_html))
                    await browser.close()
                    return url
            except Exception:
                continue

        if debug:
            debug.save_text("02_playwright_frames.html", "\n".join(all_html))
            debug.note("Playwright 未在 HTML/网络中找到 m3u8，可能需要用户交互或使用非 HLS 协议")

        print("❌ Playwright 找不到 m3u8，可能需要手动分析或站点使用其他协议")
        logging.info("❌ Playwright 找不到 m3u8")
        await browser.close()
        return None
