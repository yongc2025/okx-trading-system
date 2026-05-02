"""
OKX 量化回测系统 - 数据下载器
包含：K 线下载器、订单下载器、CSV 订单导入器
"""

import csv
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from backtest.config import (
    DB_PATH,
    DOWNLOAD_BATCH_SIZE,
    TABLE_KLINE_DATA,
    TABLE_DOWNLOAD_STATUS,
    TABLE_TRADE_RECORDS,
)
from backtest.data.okx_client import OKXClient
from backtest.data.schema import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _ms_to_iso(ts_ms: str | int) -> str:
    """毫秒时间戳 → ISO 格式字符串（UTC+8）"""
    dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
    dt = dt.astimezone(timezone(timedelta(hours=8)))
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _iso_to_ms(iso_str: str) -> int:
    """ISO 格式字符串 → 毫秒时间戳（假设 UTC+8）"""
    dt = datetime.strptime(iso_str, "%Y-%m-%d %H:%M:%S")
    dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return int(dt.timestamp() * 1000)


# ===========================================================================
# 1. K 线下载器
# ===========================================================================

class KlineDownloader:
    """K 线下载器"""

    def __init__(self, client: OKXClient, db_path: str | None = None):
        self.client = client
        self.db_path = db_path or str(DB_PATH)
        # 进度追踪：{symbol: {bar: {total, downloaded, status}}}
        self.progress: dict[str, dict[str, dict]] = {}

    # -----------------------------------------------------------------------
    # 公开接口
    # -----------------------------------------------------------------------

    async def download(
        self,
        symbols: list[str],
        bars: list[str],
        days: int = 90,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """
        下载多个币种、多个周期的 K 线

        Args:
            symbols: ["BTC-USDT-SWAP", "ETH-USDT-SWAP", ...]
            bars: ["1m", "5m", "1H", ...]
            days: 下载最近多少天（当 start_date/end_date 未指定时生效）
            start_date: 起始日期 "YYYY-MM-DD"（优先于 days）
            end_date:   结束日期 "YYYY-MM-DD"（默认今天）

        Returns:
            {"total": 100, "downloaded": 80, "errors": [...]}
        """
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        if start_date:
            # 使用自定义日期范围
            dt_start = datetime.strptime(start_date, "%Y-%m-%d")
            dt_start = dt_start.replace(tzinfo=timezone(timedelta(hours=8)))
            start_ms = int(dt_start.timestamp() * 1000)

            if end_date:
                dt_end = datetime.strptime(end_date, "%Y-%m-%d")
                # 结束日期包含当天，取当天 23:59:59
                dt_end = dt_end.replace(hour=23, minute=59, second=59, tzinfo=timezone(timedelta(hours=8)))
                end_ms = int(dt_end.timestamp() * 1000)
            else:
                end_ms = now_ms
        else:
            start_ms = now_ms - days * 24 * 3600 * 1000
            end_ms = now_ms

        total_tasks = len(symbols) * len(bars)
        downloaded = 0
        errors: list[str] = []

        # 初始化进度
        for symbol in symbols:
            self.progress.setdefault(symbol, {})
            for bar in bars:
                self.progress[symbol][bar] = {
                    "total": 0,
                    "downloaded": 0,
                    "status": "pending",
                }

        for symbol in symbols:
            for bar in bars:
                try:
                    count = await self._download_single(symbol, bar, start_ms, end_ms)
                    downloaded += 1
                    self._update_progress(symbol, bar, count, count, "done")
                    logger.info(f"[KlineDownloader] {symbol}/{bar} 下载完成，共 {count} 条")
                except Exception as e:
                    errors.append(f"{symbol}/{bar}: {e}")
                    self._update_progress(symbol, bar, 0, 0, "error")
                    logger.error(f"[KlineDownloader] {symbol}/{bar} 下载失败: {e}")

        return {
            "total": total_tasks,
            "downloaded": downloaded,
            "errors": errors,
        }

    async def _download_single(
        self,
        symbol: str,
        bar: str,
        start_time: int,
        end_time: int,
    ) -> int:
        """
        下载单个 (symbol, bar) 的 K 线

        策略：每次下载前清理该 (symbol, bar) 的旧数据，全量写入新数据。
        保证数据集干净、无断层、无重复。

        Args:
            symbol: 交易对
            bar: K 线周期
            start_time: 起始毫秒时间戳
            end_time: 结束毫秒时间戳

        Returns:
            本次下载的 K 线条数
        """
        # 1. 清理该 (symbol, bar) 的旧数据
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                f"DELETE FROM {TABLE_KLINE_DATA} WHERE symbol=? AND bar=?",
                (symbol, bar),
            )
            conn.execute(
                f"DELETE FROM {TABLE_DOWNLOAD_STATUS} WHERE symbol=? AND bar=?",
                (symbol, bar),
            )
            conn.commit()
            logger.info(f"[KlineDownloader] {symbol}/{bar} 已清理旧数据，准备重新下载")
        finally:
            conn.close()

        effective_start = start_time

        # 2. 分页拉取 K 线
        all_klines: list = []
        after_ms: Optional[int] = None  # OKX 的 after 是 "此时间戳之前的数据"
        batch_count = 0

        while True:
            klines = await self.client.get_history_candles(
                symbol=symbol,
                bar=bar,
                limit=DOWNLOAD_BATCH_SIZE,
                after=str(after_ms) if after_ms else None,
            )

            if not klines:
                break

            # 过滤：只保留 >= effective_start 的数据
            filtered = []
            stop = False
            for k in klines:
                ts = int(k[0])
                if ts < effective_start:
                    stop = True
                    break
                if ts <= end_time:
                    filtered.append(k)

            all_klines.extend(filtered)
            batch_count += len(filtered)

            # 更新进度
            self._update_progress(symbol, bar, batch_count, batch_count, "downloading")

            # 如果已经到达或越过起始点，停止
            if stop or len(klines) < DOWNLOAD_BATCH_SIZE:
                break

            # 下一页：after 参数取本页最后一条的时间戳
            after_ms = int(klines[-1][0])

        # 3. 保存数据
        if all_klines:
            self._save_klines(symbol, bar, all_klines)

        return len(all_klines)

    def get_progress(self) -> dict:
        """获取下载进度（供前端轮询）"""
        return self.progress

    def _save_klines(self, symbol: str, bar: str, klines: list[list]) -> None:
        """
        将 K 线数据写入 kline_data 表

        OKX 返回格式: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        """
        if not klines:
            return

        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            rows = []
            for k in klines:
                ts_iso = _ms_to_iso(k[0])
                rows.append((
                    symbol, bar, ts_iso,
                    float(k[1]),  # open
                    float(k[2]),  # high
                    float(k[3]),  # low
                    float(k[4]),  # close
                    float(k[5]) if k[5] else None,   # volume
                    float(k[6]) if k[6] else None,   # amount
                    "okx",
                ))

            cursor.executemany(
                f"INSERT OR IGNORE INTO {TABLE_KLINE_DATA} "
                "(symbol, bar, time, open, high, low, close, volume, amount, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

            # 更新 download_status
            first_ts = _ms_to_iso(klines[-1][0])   # 最早的时间
            last_ts = _ms_to_iso(klines[0][0])      # 最新的时间
            count = cursor.execute(
                f"SELECT COUNT(*) FROM {TABLE_KLINE_DATA} WHERE symbol=? AND bar=?",
                (symbol, bar),
            ).fetchone()[0]

            cursor.execute(
                f"INSERT OR REPLACE INTO {TABLE_DOWNLOAD_STATUS} "
                "(symbol, bar, last_time, first_time, record_count, updated_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (symbol, bar, last_ts, first_ts, count),
            )

            conn.commit()
        finally:
            conn.close()

    def _update_progress(
        self, symbol: str, bar: str, total: int, downloaded: int, status: str
    ) -> None:
        """更新进度"""
        self.progress.setdefault(symbol, {})
        self.progress[symbol][bar] = {
            "total": total,
            "downloaded": downloaded,
            "status": status,
        }


# ===========================================================================
# 2. 订单下载器
# ===========================================================================

class OrderDownloader:
    """订单下载器"""

    def __init__(self, client: OKXClient, db_path: str | None = None, account_id: str | None = None):
        self.client = client
        self.db_path = db_path or str(DB_PATH)
        self.account_id = account_id

    # -----------------------------------------------------------------------
    # 公开接口
    # -----------------------------------------------------------------------

    async def download(self, inst_type: str = "SWAP") -> dict:
        """
        从 OKX 拉取历史成交记录

        Args:
            inst_type: 产品类型，默认 SWAP（永续合约）

        Returns:
            {"total_fills": 500, "paired_trades": 200, "errors": [...]}
        """
        errors: list[str] = []

        # 1. 拉取所有 fills
        try:
            fills = await self._fetch_all_fills(inst_type)
            logger.info(f"[OrderDownloader] 共拉取 {len(fills)} 条成交记录")
        except Exception as e:
            errors.append(f"拉取成交记录失败: {e}")
            logger.error(f"[OrderDownloader] 拉取成交记录失败: {e}")
            return {"total_fills": 0, "paired_trades": 0, "errors": errors}

        if not fills:
            logger.info("[OrderDownloader] 无成交记录")
            return {"total_fills": 0, "paired_trades": 0, "errors": errors}

        # 2. 配对为完整交易
        try:
            trades = self._pair_fills_to_trades(fills)
            logger.info(f"[OrderDownloader] 配对完成，共 {len(trades)} 笔交易")
        except Exception as e:
            errors.append(f"配对交易失败: {e}")
            logger.error(f"[OrderDownloader] 配对交易失败: {e}")
            return {"total_fills": len(fills), "paired_trades": 0, "errors": errors}

        # 3. 保存到数据库
        try:
            self._save_trades(trades)
        except Exception as e:
            errors.append(f"保存交易失败: {e}")
            logger.error(f"[OrderDownloader] 保存交易失败: {e}")

        return {
            "total_fills": len(fills),
            "paired_trades": len(trades),
            "errors": errors,
        }

    async def _fetch_all_fills(self, inst_type: str) -> list[dict]:
        """分页拉取所有成交记录"""
        all_fills: list[dict] = []
        after: Optional[str] = None

        while True:
            fills = await self.client.get_fills_history(
                inst_type=inst_type,
                limit=100,
                after=after,
            )

            if not fills:
                break

            all_fills.extend(fills)

            # OKX 分页：用最后一条的 ts 作为下一页的 after
            if len(fills) < 100:
                break
            after = fills[-1].get("ts", "")

        return all_fills

    def _pair_fills_to_trades(self, fills: list[dict]) -> list[dict]:
        """
        将原始 fills 配对为完整交易

        逻辑：
        1. 按 ordId 聚合同一订单的多笔成交 → 加权均价、总量、总手续费
        2. 按 symbol 分组
        3. 在每个 symbol 内，按时间排序，配对开平仓
        4. 计算完整交易指标
        """
        # Step 1: 按 ordId 聚合
        orders: dict[str, dict] = {}
        for fill in fills:
            ord_id = fill.get("ordId", "")
            if not ord_id:
                continue

            if ord_id not in orders:
                orders[ord_id] = {
                    "ordId": ord_id,
                    "instId": fill.get("instId", ""),
                    "side": fill.get("side", ""),
                    "posSide": fill.get("posSide", ""),
                    "total_qty": 0.0,
                    "total_cost": 0.0,      # 成交金额 = price * qty
                    "total_fee": 0.0,
                    "feeCcy": fill.get("feeCcy", "USDT"),
                    "ts": fill.get("ts", "0"),
                    "fills_count": 0,
                }

            order = orders[ord_id]
            px = float(fill.get("fillPx", 0))
            sz = float(fill.get("fillSz", 0))
            fee = float(fill.get("fee", 0))

            order["total_qty"] += sz
            order["total_cost"] += px * sz
            order["total_fee"] += fee
            order["fills_count"] += 1
            # 更新时间为最新成交时间
            if fill.get("ts", "0") > order["ts"]:
                order["ts"] = fill["ts"]

        # 计算每个订单的加权均价
        for order in orders.values():
            if order["total_qty"] > 0:
                order["avg_price"] = order["total_cost"] / order["total_qty"]
            else:
                order["avg_price"] = 0.0

        # Step 2: 按 symbol 分组
        symbol_orders: dict[str, list[dict]] = {}
        for order in orders.values():
            inst_id = order["instId"]
            symbol_orders.setdefault(inst_id, []).append(order)

        # Step 3: 配对开仓和平仓
        trades: list[dict] = []

        for symbol, ords in symbol_orders.items():
            # 按时间排序
            ords.sort(key=lambda o: int(o["ts"]))

            # 按 direction (posSide) 分组
            # direction: long / short
            open_orders: dict[str, list[dict]] = {"long": [], "short": []}
            close_orders: dict[str, list[dict]] = {"long": [], "short": []}

            for o in ords:
                side = o["side"]      # buy / sell
                pos_side = o["posSide"]  # long / short / net

                if not pos_side or pos_side == "net":
                    # 单向持仓模式，根据 side 推断
                    # buy → long 开仓, sell → long 平仓 (简化处理)
                    if side == "buy":
                        direction = "long"
                        is_open = True
                    else:
                        direction = "long"
                        is_open = False
                else:
                    direction = pos_side
                    # 开仓判断
                    if (side == "buy" and pos_side == "long") or \
                       (side == "sell" and pos_side == "short"):
                        is_open = True
                    else:
                        is_open = False

                o["_direction"] = direction
                o["_is_open"] = is_open

                if is_open:
                    open_orders.setdefault(direction, []).append(o)
                else:
                    close_orders.setdefault(direction, []).append(o)

            # 配对：对每个 direction，按时间顺序配对开仓和平仓
            for direction in ("long", "short"):
                opens = open_orders.get(direction, [])
                closes = close_orders.get(direction, [])
                used_close_indices: set[int] = set()

                for open_order in opens:
                    open_ts = int(open_order["ts"])

                    # 找到时间最近的未配对平仓订单
                    best_close: Optional[dict] = None
                    best_idx: Optional[int] = None

                    for idx, close_order in enumerate(closes):
                        if idx in used_close_indices:
                            continue
                        close_ts = int(close_order["ts"])
                        if close_ts >= open_ts:
                            if best_close is None or close_ts < int(best_close["ts"]):
                                best_close = close_order
                                best_idx = idx
                                break

                    if best_close is not None and best_idx is not None:
                        used_close_indices.add(best_idx)
                        trade = self._build_trade_record(
                            symbol, direction, open_order, best_close
                        )
                        trades.append(trade)
                    else:
                        # 无配对平仓，可能持仓中，跳过
                        logger.debug(
                            f"[OrderDownloader] {symbol}/{direction} 存在未配对开仓订单 "
                            f"ordId={open_order['ordId']}，跳过"
                        )

        return trades

    def _build_trade_record(
        self,
        symbol: str,
        direction: str,
        open_order: dict,
        close_order: dict,
    ) -> dict:
        """构建单笔交易记录"""
        entry_price = open_order["avg_price"]
        exit_price = close_order["avg_price"]
        qty = open_order["total_qty"]

        entry_cost = open_order["total_cost"]
        exit_value = close_order["total_cost"]
        total_fee = abs(open_order["total_fee"]) + abs(close_order["total_fee"])

        # 计算盈亏
        if direction == "long":
            pnl = exit_value - entry_cost - total_fee
        else:
            pnl = entry_cost - exit_value - total_fee

        pnl_rate = pnl / entry_cost if entry_cost > 0 else 0.0

        # ROI = pnl / entry_cost
        roi = pnl_rate

        is_win = 1 if pnl > 0 else 0
        is_loss = 1 if pnl < 0 else 0

        # 持仓时长
        entry_time = _ms_to_iso(open_order["ts"])
        exit_time = _ms_to_iso(close_order["ts"])

        trade_id = f"okx_{symbol}_{direction}_{open_order['ts']}"

        return {
            "trade_id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "leverage": 1,  # OKX fills 不含杠杆信息，默认 1
            "entry_time": entry_time,
            "entry_price": entry_price,
            "entry_qty": qty,
            "entry_cost": entry_cost,
            "exit_time": exit_time,
            "exit_price": exit_price,
            "exit_qty": qty,
            "exit_value": exit_value,
            "pnl": round(pnl, 6),
            "pnl_rate": round(pnl_rate, 6),
            "roi": round(roi, 6),
            "is_win": is_win,
            "is_loss": is_loss,
        }

    def _save_trades(self, trades: list[dict]) -> None:
        """将配对后的交易写入 trade_records 表"""
        if not trades:
            return

        conn = get_connection(self.db_path)
        try:
            cursor = conn.cursor()
            for trade in trades:
                cursor.execute(
                    f"INSERT OR IGNORE INTO {TABLE_TRADE_RECORDS} "
                    "(trade_id, account_id, symbol, direction, leverage, entry_time, entry_price, "
                    "entry_qty, entry_cost, exit_time, exit_price, exit_qty, exit_value, "
                    "pnl, pnl_rate, roi, is_win, is_loss) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        trade["trade_id"],
                        self.account_id,
                        trade["symbol"],
                        trade["direction"],
                        trade["leverage"],
                        trade["entry_time"],
                        trade["entry_price"],
                        trade["entry_qty"],
                        trade["entry_cost"],
                        trade["exit_time"],
                        trade["exit_price"],
                        trade["exit_qty"],
                        trade["exit_value"],
                        trade["pnl"],
                        trade["pnl_rate"],
                        trade["roi"],
                        trade["is_win"],
                        trade["is_loss"],
                    ),
                )
            conn.commit()
            logger.info(f"[OrderDownloader] 保存 {len(trades)} 笔交易到数据库 (account_id={self.account_id})")
        finally:
            conn.close()


# ===========================================================================
# 3. CSV 订单导入器
# ===========================================================================

class OrderImporter:
    """CSV 订单导入器"""

    # CSV 必填列
    REQUIRED_COLUMNS = {"symbol", "direction", "entry_time", "entry_price", "exit_time", "exit_price"}
    # CSV 可选列
    OPTIONAL_COLUMNS = {"leverage", "entry_cost", "max_floating_loss", "max_floating_loss_rate"}
    # 合法 direction
    VALID_DIRECTIONS = {"long", "short"}
    # 时间格式（兼容有秒和无秒两种）
    TIME_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]

    @staticmethod
    def _parse_time(time_str: str) -> datetime | None:
        """尝试多种格式解析时间字符串"""
        for fmt in OrderImporter.TIME_FORMATS:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def generate_template(output_path: str | Path) -> Path:
        """
        生成 CSV 导入模板

        Args:
            output_path: 输出文件路径

        Returns:
            模板文件路径
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "symbol", "direction", "entry_time", "entry_price",
                "exit_time", "exit_price", "leverage", "entry_cost",
            ])
            # 示例行
            writer.writerow([
                "BTC-USDT-SWAP", "long", "2025-01-15 10:30", "42500.5",
                "2025-01-15 14:20:30", "43100.2", "3", "1000",
            ])

        logger.info(f"[OrderImporter] 模板已生成: {output_path}")
        return output_path

    @staticmethod
    def validate_csv(csv_path: str | Path) -> tuple[list[dict], list[str]]:
        """
        校验 CSV 文件

        Args:
            csv_path: CSV 文件路径

        Returns:
            (valid_records, errors)
        """
        csv_path = Path(csv_path)
        if not csv_path.exists():
            return [], [f"文件不存在: {csv_path}"]

        valid_records: list[dict] = []
        errors: list[str] = []

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            # 检查列头
            if reader.fieldnames is None:
                return [], ["CSV 文件为空或格式错误"]

            headers = {h.strip().lower() for h in reader.fieldnames}
            missing = OrderImporter.REQUIRED_COLUMNS - headers
            if missing:
                return [], [f"缺少必填列: {', '.join(sorted(missing))}"]

            for row_num, row in enumerate(reader, start=2):
                try:
                    # 清理字段名空格
                    clean_row = {k.strip().lower(): v.strip() for k, v in row.items() if k}

                    # 验证必填字段
                    symbol = clean_row.get("symbol", "")
                    if not symbol:
                        errors.append(f"第 {row_num} 行: symbol 为空")
                        continue

                    direction = clean_row.get("direction", "").lower()
                    if direction not in OrderImporter.VALID_DIRECTIONS:
                        errors.append(f"第 {row_num} 行: direction 必须为 long/short，实际: {direction}")
                        continue

                    # 解析时间
                    entry_time_str = clean_row.get("entry_time", "")
                    exit_time_str = clean_row.get("exit_time", "")
                    entry_time = OrderImporter._parse_time(entry_time_str)
                    if entry_time is None:
                        errors.append(f"第 {row_num} 行: entry_time 格式错误 '{entry_time_str}'，应为 YYYY-MM-DD HH:MM 或 YYYY-MM-DD HH:MM:SS")
                        continue
                    exit_time = OrderImporter._parse_time(exit_time_str)
                    if exit_time is None:
                        errors.append(f"第 {row_num} 行: exit_time 格式错误 '{exit_time_str}'，应为 YYYY-MM-DD HH:MM 或 YYYY-MM-DD HH:MM:SS")
                        continue

                    if exit_time <= entry_time:
                        errors.append(f"第 {row_num} 行: exit_time 必须晚于 entry_time")
                        continue

                    # 解析价格
                    try:
                        entry_price = float(clean_row.get("entry_price", 0))
                    except (ValueError, TypeError):
                        errors.append(f"第 {row_num} 行: entry_price 不是有效数字")
                        continue
                    try:
                        exit_price = float(clean_row.get("exit_price", 0))
                    except (ValueError, TypeError):
                        errors.append(f"第 {row_num} 行: exit_price 不是有效数字")
                        continue

                    if entry_price <= 0 or exit_price <= 0:
                        errors.append(f"第 {row_num} 行: 价格必须大于 0")
                        continue

                    # 可选字段
                    leverage = 1
                    if clean_row.get("leverage"):
                        try:
                            leverage = int(float(clean_row["leverage"]))
                            if leverage < 1:
                                leverage = 1
                        except (ValueError, TypeError):
                            leverage = 1

                    entry_cost = 1000.0
                    if clean_row.get("entry_cost"):
                        try:
                            entry_cost = float(clean_row["entry_cost"])
                            if entry_cost <= 0:
                                entry_cost = 1000.0
                        except (ValueError, TypeError):
                            entry_cost = 1000.0

                    # 可选：最大浮亏字段
                    max_floating_loss = 0.0
                    if clean_row.get("max_floating_loss"):
                        try:
                            max_floating_loss = float(clean_row["max_floating_loss"])
                        except (ValueError, TypeError):
                            max_floating_loss = 0.0

                    max_floating_loss_rate = 0.0
                    if clean_row.get("max_floating_loss_rate"):
                        try:
                            max_floating_loss_rate = float(clean_row["max_floating_loss_rate"])
                        except (ValueError, TypeError):
                            max_floating_loss_rate = 0.0

                    valid_records.append({
                        "symbol": symbol,
                        "direction": direction,
                        "entry_time": entry_time,
                        "entry_price": entry_price,
                        "exit_time": exit_time,
                        "exit_price": exit_price,
                        "leverage": leverage,
                        "entry_cost": entry_cost,
                        "max_floating_loss": max_floating_loss,
                        "max_floating_loss_rate": max_floating_loss_rate,
                    })

                except Exception as e:
                    errors.append(f"第 {row_num} 行: 解析异常 - {e}")

        return valid_records, errors

    @staticmethod
    def import_csv(csv_path: str | Path, db_path: str | None = None, account_id: str | None = None) -> dict:
        """
        导入 CSV 到 trade_records 表

        Args:
            csv_path: CSV 文件路径
            db_path: 数据库路径
            account_id: 绑定的账户 ID

        Returns:
            {"imported": 50, "skipped": 3, "errors": [...]}
        """
        # 1. 校验
        valid_records, validation_errors = OrderImporter.validate_csv(csv_path)
        if not valid_records and validation_errors:
            return {"imported": 0, "skipped": 0, "errors": validation_errors}

        # 2. 写入数据库
        db_path = db_path or str(DB_PATH)
        conn = get_connection(db_path)
        imported = 0
        skipped = 0
        write_errors: list[str] = []

        try:
            cursor = conn.cursor()

            for rec in valid_records:
                # 自动计算指标
                entry_cost = rec["entry_cost"]
                leverage = rec["leverage"]
                entry_price = rec["entry_price"]
                exit_price = rec["exit_price"]
                direction = rec["direction"]

                # 仓位数量 = entry_cost * leverage / entry_price
                entry_qty = (entry_cost * leverage) / entry_price if entry_price > 0 else 0
                exit_value = entry_qty * exit_price

                # 盈亏计算
                if direction == "long":
                    pnl = exit_value - entry_cost * leverage
                else:
                    pnl = entry_cost * leverage - exit_value

                pnl_rate = pnl / (entry_cost * leverage) if entry_cost > 0 else 0
                roi = pnl_rate
                is_win = 1 if pnl > 0 else 0
                is_loss = 1 if pnl < 0 else 0

                # 扛单字段（CSV提供则用CSV值，否则默认0）
                mfl = rec.get("max_floating_loss", 0.0) or 0.0
                mflr = rec.get("max_floating_loss_rate", 0.0) or 0.0
                exceeded = 1 if mflr > 0.10 else 0

                # 生成唯一 trade_id
                trade_id = f"csv_{rec['symbol']}_{direction}_{rec['entry_time'].strftime('%Y%m%d%H%M')}_{uuid.uuid4().hex[:8]}"

                try:
                    cursor.execute(
                        f"INSERT OR IGNORE INTO {TABLE_TRADE_RECORDS} "
                        "(trade_id, account_id, symbol, direction, leverage, entry_time, entry_price, "
                        "entry_qty, entry_cost, exit_time, exit_price, exit_qty, exit_value, "
                        "pnl, pnl_rate, roi, is_win, is_loss, "
                        "max_floating_loss, max_floating_loss_rate, exceeded_stoploss) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            trade_id,
                            account_id,
                            rec["symbol"],
                            direction,
                            leverage,
                            rec["entry_time"].strftime("%Y-%m-%d %H:%M:%S"),
                            entry_price,
                            round(entry_qty, 8),
                            entry_cost,
                            rec["exit_time"].strftime("%Y-%m-%d %H:%M:%S"),
                            exit_price,
                            round(entry_qty, 8),
                            round(exit_value, 6),
                            round(pnl, 6),
                            round(pnl_rate, 6),
                            round(roi, 6),
                            is_win,
                            is_loss,
                            round(mfl, 6),
                            round(mflr, 6),
                            exceeded,
                        ),
                    )
                    if cursor.rowcount > 0:
                        imported += 1
                    else:
                        skipped += 1
                except Exception as e:
                    write_errors.append(f"写入失败 {rec['symbol']}: {e}")

            conn.commit()
            logger.info(f"[OrderImporter] 导入完成: imported={imported}, skipped={skipped}")

        finally:
            conn.close()

        all_errors = validation_errors + write_errors
        return {
            "imported": imported,
            "skipped": skipped,
            "errors": all_errors,
        }