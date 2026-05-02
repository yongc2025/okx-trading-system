"""
FastAPI Web 后端
"""
import json
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
import pandas as pd
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backtest.config import WEB_HOST, WEB_PORT, PKL_DATA_DIR, DB_PATH
from backtest.data.schema import init_database
from backtest.analysis.basic_stats import get_full_analysis
from backtest.analysis.hold_loss import get_holding_loss_analysis
from backtest.analysis.stoploss_sim import get_stoploss_analysis
from backtest.analysis.position_tier import get_position_tier_analysis
from backtest.analysis.extreme_scan import (
    scan_all_symbols, get_scan_results, get_scan_summary, export_scan_results_csv,
)
from backtest.models.database import get_trade_summary, get_symbol_list
import io

app = FastAPI(title="OKX 量化回测系统", version="1.0")

# 静态文件 & 模板
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 初始化数据库
init_database()


# ===== 页面路由 =====
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页 - 基础统计看板"""
    return templates.TemplateResponse(request, "index.html")


@app.get("/hold-loss", response_class=HTMLResponse)
async def hold_loss_page(request: Request):
    """扛单行为分析页"""
    return templates.TemplateResponse(request, "hold_loss.html")


@app.get("/stoploss", response_class=HTMLResponse)
async def stoploss_page(request: Request):
    """止损回测页"""
    return templates.TemplateResponse(request, "stoploss.html")


@app.get("/position", response_class=HTMLResponse)
async def position_page(request: Request):
    """仓位策略分析页"""
    return templates.TemplateResponse(request, "position.html")


@app.get("/scan", response_class=HTMLResponse)
async def scan_page(request: Request):
    """极端行情扫描页"""
    return templates.TemplateResponse(request, "scan.html")


@app.get("/data", response_class=HTMLResponse)
async def data_page(request: Request):
    """数据管理页"""
    return templates.TemplateResponse(request, "data.html")


@app.get("/orders", response_class=HTMLResponse)
async def orders_page(request: Request):
    """订单分析页"""
    return templates.TemplateResponse(request, "orders.html")


@app.get("/simulate", response_class=HTMLResponse)
async def simulate_page(request: Request):
    """模拟回测页"""
    return templates.TemplateResponse(request, "simulate.html")


@app.get("/optimize", response_class=HTMLResponse)
async def optimize_page(request: Request):
    """参数优化页"""
    return templates.TemplateResponse(request, "optimize.html")


# ===== 原有 API 路由 =====
@app.get("/api/summary")
async def api_summary():
    """交易概要"""
    return JSONResponse(get_trade_summary())


@app.get("/api/symbols")
async def api_symbols():
    """币种列表"""
    return JSONResponse(get_symbol_list())


@app.get("/api/basic-stats")
async def api_basic_stats():
    """基础统计分析"""
    result = get_full_analysis()
    eq = result['equity_curve']
    result['equity_curve'] = {
        'time': eq['time'].tolist() if not eq.empty else [],
        'equity': [round(float(v), 2) for v in eq['equity']] if not eq.empty else [],
        'roi': [round(float(v), 4) for v in eq['roi']] if not eq.empty else [],
        'cumulative_pnl': [round(float(v), 2) for v in eq['cumulative_pnl']] if not eq.empty else [],
        'drawdown': [round(float(v), 4) for v in eq['drawdown']] if not eq.empty else [],
    }
    monthly = result['monthly_stats']
    result['monthly_stats'] = monthly.to_dict('records') if not monthly.empty else []
    sym = result['symbol_stats']
    result['symbol_stats'] = sym.to_dict('records') if not sym.empty else []
    return JSONResponse(result)


@app.get("/api/hold-loss")
async def api_hold_loss():
    """扛单分析"""
    return JSONResponse(get_holding_loss_analysis())


@app.get("/api/stoploss")
async def api_stoploss():
    """止损回测"""
    return JSONResponse(get_stoploss_analysis())


@app.get("/api/position")
async def api_position():
    """仓位分层分析"""
    return JSONResponse(get_position_tier_analysis())


@app.post("/api/scan")
async def api_scan(threshold: float = 0.10):
    """触发扫描"""
    try:
        result = scan_all_symbols(data_dir=PKL_DATA_DIR, threshold=threshold)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": f"扫描失败: {e}"})


@app.get("/api/scan/results")
async def api_scan_results(
    symbol: str = None,
    direction: str = None,
    min_pct: float = None,
    limit: int = 100,
    order_by: str = 'change_pct',
    order_desc: bool = True,
):
    """查询扫描结果"""
    df = get_scan_results(
        symbol=symbol, direction=direction, min_pct=min_pct,
        limit=limit, order_by=order_by, order_desc=order_desc,
    )
    return JSONResponse(df.to_dict('records'))


@app.get("/api/scan/summary")
async def api_scan_summary():
    """扫描摘要"""
    return JSONResponse(get_scan_summary())


@app.get("/api/scan/export")
async def api_scan_export(direction: str = None, min_pct: float = None):
    """导出 CSV"""
    output = io.StringIO()
    df = get_scan_results(limit=999999, direction=direction, min_pct=min_pct)
    df.to_csv(output, index=False, encoding='utf-8-sig')
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=extreme_scan_results.csv"},
    )


@app.post("/api/scan/clear")
async def api_scan_clear():
    """清空所有扫描结果"""
    try:
        from backtest.data.schema import get_connection, TABLE_SCAN_RESULTS
        conn = get_connection()
        cur = conn.execute(f"DELETE FROM {TABLE_SCAN_RESULTS}")
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return JSONResponse({"ok": True, "deleted": deleted})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ===== 新增 API：OKX 连接测试 =====

@app.post("/api/okx/test")
async def api_okx_test(request: Request):
    """测试 OKX API 连接"""
    body = await request.json()
    try:
        from backtest.data.okx_client import OKXClient
        client = OKXClient(
            api_key=body.get("api_key", ""),
            secret=body.get("secret", ""),
            passphrase=body.get("passphrase", ""),
            is_demo=body.get("is_demo", True),
        )
        ok = await client.connect()
        await client.close()
        return JSONResponse({"ok": ok})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ===== 新增 API：K 线数据管理 =====

# 全局下载器实例（供进度查询），使用锁保护并发访问
_kline_downloader = None
_kline_download_lock = __import__('asyncio').Lock()


@app.get("/api/kline-info")
async def api_kline_info():
    """获取 K 线数据概览"""
    from backtest.data.loader import get_kline_info
    return JSONResponse(get_kline_info())


@app.post("/api/kline/download")
async def api_kline_download(request: Request):
    """启动 K 线下载（单任务模式：已有任务运行时拒绝新请求）"""
    global _kline_downloader
    body = await request.json()
    symbols = body.get("symbols", [])
    bars = body.get("bars", ["5m"])
    days = body.get("days", 90)
    start_date = body.get("start_date")  # "YYYY-MM-DD" or None
    end_date = body.get("end_date")      # "YYYY-MM-DD" or None

    if not symbols:
        return JSONResponse({"error": "请指定币种"}, status_code=400)

    # 单任务模式：加锁防止并发覆盖
    if _kline_download_lock.locked():
        return JSONResponse({"error": "已有下载任务运行中，请等待完成"}, status_code=409)

    async with _kline_download_lock:
        try:
            from backtest.data.okx_client import OKXClient
            from backtest.data.downloader import KlineDownloader

            api_key = body.get("api_key", "")
            secret = body.get("secret", "")
            passphrase = body.get("passphrase", "")
            is_demo = body.get("is_demo", True)

            client = OKXClient(
                api_key=api_key, secret=secret,
                passphrase=passphrase, is_demo=is_demo,
            )
            _kline_downloader = KlineDownloader(client)
            result = await _kline_downloader.download(
                symbols, bars, days,
                start_date=start_date, end_date=end_date,
            )
            await client.close()
            return JSONResponse(result)
        except Exception as e:
            return JSONResponse({"error": str(e)})
        finally:
            _kline_downloader = None


@app.get("/api/kline/progress")
async def api_kline_progress():
    """获取 K 线下载进度"""
    if _kline_downloader is None:
        return JSONResponse({})
    return JSONResponse(_kline_downloader.get_progress())


# ===== 新增 API：CSV 导入 =====

@app.get("/api/csv/template")
async def api_csv_template():
    """下载 CSV 模板"""
    from backtest.data.downloader import OrderImporter
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    tmp.close()
    OrderImporter.generate_template(tmp.name)
    return FileResponse(
        tmp.name,
        media_type="text/csv",
        filename="trade_template.csv",
    )


@app.post("/api/csv/import")
async def api_csv_import(file: UploadFile = File(...)):
    """导入 CSV 订单"""
    if not file.filename.endswith('.csv'):
        return JSONResponse({"error": "请上传 .csv 文件"}, status_code=400)

    # 保存临时文件
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    content = await file.read()
    tmp.write(content)
    tmp.close()

    try:
        from backtest.data.downloader import OrderImporter
        result = OrderImporter.import_csv(tmp.name)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)})
    finally:
        Path(tmp.name).unlink(missing_ok=True)


# ===== 新增 API：补算浮亏 =====

@app.post("/api/backfill-float-loss")
async def api_backfill_float_loss():
    """
    补算 max_floating_loss 字段
    优先从数据库K线补算，没有K线则从pkl文件补算
    """
    try:
        from backtest.data.backfill import backfill_from_db_klines, backfill_from_pkl

        # 先尝试从数据库K线补算
        result = backfill_from_db_klines()

        # 如果数据库没K线，尝试从pkl补算
        if result.get("updated", 0) == 0 and "没有K线" in result.get("message", ""):
            result = backfill_from_pkl()

        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.post("/api/clear-trades")
async def api_clear_trades():
    """清空所有交易记录及相关数据"""
    try:
        from backtest.data.schema import get_connection
        from backtest.config import TABLE_TRADE_RECORDS
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {TABLE_TRADE_RECORDS}")
        cursor.execute("DELETE FROM position_snapshots")
        trades_deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return JSONResponse({"ok": True, "deleted": trades_deleted})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ===== 新增 API：订单下载与分析 =====

# 全局订单下载器实例
_order_downloader = None


@app.post("/api/orders/fetch")
async def api_orders_fetch(request: Request):
    """从 OKX 拉取成交记录并配对"""
    global _order_downloader
    body = await request.json()
    inst_type = body.get("inst_type", "SWAP")

    try:
        from backtest.data.okx_client import OKXClient
        from backtest.data.downloader import OrderDownloader

        api_key = body.get("api_key", "")
        secret = body.get("secret", "")
        passphrase = body.get("passphrase", "")
        is_demo = body.get("is_demo", True)

        client = OKXClient(
            api_key=api_key, secret=secret,
            passphrase=passphrase, is_demo=is_demo,
        )
        _order_downloader = OrderDownloader(client)
        result = await _order_downloader.download(inst_type)
        await client.close()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/orders/analysis")
async def api_orders_analysis():
    """订单多维分析"""
    try:
        from backtest.analysis.order_analysis import get_order_analysis
        return JSONResponse(get_order_analysis())
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/trades")
async def api_trades():
    """获取交易记录列表"""
    from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS
    conn = get_connection()
    df = pd.read_sql(f"SELECT * FROM {TABLE_TRADE_RECORDS} ORDER BY entry_time DESC", conn)
    conn.close()
    return JSONResponse(df.to_dict('records'))


# ===== 新增 API：模拟回测 =====

@app.post("/api/simulate")
async def api_simulate(request: Request):
    """运行模拟回测"""
    body = await request.json()
    stoploss_pct = body.get("stoploss_pct", 0.10)
    takeprofit_pct = body.get("takeprofit_pct", 0.20)
    kline_bar = body.get("kline_bar", "5m")
    trigger_priority = body.get("trigger_priority", "stoploss_first")

    try:
        from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS
        from backtest.analysis.simulator import BatchSimulator, TradeSimulator
        from backtest.analysis.basic_stats import calc_basic_stats, calc_equity_curve

        conn = get_connection()
        trades_df = pd.read_sql(f"SELECT * FROM {TABLE_TRADE_RECORDS} ORDER BY entry_time", conn)
        conn.close()

        if trades_df.empty:
            return JSONResponse({"error": "无交易数据，请先导入订单"})

        # 实际统计
        actual_stats = calc_basic_stats(trades_df)

        # 运行模拟
        sim = BatchSimulator(
            kline_bar=kline_bar,
            trigger_priority=trigger_priority,
        )
        batch = sim.run(trades_df, stoploss_pct=stoploss_pct, takeprofit_pct=takeprofit_pct)

        # 构建净值曲线
        actual_curve = calc_equity_curve(trades_df)
        actual_equity = [round(float(v), 2) for v in actual_curve['equity']] if not actual_curve.empty else []

        sim_pnl_values = [r.simulated_pnl for r in batch.simulated_trades]
        import numpy as np
        sim_cum = np.cumsum(sim_pnl_values).tolist() if sim_pnl_values else []
        initial = 10000
        sim_equity = [round(initial + v, 2) for v in sim_cum]

        # 触发分布
        trigger_dist = {}
        for r in batch.simulated_trades:
            trigger_dist[r.trigger_type] = trigger_dist.get(r.trigger_type, 0) + 1

        # 逐笔详情
        trades_detail = []
        for r in batch.simulated_trades:
            trades_detail.append({
                "trade_id": r.trade_id,
                "symbol": r.symbol,
                "direction": r.direction,
                "entry_price": r.entry_price,
                "trigger_type": r.trigger_type,
                "trigger_time": r.trigger_time,
                "exit_price": r.exit_price,
                "simulated_pnl": round(r.simulated_pnl, 2),
                "original_pnl": round(r.original_pnl, 2),
                "pnl_diff": round(r.pnl_diff, 2),
                "hold_bars": r.hold_bars,
            })

        return JSONResponse({
            "summary": {
                "total_trades": batch.total_trades,
                "wins": batch.wins,
                "losses": batch.losses,
                "timeouts": batch.timeouts,
                "win_rate": batch.win_rate,
                "profit_loss_ratio": batch.profit_loss_ratio,
                "total_pnl": batch.total_pnl,
                "avg_pnl": batch.avg_pnl,
                "max_drawdown": batch.max_drawdown,
                "avg_hold_bars": batch.avg_hold_bars,
            },
            "actual_stats": actual_stats,
            "trigger_distribution": trigger_dist,
            "equity_curve": {
                "time": actual_curve['time'].tolist() if not actual_curve.empty else [],
                "actual": actual_equity,
                "simulated": sim_equity,
            },
            "trades": trades_detail,
        })
    except Exception as e:
        import traceback
        return JSONResponse({"error": f"{e}\n{traceback.format_exc()}"})


# ===== 新增 API：参数优化 =====

@app.post("/api/optimize")
async def api_optimize(request: Request):
    """参数网格搜索"""
    body = await request.json()
    stoploss_ratios = body.get("stoploss_ratios", [0.05, 0.10, 0.15, 0.20])
    takeprofit_ratios = body.get("takeprofit_ratios", [0.05, 0.10, 0.20, 0.50])
    kline_bar = body.get("kline_bar", "5m")

    try:
        from backtest.data.schema import get_connection, TABLE_TRADE_RECORDS
        from backtest.analysis.simulator import BatchSimulator

        conn = get_connection()
        trades_df = pd.read_sql(f"SELECT * FROM {TABLE_TRADE_RECORDS} ORDER BY entry_time", conn)
        conn.close()

        if trades_df.empty:
            return JSONResponse({"error": "无交易数据，请先导入订单"})

        sim = BatchSimulator(kline_bar=kline_bar)
        grid_results = sim.run_param_grid(
            trades_df,
            stoploss_ratios=stoploss_ratios,
            takeprofit_ratios=takeprofit_ratios,
        )

        # 序列化结果
        results = []
        for (sl, tp), batch in grid_results.items():
            results.append({
                "stoploss_pct": sl,
                "takeprofit_pct": tp,
                "total_trades": batch.total_trades,
                "wins": batch.wins,
                "losses": batch.losses,
                "win_rate": batch.win_rate,
                "profit_loss_ratio": batch.profit_loss_ratio,
                "total_pnl": batch.total_pnl,
                "avg_pnl": batch.avg_pnl,
                "max_drawdown": batch.max_drawdown,
                "avg_hold_bars": batch.avg_hold_bars,
                "trigger_distribution": batch.trigger_distribution,
            })

        # 找最优参数（按总盈亏）
        optimal = max(results, key=lambda r: r["total_pnl"]) if results else None

        return JSONResponse({
            "results": results,
            "optimal": optimal,
            "total_combinations": len(results),
        })
    except Exception as e:
        import traceback
        return JSONResponse({"error": f"{e}\n{traceback.format_exc()}"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT)
