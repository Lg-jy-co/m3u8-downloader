# server/ws_bus.py
"""
简单的 WebSocket 事件总线（带历史重放）
- 每个 task_id 对应一组 WebSocket 连接 + 一份事件历史
- 新订阅者连上时，先把历史事件推给它，保证不丢消息
"""

import asyncio
from typing import Dict, List
from fastapi import WebSocket

# 每个任务最多保留的历史事件数
MAX_HISTORY = 2000


class WSBus:
    def __init__(self):
        self._subs: Dict[str, List[WebSocket]] = {}
        self._history: Dict[str, List[dict]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, task_id: str, ws: WebSocket):
        async with self._lock:
            self._subs.setdefault(task_id, []).append(ws)
            history = list(self._history.get(task_id, []))

        # 先重放历史（在锁外发，避免阻塞其他操作）
        for msg in history:
            try:
                await ws.send_json(msg)
            except Exception:
                # 发送失败就撤销订阅
                await self.unsubscribe(task_id, ws)
                return

    async def unsubscribe(self, task_id: str, ws: WebSocket):
        async with self._lock:
            conns = self._subs.get(task_id, [])
            if ws in conns:
                conns.remove(ws)
            if not conns:
                self._subs.pop(task_id, None)

    async def publish(self, task_id: str, message: dict):
        async with self._lock:
            # 记入历史
            hist = self._history.setdefault(task_id, [])
            hist.append(message)
            if len(hist) > MAX_HISTORY:
                # 超出上限就丢老的
                del hist[: len(hist) - MAX_HISTORY]

            conns = list(self._subs.get(task_id, []))

        dead = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.unsubscribe(task_id, ws)

    async def clear_history(self, task_id: str):
        """任务完成后可以调用来释放内存（可选）"""
        async with self._lock:
            self._history.pop(task_id, None)


# 全局单例
bus = WSBus()