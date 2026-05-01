"""
OKX 交易助手 - WebSocket 客户端
"""
import asyncio
import json
import time
import hmac
import hashlib
import base64
from datetime import datetime, timezone
from typing import Callable, Optional
import websockets

from trading.config import (
    OKX_WS_PUBLIC, OKX_WS_PRIVATE, OKX_WS_BUSINESS,
    OKX_WS_PUBLIC_DEMO, OKX_WS_PRIVATE_DEMO,
    WS_RECONNECT_INTERVAL, WS_RECONNECT_MAX, WS_PING_INTERVAL,
    PROXY_URL,
)
from trading.core.logger import log


class OKXWebSocket:
    """OKX WebSocket 封装，支持自动重连与多频道订阅"""

    def __init__(self, api_key: str = "", secret: str = "", passphrase: str = "",
                 is_demo: bool = False, on_message: Callable = None):
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase
        self.is_demo = is_demo
        self.on_message = on_message

        self._public_ws = None
        self._private_ws = None
        self._running = False
        self._reconnect_count = 0
        self._subscriptions: dict[str, list[dict]] = {"public": [], "private": []}
        self._last_price: dict[str, dict] = {}  # symbol -> {price, ts}

    @property
    def connected(self) -> bool:
        try:
            # websockets 14.0+ 移除了 .open 属性，改用 .state 或 .closed
            # 兼容性处理：优先检查状态
            if self._public_ws is None:
                return False
            # 兼容旧版本和新版本 websockets
            if hasattr(self._public_ws, "open"):
                return self._public_ws.open
            # 新版本用法 (State.OPEN == 1)
            return not self._public_ws.closed
        except Exception:
            return False

    def get_last_price(self, symbol: str) -> Optional[float]:
        data = self._last_price.get(symbol)
        return data["price"] if data else None

    async def start(self):
        """启动公共 + 私有 WebSocket"""
        self._running = True
        await asyncio.gather(
            self._connect_public(),
            self._connect_private(),
        )

    async def stop(self):
        """停止所有连接"""
        self._running = False
        for ws in [self._public_ws, self._private_ws]:
            if ws and ws.open:
                await ws.close()

    # ----------------------------------------------------------
    # 连接管理
    # ----------------------------------------------------------
    async def _connect_public(self):
        url = OKX_WS_PUBLIC_DEMO if self.is_demo else OKX_WS_PUBLIC
        await self._connect_loop(url, "public")

    async def _connect_private(self):
        if not self.api_key:
            return
        url = OKX_WS_PRIVATE_DEMO if self.is_demo else OKX_WS_PRIVATE
        await self._connect_loop(url, "private")

    async def _connect_loop(self, url: str, channel_type: str):
        self._reconnect_count = 0  # 每个通道独立计数
        while self._running:
            try:
                # 使用代理连接 WebSocket
                connect_kwargs = {
                    "ping_interval": WS_PING_INTERVAL,
                    "close_timeout": 5,
                }
                
                # 优化代理注入：Windows 环境下环境变量生效可能存在延迟或作用域问题
                if PROXY_URL:
                    import os
                    env_proxy = PROXY_URL.replace("socks5h://", "http://").replace("socks5://", "http://")
                    # 确保方案前缀正确 (websockets 内部库依赖此变量)
                    os.environ["HTTP_PROXY"] = env_proxy
                    os.environ["HTTPS_PROXY"] = env_proxy
                    os.environ["ALL_PROXY"] = env_proxy
                    # 某些环境下 http_proxy (小写) 也被需要
                    os.environ["http_proxy"] = env_proxy
                    os.environ["https_proxy"] = env_proxy
                
                # Windows 兼容性：确保 event loop 正确处理句柄
                # 在某些 Windows 环境中，[WinError 64] 可能是由于并发抢占 proxy 资源导致
                # 增加一个微小的错峰，防止 public 和 private 同时发起握手挤占代理通道
                if channel_type == "private":
                    await asyncio.sleep(0.5)

                async with websockets.connect(url, **connect_kwargs) as ws:
                    log.info(f"WebSocket [{channel_type}] connected: {url}")
                    self._reconnect_count = 0 # 连接成功，重置计数
                    if channel_type == "public":
                        self._public_ws = ws
                    else:
                        self._private_ws = ws
                        await self._authenticate(ws)

                    # 恢复订阅
                    for sub in self._subscriptions.get(channel_type, []):
                        await ws.send(json.dumps(sub))

                    # 消息循环
                    async for raw in ws:
                        if not self._running: break
                        await self._handle_message(raw, channel_type)

            except Exception as e:
                if not self._running: break
                
                err_msg = str(e)
                # 如果是验证类错误，直接终止该通道
                if any(code in err_msg for code in ["60024", "60011", "50101"]):
                    log.error(f"WebSocket [{channel_type}] 权限/环境错误: {err_msg}。停止重连。")
                    break

                self._reconnect_count += 1
                if self._reconnect_count > 5:
                    log.critical(f"WebSocket [{channel_type}] 连续多次失败，放弃重连。")
                    break

                wait = min(WS_RECONNECT_INTERVAL * (2 ** (self._reconnect_count - 1)), 30)
                log.warning(f"WebSocket [{channel_type}] 异常: {e}，将在 {wait}s 后重试 ({self._reconnect_count}/5)")
                await asyncio.sleep(wait)
            finally:
                if channel_type == "public": self._public_ws = None
                else: self._private_ws = None

    async def _authenticate(self, ws):
        """私有频道登录"""
        ts = str(int(time.time()))
        sign = base64.b64encode(
            hmac.new(
                self.secret.encode(),
                (ts + "GET" + "/users/self/verify").encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        await ws.send(json.dumps({
            "op": "login",
            "args": [{"apiKey": self.api_key, "passphrase": self.passphrase,
                       "timestamp": ts, "sign": sign}],
        }))

    async def _handle_message(self, raw: str, channel_type: str):
        msg = json.loads(raw)
        # 心跳 pong
        if msg == "pong":
            return
        # 订阅确认
        if "event" in msg and msg["event"] in ("subscribe", "login"):
            log.debug(f"WS event: {msg}")
            return
        # 错误
        if msg.get("event") == "error":
            # 捕获身份验证错误 (Passphrase 错误)
            if msg.get("code") == "60024" or "Wrong passphrase" in msg.get("msg", ""):
                 log.critical(f"WebSocket [{channel_type}] 身份验证失败: Passphrase 错误。已停止自动重连，请更新 API 配置并重启程序。")
                 self._running = False
                 # 注意：这里不能简单的 return，需要抛出异常让外层循环感知并停止
                 raise Exception(f"Authentication failed: {msg.get('msg')}")
            log.error(f"WS error: {msg}")
            return
        # 数据推送
        if "data" in msg and self.on_message:
            arg = msg.get("arg", {})
            channel = arg.get("channel", "")
            try:
                await self.on_message(channel, msg["data"], arg)
            except Exception as e:
                log.error(f"on_message error: {e}")

    # ----------------------------------------------------------
    # 订阅
    # ----------------------------------------------------------
    async def subscribe_ticker(self, symbol: str):
        """订阅实时 Ticker"""
        sub = {"op": "subscribe", "args": [{"channel": "tickers", "instId": symbol}]}
        self._subscriptions["public"].append(sub)
        # 兼容处理 websockets 14.0+，使用 .state == 1 代替 .open 或 .closed
        conn_open = self._public_ws and getattr(self._public_ws, "state", None) == 1
        if not conn_open:
            # 兼容旧版本
            conn_open = self._public_ws and getattr(self._public_ws, "open", False)

        if conn_open:
            await self._public_ws.send(json.dumps(sub))

    async def subscribe_depth(self, symbol: str):
        """订阅深度 (5档)"""
        sub = {"op": "subscribe", "args": [{"channel": "books5", "instId": symbol}]}
        # 避免重复添加
        if sub not in self._subscriptions["public"]:
            self._subscriptions["public"].append(sub)
        
        # 兼容处理 websockets 14.0+
        conn_open = self._public_ws and getattr(self._public_ws, "state", None) == 1
        if not conn_open:
            conn_open = self._public_ws and getattr(self._public_ws, "open", False)

        if conn_open:
            await self._public_ws.send(json.dumps(sub))
            log.info(f"Subscribed depth for {symbol}")

    async def subscribe_candle(self, symbol: str, bar: str = "1m"):
        """订阅 K 线"""
        sub = {"op": "subscribe", "args": [{"channel": f"candle{bar}", "instId": symbol}]}
        self._subscriptions["public"].append(sub)
        
        # 兼容处理 websockets 14.0+
        conn_open = self._public_ws and getattr(self._public_ws, "state", None) == 1
        if not conn_open:
            conn_open = self._public_ws and getattr(self._public_ws, "open", False)

        if conn_open:
            await self._public_ws.send(json.dumps(sub))

    async def subscribe_orders(self):
        """订阅订单状态 (私有)"""
        sub = {"op": "subscribe", "args": [{"channel": "orders", "instType": "SWAP"}]}
        self._subscriptions["private"].append(sub)
        if self._private_ws and self._private_ws.open:
            await self._private_ws.send(json.dumps(sub))

    async def subscribe_positions(self):
        """订阅持仓变化 (私有)"""
        sub = {"op": "subscribe", "args": [{"channel": "positions", "instType": "SWAP"}]}
        self._subscriptions["private"].append(sub)
        if self._private_ws and self._private_ws.open:
            await self._private_ws.send(json.dumps(sub))
