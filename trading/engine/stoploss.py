"""
OKX 交易助手 - 止损引擎
"""
import asyncio
from typing import Optional

from trading.api.okx_rest import OKXRestClient
from trading.data.database import Database
from trading.core.settings import Settings
from trading.core.logger import log
from trading.config import STOPLOSS_PRICE_RATIO


def calc_stoploss_price(entry_price: float, direction: str) -> float:
    """
    计算止损价
    规则: 价格止损线 = 开仓价 × 10% (固定, 与杠杆无关)
    多单: 止损价 = 开仓价 × (1 - 0.10)
    空单: 止损价 = 开仓价 × (1 + 0.10)
    """
    if direction == "long":
        return round(entry_price * (1 - STOPLOSS_PRICE_RATIO), 8)
    else:
        return round(entry_price * (1 + STOPLOSS_PRICE_RATIO), 8)


def calc_weighted_avg_price(existing_qty: float, existing_price: float,
                             new_qty: float, new_price: float) -> float:
    """计算加权平均开仓价"""
    total_qty = existing_qty + new_qty
    if total_qty == 0:
        return new_price
    return (existing_qty * existing_price + new_qty * new_price) / total_qty


class StoplossEngine:
    """
    止损引擎
    - 开仓自动挂止损
    - 加仓后重算并重挂
    - 记录到本地数据库
    """

    def __init__(self, rest: OKXRestClient, db: Database, settings: Settings):
        self.rest = rest
        self.db = db
        self.settings = settings

    async def attach_stoploss(self, symbol: str, direction: str,
                               entry_price: float, quantity: float) -> dict:
        """
        为新开仓挂止损单
        """
        sl_price = calc_stoploss_price(entry_price, direction)

        # 平仓方向: 多单止损用 sell，空单止损用 buy
        close_side = "sell" if direction == "long" else "buy"

        result = await self.rest.place_algo_order(
            symbol=symbol,
            side=close_side,
            pos_side=direction,
            sz=str(quantity),
            trigger_px=str(sl_price),
            order_px="-1",  # 市价执行
        )

        okx_algo_id = None
        if result.get("code") == "0" and result.get("data"):
            okx_algo_id = result["data"][0].get("algoId")

        # 记录到数据库
        sl_id = self.db.insert_stoploss(
            symbol=symbol,
            direction=direction,
            trigger_price=sl_price,
            order_type="conditional_market",
            okx_order_id=okx_algo_id,
            status="active",
        )
        self.db.log("stoploss", {
            "action": "attach",
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "stoploss_price": sl_price,
            "quantity": quantity,
            "okx_algo_id": okx_algo_id,
        }, symbol=symbol, result="success" if okx_algo_id else "fail")

        log.info(f"止损挂单: {symbol} {direction} 止损价={sl_price} 数量={quantity}")
        return {"sl_id": sl_id, "stoploss_price": sl_price, "okx_algo_id": okx_algo_id}

    async def update_stoploss(self, symbol: str, direction: str,
                               new_avg_price: float, total_qty: float,
                               old_sl_id: int = None) -> dict:
        """
        加仓后更新止损
        1. 撤销旧止损单
        2. 以新加权均价重新计算止损价
        3. 挂新止损单
        """
        # 1. 撤旧单
        if old_sl_id:
            old_sl = self.db.fetchone(
                "SELECT * FROM stoploss_orders WHERE id=?", (old_sl_id,)
            )
            if old_sl and old_sl["okx_order_id"]:
                try:
                    await self.rest.cancel_algo_order([
                        {"instId": symbol, "algoId": old_sl["okx_order_id"]}
                    ])
                except Exception as e:
                    log.warning(f"撤旧止损单失败: {e}")
                self.db.update_stoploss(old_sl_id, status="replaced")

        # 2. 计算新止损价
        sl_price = calc_stoploss_price(new_avg_price, direction)

        # 3. 挂新单
        close_side = "sell" if direction == "long" else "buy"
        result = await self.rest.place_algo_order(
            symbol=symbol,
            side=close_side,
            pos_side=direction,
            sz=str(total_qty),
            trigger_px=str(sl_price),
        )

        okx_algo_id = None
        if result.get("code") == "0" and result.get("data"):
            okx_algo_id = result["data"][0].get("algoId")

        new_sl_id = self.db.insert_stoploss(
            symbol=symbol,
            direction=direction,
            trigger_price=sl_price,
            order_type="conditional_market",
            okx_order_id=okx_algo_id,
            status="active",
            parent_sl_id=old_sl_id,
        )

        self.db.log("stoploss", {
            "action": "update",
            "symbol": symbol,
            "new_avg_price": new_avg_price,
            "stoploss_price": sl_price,
            "total_qty": total_qty,
        }, symbol=symbol, result="success" if okx_algo_id else "fail")

        log.info(f"止损更新: {symbol} 新均价={new_avg_price} 新止损价={sl_price}")
        return {"sl_id": new_sl_id, "stoploss_price": sl_price, "okx_algo_id": okx_algo_id}
