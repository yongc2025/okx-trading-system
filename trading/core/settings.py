"""
OKX 交易助手 - 用户配置管理
"""
from typing import Any
from trading.data.database import Database
import trading.config as defaults


# 配置项定义: key -> (类型, 默认值, 描述)
SETTINGS_SCHEMA = {
    "leverage_long":        (int,   defaults.DEFAULT_LEVERAGE_LONG,       "做多杠杆倍数"),
    "leverage_long_max":    (int,   defaults.DEFAULT_LEVERAGE_LONG_MAX,   "做多杠杆上限"),
    "leverage_short":       (int,   defaults.DEFAULT_LEVERAGE_SHORT,      "做空杠杆倍数"),
    "leverage_short_max":   (int,   defaults.DEFAULT_LEVERAGE_SHORT_MAX,  "做空杠杆上限"),
    "split_threshold":      (float, defaults.SPLIT_THRESHOLD_USDT,        "拆单阈值 (USDT)"),
    "split_random_min":     (float, defaults.SPLIT_RANDOM_RANGE[0],       "拆单随机浮动下限"),
    "split_random_max":     (float, defaults.SPLIT_RANDOM_RANGE[1],       "拆单随机浮动上限"),
    "limit_to_market_sec":  (int,   defaults.LIMIT_TO_MARKET_TIMEOUT,     "限价转市价超时 (秒)"),
    "confirm_before_close": (bool,  False,                                "一键全平二次确认"),
    "hotkey_long":          (str,   "F1",                                 "做多快捷键"),
    "hotkey_short":         (str,   "F2",                                 "做空快捷键"),
    "hotkey_closeall":      (str,   "F3",                                 "全平快捷键"),
    "hotkey_scope":         (str,   "global",                             "快捷键作用域: global / app"),
    "use_demo":             (bool,  False,                                "使用模拟盘"),
    "toast_enabled":        (bool,  True,                                 "启用通知弹窗"),
}


class Settings:
    """运行时配置管理，支持热更新"""

    def __init__(self, db: Database):
        self._db = db
        self._cache: dict[str, Any] = {}
        self._load_all()

    def _load_all(self):
        for key, (typ, default, _) in SETTINGS_SCHEMA.items():
            val = self._db.get_setting(key, default)
            self._cache[key] = self._coerce(val, typ)

    @staticmethod
    def _coerce(val, typ):
        if val is None:
            return None
        if typ is bool:
            if isinstance(val, bool):
                return val
            return str(val).lower() in ("1", "true", "yes")
        return typ(val)

    def get(self, key: str) -> Any:
        if key in self._cache:
            return self._cache[key]
        if key in SETTINGS_SCHEMA:
            return SETTINGS_SCHEMA[key][1]
        return None

    def set(self, key: str, value: Any):
        if key not in SETTINGS_SCHEMA:
            raise ValueError(f"Unknown setting: {key}")
        typ = SETTINGS_SCHEMA[key][0]
        coerced = self._coerce(value, typ)
        self._cache[key] = coerced
        self._db.set_setting(key, coerced)

    def all(self) -> dict[str, Any]:
        return dict(self._cache)

    def schema(self) -> dict:
        return {k: {"type": v[0].__name__, "default": v[1], "desc": v[2]}
                for k, v in SETTINGS_SCHEMA.items()}
