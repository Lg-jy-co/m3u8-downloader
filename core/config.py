# config.py

MAX_RETRY = 3
CONCURRENT_DOWNLOADS = 20

ROOT_SAVE_DIR = r"VideoDownload"  # 视频保存根目录
DEBUG_ROOT_DIR = r"VideoDownload\_debug"  # debug 文件保存路径

DEBUG = False  # 是否开启调试：保存 html/json/m3u8 等中间结果

# 清晰度选择模式
# "auto"：自动选择
# "ask" ：命令行交互选择
QUALITY_MODE = "auto"       # "auto" 或 "ask"
AUTO_QUALITY_POLICY = "max" # 当 QUALITY_MODE="auto" 时，"max"=最高码率，"min"=最低码率

# ========== 运行模式 ==========
# 1 = 剧集模式：你给每一集的完整页面 URL + 一个统一剧名
# 2 = ID + URL 模板模式：你给一份 ID 列表和一个 URL 模板
RUN_MODE = 2  # 默认 2，可被命令行覆盖

# ===== 模式 1：剧集模式（同一剧名，不同集数） =====
SERIES_NAME = "MySeries"  # 统一剧名，用来建目录 & 文件前缀

# 方式 A：直接给每一集的完整 URL
EPISODE_URLS = [
    # "https://example.com/video/ep1",
    # "https://example.com/video/ep2",
]

# 方式 B：给一个「集数 URL 模板」+ 集数
# 支持 "{}" 或 "{id}" 占位符：
#   "https://xxx.com/series/myshow/ep={}" 或 "https://xxx.com/view?ep={id}"
EPISODE_URL_TEMPLATE = ""
EPISODE_COUNT = 0
EPISODE_START = 1  # 起始集数，默认从第 1 集开始

# ===== 模式 2：ID + URL 模板模式 =====
# 用来分组保存和 debug 的“站点/项目名”，可以随便起，比如 "mysite"
SITE_NAME = "mysite"

# 页面 URL 模板：
# - 支持 {} 占位：    "https://xx.com/viewkey={}/foo"
# - 也支持 {id} 占位："https://xx.com/video/{id}/play"
PAGE_URL_TEMPLATE = "https://example.com/viewkey={id}"

ID_LIST = ["0101010101", "ab12cd3456"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/139.0.0.0 Safari/537.36"
}