"""
OKX 交易助手 - OKX API Mock (联调测试用)
模拟 OKX REST/WebSocket 响应，用于本地集成测试
"""
import json
import time
import asyncio
from typing import Optional


class MockOKXRestResponse:
    """模拟 OKX REST API 响应"""

    # 账户余额
    BALANCE = {
        "code": "0", "msg": "", "data": [{
            "totalEq": "10000.00",
            "details": [
                {"ccy": "USDT", "availBal": "5000.00", "frozenBal": "0",
                 "eqUsd": "10000.00"}
            ]
        }]
    }

    # 持仓
    POSITIONS_EMPTY = {"code": "0", "msg": "", "data": []}

    @staticmethod
    def position(symbol="BTC-USDT-SWAP", direction="long", qty=1, avg_px=50000, upl=100):
        return {
            "code": "0", "msg": "", "data": [{
                "instId": symbol,
                "posSide": direction,
                "pos": str(qty),
                "avgPx": str(avg_px),
                "markPx": str(avg_px * 1.01),
                "upl": str(upl),
                "lever": "3",
                "margin": str(avg_px * qty / 3),
            }]
        }

    # 下单成功
    @staticmethod
    def order_ok(order_id="ord_123456"):
        return {
            "code": "0", "msg": "",
            "data": [{"ordId": order_id, "sCode": "0", "sMsg": ""}]
        }

    # 条件单 (止损) 成功
    @staticmethod
    def algo_order_ok(algo_id="algo_789"):
        return {
            "code": "0", "msg": "",
            "data": [{"algoId": algo_id, "sCode": "0", "sMsg": ""}]
        }

    # 撤单成功
    CANCEL_OK = {"code": "0", "msg": "", "data": [{"ordId": "", "sCode": "0", "sMsg": ""}]}

    # 条件单撤单成功
    CANCEL_ALGO_OK = {"code": "0", "msg": "", "data": [{"algoId": "", "sCode": "0", "sMsg": ""}]}

    # 挂单列表
    @staticmethod
    def pending_orders(orders=None):
        return {"code": "0", "msg": "", "data": orders or []}

    # Ticker
    @staticmethod
    def ticker(symbol="BTC-USDT-SWAP", price=50000):
        return {
            "code": "0", "msg": "", "data": [{
                "instId": symbol,
                "last": str(price),
                "lastSz": "1",
                "askPx": str(price + 1),
                "bidPx": str(price - 1),
                "open24h": str(price * 0.98),
                "high24h": str(price * 1.05),
                "low24h": str(price * 0.95),
                "vol24h": "1234567",
                "ts": str(int(time.time() * 1000)),
            }]
        }

    # 合约列表
    INSTRUMENTS = {
        "code": "0", "msg": "", "data": [
            {"instId": "BTC-USDT-SWAP", "instType": "SWAP", "uly": "BTC-USDT",
             "ctVal": "0.01", "ctMult": "1", "settleCcy": "USDT"},
            {"instId": "ETH-USDT-SWAP", "instType": "SWAP", "uly": "ETH-USDT",
             "ctVal": "0.1", "ctMult": "1", "settleCcy": "USDT"},
            {"instId": "SOL-USDT-SWAP", "instType": "SWAP", "uly": "SOL-USDT",
             "ctVal": "1", "ctMult": "1", "settleCcy": "USDT"},
        ]
    }

    # 杠杆设置
    SET_LEVERAGE_OK = {"code": "0", "msg": "", "data": [{"instId": "", "lever": "3", "mgnMode": "cross"}]}

    # 历史成交
    FILLS_HISTORY = {
        "code": "0", "msg": "", "data": [{
            "instId": "BTC-USDT-SWAP",
            "tradeId": "t_001",
            "ordId": "ord_001",
            "clOrdId": "",
            "fillPx": "50000",
            "fillSz": "1",
            "side": "buy",
            "posSide": "long",
            "fee": "-0.5",
            "ts": str(int(time.time() * 1000)),
        }]
    }

    # 错误响应
    ERROR_AUTH = {"code": "50111", "msg": "Invalid API Key"}
    ERROR_RATE_LIMIT = {"code": "50011", "msg": "Rate limit exceeded"}
    ERROR_INSUFFICIENT = {"code": "51008", "msg": "Insufficient balance"}
    ERROR_ORDER = {"code": "51000", "msg": "Order placement failed"}


class MockOKXWebSocketMessages:
    """模拟 OKX WebSocket 推送消息"""

    @staticmethod
    def ticker_msg(symbol="BTC-USDT-SWAP", price=50000):
        return json.dumps({
            "arg": {"channel": "tickers", "instId": symbol},
            "data": [{
                "instId": symbol,
                "last": str(price),
                "ts": str(int(time.time() * 1000)),
            }]
        })

    @staticmethod
    def order_msg(symbol="BTC-USDT-SWAP", state="filled", side="buy", pos_side="long"):
        return json.dumps({
            "arg": {"channel": "orders", "instType": "SWAP"},
            "data": [{
                "instId": symbol,
                "ordId": "ord_123",
                "state": state,
                "side": side,
                "posSide": pos_side,
                "sz": "1",
                "avgPx": "50000",
                "ts": str(int(time.time() * 1000)),
            }]
        })

    @staticmethod
    def position_msg(symbol="BTC-USDT-SWAP", direction="long", qty=1, upl=100):
        return json.dumps({
            "arg": {"channel": "positions", "instType": "SWAP"},
            "data": [{
                "instId": symbol,
                "posSide": direction,
                "pos": str(qty),
                "avgPx": "50000",
                "upl": str(upl),
            }]
        })

    @staticmethod
    def login_ok():
        return json.dumps({"event": "login", "code": "0", "msg": ""})

    @staticmethod
    def subscribe_ok(channel="tickers", symbol="BTC-USDT-SWAP"):
        return json.dumps({"event": "subscribe", "arg": {"channel": channel, "instId": symbol}})

    PONG = "pong"
