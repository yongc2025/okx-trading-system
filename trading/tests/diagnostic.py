"""
OKX 交易助手 - 诊断工具
连接健康检查、延迟测试、状态报告
"""
import sys
import time
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trading.config import OKX_REST_BASE, OKX_WS_PUBLIC, TARGET_ORDER_LATENCY_MS
from trading.core.logger import log


async def check_rest_latency(rest_client, rounds: int = 10) -> dict:
    """REST API 延迟测试"""
    latencies = []
    for _ in range(rounds):
        t0 = time.monotonic()
        try:
            resp = await rest_client.get_ticker("BTC-USDT-SWAP")
            latency = (time.monotonic() - t0) * 1000
            if resp.get("code") == "0":
                latencies.append(latency)
        except Exception as e:
            log.warning(f"REST 延迟测试异常: {e}")
        await asyncio.sleep(0.1)

    if not latencies:
        return {"status": "fail", "error": "所有请求失败"}

    avg = sum(latencies) / len(latencies)
    p50 = sorted(latencies)[len(latencies) // 2]
    p99 = sorted(latencies)[int(len(latencies) * 0.99)]
    return {
        "status": "ok",
        "avg_ms": round(avg, 1),
        "p50_ms": round(p50, 1),
        "p99_ms": round(p99, 1),
        "min_ms": round(min(latencies), 1),
        "max_ms": round(max(latencies), 1),
        "success_rate": f"{len(latencies)}/{rounds}",
        "target_met": avg < TARGET_ORDER_LATENCY_MS * 5,  # 查询延迟目标宽松些
    }


async def check_account(rest_client) -> dict:
    """账户状态检查"""
    balance = await rest_client.get_balance()
    positions = await rest_client.get_positions()

    if balance.get("code") != "0":
        return {"status": "fail", "error": balance.get("msg", "unknown")}

    total_eq = 0
    available = 0
    for d in balance.get("data", []):
        total_eq = float(d.get("totalEq", 0))
        for detail in d.get("details", []):
            if detail.get("ccy") == "USDT":
                available = float(detail.get("availBal", 0))

    pos_count = 0
    total_upl = 0
    if positions.get("code") == "0":
        for p in positions.get("data", []):
            if float(p.get("pos", 0)) != 0:
                pos_count += 1
                total_upl += float(p.get("upl", 0))

    return {
        "status": "ok",
        "total_equity_usdt": round(total_eq, 2),
        "available_usdt": round(available, 2),
        "open_positions": pos_count,
        "total_unrealized_pnl": round(total_upl, 2),
    }


async def check_websocket(ws_client) -> dict:
    """WebSocket 连接检查"""
    if not ws_client:
        return {"status": "not_initialized"}
    return {
        "status": "ok" if ws_client.connected else "disconnected",
        "connected": ws_client.connected,
    }


async def full_diagnostic(rest_client=None, ws_client=None, db=None) -> dict:
    """完整诊断报告"""
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "api_base": OKX_REST_BASE,
    }

    # REST
    if rest_client:
        report["rest_latency"] = await check_rest_latency(rest_client, rounds=5)
        report["account"] = await check_account(rest_client)
    else:
        report["rest_latency"] = {"status": "not_initialized"}
        report["account"] = {"status": "not_initialized"}

    # WebSocket
    report["websocket"] = await check_websocket(ws_client)

    # 数据库
    if db:
        try:
            trade_count = db.fetchone("SELECT COUNT(*) as cnt FROM trade_records")["cnt"]
            log_count = db.fetchone("SELECT COUNT(*) as cnt FROM trade_logs")["cnt"]
            sl_count = db.fetchone("SELECT COUNT(*) as cnt FROM stoploss_orders WHERE status='active'")["cnt"]
            report["database"] = {
                "status": "ok",
                "total_trades": trade_count,
                "total_logs": log_count,
                "active_stoplosses": sl_count,
            }
        except Exception as e:
            report["database"] = {"status": "error", "error": str(e)}
    else:
        report["database"] = {"status": "not_initialized"}

    return report


def print_report(report: dict):
    """打印诊断报告"""
    print("=" * 50)
    print(f"OKX 交易助手 - 诊断报告")
    print(f"时间: {report.get('timestamp', '?')}")
    print(f"API:  {report.get('api_base', '?')}")
    print("=" * 50)

    # REST
    rest = report.get("rest_latency", {})
    if rest.get("status") == "ok":
        met = "✅" if rest["target_met"] else "⚠️"
        print(f"\n📡 REST API 延迟:")
        print(f"   平均: {rest['avg_ms']}ms | P50: {rest['p50_ms']}ms | P99: {rest['p99_ms']}ms")
        print(f"   范围: {rest['min_ms']}ms ~ {rest['max_ms']}ms")
        print(f"   成功率: {rest['success_rate']}")
        print(f"   目标达标: {met}")
    else:
        print(f"\n📡 REST API: ❌ {rest.get('error', '未初始化')}")

    # 账户
    acct = report.get("account", {})
    if acct.get("status") == "ok":
        print(f"\n💰 账户:")
        print(f"   总权益: {acct['total_equity_usdt']} USDT")
        print(f"   可用:   {acct['available_usdt']} USDT")
        print(f"   持仓数: {acct['open_positions']}")
        print(f"   浮盈:   {acct['total_unrealized_pnl']} USDT")
    else:
        print(f"\n💰 账户: ❌ {acct.get('error', '未初始化')}")

    # WebSocket
    ws = report.get("websocket", {})
    status = "✅ 已连接" if ws.get("connected") else "❌ 未连接"
    print(f"\n🔌 WebSocket: {status}")

    # 数据库
    db_info = report.get("database", {})
    if db_info.get("status") == "ok":
        print(f"\n💾 数据库:")
        print(f"   交易记录: {db_info['total_trades']}")
        print(f"   操作日志: {db_info['total_logs']}")
        print(f"   活跃止损: {db_info['active_stoplosses']}")
    else:
        print(f"\n💾 数据库: ❌ {db_info.get('error', '未初始化')}")

    print()


if __name__ == "__main__":
    print("独立运行模式 - 请通过 app.py 启动后访问 /api/diagnostic 获取诊断报告")
    print("或在已连接的状态下调用 full_diagnostic(rest_client, ws_client, db)")
