# downloader.py

import os
import asyncio
import logging
import subprocess
import aiohttp
import aiofiles
from Crypto.Cipher import AES
from tqdm import tqdm
from core import config
from core.utils import safe_name, request_with_referer
from core.crypto_utils import looks_like_ts, iv_from_seq
from core.m3u8_resolver import resolve_to_media_m3u8, parse_m3u8_segments
from core.debug_utils import DebugRecorder

# ===================== STEP 3 - 下载单个分片 =====================
async def download_ts_file(i, ts_info, save_path, session,
                           total=0, retry=None,
                           debug: DebugRecorder | None = None,
                           page_url: str | None = None):
    ts_url = ts_info['url']
    key = ts_info.get('key')
    iv = ts_info.get('iv')
    seq = ts_info.get('seq')

    filename = os.path.join(save_path, f"{i:04d}.ts")
    if retry is None:
        retry = config.MAX_RETRY
    if os.path.exists(filename):
        return

    for attempt in range(retry):
        try:
            async with session.get(ts_url, ssl=False, timeout=300) as resp:
                if resp.status != 200:
                    raise Exception(f"状态码错误: {resp.status}")
                raw = await resp.read()

                final_data = raw
                status = 'plain' if not key else 'try_decrypt'
                reason = ''
                iv_used_label = ''

                if key:
                    candidates = []
                    if iv is not None:
                        candidates.append(('显式IV', iv))
                    else:
                        if seq is not None:
                            candidates.append(('序列IV', iv_from_seq(seq)))
                        candidates.append(('全零IV', b'\x00' * 16))

                    decrypted_ok = False
                    last_error = None

                    for label, civ in candidates:
                        try:
                            dec = AES.new(key, AES.MODE_CBC, iv=civ).decrypt(raw)
                            if looks_like_ts(dec):
                                final_data = dec
                                status = 'decrypted'
                                iv_used_label = label
                                decrypted_ok = True
                                break
                            else:
                                last_error = '解密后未通过 TS 判定'
                        except Exception as e:
                            last_error = str(e)

                    if not decrypted_ok:
                        if looks_like_ts(raw):
                            status = 'plain_kept'
                            if len(raw) % 16 != 0:
                                reason = '密文长度非 16 字节倍数，疑似未加密分片'
                            else:
                                reason = f'解密失败（{last_error}），但原始数据为 TS，疑似未加密分片'
                        else:
                            status = 'suspect_kept'
                            if len(raw) % 16 != 0:
                                reason = '密文长度非 16 字节倍数且原始数据不像 TS'
                            else:
                                reason = f'解密失败（{last_error}）且原始数据不像 TS'

                async with aiofiles.open(filename, 'wb') as f:
                    await f.write(final_data)

                prefix = f"[{i + 1}/{total}]"
                if status == 'decrypted':
                    msg = f"✅ {prefix} 已解密保存（IV={iv_used_label}）"
                elif status == 'plain':
                    msg = f"✅ {prefix} 已保存（未加密）"
                elif status == 'plain_kept':
                    msg = f"✅ {prefix} 已保存（保留原数据：{reason}）"
                else:
                    msg = f"⚠️ {prefix} 已保存（疑似异常：{reason}）"
                logging.info(msg)
                return

        except Exception as e:
            if attempt < retry - 1:
                print(f"🔁 [{i + 1}] 重试 {attempt + 1}/{retry}（原因：{e}）")
            else:
                print(f"❌ [{i + 1}] 下载失败 {ts_url}：{e}")
                logging.error(f"TS 分片下载失败：{ts_url}，{e}")
                if debug:
                    debug.note(f"TS 分片下载失败：{ts_url}，{e}")


# ===================== STEP 4 - 下载完整视频 & 合并 =====================
async def download_m3u8_video(m3u8_url, session, title='video', name='unknown',
                              debug: DebugRecorder | None = None):
    print(f"📥 开始下载：{title}")
    logging.info(f"📥 开始下载：{title}")

    safe_title = safe_name(title)

    base_dir = os.path.join(config.ROOT_SAVE_DIR, name)
    output_dir = os.path.join(base_dir, "videos", safe_title)
    merged_dir = base_dir
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(merged_dir, exist_ok=True)

    # 先解析到最终的"媒体 m3u8"
    try:
        final_m3u8_url, m3u8_text = resolve_to_media_m3u8(m3u8_url, session, debug)
    except Exception as e:
        print(f"❌ 解析 m3u8 失败：{e}")
        logging.error("解析 m3u8 失败", exc_info=True)
        return

    base_url = final_m3u8_url.rsplit("/", 1)[0] + "/"
    if debug:
        debug.save_text("final_media.m3u8", m3u8_text)
        debug.note(f"最终媒体 m3u8 URL：{final_m3u8_url}")

    segments = parse_m3u8_segments(m3u8_text, base_url, session)
    if not segments:
        print("❌ 未解析到任何分片，请检查 m3u8")
        logging.error("未解析到任何分片")
        if debug:
            debug.note("未从最终 m3u8 解析出任意媒体分片")
        return

    # 下载分片：预试探后全局复用 Referer + Cookie
    # 1. 读取 session 上的 page_url（由 page_parser.py 注入）
    page_url_for_probe = getattr(session, '_page_url', None)

    # 2. 预试探：用 HEAD 快速探测第一个 TS 分片，找到能用的 Referer
    referer = ""
    if segments:
        probe_url = segments[0]['url']
        try:
            resp = request_with_referer(session, "HEAD", probe_url,
                                        page_url=page_url_for_probe, timeout=10)
            # 从响应中提取实际使用的 Referer
            referer = resp.request.headers.get('Referer', '')
            resp.close()
        except Exception:
            try:
                resp = request_with_referer(session, "GET", probe_url,
                                            page_url=page_url_for_probe,
                                            timeout=10, stream=True)
                referer = resp.request.headers.get('Referer', '')
                resp.close()
            except Exception:
                pass

    # 3. 同步 Cookie（requests 同步请求后续可能更新，复制到异步请求）
    aio_headers = dict(config.HEADERS)
    if referer:
        aio_headers["Referer"] = referer
    if hasattr(session, 'cookies') and session.cookies:
        cookies_str = '; '.join(f'{k}={v}' for k, v in session.cookies.items())
        if cookies_str:
            aio_headers['Cookie'] = cookies_str

    connector = aiohttp.TCPConnector(limit=config.CONCURRENT_DOWNLOADS, ssl=False)
    async with aiohttp.ClientSession(connector=connector, headers=aio_headers) as aio_session:
        tasks = [
            download_ts_file(i, seg, output_dir, aio_session,
                             total=len(segments), debug=debug, page_url=page_url_for_probe)
            for i, seg in enumerate(segments)
        ]
        for coro in tqdm(
            asyncio.as_completed(tasks),
            total=len(tasks),
            desc="📥 下载进度"
        ):
            await coro

    # 合并前检查分片完整性
    missing = []
    for i in range(len(segments)):
        ts_file = os.path.join(output_dir, f'{i:04d}.ts')
        if not os.path.exists(ts_file):
            missing.append(ts_file)

    if missing:
        print(f"❌ 合并失败：以下 {len(missing)} 个分片缺失：")
        for f in missing:
            print(f"  - {f}")
        logging.error(f"缺失 {len(missing)} 个分片，无法合并")
        return

    # 合并
    file_list = os.path.join(output_dir, "file_list.txt")
    with open(file_list, 'w', encoding='utf-8') as f:
        for i in range(len(segments)):
            ts_path = os.path.abspath(os.path.join(output_dir, f'{i:04d}.ts')).replace('\\', '/')
            f.write(f"file '{ts_path}'\n")

    out_file = os.path.join(merged_dir, f"{safe_title}.mp4")
    try:
        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', file_list,
            '-c', 'copy', out_file
        ], check=True)
        print(f"✅ 合并完成，输出文件：{out_file}")
        logging.info(f"合并完成：{out_file}")
    except Exception:
        print("❌ ffmpeg 合并失败，请检查日志")
        logging.error("ffmpeg 合并失败", exc_info=True)