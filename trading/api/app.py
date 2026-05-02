"""
OKX 交易助手 - FastAPI 应用
交易执行模块 Web 界面与 API
"""
import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from trading.config import BASE_DIR, PROXY_URL
from trading.data.database import Database
from trading.core.settings import Settings
from trading.core.credentials import CredentialManager
from trading.core.session import SessionManager
from trading.core.logger import log
from trading.api.okx_rest import OKXRestClient
from trading.api.okx_ws import OKXWebSocket
from trading.engine.stoploss import StoplossEngine
from trading.engine.order import OrderEngine
from trading.engine.position import PositionManager
from trading.engine.risk import RiskController

# ============================================================
# 全局状态
# ============================================================
db: Database = None
settings: Settings = None
session_mgr: SessionManager = None
rest_client: OKXRestClient = None
ws_client: OKXWebSocket = None
order_engine: OrderEngine = None
stoploss_engine: StoplossEngine = None
position_mgr: PositionManager = None
risk_ctrl: RiskController = None
ws_clients: list[WebSocket] = []  # 前端 WebSocket 连接


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    global db, settings, session_mgr
    db = Database()
    settings = Settings(db)
    session_mgr = SessionManager(db=db)
    log.info("交易模块启动")
    yield
    if rest_client:
        await rest_client.close()
    if ws_client:
        await ws_client.stop()
    db.close()
    log.info("交易模块关闭")


app = FastAPI(title="OKX 交易助手", version="1.0.0", lifespan=lifespan)

# S-01 修复: 使用项目根目录下的 templates 和 static 目录
STATIC_DIR = Path(__file__).parent.parent / "static"
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


# ============================================================
# 工具
# ============================================================
def _require_unlocked():
    """检查会话是否已解锁"""
    if not session_mgr or not session_mgr.is_unlocked:
        return JSONResponse({"error": "会话未解锁，请先登录"}, status_code=401)
    return None


def _require_connected():
    """检查 OKX 是否已连接"""
    if not rest_client:
        return JSONResponse({"error": "未连接 OKX"}, status_code=400)
    return None


async def _init_okx(api_key: str, secret: str, passphrase: str, is_demo: bool = False):
    """初始化 OKX 客户端和引擎"""
    global rest_client, ws_client, order_engine, stoploss_engine, position_mgr, risk_ctrl

    rest_client = OKXRestClient(api_key, secret, passphrase, is_demo)
    ws_client = OKXWebSocket(api_key, secret, passphrase, is_demo,
                              on_message=_on_ws_message)

    stoploss_engine = StoplossEngine(rest_client, db, settings)
    order_engine = OrderEngine(rest_client, ws_client, db, settings, stoploss_engine)
    position_mgr = PositionManager(rest_client, db)
    risk_ctrl = RiskController(settings)

    # 启动 WebSocket
    asyncio.create_task(ws_client.start())
    await ws_client.subscribe_orders()
    await ws_client.subscribe_positions()


# ============================================================
# 页面路由
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ============================================================
# 会话 API (登录/注册/状态)
# ============================================================
@app.get("/api/session")
async def api_session_status():
    """获取会话状态"""
    return {
        "first_run": session_mgr.is_first_run,
        "unlocked": session_mgr.is_unlocked,
        "connected": rest_client is not None,
        "ws_connected": ws_client.connected if ws_client else False,
    }


@app.post("/api/session/register")
async def api_register(request: Request):
    """首次设置本地密码"""
    body = await request.json()
    password = body.get("password", "")
    if len(password) < 6:
        return JSONResponse({"error": "密码至少6位"}, status_code=400)

    result = session_mgr.setup_password(password)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return result


@app.post("/api/session/login")
async def api_login(request: Request):
    """解锁会话"""
    body = await request.json()
    password = body.get("password", "")

    result = session_mgr.verify_password(password)
    if "error" in result:
        return JSONResponse(result, status_code=401)

    # 优化：解锁时自动尝试连接最近一次成功使用的凭证
    auto_connect = await _try_auto_connect()

    return {
        "status": "ok",
        "auto_connect": auto_connect,
    }


@app.post("/api/session/lock")
async def api_lock():
    """锁定会话"""
    global rest_client, ws_client
    if ws_client:
        await ws_client.stop()
    if rest_client:
        await rest_client.close()
    rest_client = None
    ws_client = None
    session_mgr.lock()
    return {"status": "ok"}


@app.post("/api/session/change-password")
async def api_change_password(request: Request):
    """修改本地密码"""
    body = await request.json()
    result = session_mgr.change_password(body.get("old_password", ""), body.get("new_password", ""), db=db)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return result


async def _try_auto_connect() -> dict:
    """尝试用已保存的凭证自动连接 OKX"""
    if not session_mgr.is_unlocked:
        return {"status": "skipped", "reason": "session_locked"}

    cred_mgr = CredentialManager(db, session_mgr.password)
    labels = cred_mgr.list_labels()
    if not labels:
        return {"status": "skipped", "reason": "no_saved_credentials"}

    # 使用第一个保存的凭证
    label = labels[0]["label"]
    creds = cred_mgr.load(label)
    if not creds:
        return {"status": "skipped", "reason": "load_failed"}

    try:
        await _init_okx(creds["api_key"], creds["secret"], creds["passphrase"], creds["is_demo"])
        # 验证连接
        balance = await rest_client.get_balance()
        if balance.get("code") == "0":
            log.info(f"自动连接成功 (凭证: {label})")
            return {"status": "ok", "label": label}
        else:
            log.warning(f"自动连接失败: {balance.get('msg')}")
            return {"status": "fail", "reason": balance.get("msg", "unknown")}
    except Exception as e:
        log.error(f"自动连接异常: {e}")
        return {"status": "fail", "reason": str(e)}


# ============================================================
# OKX 连接 API (手动)
# ============================================================
@app.post("/api/connect")
async def api_connect(request: Request):
    """手动连接 OKX API"""
    global rest_client, ws_client
    check = _require_unlocked()
    if check:
        return check

    # 关键优化：连接前先关闭旧的连接对象，防止后台后台重复报错
    if ws_client:
        log.info("检测到已有连接，正在清理旧的 WS 实例...")
        await ws_client.stop()
        ws_client = None
    if rest_client:
        await rest_client.close()
        rest_client = None

    body = await request.json()
    api_key = body.get("api_key", "")
    secret = body.get("secret", "")
    passphrase = body.get("passphrase", "")
    is_demo = body.get("is_demo", False)
    save = body.get("save", True)  # 是否保存凭证

    if not all([api_key, secret, passphrase]):
        return JSONResponse({"error": "缺少 API 凭证"}, status_code=400)

    # 保存凭证
    if save:
        cred_mgr = CredentialManager(db, session_mgr.password)
        cred_mgr.save(api_key, secret, passphrase, is_demo=is_demo)

    # 初始化并测试
    try:
        await _init_okx(api_key, secret, passphrase, is_demo)
        balance = await rest_client.get_balance()
        
        code = balance.get("code")
        if code != "0":
            # 翻译 OKX 常用错误码
            error_map = {
                "50101": "API Key 与当前环境不匹配。请检查是否在实盘环境使用了模拟盘 Key，或反之。",
                "50105": "Passphrase (API 密码) 错误。请确认您在 OKX 创建 Key 时设置的密码。",
                "50110": "API Key 错误或不存在。请检查输入是否完整。",
                "50004": "请求速度过快，被限制。请稍后再试。",
                "400": "网络连接错误 (400)。请检查 VPN/代理端口是否正确。",
                "50100": "签名错误。请检查 Secret Key 是否输入正确。",
            }
            raw_msg = balance.get("msg", "unknown")
            msg = error_map.get(code, f"OKX 错误({code}): {raw_msg}")
            return JSONResponse({"error": msg}, status_code=400)
            
        return {"status": "ok", "message": "连接成功"}
        
    except Exception as e:
        err_str = str(e)
        if "10054" in err_str or "64" in err_str or "All connection attempts failed" in err_str:
            friendly_err = f"网络连接被拒绝。请确认 VPN 端口 (目前: {PROXY_URL}) 已开启且正确。"
        elif "Unknown scheme" in err_str:
            friendly_err = "代理协议不支持。请在 config.py 中将 PROXY_URL 改回 http:// 格式。"
        else:
            friendly_err = f"连接异常: {err_str}"
            
        return JSONResponse({"error": friendly_err}, status_code=500)

    return {"status": "connected", "balance": balance.get("data", [])}


@app.get("/api/status")
async def api_status():
    """连接状态"""
    return {
        "connected": rest_client is not None,
        "ws_connected": ws_client.connected if ws_client else False,
    }


# ============================================================
# 交易 API
# ============================================================
@app.post("/api/order")
async def api_place_order(request: Request):
    """下单"""
    check = _require_connected()
    if check:
        return check

    body = await request.json()
    symbol = body["symbol"]
    direction = body["direction"]
    price = float(body["price"])
    quantity = int(body["quantity"])
    notional = float(body.get("notional", quantity * price))
    order_type = body.get("order_type", "limit")
    position_tier = body.get("position_tier", "first")

    # 风控校验
    balance_resp = await rest_client.get_balance()
    available = position_mgr.get_available_balance(balance_resp)
    leverage = settings.get(f"leverage_{direction}")
    ok, msg = risk_ctrl.validate_order(direction, leverage, available, position_tier)
    if not ok:
        return JSONResponse({"error": msg}, status_code=400)

    # 真实下发杠杆到交易所
    try:
        pos_side = "long" if direction == "long" else "short"
        await rest_client.set_leverage(symbol, leverage, pos_side=pos_side)
    except Exception as e:
        log.warning(f"设置杠杆失败: {e}")

    result = await order_engine.place_order(symbol, direction, price, quantity, notional,
                                             position_tier=position_tier, order_type=order_type)

    # 自动挂止损 (市价单也需要止损)
    await stoploss_engine.attach_stoploss(symbol, direction, price, quantity)

    return result


@app.post("/api/add-position")
async def api_add_position(request: Request):
    """加仓"""
    check = _require_connected()
    if check:
        return check

    body = await request.json()
    symbol = body["symbol"]
    direction = body["direction"]
    price = float(body["price"])

    result = await order_engine.add_position(symbol, direction, price)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return result


@app.post("/api/close-all")
async def api_close_all():
    """一键全平"""
    check = _require_connected()
    if check:
        return check

    results = await order_engine.close_all()
    return {"results": results}


@app.get("/api/positions")
async def api_positions():
    """查询持仓"""
    if not position_mgr:
        return {"positions": []}
    positions = await position_mgr.sync_positions()
    return {"positions": positions or []}


@app.get("/api/balance")
async def api_balance():
    """查询余额"""
    check = _require_connected()
    if check:
        return check
    return await rest_client.get_balance()


@app.get("/api/ticker/{symbol}")
async def api_ticker(symbol: str):
    """获取实时价格并订阅推送"""
    check = _require_connected()
    if check:
        return check
    
    # 获取初始行情
    ticker_data = await rest_client.get_ticker(symbol)
    
    # 异步触发 WebSocket 订阅 (Ticker + Depth)
    if ws_client:
        asyncio.create_task(ws_client.subscribe_ticker(symbol))
        asyncio.create_task(ws_client.subscribe_depth(symbol))
        
    return ticker_data

@app.get("/api/books/{symbol}")
async def api_books(symbol: str):
    """获取深度数据"""
    check = _require_connected()
    if check:
        return check
    return await rest_client.get_books(symbol)


@app.get("/api/instruments")
async def api_instruments():
    """获取合约列表"""
    check = _require_connected()
    if check:
        return check
    return await rest_client.get_instruments()


# ============================================================
# 配置 API
# ============================================================
@app.get("/api/settings")
async def api_get_settings():
    return settings.all()


@app.get("/api/settings/schema")
async def api_get_settings_schema():
    """返回配置项 Schema（类型、默认值、描述）"""
    return settings.schema()


@app.post("/api/settings")
async def api_set_settings(request: Request):
    body = await request.json()
    for key, value in body.items():
        try:
            settings.set(key, value)
        except ValueError:
            pass
    return settings.all()


# ============================================================
# 页面路由
# ============================================================
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})


# ============================================================
# 常用币种 API
# ============================================================
@app.get("/api/favorites")
async def api_favorites():
    return db.get_favorites()


# ============================================================
# 交易日志 API
# ============================================================
@app.get("/api/logs")
async def api_logs(limit: int = 100, action: str = None):
    if action:
        return db.fetchall(
            "SELECT * FROM trade_logs WHERE action=? ORDER BY id DESC LIMIT ?",
            (action, limit),
        )
    return db.fetchall("SELECT * FROM trade_logs ORDER BY id DESC LIMIT ?", (limit,))


# ============================================================
# 凭证管理 API
# ============================================================
@app.get("/api/credentials")
async def api_list_credentials():
    """列出已保存的凭证"""
    check = _require_unlocked()
    if check:
        return check
    cred_mgr = CredentialManager(db, session_mgr.password)
    return cred_mgr.list_labels()


@app.delete("/api/credentials/{label}")
async def api_delete_credential(label: str):
    """删除已保存的凭证"""
    check = _require_unlocked()
    if check:
        return check
    cred_mgr = CredentialManager(db, session_mgr.password)
    cred_mgr.delete(label)
    return {"status": "ok"}


@app.post("/api/credentials/test")
async def api_test_credential(request: Request):
    """测试 API 凭证是否有效"""
    check = _require_unlocked()
    if check:
        return check

    body = await request.json()
    label = body.get("label")

    cred_mgr = CredentialManager(db, session_mgr.password)

    if label:
        # 测试已保存的凭证
        creds = cred_mgr.load(label)
        if not creds:
            return JSONResponse({"error": f"凭证 '{label}' 不存在"}, status_code=404)
    else:
        # 测试手动输入的凭证
        creds = {
            "api_key": body.get("api_key", ""),
            "secret": body.get("secret", ""),
            "passphrase": body.get("passphrase", ""),
            "is_demo": body.get("is_demo", False),
        }
        if not all([creds["api_key"], creds["secret"], creds["passphrase"]]):
            return JSONResponse({"error": "缺少 API 凭证"}, status_code=400)

    try:
        from trading.api.okx_rest import OKXRestClient
        client = OKXRestClient(
            creds["api_key"], creds["secret"], creds["passphrase"], creds["is_demo"]
        )
        balance = await client.get_balance()
        await client.close()

        code = balance.get("code")
        if code == "0":
            # 提取 USDT 余额
            usdt_balance = 0
            for d in balance.get("data", []):
                for detail in d.get("details", []):
                    if detail.get("ccy") == "USDT":
                        usdt_balance = float(detail.get("availBal", 0))
            return {"ok": True, "usdt_balance": usdt_balance}
        else:
            error_map = {
                "50101": "API Key 与环境不匹配（实盘/模拟盘）",
                "50105": "Passphrase 错误",
                "50110": "API Key 错误或不存在",
                "50100": "Secret Key 签名错误",
            }
            msg = error_map.get(code, f"OKX 错误({code}): {balance.get('msg', '')}")
            return {"ok": False, "error": msg}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/credentials/connect")
async def api_connect_from_saved(request: Request):
    """用已保存的凭证连接 OKX"""
    check = _require_unlocked()
    if check:
        return check

    body = await request.json()
    label = body.get("label", "default")

    cred_mgr = CredentialManager(db, session_mgr.password)
    creds = cred_mgr.load(label)
    if not creds:
        return JSONResponse({"error": f"凭证 '{label}' 不存在"}, status_code=404)

    try:
        await _init_okx(creds["api_key"], creds["secret"], creds["passphrase"], creds["is_demo"])
        balance = await rest_client.get_balance()
        code = balance.get("code")
        if code == "0":
            return {"status": "ok", "label": label}
        else:
            return JSONResponse({"error": f"连接失败: {balance.get('msg', '')}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================
# 前端 WebSocket (推送实时数据到浏览器)
# ============================================================
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_clients.remove(ws)


async def broadcast_to_clients(data: dict):
    """向所有前端 WebSocket 推送数据"""
    for ws in ws_clients[:]:
        try:
            await ws.send_json(data)
        except Exception:
            ws_clients.remove(ws)


async def _on_ws_message(channel: str, data: list, arg: dict):
    """OKX WebSocket 消息处理"""
    if channel == "tickers":
        for item in data:
            symbol = item.get("instId", "")
            price = float(item.get("last", 0))
            if ws_client:
                ws_client._last_price[symbol] = {"price": price, "ts": time.time()}
            await broadcast_to_clients({
                "type": "ticker", "symbol": symbol, "price": price,
            })
    elif channel == "books5":
        # 深度推送
        symbol = arg.get("instId")
        await broadcast_to_clients({
            "type": "depth", "symbol": symbol, "data": data[0]
        })
    elif channel == "orders":
        for item in data:
            await broadcast_to_clients({"type": "order", "data": item})
            db.log("order_update", item, symbol=item.get("instId"))
    elif channel.startswith("positions") or channel == "positions":
        for item in data:
            await broadcast_to_clients({"type": "position", "data": item})


# ============================================================
# 诊断 API
# ============================================================
@app.get("/api/diagnostic")
async def api_diagnostic():
    """系统诊断报告"""
    from trading.tests.diagnostic import full_diagnostic
    return await full_diagnostic(rest_client, ws_client, db)


# ============================================================
# 启动入口
# ============================================================
def run(host: str = "0.0.0.0", port: int = 8888):
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
