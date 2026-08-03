# debug_utils.py

import os
import logging
import config
from utils import safe_name

class DebugRecorder:
    def __init__(self, site: str, episode: str):
        self.enabled = config.DEBUG
        if not self.enabled:
            self.base_dir = None
            return

        base = os.path.join(config.DEBUG_ROOT_DIR, safe_name(site), safe_name(episode))
        os.makedirs(base, exist_ok=True)
        self.base_dir = base

        logging.debug(f"本集的 debug 文件目录为: {self.base_dir}")

    def save_text(self, filename: str, text: str):
        if not self.enabled or not self.base_dir:
            return
        path = os.path.join(self.base_dir, filename)
        try:
            with open(path, "w", encoding="utf-8", errors="ignore") as f:
                f.write(text)
            logging.debug(f"{filename}已保存到: {path}")
        except Exception as e:
            logging.error(f"写入 debug 文本失败: {path}, {e}")

    def save_binary(self, filename: str, data: bytes):
        if not self.enabled or not self.base_dir:
            return
        path = os.path.join(self.base_dir, filename)
        try:
            with open(path, "wb") as f:
                f.write(data)
        except Exception as e:
            logging.error(f"写入 debug 二进制失败: {path}, {e}")

    def note(self, msg: str):
        # 额外在日志里标记 debug 信息
        logging.debug(f"[DEBUG] {msg}")