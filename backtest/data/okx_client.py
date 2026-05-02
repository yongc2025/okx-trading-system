"""
OKX REST API 客户端 - 回测专用
轻量级、独立实现，不依赖 trading 模块
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class RateLimiter:
    """滑动窗口限速器（OKX 限制：20次/2秒）"""

    def __init__(self, max_requests: int = 20, window_seconds: float = 2.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """等待直到可以发送请求"""
        async with self._lock:
            now = time.monotonic()
            # 清除窗口外的旧时间戳
            self._timestamps = [
                ts for ts in self._timestamps if now - ts < self.window_seconds
            ]
            if len(self._timestamps) >= self.max_requests:
                # 计算需要等待的时间
                oldest = self._timestamps[0]
                wait_time = self.window_seconds - (now - oldest) + 0.05
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    now = time.monotonic()
                    self._timestamps = [
                        ts for ts in self._timestamps if now - ts < self.window_seconds
                    ]
            self._timestamps.append(time.monotonic())


class OKXClient:
    """回测专用 OKX API 客户端（独立于 trading 模块）"""

    BASE_URL = "https://www.okx.com"

    def __init__(
        self,
        api_key: str = "",
        secret: str = "",
        passphrase: str = "",
        is_demo: bool = True,
        proxy: Optional[str] = None,
    ):
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase
        self.is_demo = is_demo
        self._rate_limiter = RateLimiter(max_requests=20, window_seconds=2.0)
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            proxy=proxy,
            timeout=httpx.Timeout(30.0),
        )

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """生成 OKX API HMAC-SHA256 签名"""
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(signature.digest()).decode("utf-8")

    def _build_headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        """构建带签名的请求头"""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        headers: dict[str, str] = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": self._sign(timestamp, method, path, body),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if self.is_demo:
            headers["x-simulated-trading"] = "1"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        signed: bool = False,
    ) -> dict[str, Any]:
        """发送 HTTP 请求，自动限速"""
        await self._rate_limiter.acquire()

        # 构建查询字符串用于签名
        query_string = ""
        if params:
            query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
            full_path = f"{path}?{query_string}"
        else:
            full_path = path

        headers: dict[str, str] = {}
        if signed and self.api_key:
            headers = self._build_headers(method.upper(), full_path)

        try:
            response = await self._client.request(
                method=method,
                url=full_path,
                headers=headers,
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except httpx.TimeoutException as e:
            raise ConnectionError(f"OKX API 请求超时: {e}") from e
        except httpx.HTTPStatusError as e:
            raise ConnectionError(f"OKX API HTTP 错误 {e.response.status_code}: {e.response.text}") from e
        except Exception as e:
            raise ConnectionError(f"OKX API 请求失败: {e}") from e

        # 检查 OKX 业务错误码
        code = data.get("code", "0")
        if str(code) != "0":
            msg = data.get("msg", "") or data.get("data", "")
            raise ValueError(f"OKX API 错误 (code={code}): {msg}")

        return data

    async def connect(self) -> bool:
        """测试连接，通过签名接口验证 API 凭据是否有效"""
        try:
            # 使用需要签名的接口来验证凭据，而非公开接口
            result = await self._request("GET", "/api/v5/account/balance", signed=True)
            logger.info("OKX 连接成功，凭据验证通过")
            return True
        except Exception as e:
            logger.error(f"OKX 连接失败: {e}")
            return False

    async def get_instruments(self, inst_type: str = "SWAP") -> list[dict[str, Any]]:
        """获取合约品种列表
        
        Args:
            inst_type: 产品类型 SPOT/MARGIN/SWAP/FUTURES/OPTION
        """
        result = await self._request(
            "GET", "/api/v5/public/instruments", params={"instType": inst_type}
        )
        return result.get("data", [])

    async def get_history_candles(
        self,
        symbol: str,
        bar: str = "5m",
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> list[list[str]]:
        """获取历史 K 线数据

        Args:
            symbol: 交易对，如 "BTC-USDT-SWAP"
            bar: K 线周期，如 "1m","5m","15m","1H","4H","1D"
            limit: 返回条数，最大 100
            after: 分页参数，返回此时间戳之前的数据
            before: 分页参数，返回此时间戳之后的数据

        Returns:
            [[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm], ...]
        """
        params: dict[str, Any] = {
            "instId": symbol,
            "bar": bar,
            "limit": str(limit),
        }
        if after is not None:
            params["after"] = str(after)
        if before is not None:
            params["before"] = str(before)

        result = await self._request(
            "GET", "/api/v5/market/history-candles", params=params
        )
        return result.get("data", [])

    async def get_fills_history(
        self,
        inst_type: str = "SWAP",
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """获取历史成交记录

        Args:
            inst_type: 产品类型 SPOT/MARGIN/SWAP/FUTURES/OPTION
            limit: 返回条数，最大 100
            after: 分页参数
            before: 分页参数

        Returns:
            成交记录列表
        """
        params: dict[str, Any] = {
            "instType": inst_type,
            "limit": str(limit),
        }
        if after is not None:
            params["after"] = str(after)
        if before is not None:
            params["before"] = str(before)

        result = await self._request(
            "GET", "/api/v5/trade/fills-history", params=params, signed=True
        )
        return result.get("data", [])

    async def close(self) -> None:
        """关闭 HTTP 连接"""
        await self._client.aclose()
