"""
OKX 交易助手 - 持仓管理器
"""
import asyncio
from typing import Optional
from datetime import datetime

from trading.api.okx_rest import OKXRestClient
from trading.data.database import Database
from trading.core.logger import log


class PositionManager:
    """
    持仓管理
    - 实时持仓同步
    - 浮盈浮亏快照
    - 持仓状态刷新
    """

    def __init__(self, rest: OKXRestClient, db: Database):
        self.rest = rest
        self.db = db
        self._positions: dict[str, dict] = {}  # symbol+direction -> position

    async def sync_positions(self):
        """从 OKX 同步最新持仓到内存"""
        resp = await self.rest.get_positions()
        if resp.get("code") != "0":
            log.error(f"同步持仓失败: {resp}")
            return

        self._positions.clear()
        for p in resp.get("data", []):
            qty = float(p.get("pos", 0))
            if qty == 0:
                continue
            key = f"{p['instId']}_{p['posSide']}"
            self._positions[key] = {
                "symbol": p["instId"],
                "direction": p["posSide"],
                "quantity": abs(qty),
                "avg_price": float(p.get("avgPx", 0)),
                "mark_price": float(p.get("markPx", 0)),
                "unrealized_pnl": float(p.get("upl", 0)),
                "leverage": int(p.get("lever", 1)),
                "margin": float(p.get("margin", 0)),
            }
        return list(self._positions.values())

    def get_position(self, symbol: str, direction: str = None) -> Optional[dict]:
        """获取指定持仓"""
        if direction:
            return self._positions.get(f"{symbol}_{direction}")
        # 查两个方向
        for d in ("long", "short"):
            p = self._positions.get(f"{symbol}_{d}")
            if p:
                return p
        return None

    def get_all_positions(self) -> list[dict]:
        return list(self._positions.values())

    async def take_snapshots(self):
        """对所有持仓记录浮盈浮亏快照"""
        positions = await self.sync_positions()
        if not positions:
            return

        for p in positions:
            ratio = 0
            if p["avg_price"] > 0:
                if p["direction"] == "long":
                    ratio = (p["mark_price"] - p["avg_price"]) / p["avg_price"]
                else:
                    ratio = (p["avg_price"] - p["mark_price"]) / p["avg_price"]

            self.db.insert_snapshot(
                symbol=p["symbol"],
                direction=p["direction"],
                entry_price=p["avg_price"],
                mark_price=p["mark_price"],
                quantity=p["quantity"],
                unrealized_pnl=p["unrealized_pnl"],
                unrealized_ratio=ratio,
            )

    def get_available_balance(self, balance_resp: dict) -> float:
        """从余额响应中提取可用 USDT"""
        if balance_resp.get("code") != "0":
            return 0
        for d in balance_resp.get("data", []):
            for detail in d.get("details", []):
                if detail.get("ccy") == "USDT":
                    return float(detail.get("availBal", 0))
        return 0
