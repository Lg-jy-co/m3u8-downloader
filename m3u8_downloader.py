# m3u8_downloader.py

import sys
import argparse
import asyncio
import requests
import config
import logging
from logger_config import setup_logging
from utils import build_page_url_from_template
from debug_utils import DebugRecorder
from page_parser import get_m3u8_url_smart
from downloader import download_m3u8_video
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ===================== argparse 命令行入口 =====================
def parse_cli_and_set_globals():
    """
    解析命令行参数，并覆盖全局配置（RUN_MODE / EPISODE_* / PAGE_URL_TEMPLATE / ID_LIST 等）
    """
    parser = argparse.ArgumentParser(
        description="通用 m3u8 下载器（版本 B，支持剧集模式 & ID+模板模式）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--mode1", action="store_true",
        help="模式 1：剧集模式（同一剧名，不同集数）"
    )
    mode_group.add_argument(
        "--mode2", action="store_true",
        help="模式 2：ID + URL 模板模式"
    )

    # 通用可选：剧名 / 站点名
    parser.add_argument(
        "--series-name", type=str, help="模式1：剧名（不指定则使用代码中的默认值）"
    )
    parser.add_argument(
        "--site-name", type=str, help="模式2：站点名（不指定则使用代码中的默认值）"
    )

    # 模式1参数
    parser.add_argument(
        "-a", "--episode-urls", nargs="+",
        help="模式1-A：每一集的完整页面 URL 列表（与 -b/-c 互斥）"
    )
    parser.add_argument(
        "-b", "--episode-template", type=str,
        help="模式1-B：集数 URL 模板，包含 {} 或 {id}"
    )
    parser.add_argument(
        "-c", "--count", type=int,
        help="模式1-B：总集数（正整数）"
    )
    parser.add_argument(
        "-s", "--start", type=int, default=1,
        help="模式1-B：起始集数编号（默认 1）"
    )

    # 模式2参数
    parser.add_argument(
        "-t", "--page-template", type=str,
        help="模式2：页面 URL 模板，包含 {} 或 {id}"
    )
    parser.add_argument(
        "-i", "--ids", nargs="+",
        help="模式2：ID / viewkey 列表"
    )

    # 路径修改
    parser.add_argument(
        "-o", "--output-dir", type=str,
        help="视频保存根目录（覆盖代码中的 ROOT_SAVE_DIR）"
    )
    parser.add_argument(
        "-d", "--debug-dir", type=str,
        help="Debug 文件保存根目录（覆盖代码中的 DEBUG_ROOT_DIR）"
    )

    # DEBUG 修改
    parser.add_argument(
        "--debug", action="store_true",
        help="开启调试模式（默认关闭）"
    )

    args = parser.parse_args()

    # 覆盖公共配置
    if args.series_name:
        config.SERIES_NAME = args.series_name
    if args.site_name:
        config.SITE_NAME = args.site_name
    if args.output_dir:
        config.ROOT_SAVE_DIR = args.output_dir
    if args.debug_dir:
        config.DEBUG_ROOT_DIR = args.debug_dir
    if args.debug:
        config.DEBUG = True

    if args.mode1:
        config.RUN_MODE = 1

        # 两种方式二选一：
        use_list = bool(args.episode_urls)
        use_tpl = bool(args.episode_template and args.count)

        if use_list == use_tpl:
            parser.error(
                "模式1需要在以下两种方式中二选一：\n"
                "  ① -a/--episode-urls URL1 URL2 ...\n"
                "  ② -b/--episode-template TPL -c/--count N [-s/--start S]"
            )

        if use_list:
            config.EPISODE_URLS = args.episode_urls
            config.EPISODE_URL_TEMPLATE = ""
            config.EPISODE_COUNT = 0
            config.EPISODE_START = 1
        else:
            if args.count <= 0:
                parser.error("模式1-B：-c/--count 必须为正整数")
            config.EPISODE_URLS = []
            config.EPISODE_URL_TEMPLATE = args.episode_template
            config.EPISODE_COUNT = args.count
            config.EPISODE_START = args.start if args.start and args.start > 0 else 1

    elif args.mode2:
        config.RUN_MODE = 2

        if not args.page_template or not args.ids:
            parser.error("模式2需要同时提供 -t/--page-template 和 -i/--ids")

        config.PAGE_URL_TEMPLATE = args.page_template
        config.ID_LIST = args.ids


# ===================== 运行模式封装 =====================
async def run_mode_series(session):
    """
    模式 1：剧集模式
    - 情况 A：EPISODE_URLS 非空 → 每个 URL 当一集
    - 情况 B：EPISODE_URL_TEMPLATE 非空 + EPISODE_COUNT>0 → 用模板 + 集数生成每集 URL
    """
    series_name = config.SERIES_NAME

    # 情况 A：直接使用 EPISODE_URLS
    if config.EPISODE_URL_TEMPLATE == "" and config.EPISODE_URLS:
        for idx, url in enumerate(config.EPISODE_URLS, start=1):
            title = f"第{idx:03d}集"
            print(f"\n===== 开始下载 {series_name} - {title} =====")
            debug = DebugRecorder(site=series_name, episode=title)

            m3u8_url, _page_title = await get_m3u8_url_smart(url, session, debug)

            if m3u8_url:
                await download_m3u8_video(m3u8_url, session, title=title, name=series_name, debug=debug)
            else:
                print(f"❌ 未找到 {title} 的 m3u8，详见 debug 日志目录")
                logging.error(f"未找到 {title} 的 m3u8：{url}")
                if debug:
                    debug.note("整个流程未找到 m3u8，可能是非 HLS 播放或需要复杂交互")
        return

    # 情况 B：使用模板 + 集数
    if not config.EPISODE_URLS and config.EPISODE_URL_TEMPLATE:
        if config.EPISODE_COUNT <= 0:
            raise ValueError("下载集数需为正数！")
        for i in range(config.EPISODE_START, config.EPISODE_START + config.EPISODE_COUNT):
            title = f"第{i:03d}集"
            print(f"\n===== 开始下载 {series_name} - {title} =====")
            debug = DebugRecorder(site=series_name, episode=title)
            url = build_page_url_from_template(config.EPISODE_URL_TEMPLATE, str(i))
            m3u8_url, _page_title = await get_m3u8_url_smart(url, session, debug)

            if m3u8_url:
                await download_m3u8_video(m3u8_url, session, title=title, name=series_name, debug=debug)
            else:
                print(f"❌ 未找到 {title} 的 m3u8，详见 debug 日志目录")
                logging.error(f"未找到 {title} 的 m3u8：{url}")
                if debug:
                    debug.note("整个流程未找到 m3u8，可能是非 HLS 播放或需要复杂交互")
        return

    raise ValueError(
        "模式1参数缺失或重复！\n"
        "注意：①EPISODE_URLS  ②EPISODE_URL_TEMPLATE + EPISODE_COUNT\n"
        "二者要有且只能有一个"
    )


async def run_mode_ids(session):
    """
    模式 2：ID + URL 模板模式
    - 使用 PAGE_URL_TEMPLATE + ID_LIST 里的 id 组成多个页面 URL
    - 每个页面自动提取标题作为输出文件名
    - 所有视频统一放在 ROOT_SAVE_DIR/SITE_NAME/ 下面
    """
    if not config.PAGE_URL_TEMPLATE or not config.ID_LIST:
        raise ValueError("模式2需要配置 PAGE_URL_TEMPLATE 和非空的 ID_LIST")

    for idx, vid in enumerate(config.ID_LIST, start=1):
        page_url = build_page_url_from_template(config.PAGE_URL_TEMPLATE, vid)
        print(f"\n===== [{idx}/{len(config.ID_LIST)}] 处理 id={vid} =====")

        # debug 目录用 SITE_NAME + id 区分
        debug = DebugRecorder(site=config.SITE_NAME, episode=f"id_{vid}")

        m3u8_url, page_title = await get_m3u8_url_smart(page_url, session, debug)

        if not m3u8_url:
            print(f"❌ 未找到 id={vid} 的 m3u8，详见 debug 日志目录")
            logging.error(f"未找到 id={vid} 的 m3u8：{page_url}")
            if debug:
                debug.note("整个流程未找到 m3u8，可能是非 HLS 播放或需要复杂交互")
            continue

        # 文件名：优先用页面标题，失败就退回用 id
        if not page_title:
            page_title = vid

        print(f"▶ 将使用文件名：{page_title}.mp4")
        await download_m3u8_video(m3u8_url, session, title=page_title, name=config.SITE_NAME, debug=debug)


# ===================== STEP 5 - 批量主函数 =====================
async def main():
    session = requests.Session()
    session.headers.update(config.HEADERS)
    if config.RUN_MODE == 1:
        await run_mode_series(session)
    elif config.RUN_MODE == 2:
        await run_mode_ids(session)
    else:
        raise ValueError("RUN_MODE 只能是 1（剧集模式）或 2（ID+模板模式）")


def entry():
    asyncio.run(main())



if __name__ == '__main__':
    # 若传入了命令行参数，则用 argparse 覆盖全局配置；否则使用代码中的默认配置
    if len(sys.argv) > 1:
        parse_cli_and_set_globals()
    setup_logging() #配置日志
    entry()