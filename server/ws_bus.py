# server/ws_bus.py
"""
简单的 WebSocket 事件总线
- 每个 task_id 对应一组 WebSocket 连接
- 日志 / 进度事件会被广播给订阅该 task_id 的所有连接
"""

import asyncio
import logging
from typing import Dict, List
from fastapi import WebSocket


class WSBus:
    def __init__(self):
        # {task_id: [WebSocket, WebSocket, ...]}
        self._subs: Dict[str, List[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, task_id: str, ws: WebSocket):
        async with self._lock:
            self._subs.setdefault(task_id, []).append(ws)

    async def unsubscribe(self, task_id: str, ws: WebSocket):
        async with self._lock:
            conns = self._subs.get(task_id, [])
            if ws in conns:
                conns.remove(ws)
            if not conns:
                self._subs.pop(task_id, None)

    async def publish(self, task_id: str, message: dict):
        """把消息广播给订阅该 task_id 的所有连接"""
        conns = self._subs.get(task_id, [])
        dead = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        # 清理死连接
        for ws in dead:
            await self.unsubscribe(task_id, ws)


# 全局单例
bus = WSBus()