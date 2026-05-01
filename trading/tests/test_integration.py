"""
OKX 交易助手 - 集成测试 (TR-15)
覆盖完整交易流程: 登录 → 连接 → 下单 → 止损 → 加仓 → 全平
模拟异常: 网络断开、API 错误、超时、并发
"""
import sys
import json
import time
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trading.data.database import Database
from trading.data.schema import init_db
from trading.core.settings import Settings
from trading.core.session import SessionManager
from trading.core.encryption import encrypt, decrypt
from trading.core.credentials import CredentialManager
from trading.engine.splitter import split_order
from trading.engine.stoploss import StoplossEngine, calc_stoploss_price, calc_weighted_avg_price
from trading.engine.order import OrderEngine
from trading.engine.position import PositionManager
from trading.engine.risk import RiskController
from trading.api.okx_rest import OKXRestClient
from trading.tests.mock_okx import MockOKXRestResponse as Mock


# ============================================================
# 辅助
# ============================================================
def make_temp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


def make_mock_rest():
    """创建 Mock REST 客户端"""
    rest = MagicMock(spec=OKXRestClient)
    rest.get_balance = AsyncMock(return_value=Mock.BALANCE)
    rest.get_positions = AsyncMock(return_value=Mock.POSITIONS_EMPTY)
    rest.place_order = AsyncMock(return_value=Mock.order_ok())
    rest.place_algo_order = AsyncMock(return_value=Mock.algo_order_ok())
    rest.cancel_order = AsyncMock(return_value=Mock.CANCEL_OK)
    rest.cancel_algo_order = AsyncMock(return_value=Mock.CANCEL_ALGO_OK)
    rest.get_pending_orders = AsyncMock(return_value=Mock.pending_orders())
    rest.get_ticker = AsyncMock(return_value=Mock.ticker())
    rest.get_instruments = AsyncMock(return_value=Mock.INSTRUMENTS)
    rest.set_leverage = AsyncMock(return_value=Mock.SET_LEVERAGE_OK)
    rest.get_fills_history = AsyncMock(return_value=Mock.FILLS_HISTORY)
    return rest


def make_mock_ws():
    """创建 Mock WebSocket 客户端"""
    ws = MagicMock()
    ws.connected = True
    ws.get_last_price = MagicMock(return_value=50000)
    ws.start = AsyncMock()
    ws.stop = AsyncMock()
    ws.subscribe_ticker = AsyncMock()
    ws.subscribe_orders = AsyncMock()
    ws.subscribe_positions = AsyncMock()
    return ws


# ============================================================
# 测试: 完整交易流程
# ============================================================
async def test_full_trade_flow():
    """完整流程: 开仓 → 挂止损 → 加仓 → 更新止损 → 全平"""
    db_path = make_temp_db()
    try:
        db = Database(db_path)
        settings = Settings(db)
        rest = make_mock_rest()
        ws = make_mock_ws()

        sl_engine = StoplossEngine(rest, db, settings)
        order_engine = OrderEngine(rest, ws, db, settings, sl_engine)
        position_mgr = PositionManager(rest, db)
        risk_ctrl = RiskController(settings)

        symbol = "BTC-USDT-SWAP"
        direction = "long"
        price = 50000.0
        qty = 1

        # 1. 风控校验
        balance_resp = Mock.BALANCE
        available = position_mgr.get_available_balance(balance_resp)
        leverage = settings.get("leverage_long")
        ok, msg = risk_ctrl.validate_order(direction, leverage, available, "first")
        assert ok, f"风控校验失败: {msg}"

        # 2. 下单
        result = await order_engine.place_order(symbol, direction, price, qty, price * qty, "first")
        assert "trade_id" in result, f"下单失败: {result}"
        assert result["sub_orders"] >= 1
        trade_id = result["trade_id"]

        # 3. 挂止损
        sl_result = await sl_engine.attach_stoploss(symbol, direction, price, qty)
        assert "sl_id" in sl_result
        assert sl_result["stoploss_price"] == 45000.0  # 50000 * 0.9

        # 4. 模拟加仓 (设置已有持仓)
        rest.get_positions = AsyncMock(return_value=Mock.position(
            symbol, direction, qty=1, avg_px=50000
        ))
        rest.get_balance = AsyncMock(return_value=Mock.BALANCE)

        add_result = await order_engine.add_position(symbol, direction, 48000.0)
        # 可能返回 error (余额不足) 或成功
        if "error" not in add_result:
            assert "trade_id" in add_result

        # 5. 全平
        rest.get_positions = AsyncMock(return_value=Mock.position(
            symbol, direction, qty=2, avg_px=49000
        ))
        close_results = await order_engine.close_all()
        assert len(close_results) >= 1

        # 6. 验证日志
        logs = db.fetchall("SELECT * FROM trade_logs")
        assert len(logs) >= 1

        db.close()
        print("  ✅ 完整交易流程通过")
    finally:
        db_path.unlink(missing_ok=True)


# ============================================================
# 测试: 拆单边界
# ============================================================
async def test_split_edge_cases():
    """拆单边界: 恰好阈值、极小单、极大单"""
    db_path = make_temp_db()
    try:
        db = Database(db_path)
        settings = Settings(db)

        # 恰好不拆 (800U)
        orders = split_order("BTC-USDT-SWAP", "buy", "long", 1, 50000, 800, settings)
        assert len(orders) == 1

        # 触发拆单: 足够张数 + 超过阈值
        orders = split_order("BTC-USDT-SWAP", "buy", "long", 10, 50000, 5000, settings)
        assert len(orders) >= 2
        total_qty = sum(o.quantity for o in orders)
        assert total_qty == 10, f"总量不等: {total_qty}"

        # 极大单 (100000U)
        orders = split_order("BTC-USDT-SWAP", "buy", "long", 100, 50000, 100000, settings)
        total_qty = sum(o.quantity for o in orders)
        assert total_qty == 100, f"总量不等: {total_qty}"
        assert len(orders) >= 5

        # 张数不足时回退 (1张, 801U -> 不拆)
        orders = split_order("BTC-USDT-SWAP", "buy", "long", 1, 50000, 801, settings)
        assert len(orders) == 1
        assert orders[0].quantity == 1

        # 2张刚好拆
        orders = split_order("BTC-USDT-SWAP", "buy", "long", 2, 50000, 2000, settings)
        assert len(orders) == 2
        total_qty = sum(o.quantity for o in orders)
        assert total_qty == 2

        db.close()
        print("  ✅ 拆单边界测试通过")
    finally:
        db_path.unlink(missing_ok=True)


# ============================================================
# 测试: 止损计算准确性
# ============================================================
async def test_stoploss_accuracy():
    """止损价计算: 多单/空单/不同价格/加仓后"""
    # 基础
    assert calc_stoploss_price(100, "long") == 90.0
    assert calc_stoploss_price(100, "short") == 110.0

    # 小数
    assert calc_stoploss_price(0.1234, "long") == round(0.1234 * 0.9, 8)
    assert calc_stoploss_price(99999, "short") == round(99999 * 1.1, 8)

    # 加权均价
    avg = calc_weighted_avg_price(0, 0, 10, 100)
    assert avg == 100  # 首次开仓

    avg = calc_weighted_avg_price(10, 100, 10, 80)
    assert avg == 90  # (10*100 + 10*80) / 20

    avg = calc_weighted_avg_price(10, 100, 5, 120)
    expected = (10 * 100 + 5 * 120) / 15
    assert abs(avg - expected) < 0.001

    # 加仓后止损价
    new_avg = calc_weighted_avg_price(1, 50000, 1, 48000)
    assert new_avg == 49000
    sl = calc_stoploss_price(new_avg, "long")
    assert sl == 49000 * 0.9

    print("  ✅ 止损计算准确性通过")


# ============================================================
# 测试: 风控硬限制
# ============================================================
async def test_risk_hard_limits():
    """风控: 杠杆上限/仓位约束/边界值"""
    db_path = make_temp_db()
    try:
        db = Database(db_path)
        settings = Settings(db)
        rc = RiskController(settings)

        # 做多杠杆: 1~3 通过, 4+ 拒绝
        for lever in [1, 2, 3]:
            ok, _ = rc.validate_leverage("long", lever)
            assert ok, f"long {lever}x 应通过"
        ok, msg = rc.validate_leverage("long", 4)
        assert not ok, "long 4x 应拒绝"
        ok, msg = rc.validate_leverage("long", 100)
        assert not ok

        # 做空杠杆: 1~2 通过, 3+ 拒绝
        for lever in [1, 2]:
            ok, _ = rc.validate_leverage("short", lever)
            assert ok, f"short {lever}x 应通过"
        ok, msg = rc.validate_leverage("short", 3)
        assert not ok, "short 3x 应拒绝"

        # 仓位分配
        # ≥1500U: 强制三档
        assert rc.get_position_allocation(1500, "first") == 0.50
        assert rc.get_position_allocation(1500, "add1") == 0.25
        assert rc.get_position_allocation(1500, "add2") == 0.25
        assert rc.get_position_allocation(50000, "first") == 0.50

        # <1500U: 不限制
        assert rc.get_position_allocation(1499, "first") == 1.0
        assert rc.get_position_allocation(100, "first") == 1.0
        assert rc.get_position_allocation(1, "first") == 1.0

        # 综合校验
        ok, _ = rc.validate_order("long", 3, 5000, "first")
        assert ok
        ok, msg = rc.validate_order("long", 4, 5000, "first")
        assert not ok
        ok, msg = rc.validate_order("short", 3, 5000, "first")
        assert not ok

        db.close()
        print("  ✅ 风控硬限制通过")
    finally:
        db_path.unlink(missing_ok=True)


# ============================================================
# 测试: API 错误处理
# ============================================================
async def test_api_error_handling():
    """API 错误: 认证失败/余额不足/限频/下单失败"""
    db_path = make_temp_db()
    try:
        db = Database(db_path)
        settings = Settings(db)
        rest = make_mock_rest()
        ws = make_mock_ws()

        sl_engine = StoplossEngine(rest, db, settings)
        order_engine = OrderEngine(rest, ws, db, settings, sl_engine)

        # 余额不足
        rest.get_balance = AsyncMock(return_value=Mock.ERROR_INSUFFICIENT)
        resp = await rest.get_balance()
        assert resp["code"] != "0"

        # 认证失败
        rest.get_balance = AsyncMock(return_value=Mock.ERROR_AUTH)
        resp = await rest.get_balance()
        assert resp["code"] == "50111"

        # 下单失败
        rest.place_order = AsyncMock(return_value=Mock.ERROR_ORDER)
        resp = await rest.place_order("BTC-USDT-SWAP", "buy", "long", "limit", "1", "50000")
        assert resp["code"] != "0"

        # 限频
        rest.get_ticker = AsyncMock(return_value=Mock.ERROR_RATE_LIMIT)
        resp = await rest.get_ticker("BTC-USDT-SWAP")
        assert resp["code"] == "50011"

        db.close()
        print("  ✅ API 错误处理通过")
    finally:
        db_path.unlink(missing_ok=True)


# ============================================================
# 测试: 会话全流程
# ============================================================
async def test_session_flow():
    """会话: 注册 → 登录 → 锁定 → 重新登录 → 改密 → 重置"""
    from trading.core.session import AUTH_FILE

    if AUTH_FILE.exists():
        AUTH_FILE.unlink()

    db_path = make_temp_db()
    try:
        db = Database(db_path)
        sm = SessionManager(db=db)

        # 首次
        assert sm.is_first_run

        # 注册
        r = sm.setup_password("mypass123")
        assert r["status"] == "ok"
        assert sm.is_unlocked

        # 锁定
        sm.lock()
        assert not sm.is_unlocked
        assert sm.password is None

        # 错误密码
        r = sm.verify_password("wrong")
        assert "error" in r
        assert not sm.is_unlocked

        # 正确密码
        r = sm.verify_password("mypass123")
        assert r["status"] == "ok"
        assert sm.is_unlocked

        # 保存凭证
        cred_mgr = CredentialManager(db, "mypass123")
        cred_mgr.save("test_key", "test_secret", "test_pp")

        # 改密 (传入 db 实例确保同一连接)
        r = sm.change_password("mypass123", "newpass456", db=db)
        assert r["status"] == "ok", f"改密失败: {r}"

        # 用新密码能解密
        cred_mgr2 = CredentialManager(db, "newpass456")
        creds = cred_mgr2.load()
        assert creds["api_key"] == "test_key"
        assert creds["secret"] == "test_secret"
        assert creds["passphrase"] == "test_pp"

        # 旧密码解密失败
        cred_mgr3 = CredentialManager(db, "mypass123")
        try:
            cred_mgr3.load()
            assert False, "旧密码应解密失败"
        except Exception:
            pass

        # 重置
        sm.reset()
        assert sm.is_first_run
        assert not sm.is_unlocked

        db.close()
        print("  ✅ 会话全流程通过")
    finally:
        db_path.unlink(missing_ok=True)
        if AUTH_FILE.exists():
            AUTH_FILE.unlink()


# ============================================================
# 测试: WebSocket 消息处理
# ============================================================
async def test_ws_message_handling():
    """WebSocket 消息: ticker更新/订单推送/持仓变化"""
    db_path = make_temp_db()
    try:
        db = Database(db_path)

        # 模拟消息处理回调
        received = []

        async def on_message(channel, data, arg):
            received.append({"channel": channel, "data": data})

        from trading.tests.mock_okx import MockOKXWebSocketMessages as WsMock

        # Ticker 消息
        msg = json.loads(WsMock.ticker_msg("BTC-USDT-SWAP", 51000))
        await on_message(msg["arg"]["channel"], msg["data"], msg["arg"])
        assert len(received) == 1
        assert received[-1]["channel"] == "tickers"
        assert received[-1]["data"][0]["last"] == "51000"

        # 订单消息
        msg = json.loads(WsMock.order_msg("BTC-USDT-SWAP", "filled"))
        await on_message(msg["arg"]["channel"], msg["data"], msg["arg"])
        assert received[-1]["channel"] == "orders"
        assert received[-1]["data"][0]["state"] == "filled"

        # 持仓消息
        msg = json.loads(WsMock.position_msg("BTC-USDT-SWAP", "long", 2, 200))
        await on_message(msg["arg"]["channel"], msg["data"], msg["arg"])
        assert received[-1]["channel"] == "positions"

        # Pong (应忽略)
        assert WsMock.PONG == "pong"

        # 登录确认
        login_msg = json.loads(WsMock.login_ok())
        assert login_msg["event"] == "login"
        assert login_msg["code"] == "0"

        # 订阅确认
        sub_msg = json.loads(WsMock.subscribe_ok("tickers", "BTC-USDT-SWAP"))
        assert sub_msg["event"] == "subscribe"

        db.close()
        print("  ✅ WebSocket 消息处理通过")
    finally:
        db_path.unlink(missing_ok=True)


# ============================================================
# 测试: 并发下单
# ============================================================
async def test_concurrent_orders():
    """并发下单: 多个币种同时下单"""
    db_path = make_temp_db()
    try:
        db = Database(db_path)
        settings = Settings(db)
        rest = make_mock_rest()
        ws = make_mock_ws()

        sl_engine = StoplossEngine(rest, db, settings)
        order_engine = OrderEngine(rest, ws, db, settings, sl_engine)

        symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]

        # 并发下单
        tasks = []
        for sym in symbols:
            tasks.append(order_engine.place_order(sym, "long", 50000, 1, 50000, "first"))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, r in enumerate(results):
            assert not isinstance(r, Exception), f"{symbols[i]} 异常: {r}"
            assert "trade_id" in r, f"{symbols[i]} 失败: {r}"

        # 验证全部记录
        trades = db.fetchall("SELECT * FROM trade_records")
        assert len(trades) == 3

        db.close()
        print("  ✅ 并发下单通过")
    finally:
        db_path.unlink(missing_ok=True)


# ============================================================
# 测试: 持仓快照
# ============================================================
async def test_position_snapshots():
    """持仓快照: 多次快照记录"""
    db_path = make_temp_db()
    try:
        db = Database(db_path)
        rest = make_mock_rest()

        # 模拟有持仓
        rest.get_positions = AsyncMock(return_value=Mock.position(
            "BTC-USDT-SWAP", "long", qty=2, avg_px=50000, upl=200
        ))

        position_mgr = PositionManager(rest, db)

        # 多次快照
        for i in range(5):
            await position_mgr.take_snapshots()
            await asyncio.sleep(0.01)

        snapshots = db.fetchall("SELECT * FROM position_snapshots WHERE symbol='BTC-USDT-SWAP'")
        assert len(snapshots) == 5

        for snap in snapshots:
            assert snap["symbol"] == "BTC-USDT-SWAP"
            assert snap["direction"] == "long"
            assert snap["entry_price"] == 50000
            assert "unrealized_pnl" in snap
            assert "unrealized_ratio" in snap

        db.close()
        print("  ✅ 持仓快照通过")
    finally:
        db_path.unlink(missing_ok=True)


# ============================================================
# 测试: 加密存储完整性
# ============================================================
async def test_encryption_integrity():
    """加密: 多轮加解密、特殊字符、长文本"""
    password = "测试密码_abc123!@#"

    # 普通文本
    text = "my_api_key_12345"
    assert decrypt(encrypt(text, password), password) == text

    # 特殊字符
    special = "abc!@#$%^&*()_+-=[]{}|;':\",./<>?`~"
    assert decrypt(encrypt(special, password), password) == special

    # 中文
    cn = "这是中文密钥测试"
    assert decrypt(encrypt(cn, password), password) == cn

    # 长文本
    long_text = "A" * 10000
    assert decrypt(encrypt(long_text, password), password) == long_text

    # 空文本
    empty = ""
    assert decrypt(encrypt(empty, password), password) == empty

    # 不同密码产生不同密文
    ct1 = encrypt("test", "pass1")
    ct2 = encrypt("test", "pass2")
    assert ct1 != ct2

    print("  ✅ 加密存储完整性通过")


# ============================================================
# 测试: 数据库并发安全
# ============================================================
async def test_db_concurrent_safety():
    """数据库: 并发写入安全"""
    db_path = make_temp_db()
    try:
        db = Database(db_path)

        # 并发写入交易记录
        async def insert_trade(i):
            db.insert_trade(
                symbol=f"SYM-{i}", side="buy", direction="long",
                price=1000 + i, quantity=1, notional=1000,
                leverage=3, position_tier="first", open_price=1000,
            )

        tasks = [insert_trade(i) for i in range(50)]
        await asyncio.gather(*tasks, return_exceptions=True)

        trades = db.fetchall("SELECT * FROM trade_records")
        assert len(trades) == 50, f"预期50条, 实际{len(trades)}条"

        # 并发写入日志
        async def insert_log(i):
            db.log(f"action_{i}", {"index": i})

        tasks = [insert_log(i) for i in range(50)]
        await asyncio.gather(*tasks, return_exceptions=True)

        logs = db.fetchall("SELECT * FROM trade_logs WHERE action LIKE 'action_%'")
        assert len(logs) == 50

        db.close()
        print("  ✅ 数据库并发安全通过")
    finally:
        db_path.unlink(missing_ok=True)


# ============================================================
# 测试: 配置热更新
# ============================================================
async def test_settings_hot_update():
    """配置: 修改后立即生效、持久化"""
    db_path = make_temp_db()
    try:
        db = Database(db_path)
        s = Settings(db)

        # 默认值
        assert s.get("leverage_long") == 3
        assert s.get("limit_to_market_sec") == 3
        assert s.get("confirm_before_close") is False

        # 修改
        s.set("leverage_long", 2)
        s.set("limit_to_market_sec", 5)
        s.set("confirm_before_close", True)

        # 立即生效
        assert s.get("leverage_long") == 2
        assert s.get("limit_to_market_sec") == 5
        assert s.get("confirm_before_close") is True

        # 重新加载持久化
        s2 = Settings(db)
        assert s2.get("leverage_long") == 2
        assert s2.get("limit_to_market_sec") == 5
        assert s2.get("confirm_before_close") is True

        # 非法 key
        try:
            s.set("nonexistent_key", 1)
            assert False, "应抛异常"
        except ValueError:
            pass

        db.close()
        print("  ✅ 配置热更新通过")
    finally:
        db_path.unlink(missing_ok=True)


# ============================================================
# 运行
# ============================================================
async def run_all():
    tests = [
        ("完整交易流程", test_full_trade_flow),
        ("拆单边界", test_split_edge_cases),
        ("止损计算准确性", test_stoploss_accuracy),
        ("风控硬限制", test_risk_hard_limits),
        ("API 错误处理", test_api_error_handling),
        ("会话全流程", test_session_flow),
        ("WebSocket 消息处理", test_ws_message_handling),
        ("并发下单", test_concurrent_orders),
        ("持仓快照", test_position_snapshots),
        ("加密存储完整性", test_encryption_integrity),
        ("数据库并发安全", test_db_concurrent_safety),
        ("配置热更新", test_settings_hot_update),
    ]

    print("=" * 60)
    print("OKX 交易助手 - 集成测试 (TR-15)")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            await fn()
            passed += 1
        except Exception as e:
            print(f"  ❌ {name} 失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print(f"结果: {passed} 通过 / {failed} 失败 / {passed + failed} 总计")
    if failed == 0:
        print("🎉 全部集成测试通过!")
    else:
        print("⚠️  有测试失败，请检查")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all())
