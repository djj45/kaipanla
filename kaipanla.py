# -*- coding: utf-8 -*-
"""
开盘啦行情数据统一接口

四个核心方法：
    get_intraday(code, ...)        — 分时数据（当日实时 / 历史单日 / 历史多日）
    get_kline(code, ...)           — 日K线序列
    get_turnover_curve(date, ...)  — 成交额预测曲线（当日实时 / 历史日期）
    get_market_sentiment()         — 市场情绪概览（涨停跌停、涨跌平盘家数）

自动识别 A股个股 / A股指数 / 美股个股 / 美股指数，调用方无需关心后端差异。
全部通过 HTTP API 获取，无需 frida / 模拟器 / 认证。

用法：
    from kaipanla import KaipanlaCrawler

    crawler = KaipanlaCrawler()

    # 分时
    df = crawler.get_intraday("000938")                    # A股个股 当日
    df = crawler.get_intraday("000938", date="2026-07-07")  # A股个股 历史
    df = crawler.get_intraday("SH000001")                   # A股指数
    df = crawler.get_intraday("US:SNDK")                    # 美股个股 (仅当日)
    df = crawler.get_intraday("IXIC")                       # 海外指数 (仅当日)

    # 日K
    df = crawler.get_kline("000938", count=100)
    df = crawler.get_kline("US:SNDK", start="2026-01-01", end="2026-07-07")

    # 成交额预测曲线
    df = crawler.get_turnover_curve()                       # 当日实时
    df = crawler.get_turnover_curve(date="2026-07-08")      # 历史日期

    # 市场情绪
    s = crawler.get_market_sentiment()                      # 涨停/跌停/涨跌平盘家数
"""

import uuid
from datetime import datetime, timedelta

import pandas as pd
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# 已知的海外指数代码（无市场前缀）
_OVERSEAS_INDICES = {"IXIC", "DJI", "SPX", "INX", "NDX", "RUT", "VIX",
                     "HSI", "HSCEI", "HSTECH", "N225", "UKX", "DAX", "CAC"}


def _classify(code):
    """判断代码属于哪个市场/类型。

    Returns: 'a_stock' | 'a_index' | 'us_stock' | 'us_index'
    """
    code = code.strip().upper()

    # 海外个股（带前缀）
    if code.startswith("US:") or code.startswith("HK:"):
        return "us_stock"

    # 海外指数（无前缀，在已知列表中）
    if code in _OVERSEAS_INDICES:
        return "us_index"

    # A股指数（SH000xxx / SZ399xxx）
    if (code.startswith("SH") and code[2:].startswith("000")) or \
       (code.startswith("SZ") and code[2:].startswith("399")):
        return "a_index"

    # 带市场前缀的A股个股
    if code.startswith(("SH", "SZ")):
        return "a_stock"

    # 纯数字：按代码规则判断
    if code.isdigit():
        c = code[0]
        if c == "6" or code.startswith("68") or code.startswith("9"):
            return "a_stock"  # 沪市
        if c in ("0", "3"):
            return "a_stock"  # 深市
        return "a_stock"

    return "a_stock"


def _is_today(date_str):
    """判断日期字符串是否是今天"""
    if not date_str:
        return True
    return date_str == datetime.now().strftime("%Y-%m-%d")


def _trading_dates(start, end):
    """获取日期范围内的交易日列表（排除周末）"""
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    dates = []
    cur = s
    while cur <= e:
        if cur.weekday() < 5:  # 周一到周五
            dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return dates


class KaipanlaCrawler:
    """开盘啦行情数据统一接口"""

    def __init__(self):
        # A股历史数据域名
        self.base_url = "https://apphis.longhuvip.com/w1/api/index.php"
        # A股实时数据域名
        self.sector_url = "https://apphwhq.longhuvip.com/w1/api/index.php"
        # 海外行情域名（美股/海外指数，安卓版专用）
        self.global_url = "https://apphwshhq.longhuvip.com/w1/api/index.php"

        self.headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; PHU110 Build/W528JS)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
        }

    def _post(self, url, params, timeout=30):
        """发送 POST 请求并返回 JSON"""
        headers = dict(self.headers)
        headers["Host"] = url.split("//")[1].split("/")[0]
        try:
            resp = requests.post(
                url, data=params, headers=headers,
                verify=False, proxies={"http": None, "https": None}, timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"请求失败 ({url}, {params.get('a', '?')}): {e}")
            return {}

    # ============================================================
    #  统一入口
    # ============================================================

    def get_intraday(self, code, date=None, start=None, end=None):
        """获取分时数据

        Args:
            code: 股票/指数代码
            date: 单日 "YYYY-MM-DD"（可选）
            start/end: 日期范围 "YYYY-MM-DD"（可选）
            不传日期 → 当日实时

        Returns: DataFrame，列 [date, time, price, yellow_line, volume, ddje, flag]
                 ddje 仅 A股个股有值，其余为 NaN
        """
        market = _classify(code)

        # 美股不支持历史分时
        # 美股不支持历史分时：传了 date（非今天）或 start 即报错
        if market in ("us_stock", "us_index"):
            if (date and not _is_today(date)) or start:
                raise ValueError(f"美股({code})不支持历史分时，仅支持当日实时")

        # 确定要查询的日期列表
        if start and end:
            dates = _trading_dates(start, end)
        elif date:
            dates = [date]
        else:
            dates = [None]  # None 表示当日实时

        frames = []
        for d in dates:
            if market == "a_stock":
                df = self._a_stock_intraday(code, d)
            elif market == "a_index":
                df = self._a_index_intraday(code, d)
            elif market == "us_stock":
                df = self._us_stock_intraday(code)
            else:
                df = self._us_index_intraday(code)
            if df is not None and len(df) > 0:
                frames.append(df)

        if not frames:
            return pd.DataFrame(columns=["date", "time", "price", "yellow_line", "volume", "ddje", "flag"])

        result = pd.concat(frames, ignore_index=True)
        return result

    def get_kline(self, code, count=100, start=None, end=None):
        """获取日K线序列

        Args:
            code: 股票/指数代码
            count: 返回最近 N 天（默认100），与 start/end 二选一
            start/end: 日期范围（可选，优先于 count）

        Returns: DataFrame，列 [date, open, close, high, low, volume, amount, turnover_ratio]
        """
        market = _classify(code)

        if market in ("a_stock", "a_index"):
            return self._a_kline(code, count, start, end)
        else:
            return self._us_kline(code, count, start, end)

    # ============================================================
    #  A股分时实现
    # ============================================================

    def _a_stock_intraday(self, code, date):
        """A股个股分时（含大单 ddje）"""
        is_today = _is_today(date)

        # 1. 分时数据
        if is_today:
            trend = self._post(self.sector_url, {
                "a": "GetStockTrendIncremental", "c": "StockL2Data", "apiv": "w44",
                "PhoneOSNew": "2", "DeviceID": str(uuid.uuid4()),
                "VerSion": "5.23.0.4", "Token": "0", "UserID": "0", "StockID": code,
            })
            display_date = datetime.now().strftime("%Y-%m-%d")
        else:
            trend = self._post(self.base_url, {
                "a": "GetStockTrend", "c": "StockL2History", "apiv": "w44",
                "PhoneOSNew": "1", "DeviceID": str(uuid.uuid4()),
                "VerSion": "5.23.0.4", "Token": "0", "UserID": "0",
                "StockID": code, "Day": date.replace("-", ""),
            })
            display_date = date

        if not trend or trend.get("errcode") != "0":
            return pd.DataFrame()

        trend_data = trend.get("trend", [])
        if not trend_data:
            return pd.DataFrame()

        # trend 5字段: [时间, 价格, 均价(yellow_line), 成交量, flag]
        df = pd.DataFrame(trend_data, columns=["time", "price", "yellow_line", "volume", "flag"])
        df["price"] = df["price"].astype(float)
        df["yellow_line"] = df["yellow_line"].astype(float)
        df["volume"] = df["volume"].astype(int)
        df["flag"] = df["flag"].astype(int)
        df["date"] = display_date

        # 2. 大单分时（ddje 累计曲线）
        if is_today:
            dd = self._post(self.sector_url, {
                "a": "GetStockDaDanTrendIncremental", "c": "StockL2Data", "apiv": "w44",
                "PhoneOSNew": "2", "DeviceID": str(uuid.uuid4()),
                "VerSion": "5.23.0.4", "Token": "0", "UserID": "0", "StockID": code,
            })
        else:
            dd = self._post(self.base_url, {
                "a": "GetStockDaDanTrend", "c": "StockL2History", "apiv": "w44",
                "PhoneOSNew": "1", "DeviceID": str(uuid.uuid4()),
                "VerSion": "5.23.0.4", "Token": "0", "UserID": "0",
                "StockID": code, "Day": date.replace("-", ""),
            })

        dd_data = dd.get("dadanjinge", []) if dd else []
        # dadanjinge: [时间, 大单累计净额]，条数可能与分时不一致（如多一条15:00），用时间匹配
        dd_map = {item[0]: float(item[1]) for item in dd_data if len(item) >= 2}
        df["ddje"] = df["time"].map(dd_map)

        return df[["date", "time", "price", "yellow_line", "volume", "ddje", "flag"]]

    def _a_index_intraday(self, code, date):
        """A股指数分时（无 ddje）"""
        is_today = _is_today(date)

        if is_today:
            result = self._post(self.sector_url, {
                "a": "GetZstrend", "c": "StockL2Data", "apiv": "w44",
                "PhoneOSNew": "2", "DeviceID": str(uuid.uuid4()),
                "VerSion": "5.23.0.4", "Token": "0", "UserID": "0", "StockID": code,
            })
            display_date = datetime.now().strftime("%Y-%m-%d")
        else:
            result = self._post(self.base_url, {
                "a": "GetStockTrend", "c": "StockL2History", "apiv": "w44",
                "PhoneOSNew": "1", "DeviceID": str(uuid.uuid4()),
                "VerSion": "5.23.0.4", "Token": "0", "UserID": "0",
                "StockID": code, "Day": date.replace("-", ""),
            })
            display_date = date

        if not result or result.get("errcode") != "0":
            return pd.DataFrame()

        trend_data = result.get("trend", [])
        if not trend_data:
            return pd.DataFrame()

        df = pd.DataFrame(trend_data, columns=["time", "price", "yellow_line", "volume", "flag"])
        df["price"] = df["price"].astype(float)
        df["yellow_line"] = df["yellow_line"].astype(float)
        df["volume"] = df["volume"].astype(int)
        df["flag"] = df["flag"].astype(int)
        df["date"] = display_date
        df["ddje"] = float("nan")

        return df[["date", "time", "price", "yellow_line", "volume", "ddje", "flag"]]

    # ============================================================
    #  美股分时实现（仅当日实时）
    # ============================================================

    def _us_stock_intraday(self, code):
        """美股个股分时"""
        result = self._post(self.global_url, {
            "a": "IndividualStockTimeChart", "c": "GlobalIndex", "apiv": "w44",
            "StockID": code, "type": "0", "chartIndex": "0",
            "PhoneOSNew": "1", "UserID": "0", "DeviceID": str(uuid.uuid4()),
            "VerSion": "5.23.0.4", "Token": "0",
        })

        if not result or result.get("errcode") != "0":
            return pd.DataFrame()

        info = result.get("info", {})
        trend = info.get("trend", [])
        if not trend:
            return pd.DataFrame()

        # trend 6字段: [时间, 价格, 均价(yellow_line), 成交量, 成交额, flag]
        df = pd.DataFrame(trend, columns=["time", "price", "yellow_line", "volume", "amount", "flag"])
        df["price"] = df["price"].astype(float)
        df["yellow_line"] = df["yellow_line"].astype(float)
        df["volume"] = df["volume"].astype(int)
        df["flag"] = df["flag"].astype(int)
        df["date"] = datetime.now().strftime("%Y-%m-%d")
        df["ddje"] = float("nan")

        return df[["date", "time", "price", "yellow_line", "volume", "ddje", "flag"]]

    def _us_index_intraday(self, code):
        """海外指数分时"""
        result = self._post(self.global_url, {
            "a": "IndividualIndexTimeChart", "c": "GlobalIndex", "apiv": "w44",
            "code": code, "type": "4", "chartIndex": "0",
            "PhoneOSNew": "1", "UserID": "0", "DeviceID": str(uuid.uuid4()),
            "VerSion": "5.23.0.4", "Token": "0",
        })

        if not result or result.get("errcode") != "0":
            return pd.DataFrame()

        info = result.get("info", {})
        trend = info.get("trend", [])
        if not trend:
            return pd.DataFrame()

        # trend 6字段: [时间, 价格, 均价(yellow_line), 成交量, 成交额, flag]
        df = pd.DataFrame(trend, columns=["time", "price", "yellow_line", "volume", "amount", "flag"])
        df["price"] = df["price"].astype(float)
        df["yellow_line"] = df["yellow_line"].astype(float)
        df["volume"] = df["volume"].astype(int)
        df["flag"] = df["flag"].astype(int)
        df["date"] = datetime.now().strftime("%Y-%m-%d")
        df["ddje"] = float("nan")

        return df[["date", "time", "price", "yellow_line", "volume", "ddje", "flag"]]

    # ============================================================
    #  日K实现
    # ============================================================

    def _a_kline(self, code, count, start, end):
        """A股日K（个股/指数通用）"""
        # 多请求1天用于计算第一天的涨幅
        params = {
            "a": "GetKLineDay_W14", "c": "StockLineData", "apiv": "w44",
            "PhoneOSNew": "1", "DeviceID": str(uuid.uuid4()),
            "VerSion": "5.23.0.4", "Token": "0", "UserID": "0",
            "StockID": code, "Type": "d", "Index": "0",
            "st": str(count + 1), "Is_FS": "1",
        }
        result = self._post(self.base_url, params)

        if not result or result.get("errcode") != "0":
            return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume", "amount", "turnover_ratio", "change_pct"])

        x = result.get("x", [])
        y = result.get("y", [])
        vol = result.get("vol", [])
        bal = result.get("bal", [])
        turnover = result.get("turnover", [])

        if not x:
            return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume", "amount", "turnover_ratio", "change_pct"])

        df = pd.DataFrame({
            "date": x,
            "open": [row[0] if len(row) > 0 else None for row in y],
            "close": [row[1] if len(row) > 1 else None for row in y],
            "high": [row[2] if len(row) > 2 else None for row in y],
            "low": [row[3] if len(row) > 3 else None for row in y],
            "volume": vol,
            "amount": bal,
            "turnover_ratio": turnover,
        })

        # 数值转换
        for col in ["open", "close", "high", "low", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["turnover_ratio"] = pd.to_numeric(df["turnover_ratio"], errors="coerce")

        # 计算涨幅（基于前一日close），然后裁掉多请求的第1行
        df = self._add_change_pct(df)

        # 日期范围过滤
        if start:
            start_fmt = start.replace("-", "")
            df = df[df["date"] >= start_fmt]
        if end:
            end_fmt = end.replace("-", "")
            df = df[df["date"] <= end_fmt]

        return df.reset_index(drop=True)

    def _add_change_pct(self, df):
        """计算涨幅列并裁掉多请求的第1行（用于基准）。

        涨幅 = (今日close - 昨日close) / 昨日close × 100
        第1行（最早那天）没有前日基准，裁掉。
        """
        if len(df) < 2:
            df["change_pct"] = float("nan")
            return df
        df = df.copy()
        df["prev_close"] = df["close"].shift(1)
        df["change_pct"] = (df["close"] - df["prev_close"]) / df["prev_close"] * 100
        df["change_pct"] = df["change_pct"].round(2)
        df = df.drop(columns=["prev_close"])
        # 裁掉第1行（无前日基准）
        df = df.iloc[1:].reset_index(drop=True)
        return df

    def _us_kline(self, code, count, start, end):
        """美股日K（个股/指数通用）

        注意：海外日K走 apphis 域名（base_url），GetDayKLineGlobal 接口。
        apphwshhq 上此接口对指数返回空数据。
        """
        # 多请求1天用于计算第一天的涨幅
        params = {
            "a": "GetDayKLineGlobal", "c": "StockLineData", "apiv": "w44",
            "PhoneOSNew": "1", "DeviceID": str(uuid.uuid4()),
            "VerSion": "5.23.0.4", "Token": "0", "UserID": "0",
            "StockID": code, "Type": "d", "Index": "0", "st": str(count + 1),
        }
        result = self._post(self.base_url, params)

        if not result or result.get("errcode") != "0":
            return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume", "amount", "turnover_ratio", "change_pct"])

        x = result.get("x", [])
        y = result.get("y", [])
        vol = result.get("vol", [])
        bal = result.get("bal", [])
        turnover = result.get("turnover", [])

        if not x:
            return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume", "amount", "turnover_ratio", "change_pct"])

        # 美股 y 的元素可能是字符串
        df = pd.DataFrame({
            "date": x,
            "open": [float(row[0]) if len(row) > 0 and row[0] else None for row in y],
            "close": [float(row[1]) if len(row) > 1 and row[1] else None for row in y],
            "high": [float(row[2]) if len(row) > 2 and row[2] else None for row in y],
            "low": [float(row[3]) if len(row) > 3 and row[3] else None for row in y],
            "volume": vol,
            "amount": bal,
            "turnover_ratio": turnover,
        })

        for col in ["volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["turnover_ratio"] = pd.to_numeric(df["turnover_ratio"], errors="coerce")

        # 计算涨幅（基于前一日close），然后裁掉多请求的第1行
        df = self._add_change_pct(df)

        if start:
            start_fmt = start.replace("-", "")
            df = df[df["date"] >= start_fmt]
        if end:
            end_fmt = end.replace("-", "")
            df = df[df["date"] <= end_fmt]

        return df.reset_index(drop=True)

    # ============================================================
    #  成交额预测曲线 / 市场情绪
    # ============================================================
    # 通过 HTTP API 获取，无需 frida / 模拟器 / 认证。
    # 当日实时：apphswhhq.longhuvip.com HomeDingPan/MarketCapacity
    # 历史日期：apphis.longhuvip.com HisHomeDingPan/MarketSCLN?Date=xxx
    # 市场情绪：apphswhhq.longhuvip.com Index/GetInfo

    def get_turnover_curve(self, date=None, curve_type=0):
        """获取成交额预测曲线（当日实时 / 历史单日）

        通过 HTTP API 获取，无需 frida/socket/signature。

        Args:
            date: 日期 "YYYY-MM-DD"，None=当日实时
            curve_type: 0=全市场, 1=沪市, 2=深市

        Returns:
            DataFrame: [date, time, amount, sh_amount, sz_amount, change_pct, desc]
            - amount: 全市场成交额（亿）
            - sh_amount: 沪市成交额（亿）
            - sz_amount: 深市成交额（亿）
            - change_pct: 相对昨日同期涨幅%
            - desc: 描述 "29137亿(13.66%,增量3502亿)"
        """
        params = {
            "c": "HomeDingPan" if (date is None or date == datetime.now().strftime("%Y-%m-%d")) else "HisHomeDingPan",
            "a": "MarketCapacity" if (date is None or date == datetime.now().strftime("%Y-%m-%d")) else "MarketSCLN",
            "Type": str(curve_type),
            "PhoneOSNew": "1",
            "DeviceID": "c3dd17d3-cefb-3884-9edd-c8c03274cc83",
            "VerSion": "5.23.0.4",
        }

        if date is not None and date != datetime.now().strftime("%Y-%m-%d"):
            params["Date"] = date
            url = self.base_url  # apphis
        else:
            url = self.global_url  # apphwshhq

        data = self._post(url, params)

        info = data.get("info", {})
        trends = info.get("trends", [])
        resp_date = info.get("date", date or datetime.now().strftime("%Y-%m-%d"))

        rows = []
        for t in trends:
            # t = [时间, 全市场额(万), 沪市额(万), 深市额(万), 涨幅%, 描述, 颜色, 标记]
            if len(t) < 6:
                continue
            rows.append({
                "date": resp_date,
                "time": t[0],
                "amount": round(int(t[1]) / 10000, 2) if t[1] else None,       # 万→亿
                "sh_amount": round(int(t[2]) / 10000, 2) if t[2] else None,     # 万→亿
                "sz_amount": round(int(t[3]) / 10000, 2) if t[3] else None,     # 万→亿
                "change_pct": float(t[4]) if t[4] else None,
                "desc": t[5] if len(t) > 5 else "",
            })

        if not rows:
            return pd.DataFrame(columns=["date", "time", "amount", "sh_amount",
                                         "sz_amount", "change_pct", "desc"])

        df = pd.DataFrame(rows)
        return df

    def get_market_sentiment(self):
        """获取市场情绪概览（涨停跌停家数、涨跌平盘家数）

        对应开盘啦 app 市场情绪页面的核心数据。
        涨停/跌停/涨跌家数来自 HTTP API（Index/GetInfo），
        平盘家数来自 socket 2110（涨跌幅分布 change_pct==0 的家数）。

        Returns:
            dict:
                - limit_up: 涨停家数
                - limit_down: 跌停家数
                - up_count: 上涨家数
                - down_count: 下跌家数
                - flat_count: 平盘家数
                - total: 总家数
        """
        # HTTP API 拿涨停跌停 + 涨跌家数
        params = {
            "c": "Index", "a": "GetInfo",
            "View": "2,3,4",
            "PhoneOSNew": "1",
            "DeviceID": "c3dd17d3-cefb-3884-9edd-c8c03274cc83",
            "VerSion": "5.23.0.4",
        }
        data = self._post(self.global_url, params)
        db = data.get("DaBanList", {})
        up = db.get("SZJS", 0)
        down = db.get("XDJS", 0)

        # socket 2110 拿平盘家数（distribution 里 change_pct==0）
        flat = 0
        try:
            from kpl_socket import get_market_summary
            s = get_market_summary()
            for d in s.get("distribution", []):
                if d.get("change_pct") == "0":
                    flat = d.get("count", 0)
                    break
        except Exception:
            pass

        return {
            "limit_up": db.get("tZhangTing", 0),
            "limit_down": db.get("tDieTing", 0),
            "up_count": up,
            "down_count": down,
            "flat_count": flat,
            "total": up + down + flat,
        }


if __name__ == "__main__":
    c = KaipanlaCrawler()

    print("=" * 60)
    print("分时接口测试")
    print("=" * 60)

    for code in ["000938", "SH000001", "US:SNDK", "IXIC"]:
        df = c.get_intraday(code)
        print(f"\n{code}: {len(df)}条")
        if len(df) > 0:
            print(df.head(3).to_string())

    print("\n" + "=" * 60)
    print("日K接口测试")
    print("=" * 60)

    for code in ["000938", "SH000001", "US:SNDK", "IXIC"]:
        df = c.get_kline(code, count=5)
        print(f"\n{code}: {len(df)}条")
        if len(df) > 0:
            print(df.to_string())

    print("\n" + "=" * 60)
    print("成交额预测曲线测试")
    print("=" * 60)

    # 当日
    df = c.get_turnover_curve()
    print(f"\n当日: {len(df)}条")
    if len(df) > 0:
        print(f"  最新: {df.iloc[-1]['time']} {df.iloc[-1]['amount']}亿 {df.iloc[-1]['change_pct']}%")
        print(df.tail(3).to_string())

    # 历史
    for d in ["2026-07-08", "2026-07-01"]:
        df = c.get_turnover_curve(date=d)
        print(f"\n{d}: {len(df)}条")
        if len(df) > 0:
            print(f"  收盘: {df.iloc[-1]['amount']}亿 {df.iloc[-1]['change_pct']}%")

    print("\n" + "=" * 60)
    print("市场情绪测试")
    print("=" * 60)

    s = c.get_market_sentiment()
    print(f"  涨停: {s['limit_up']}    跌停: {s['limit_down']}")
    print(f"  上涨: {s['up_count']}  下跌: {s['down_count']}  平盘: {s['flat_count']}")
    print(f"  总计: {s['total']}")
