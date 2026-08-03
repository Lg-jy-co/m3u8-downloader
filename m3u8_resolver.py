# m3u8_resolver.py

import re
import logging
import config
import requests
from urllib.parse import urljoin
from debug_utils import DebugRecorder   # 类型注解

# ===================== STEP 1.5 - 多层 m3u8 解析 & 清晰度选择 =====================
def parse_master_variants(lines: list[str]) -> list[dict]:
    """
    从 master m3u8 中解析出多码率变体：
    返回每个变体 dict：
      {
        'attrs_line': str,
        'uri': str,
        'bandwidth': int | None,
        'resolution': (w,h) | None
      }
    """
    variants = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXT-X-STREAM-INF"):
            attrs = line
            uri = None
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith("#")):
                j += 1
            if j < len(lines) and not lines[j].startswith("#"):
                uri = lines[j].strip()

            if uri:
                bw = None
                m_bw = re.search(r'BANDWIDTH=(\d+)', attrs)
                if m_bw:
                    bw = int(m_bw.group(1))
                res = None
                m_res = re.search(r'RESOLUTION=(\d+)x(\d+)', attrs)
                if m_res:
                    res = (int(m_res.group(1)), int(m_res.group(2)))
                variants.append({
                    "attrs_line": attrs,
                    "uri": uri,
                    "bandwidth": bw,
                    "resolution": res
                })
                i = j
            else:
                i += 1
        else:
            i += 1
    return variants

def choose_variant(variants: list[dict], debug: DebugRecorder | None = None) -> dict:
    """
    根据 QUALITY_MODE / AUTO_QUALITY_POLICY 选择一个变体。
    """
    if not variants:
        raise ValueError("无可选变体")

    # Debug 打印可选项
    if debug:
        msg_lines = ["检测到 master m3u8 多清晰度变体："]
        for idx, v in enumerate(variants):
            bw = v["bandwidth"] or 0
            res = v["resolution"]
            res_str = f"{res[0]}x{res[1]}" if res else "未知分辨率"
            msg_lines.append(f"  [{idx}] bw={bw}, res={res_str}, uri={v['uri']}")
        debug.note("\n".join(msg_lines))

    # 交互模式
    if config.QUALITY_MODE == "ask":
        print("检测到多清晰度可选：")
        for idx, v in enumerate(variants):
            bw = v["bandwidth"] or 0
            res = v["resolution"]
            res_str = f"{res[0]}x{res[1]}" if res else "未知分辨率"
            print(f"  [{idx}] 码率={bw}, 分辨率={res_str}, 路径={v['uri']}")
        try:
            choice = input(f"请输入要选择的清晰度序号（0-{len(variants)-1}，回车默认 0）：").strip()
            if choice == "":
                idx = 0
            else:
                idx = int(choice)
            if not (0 <= idx < len(variants)):
                raise ValueError("超出范围")
        except Exception as e:
            print(f"输入无效，自动选择第 0 个。原因：{e}")
            idx = 0
        selected = variants[idx]
        if debug:
            debug.note(f"用户选择变体序号 {idx}: {selected}")
        return selected

    # 自动模式
    if config.AUTO_QUALITY_POLICY == "min":
        selected = min(variants, key=lambda v: v["bandwidth"] or 0)
    else:
        selected = max(variants, key=lambda v: v["bandwidth"] or 0)

    if debug:
        debug.note(f"自动选择变体（{config.AUTO_QUALITY_POLICY} 码率）: {selected}")
    return selected

def resolve_to_media_m3u8(start_url: str, session: requests.Session,
                          debug: DebugRecorder | None = None, max_depth: int = 5) -> tuple[str, str]:
    """
    从可能是多层 index/master 的 m3u8 一路解析到真正的“媒体播放列表”：
    - 支持标准 master：#EXT-X-STREAM-INF + 子 m3u8（带清晰度选择）
    - 支持“index 列表式”：所有非注释行都是 .m3u8（同样可选择）
    返回 (最终媒体 m3u8 的 URL, 文本内容)
    """
    visited = set()
    cur_url = start_url
    depth = 0

    while depth < max_depth and cur_url not in visited:
        visited.add(cur_url)
        logging.info(f"解析 m3u8（第 {depth + 1} 层）：{cur_url}")
        if debug:
            debug.note(f"解析 m3u8（第 {depth + 1} 层）：{cur_url}")

        try:
            resp = session.get(cur_url, verify=False, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            logging.error(f"获取 m3u8 失败：{cur_url}, {e}")
            if debug:
                debug.note(f"获取 m3u8 失败：{cur_url}, {e}")
            raise

        text = resp.text
        if debug:
            debug.save_text(f"m3u8_layer_{depth:02d}.m3u8", text)

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        payload_lines = [l for l in lines if not l.startswith("#")]

        # 没有任何非注释行，认为已经是媒体列表但内容为空
        if not payload_lines:
            if debug:
                debug.note("m3u8 无任何非注释行，返回当前作为媒体列表（可能为空）")
            return cur_url, text

        # 若存在任何一行不是 .m3u8（如 .ts/.m4s），认为已经是媒体播放列表
        if any(not re.search(r'\.m3u8(\?|$)', l) for l in payload_lines):
            if debug:
                debug.note("检测到媒体分片行（非 .m3u8），到达最终媒体播放列表")
            return cur_url, text

        base_url = cur_url.rsplit("/", 1)[0] + "/"

        # 标准 master：有 #EXT-X-STREAM-INF
        if "#EXT-X-STREAM-INF" in text:
            variants = parse_master_variants(lines)
            if not variants:
                if debug:
                    debug.note("存在 #EXT-X-STREAM-INF 但未解析出变体，回退使用第一个 payload 行")
                next_uri = payload_lines[0]
            else:
                selected = choose_variant(variants, debug)
                next_uri = selected["uri"]
            next_url = urljoin(base_url, next_uri)
            if debug:
                debug.note(f"选择 master 层的子 m3u8：{next_url}")
        else:
            # 非标准 index：所有非注释行都是 .m3u8
            if len(payload_lines) > 1 and config.QUALITY_MODE == "ask":
                print("检测到多条子 m3u8（index 列表），可选择：")
                for idx, u in enumerate(payload_lines):
                    print(f"  [{idx}] {u}")
                try:
                    choice = input(f"请输入要选择的序号（0-{len(payload_lines)-1}，回车默认 0）：").strip()
                    if choice == "":
                        idx = 0
                    else:
                        idx = int(choice)
                    if not (0 <= idx < len(payload_lines)):
                        raise ValueError("超出范围")
                except Exception as e:
                    print(f"输入无效，自动选择第 0 个。原因：{e}")
                    idx = 0
                next_uri = payload_lines[idx]
                if debug:
                    debug.note(f"用户在 index 层选择子 m3u8 序号 {idx}: {next_uri}")
            else:
                next_uri = payload_lines[0]
                if debug and len(payload_lines) > 1:
                    debug.note("index 层有多条子 m3u8，但当前为自动模式，默认选择第一个")

            next_url = urljoin(base_url, next_uri)
            if debug:
                debug.note(f"选择 index 层的子 m3u8：{next_url}")

        cur_url = next_url
        depth += 1

    logging.warning(f"m3u8 嵌套层级过深或循环引用，返回当前：{cur_url}")
    if debug:
        debug.note(f"m3u8 嵌套层级过深或循环引用，返回当前：{cur_url}")
        debug.save_text("m3u8_layer_over_depth.txt", f"url={cur_url}")
    # 最后再请求一次当前 m3u8 内容
    resp = session.get(cur_url, verify=False, timeout=20)
    return cur_url, resp.text

# ===================== STEP 2 - 解析媒体 m3u8（多 KEY + 片段式加密） =====================
def parse_m3u8_segments(m3u8_text: str, base_url: str, session: requests.Session):
    """
    返回 [{'url':..., 'key': bytes|None, 'iv': bytes|None, 'seq': int}, ...]
    - 支持多次 #EXT-X-KEY 切换（METHOD=AES-128 / NONE）
    - 若未提供 IV，下载时按 HLS 规范用媒体序列号生成 16 字节 IV
    - 支持“加密→不加密→加密”的混合情况
    """
    lines = m3u8_text.strip().splitlines()
    segments = []
    key = None
    iv = None
    key_cache = {}

    media_seq = 0
    m = re.search(r'#EXT-X-MEDIA-SEQUENCE:(\d+)', m3u8_text)
    if m:
        media_seq = int(m.group(1))

    def get_key_bytes(key_uri):
        key_url = urljoin(base_url, key_uri)
        if key_url in key_cache:
            return key_cache[key_url]
        kb = session.get(key_url, verify=False, timeout=20).content
        key_cache[key_url] = kb
        return kb

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith('#EXT-X-KEY'):
            method_m = re.search(r'METHOD=([^,]+)', line)
            method = method_m.group(1).strip() if method_m else 'NONE'

            if method == 'NONE':
                key = None
                iv = None
                continue

            if method == 'AES-128':
                uri_m = re.search(r'URI="(.*?)"', line)
                iv_m = re.search(r'IV=0x([0-9a-fA-F]+)', line)

                if uri_m:
                    try:
                        key = get_key_bytes(uri_m.group(1))
                    except Exception:
                        print("❌ KEY 下载失败，后续分片将不解密")
                        logging.error("KEY 下载失败", exc_info=True)
                        key = None

                if iv_m:
                    iv_hex = iv_m.group(1).zfill(32)
                    iv = bytes.fromhex(iv_hex)
                else:
                    iv = None
                continue

            # 其他加密方式暂不支持
            key = None
            iv = None
            continue

        if line.startswith('#'):
            continue

        ts_url = urljoin(base_url, line)
        segments.append({
            'url': ts_url,
            'key': key,
            'iv': iv,
            'seq': media_seq
        })
        media_seq += 1

    return segments

