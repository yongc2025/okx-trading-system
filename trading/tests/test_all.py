"""
OKX 交易助手 - 交易模块测试
"""
import sys
import os
import asyncio
import tempfile
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_schema():
    """测试数据库初始化"""
    from trading.data.schema import init_db
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        conn = init_db(db_path)
        # 验证表存在
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        expected = {
            "api_credentials", "app_settings", "favorite_symbols",
            "trade_records", "position_snapshots", "stoploss_orders",
            "trade_logs", "scan_results",
        }
        assert expected.issubset(table_names), f"缺少表: {expected - table_names}"
        conn.close()
        print("✅ schema 初始化通过")
    finally:
        db_path.unlink(missing_ok=True)


def test_encryption():
    """测试加密解密"""
    from trading.core.encryption import encrypt, decrypt
    password = "test_password_123"
    plaintext = "my_api_key_secret_abc123"

    encrypted = encrypt(plaintext, password)
    assert encrypted != plaintext, "加密后应不同"
    assert len(encrypted) > 0, "加密结果不应为空"

    decrypted = decrypt(encrypted, password)
    assert decrypted == plaintext, "解密应恢复原文"

    # 错误密码
    try:
        decrypt(encrypted, "wrong_password")
        assert False, "错误密码应抛异常"
    except Exception:
        pass

    print("✅ 加密解密通过")


def test_database():
    """测试数据库 CRUD"""
    from trading.data.database import Database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        db = Database(db_path)

        # 设置
        db.set_setting("test_key", {"a": 1})
        val = db.get_setting("test_key")
        assert val == {"a": 1}, f"设置读取失败: {val}"

        # 常用币种
        db.touch_favorite("BTC-USDT-SWAP")
        db.touch_favorite("BTC-USDT-SWAP")
        favs = db.get_favorites()
        assert len(favs) == 1
        assert favs[0]["use_count"] == 2

        # 交易记录
        tid = db.insert_trade(
            symbol="BTC-USDT-SWAP", side="buy", direction="long",
            price=50000, quantity=1, notional=50000, leverage=3,
            position_tier="first", open_price=50000, status="open",
        )
        assert tid > 0
        trades = db.get_open_trades("BTC-USDT-SWAP")
        assert len(trades) == 1

        # 日志
        db.log("test", {"msg": "hello"}, symbol="BTC-USDT-SWAP")
        logs = db.fetchall("SELECT * FROM trade_logs")
        assert len(logs) >= 1

        db.close()
        print("✅ 数据库 CRUD 通过")
    finally:
        db_path.unlink(missing_ok=True)


def test_settings():
    """测试配置管理"""
    from trading.data.database import Database
    from trading.core.settings import Settings
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        db = Database(db_path)
        s = Settings(db)

        # 默认值
        assert s.get("leverage_long") == 3
        assert s.get("hotkey_long") == "F1"
        assert s.get("confirm_before_close") is False

        # 修改
        s.set("leverage_long", 2)
        assert s.get("leverage_long") == 2

        # 重新加载
        s2 = Settings(db)
        assert s2.get("leverage_long") == 2

        db.close()
        print("✅ 配置管理通过")
    finally:
        db_path.unlink(missing_ok=True)


def test_splitter():
    """测试拆单逻辑"""
    from trading.data.database import Database
    from trading.core.settings import Settings
    from trading.engine.splitter import split_order
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        db = Database(db_path)
        s = Settings(db)

        # 小单不拆
        orders = split_order("BTC-USDT-SWAP", "buy", "long", 1, 50000, 500, s)
        assert len(orders) == 1

        # 大单拆分
        orders = split_order("BTC-USDT-SWAP", "buy", "long", 10, 50000, 5000, s)
        assert len(orders) >= 2
        total_qty = sum(o.quantity for o in orders)
        assert total_qty == 10, f"拆单总量不等: {total_qty}"

        db.close()
        print("✅ 拆单逻辑通过")
    finally:
        db_path.unlink(missing_ok=True)


def test_stoploss_calc():
    """测试止损价计算"""
    from trading.engine.stoploss import calc_stoploss_price, calc_weighted_avg_price

    # 多单止损
    sl = calc_stoploss_price(100, "long")
    assert sl == 90.0, f"多单止损: {sl}"

    # 空单止损
    sl = calc_stoploss_price(100, "short")
    assert sl == 110.0, f"空单止损: {sl}"

    # 加权均价
    avg = calc_weighted_avg_price(10, 100, 5, 80)
    expected = (10 * 100 + 5 * 80) / 15
    assert abs(avg - expected) < 0.01

    print("✅ 止损计算通过")


def test_risk_controller():
    """测试风控"""
    from trading.core.settings import Settings
    from trading.engine.risk import RiskController
    from trading.data.database import Database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        db = Database(db_path)
        s = Settings(db)
        rc = RiskController(s)

        # 杠杆校验
        ok, _ = rc.validate_leverage("long", 3)
        assert ok
        ok, _ = rc.validate_leverage("long", 4)
        assert not ok
        ok, _ = rc.validate_leverage("short", 2)
        assert ok
        ok, _ = rc.validate_leverage("short", 3)
        assert not ok

        # 仓位分配
        alloc = rc.get_position_allocation(5000, "first")
        assert alloc == 0.5
        alloc = rc.get_position_allocation(500, "first")
        assert alloc == 1.0  # 低于阈值不限制

        db.close()
        print("✅ 风控逻辑通过")
    finally:
        db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    print("=" * 50)
    print("OKX 交易助手 - 交易模块测试")
    print("=" * 50)
    test_schema()
    test_encryption()
    test_database()
    test_settings()
    test_splitter()
    test_stoploss_calc()
    test_risk_controller()
    print()
    print("🎉 全部测试通过!")
