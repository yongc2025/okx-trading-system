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
    result = scan_all_symbols(data_dir=PKL_DATA_DIR, threshold=threshold)
    return JSONResponse(result)


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT)
