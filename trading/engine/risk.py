"""
OKX 交易助手 - 风控控制器
"""
from trading.core.settings import Settings
from trading.core.logger import log
from trading.config import (
    DEFAULT_LEVERAGE_LONG_MAX, DEFAULT_LEVERAGE_SHORT_MAX,
    POSITION_MIN_BALANCE, POSITION_TIER_1, POSITION_TIER_2, POSITION_TIER_3,
)


class RiskController:
    """
    强制风控
    - 杠杆上限硬限制 (多单≤3x, 空单≤2x)
    - 仓位分配规则 (≥1500U 时强制)
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_leverage(self, direction: str, leverage: int) -> tuple[bool, str]:
        """
        验证杠杆是否在硬限制内
        返回: (通过, 原因)
        """
        max_lever = (DEFAULT_LEVERAGE_LONG_MAX if direction == "long"
                     else DEFAULT_LEVERAGE_SHORT_MAX)
        if leverage > max_lever:
            return False, f"{'做多' if direction == 'long' else '做空'}杠杆上限为 {max_lever}x，当前设置 {leverage}x 超限"
        if leverage < 1:
            return False, "杠杆倍数不能低于 1x"
        return True, ""

    def get_position_allocation(self, balance_usdt: float, tier: str) -> float:
        """
        获取仓位分配比例
        balance_usdt: 账户可用余额
        tier: first / add1 / add2
        """
        if balance_usdt < POSITION_MIN_BALANCE:
            # 低于阈值，不限制
            return 1.0

        tier_map = {
            "first": POSITION_TIER_1,  # 50%
            "add1":  POSITION_TIER_2,  # 25%
            "add2":  POSITION_TIER_3,  # 25%
        }
        return tier_map.get(tier, 0)

    def validate_order(self, direction: str, leverage: int,
                       balance_usdt: float, tier: str) -> tuple[bool, str]:
        """
        综合下单前风控校验
        返回: (通过, 原因)
        """
        # 杠杆校验
        ok, msg = self.validate_leverage(direction, leverage)
        if not ok:
            return False, msg

        # 仓位分配校验
        alloc = self.get_position_allocation(balance_usdt, tier)
        if alloc == 0:
            return False, f"未知仓位档位: {tier}"

        return True, ""

    def calc_max_notional(self, balance_usdt: float, leverage: int, tier: str) -> float:
        """计算当前档位最大名义价值"""
        alloc = self.get_position_allocation(balance_usdt, tier)
        return balance_usdt * alloc * leverage
