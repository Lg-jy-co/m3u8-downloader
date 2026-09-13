# server/schemas.py
"""
定义前端请求后端时，传递的数据结构（Pydantic 模型）
FastAPI 会自动根据这些定义校验数据，并生成 API 文档
"""

from pydantic import BaseModel
from typing import List, Optional

class TaskRequest(BaseModel):
    # 运行模式：1=剧集模式，2=ID模板模式
    mode: int = 2

    # 模式1参数
    series_name: Optional[str] = None
    episode_urls: Optional[List[str]] = None
    episode_template: Optional[str] = None
    episode_count: Optional[int] = None
    episode_start: Optional[int] = 1

    # 模式2参数
    site_name: Optional[str] = None
    page_template: Optional[str] = None
    ids: Optional[List[str]] = None

    # 通用参数
    output_dir: Optional[str] = None
    debug: bool = False
    quality_mode: str = "auto"          # "auto" 或 "ask"
    auto_quality_policy: str = "max"    # "max" 或 "min"