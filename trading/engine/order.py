"""
OKX 交易助手 - 订单管理引擎
"""
import asyncio
import time
import uuid
from typing import Optional

from trading.api.okx_rest import OKXRestClient
from trading.api.okx_ws import OKXWebSocket
from trading.data.database import Database
from trading.core.settings import Settings
from trading.core.logger import log
from trading.engine.splitter import split_order
from trading.engine.stoploss import StoplossEngine, calc_weighted_avg_price
from trading.config import POSITION_TIER_1, POSITION_TIER_2, POSITION_TIER_3, POSITION_MIN_BALANCE


class OrderEngine:
    """
    订单执行引擎
    - 极速下单 (限价单)
    - 智能拆单
    - 加仓计算
    - 一键全平 (双通道并发)
    """

    def __init__(self, rest: OKXRestClient, ws: OKXWebSocket,
                 db: Database, settings: Settings, sl_engine: StoplossEngine):
        self.rest = rest
        self.ws = ws
        self.db = db
        self.settings = settings
        self.sl_engine = sl_engine

    # ==========================================================
    # 下单
    # ==========================================================
    async def place_order(self, symbol: str, direction: str, price: float,
                           quantity: float, notional_usdt: float,
                           position_tier: str = "first",
                           order_type: str = "limit") -> dict:
        """
        执行下单（含拆单逻辑）
        direction: long / short
        order_type: limit / market
        """
        side = "buy" if direction == "long" else "sell"
        t0 = time.monotonic()

        # 拆单 (市价单通常不需要拆单逻辑，但这里为了保持一致性保持原样。如果市价单也不想记录 px，需要调整 rest 调用)
        # 注意: OKX 市价单不需要 px
        sub_orders = split_order(
            symbol, side, direction, quantity, price, notional_usdt, self.settings
        )

        results = []
        for so in sub_orders:
            client_id = f"t{uuid.uuid4().hex[:16]}"
            px_val = str(so.price) if order_type == "limit" else None
            r = await self.rest.place_order(
                symbol=so.symbol,
                side=so.side,
                pos_side=so.pos_side,
                order_type=order_type,
                sz=str(int(so.quantity)),
                px=px_val,
                client_order_id=client_id,
            )
            results.append(r)

        latency = (time.monotonic() - t0) * 1000

        # 检查所有子单是否成功
        failed_orders = [r for r in results if r.get("code") != "0"]
        if failed_orders:
            error_msgs = [r.get("msg", "unknown") for r in failed_orders]
            log.error(f"下单失败: {symbol} {direction} - {'; '.join(error_msgs)}")
            self.db.log("order", {
                "action": "place_failed",
                "symbol": symbol,
                "direction": direction,
                "errors": error_msgs,
            }, symbol=symbol, result="fail")
            return {"error": f"下单失败: {'; '.join(error_msgs)}"}

        # 记录成交（所有子单成功才写本地）
        okx_order_id = None
        if results and results[0].get("data"):
            okx_order_id = results[0]["data"][0].get("ordId")

        trade_id = self.db.insert_trade(
            order_id=okx_order_id,
            symbol=symbol,
            side=side,
            direction=direction,
            price=price,
            quantity=quantity,
            notional=notional_usdt,
            leverage=self._get_leverage(direction),
            position_tier=position_tier,
            open_price=price,
            status="open",
        )

        # 常用币种记录
        self.db.touch_favorite(symbol)

        self.db.log("order", {
            "action": "place",
            "symbol": symbol,
            "direction": direction,
            "price": price,
            "quantity": quantity,
            "sub_orders": len(sub_orders),
            "latency_ms": latency,
        }, symbol=symbol, latency_ms=latency, result="success")

        log.info(f"下单完成: {symbol} {direction} {quantity}张@{price} ({latency:.1f}ms)")
        return {"trade_id": trade_id, "okx_order_id": okx_order_id,
                "sub_orders": len(sub_orders), "latency_ms": latency}

    # ==========================================================
    # 加仓
    # ==========================================================
    async def add_position(self, symbol: str, direction: str, current_price: float) -> dict:
        """
        加仓逻辑
        - 读取当前持仓
        - 计算加仓数量 (25%)
        - 更新止损
        """
        # 查账户余额
        balance_resp = await self.rest.get_balance()
        available = 0
        if balance_resp.get("code") == "0" and balance_resp.get("data"):
            details = balance_resp["data"][0].get("details", [])
            for d in details:
                if d.get("ccy") == "USDT":
                    available = float(d.get("availBal", 0))
                    break

        # 查当前持仓
        pos_resp = await self.rest.get_positions()
        existing_qty = 0
        existing_price = 0
        if pos_resp.get("code") == "0" and pos_resp.get("data"):
            for p in pos_resp["data"]:
                if p.get("instId") == symbol and p.get("posSide") == direction:
                    existing_qty = abs(float(p.get("pos", 0)))
                    existing_price = float(p.get("avgPx", 0))
                    break

        # 确定加仓档位
        existing_trades = self.db.get_open_trades(symbol)
        tier_counts = [t["position_tier"] for t in existing_trades]
        if "add1" not in tier_counts:
            position_tier = "add1"
            ratio = POSITION_TIER_2  # 25%
        elif "add2" not in tier_counts:
            position_tier = "add2"
            ratio = POSITION_TIER_3  # 25%
        else:
            return {"error": "已满仓，无法继续加仓"}

        # 计算加仓数量
        leverage = self._get_leverage(direction)
        add_usdt = available * ratio
        add_qty = int(add_usdt * leverage / current_price)
        if add_qty <= 0:
            return {"error": "可用余额不足"}

        notional = add_qty * current_price / leverage

        # 下单
        result = await self.place_order(
            symbol, direction, current_price, add_qty, notional, position_tier
        )

        # 更新止损
        new_total = existing_qty + add_qty
        new_avg = calc_weighted_avg_price(existing_qty, existing_price, add_qty, current_price)

        old_sl = self.db.get_active_stoploss(symbol)
        sl_result = await self.sl_engine.update_stoploss(
            symbol, direction, new_avg, new_total,
            old_sl_id=old_sl["id"] if old_sl else None,
        )

        result["new_avg_price"] = new_avg
        result["new_stoploss"] = sl_result
        return result

    # ==========================================================
    # 一键全平
    # ==========================================================
    async def close_all(self) -> list[dict]:
        """
        一键全平
        1. 查询所有持仓
        2. 对每个持仓: 限价单 -> 超时撤单 -> 市价单
        3. REST + WebSocket 双通道并发
        """
        pos_resp = await self.rest.get_positions()
        if pos_resp.get("code") != "0":
            return [{"error": "查询持仓失败"}]

        positions = [p for p in pos_resp.get("data", []) if float(p.get("pos", 0)) != 0]
        if not positions:
            return [{"info": "无持仓"}]

        timeout = self.settings.get("limit_to_market_sec")
        results = []

        for pos in positions:
            symbol = pos["instId"]
            direction = pos["posSide"]
            qty = abs(float(pos["pos"]))
            close_side = "sell" if direction == "long" else "buy"

            # 获取当前价格
            price = self.ws.get_last_price(symbol)
            if price is None:
                ticker = await self.rest.get_ticker(symbol)
                price = float(ticker["data"][0]["last"]) if ticker.get("code") == "0" else 0

            r = await self._close_position_with_timeout(
                symbol, direction, close_side, qty, price, timeout
            )
            results.append(r)

        return results

    async def _close_position_with_timeout(self, symbol: str, direction: str,
                                            close_side: str, qty: float,
                                            price: float, timeout: float) -> dict:
        """单个持仓平仓：限价 -> 超时 -> 市价"""
        t0 = time.monotonic()

        # 1. 限价平仓
        order_result = await self.rest.place_order(
            symbol=symbol,
            side=close_side,
            pos_side=direction,
            order_type="limit",
            sz=str(int(qty)),
            px=str(price),
            reduce_only=True,
        )

        order_id = None
        if order_result.get("code") == "0" and order_result.get("data"):
            order_id = order_result["data"][0].get("ordId")

        # 2. 等待超时
        await asyncio.sleep(timeout)

        # 3. 检查是否已成交
        pending = await self.rest.get_pending_orders()
        still_pending = False
        if pending.get("code") == "0":
            for o in pending.get("data", []):
                if o.get("ordId") == order_id:
                    still_pending = True
                    break

        # 4. 超时未成交 -> 撤单 + 市价强平
        if still_pending and order_id:
            await self.rest.cancel_order(symbol, order_id)
            market_result = await self.rest.place_order(
                symbol=symbol,
                side=close_side,
                pos_side=direction,
                order_type="market",
                sz=str(int(qty)),
                reduce_only=True,
            )
            latency = (time.monotonic() - t0) * 1000
            self.db.log("close", {
                "symbol": symbol, "direction": direction,
                "limit_order_id": order_id, "fallback": "market",
            }, symbol=symbol, latency_ms=latency, result="success")
            # 更新本地交易记录
            self._close_local_trades(symbol, direction, price)
            return {"symbol": symbol, "method": "limit->market", "latency_ms": latency}

        latency = (time.monotonic() - t0) * 1000
        self.db.log("close", {
            "symbol": symbol, "direction": direction, "order_id": order_id,
        }, symbol=symbol, latency_ms=latency, result="success")
        # 更新本地交易记录
        self._close_local_trades(symbol, direction, price)
        return {"symbol": symbol, "method": "limit", "latency_ms": latency}

    def _close_local_trades(self, symbol: str, direction: str, close_price: float):
        """平仓后更新本地交易记录状态"""
        from datetime import datetime
        open_trades = self.db.fetchall(
            "SELECT * FROM trade_records WHERE symbol=? AND direction=? AND status='open'",
            (symbol, direction),
        )
        for trade in open_trades:
            # 计算盈亏
            entry_price = trade.get("open_price") or trade.get("price", 0)
            qty = trade.get("quantity", 0)
            leverage = trade.get("leverage", 1)
            if direction == "long":
                pnl = (close_price - entry_price) * qty * leverage
            else:
                pnl = (entry_price - close_price) * qty * leverage
            self.db.update_trade(
                trade["id"],
                status="closed",
                pnl=round(pnl, 2),
                closed_at=datetime.utcnow().isoformat(),
            )
        if open_trades:
            log.info(f"本地记录已更新: {symbol} {direction} {len(open_trades)} 笔已关闭")

    # ==========================================================
    # 工具
    # ==========================================================
    def _get_leverage(self, direction: str) -> int:
        if direction == "long":
            return self.settings.get("leverage_long")
        return self.settings.get("leverage_short")
