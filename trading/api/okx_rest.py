"""
OKX 交易助手 - REST API 客户端
"""
import time
import hmac
import hashlib
import base64
from datetime import datetime, timezone
from typing import Optional
import httpx

from trading.config import OKX_REST_BASE, OKX_REST_DEMO, PROXY_URL
from trading.core.logger import log


class OKXRestClient:
    """OKX REST API 封装 (同步 + 异步)"""

    def __init__(self, api_key: str, secret: str, passphrase: str, is_demo: bool = False):
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase
        self.is_demo = is_demo
        self.base_url = OKX_REST_DEMO if is_demo else OKX_REST_BASE
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # 配置代理
            proxy = None
            if PROXY_URL:
                proxy = PROXY_URL
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(10.0, connect=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                proxy=proxy
            )
        return self._client

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """生成 OKX API 签名"""
        message = timestamp + method.upper() + path + body
        mac = hmac.new(
            self.secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode("ascii")

    async def _request(self, method: str, path: str, params: Optional[dict] = None, body: Optional[dict] = None) -> dict:
        """发送 REST 请求 (带自动时间戳格式化)"""
        client = await self._get_client()
        
        # OKX 推荐使用 ISO 8601 格式: 2020-12-08T09:08:49.070Z
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        
        body_str = ""
        if body:
            import json
            body_str = json.dumps(body)

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": self._sign(timestamp, method, path, body_str),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if "pap" in self.base_url or "test网" in self.base_url: # 或者是根据 is_demo 判断
             # 如果是模拟盘环境，有时需要额外 header，虽然大部分时间自动识别
             pass

    def _headers(self, method: str, path: str, body: str = "") -> dict:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        sign = self._sign(ts, method, path, body)
        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        # 如果当前实例被标记为 demo (由 OKXRestClient 构造函数设置)，则加上这个 Header
        if hasattr(self, 'is_demo') and self.is_demo:
            headers["x-simulated-trading"] = "1"
        return headers

    async def _request(self, method: str, path: str, params: dict = None, data: dict = None) -> dict:
        client = await self._get_client()
        body = ""
        if data:
            import json
            body = json.dumps(data)

        headers = self._headers(method, path + ("?" + self._urlencode(params) if params else ""), body)

        t0 = time.monotonic()
        if method == "GET":
            resp = await client.get(path, params=params, headers=headers)
        else:
            resp = await client.post(path, content=body, headers=headers)
        latency = (time.monotonic() - t0) * 1000

        result = resp.json()
        if result.get("code") != "0":
            log.error(f"OKX API error: {path} -> {result} ({latency:.1f}ms)")
        return result

    @staticmethod
    def _urlencode(params: dict) -> str:
        if not params:
            return ""
        from urllib.parse import urlencode
        return urlencode({k: v for k, v in params.items() if v is not None})

    # ==========================================================
    # 行情接口 (公开)
    # ==========================================================
    async def get_ticker(self, symbol: str) -> dict:
        """获取实时最新价格"""
        return await self._request("GET", "/api/v5/market/ticker", {"instId": symbol})

    async def get_candles(self, symbol: str, bar: str = "1m", limit: int = 100, after: str = None) -> dict:
        """获取 K 线数据"""
        params = {"instId": symbol, "bar": bar, "limit": str(limit)}
        if after:
            params["after"] = after
        return await self._request("GET", "/api/v5/market/candles", params)

    async def get_history_candles(self, symbol: str, bar: str = "1m", limit: int = 100,
                                   after: str = None, before: str = None) -> dict:
        """获取历史 K 线"""
        params = {"instId": symbol, "bar": bar, "limit": str(limit)}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return await self._request("GET", "/api/v5/market/history-candles", params)

    async def get_instruments(self, inst_type: str = "SWAP") -> dict:
        """获取合约品种列表"""
        return await self._request("GET", "/api/v5/public/instruments", {"instType": inst_type})

    async def get_books(self, symbol: str, sz: int = 20) -> dict:
        """获取深度数据"""
        return await self._request("GET", "/api/v5/market/books", {"instId": symbol, "sz": str(sz)})
        return await self._request("GET", "/api/v5/public/instruments", {"instType": inst_type})

    # ==========================================================
    # 交易接口 (需鉴权)
    # ==========================================================
    async def place_order(self, symbol: str, side: str, pos_side: str,
                          order_type: str, sz: str, px: str = None,
                          reduce_only: bool = False, client_order_id: str = None) -> dict:
        """
        下单
        side: buy / sell
        pos_side: long / short (双向持仓模式)
        order_type: limit / market
        sz: 张数
        px: 限价价格 (限价单必填)
        """
        data = {
            "instId": symbol,
            "tdMode": "cross",  # 全仓模式
            "side": side,
            "posSide": pos_side,
            "ordType": order_type,
            "sz": str(sz),
        }
        if px is not None:
            data["px"] = str(px)
        if reduce_only:
            data["reduceOnly"] = True
        if client_order_id:
            data["clOrdId"] = client_order_id
        return await self._request("POST", "/api/v5/trade/order", data=data)

    async def place_algo_order(self, symbol: str, side: str, pos_side: str,
                                sz: str, trigger_px: str, order_px: str = "-1") -> dict:
        """
        条件单 (止损)
        trigger_px: 触发价
        order_px: "-1" = 市价执行
        """
        data = {
            "instId": symbol,
            "tdMode": "cross",
            "side": side,
            "posSide": pos_side,
            "ordType": "conditional",
            "sz": str(sz),
            "triggerPx": str(trigger_px),
            "triggerPxType": "last",
            "orderPx": order_px,
        }
        return await self._request("POST", "/api/v5/trade/order-algo", data=data)

    async def cancel_algo_order(self, algo_ids: list[dict]) -> dict:
        """批量撤条件单"""
        return await self._request("POST", "/api/v5/trade/cancel-algos", data=algo_ids)

    async def cancel_order(self, symbol: str, order_id: str) -> dict:
        """撤单"""
        return await self._request("POST", "/api/v5/trade/cancel-order",
                                   data={"instId": symbol, "ordId": order_id})

    async def get_pending_orders(self, inst_type: str = "SWAP") -> dict:
        """查询挂单"""
        return await self._request("GET", "/api/v5/trade/orders-pending", {"instType": inst_type})

    # ==========================================================
    # 账户接口 (需鉴权)
    # ==========================================================
    async def get_balance(self, ccy: str = "USDT") -> dict:
        """查询账户余额"""
        return await self._request("GET", "/api/v5/account/balance", {"ccy": ccy})

    async def get_positions(self, inst_type: str = "SWAP") -> dict:
        """查询当前持仓"""
        return await self._request("GET", "/api/v5/account/positions", {"instType": inst_type})

    async def set_leverage(self, symbol: str, leverage: int, pos_side: str = "") -> dict:
        """设置杠杆"""
        data = {"instId": symbol, "lever": str(leverage), "mgnMode": "cross"}
        if pos_side:
            data["posSide"] = pos_side
        return await self._request("POST", "/api/v5/account/set-leverage", data=data)

    async def get_fills_history(self, inst_type: str = "SWAP", limit: int = 100) -> dict:
        """查询历史成交"""
        return await self._request("GET", "/api/v5/trade/fills-history",
                                   {"instType": inst_type, "limit": str(limit)})

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
