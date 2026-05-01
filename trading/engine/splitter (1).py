"""
OKX 交易助手 - 智能拆单引擎
"""
import random
from typing import NamedTuple

from trading.core.settings import Settings
from trading.core.logger import log


class SubOrder(NamedTuple):
    symbol: str
    side: str           # buy / sell
    pos_side: str       # long / short
    quantity: float     # 张数
    price: float        # 限价


def split_order(symbol: str, side: str, pos_side: str,
                total_qty: float, price: float, notional_usdt: float,
                settings: Settings) -> list[SubOrder]:
    """
    智能拆单逻辑
    - 名义价值 > 阈值时自动拆分
    - 子订单数量加入随机浮动因子
    - 最后一笔补齐总量误差
    """
    threshold = settings.get("split_threshold")
    if notional_usdt <= threshold:
        return [SubOrder(symbol, side, pos_side, total_qty, price)]

    # 计算拆单数量 (按张数整数拆分)
    # 平均拆为 N 单，每单约 400~800U
    avg_size = threshold * 0.7  # 每单目标约 560U
    n_splits = max(2, int(notional_usdt / avg_size))
    # 张数不足时，减少拆单数
    n_splits = min(n_splits, int(total_qty))

    random_min = settings.get("split_random_min")
    random_max = settings.get("split_random_max")

    # 生成随机权重
    weights = [1.0 + random.uniform(random_min, random_max) for _ in range(n_splits)]
    total_weight = sum(weights)

    sub_orders = []
    remaining = total_qty

    for i in range(n_splits):
        if i == n_splits - 1:
            # 最后一笔补齐
            qty = remaining
        else:
            qty = round(total_qty * weights[i] / total_weight)
            qty = max(1, min(qty, remaining - (n_splits - i - 1)))

        remaining -= qty
        if qty > 0:
            sub_orders.append(SubOrder(symbol, side, pos_side, qty, price))

    log.info(f"拆单: {total_qty}张 -> {len(sub_orders)}笔, 总价值≈{notional_usdt:.0f}U")
    return sub_orders
