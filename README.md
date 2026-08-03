# 🎬 M3U8 通用下载器 (v2.0)

一款支持页面嗅探、多清晰度选择、AES-128加密自适应下载的 Python 工具。

## ✨ 特性
- 🕵️ 自动发现：Requests + Playwright 双引擎抓取 m3u8
- 📺 清晰度选择：支持交互式或自动选择最高/最低码率
- 🔐 加密兼容：自适应多 KEY/IV，智能判断 TS 结构
- 🛠️ 双模式：支持硬编码配置或命令行参数

## ⚠️ 已知限制
- 在 HTML/JSON 层只返回“第一个找到的 m3u8 地址”，
  不会收集多个候选并区分清晰度：
  - 如果页面脚本里直接写了多个不同清晰度的 m3u8（如 1080P/720P/480P），当前实现只会拿到第一个被正则命中的 URL，无法在 HTML 层手动选择清晰度。
- 清晰度选择仅在 m3u8 结构（master/index）内生效；HTML/JSON 多 m3u8 的情况未专门处理。
- 未处理 cookie/token/DRM 等复杂鉴权场景；仅适合“常规公开 HLS”。
- Python 版本要求： 本脚本使用了 str | None 联合类型语法，需要 Python 3.10 或更高版本。

## 🚀 快速开始
```bash
# 安装依赖
pip install -r requirements.txt
playwright install chromium

# 无参数运行（使用默认硬编码配置）
python m3u8_downloader.py

# 命令行模式（ID模板）
python m3u8_downloader.py --mode2 -t "https://example.com/v/{id}" -i "123" "456"
```

## ⚙️ 参数说明
    --mode1 / --mode2           选择运行模式（二选一）
    -a, --episode-urls          模式1-A：每集完整 URL（一个或多个）
    -b, --episode-template      模式1-B：集数 URL 模板（包含 {} 或 {id}）
    -c, --count                 模式1-B：总集数（正整数）
    -s, --start                 模式1-B：起始集数编号（默认 1）
    -t, --page-template         模式2：页面 URL 模板（包含 {} 或 {id}）
    -i, --ids                   模式2：ID / viewkey 列表（一个或多个）
    -o, --output-dir            视频保存根目录（可选，不传则用代码中的默认 ROOT_SAVE_DIR）
    -d, --debug-dir             Debug 文件保存根目录（可选，不传则用代码中的默认 DEBUG_ROOT_DIR）
    --series-name               模式1：剧名（可选，不传则用代码中的默认 SERIES_NAME）
    --site-name                 模式2：站点名（可选，不传则用代码中的默认 SITE_NAME）
    --debug                     Debug 模式开关（可选，默认为 False，即不开启调试模式）

  若不传任何命令行参数，则使用文件内默认配置（RUN_MODE、EPISODE_URLS 等）运行。


##  ️▶️ 运行模式
- 模式 1：剧集模式（同一剧名，不同集数）
  - 方式 A：直接给每一集完整页面 URL 列表
  ```bash
  python m3u8_downloader.py --mode1 -a "https://xx.com/ep1" "https://xx.com/ep2"
  ```

  - 方式 B：给一个「集数 URL 模板」+ 总集数（可指定起始集数，默认 1）
  ```bash
  python m3u8_downloader.py --mode1 \
          -b "https://xx.com/series/myshow/ep-{id}" \
          -c 30 -s 1
  ```

- 模式 2：ID + URL 模板模式（适合 viewkey / videoId 之类的站点）
  - 根据 ID 列表和页面 URL 模板自动拼出多个播放页，并从页面提取标题命名文件
  ```bash
    python m3u8_downloader.py --mode2 \
          -t "https://xx.com/viewkey={id}" \
          -i "1234" "4321"
  ```