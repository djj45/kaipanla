# 开盘啦行情数据统一接口

精简、统一的行情数据接口，自动识别 A股/美股、个股/指数。
全部通过 HTTP API 获取，无需 frida / 模拟器 / socket / 认证。

## 安装

```bash
uv run python kaipanla.py  # 直接运行自带测试
```

依赖：`requests`、`pandas`（uv 已配置）。

## 快速开始

```python
from kaipanla import KaipanlaCrawler

crawler = KaipanlaCrawler()

# 分时数据
df = crawler.get_intraday("000938")                    # A股个股 当日
df = crawler.get_intraday("SH000001")                   # A股指数 当日
df = crawler.get_intraday("US:SNDK")                    # 美股个股 当日
df = crawler.get_intraday("IXIC")                       # 纳斯达克指数 当日

# 日K线
df = crawler.get_kline("000938", count=100)             # 最近100天

# 成交额预测曲线（单日分时，约241点）
df = crawler.get_turnover_curve()                       # 当日实时
df = crawler.get_turnover_curve(date="2026-07-08")      # 历史某日

# 成交额日线（多日，一次请求取回）
df = crawler.get_turnover_kline(count=60)               # 最近60个交易日
df = crawler.get_turnover_kline(curve_type=1)           # 上证口径

# 市场情绪（实时，含平盘家数）
s = crawler.get_market_sentiment()                      # 涨停/跌停/涨跌平盘家数

# 历史每日涨跌家数
df = crawler.get_market_sentiment_history(count=30)
df = crawler.get_market_sentiment_history(start="2026-01-01", end="2026-09-16")
```

## API

### get_intraday(code, date=None, start=None, end=None)

获取分时数据（每分钟一个数据点）。

| 参数 | 说明 |
|---|---|
| `code` | 股票/指数代码 |
| `date` | 单日 `"YYYY-MM-DD"`（可选） |
| `start`/`end` | 日期范围 `"YYYY-MM-DD"`（可选） |
| 不传日期 | 当日实时 |

**返回 DataFrame 列：**

| 列 | 含义 |
|---|---|
| `date` | 交易日 |
| `time` | 时间 |
| `price` | 价格（指数为白线/加权指数） |
| `yellow_line` | 黄线（个股=成交均价；A股指数=不加权指数） |
| `volume` | 成交量 |
| `ddje` | 大单累计净额（仅 A 股个股，其余为 NaN；从开盘到当前的累计值，单位元） |
| `flag` | 涨跌方向（0=跌，1=涨，2=平盘；相对前一分钟） |

### get_kline(code, count=100, start=None, end=None)

获取日K线序列（每天一个数据点）。

| 参数 | 说明 |
|---|---|
| `code` | 股票/指数代码 |
| `count` | 返回最近 N 天（默认100） |
| `start`/`end` | 日期范围（可选，优先于 count） |

**返回 DataFrame 列：**

| 列 | 含义 |
|---|---|
| `date` | 交易日 (YYYYMMDD) |
| `open` | 开盘价 |
| `close` | 收盘价 |
| `high` | 最高价 |
| `low` | 最低价 |
| `volume` | 成交量 |
| `amount` | 成交额（元） |
| `turnover_ratio` | 换手率(%) |
| `change_pct` | 涨跌幅(%)（基于前日收盘） |

### get_turnover_curve(date=None, curve_type=0)

获取成交额预测曲线（每分钟一个数据点）。

| 参数 | 说明 |
|---|---|
| `date` | `"YYYY-MM-DD"`，不传=当日实时 |
| `curve_type` | 成交额口径，见下表（**注意：2 不是深市**） |

`curve_type`（即接口的 `Type` 参数）实测口径：

| 值 | 含义 | 2026-09-17 收盘 | 独立验证 |
|---|---|---|---|
| 0 | 沪深两市（默认） | 18231 亿 | = 上证 8688 + 深市 9544 |
| 1 | 上证（沪市） | 8688 亿 | 上证指数成交额 = 8688 亿 |
| 2 | **创业板** | 4432 亿 | 创业板指成交额 = 4432 亿 |
| 3 | 北证 | 135 亿 | — |
| 4 | 沪深京 | 18366 亿 | = 沪深两市 + 北证 |
| 5 | 科创板 | 2607 亿 | — |

深市没有独立的 `Type`，可用「沪深两市 − 上证」推算（与深证综指逐日精确相等）。

**返回 DataFrame 列：**

| 列 | 含义 |
|---|---|
| `date` | 交易日 |
| `time` | 时间（09:30-15:00） |
| `amount` | 该口径下的今日累计成交额（亿） |
| `prev_amount` | 上一交易日**同一时刻**的累计成交额（亿） |
| `ref_amount` | 接口返回的第三条参考序列（亿），**含义未确认，请勿依赖** |
| `change_pct` | 相对昨日同期涨幅（%） |
| `desc` | 描述，如 "29137亿(13.66%,增量3502亿)" |

> **关于列名**：接口每行是 `[时间, 今日累计, 昨日同期累计, 第三条序列, 涨幅%, 描述, ...]`。
> 早期版本把第 3、4 列命名为 `sh_amount` / `sz_amount`（沪市/深市），
> 但实测二者相加远大于第 2 列，并非拆分关系，属于错误命名。现已改为：
>
> - `prev_amount`：上一交易日同一时刻 —— 用连续 5 组交易日、在 09:30 与 15:00
>   两个时刻逐点比对确认（与该日 t1 完全相等）
> - `ref_amount`：第三条序列，已排除「任一历史日收盘值」和「5/10/20/30/60 日均线」，
>   未能确认含义，故保留原名中性化并标注不可依赖
>
> 若不需要 `ref_amount`，可直接 `df.drop(columns=["ref_amount"])`。

- 交易时间内调用返回截至当前时刻的分时点，盘后返回全天数据（约241点）
- 任意历史日期均可查询

### get_turnover_kline(curve_type=0, count=None, start=None, end=None)

获取成交额日线序列（多日，一次请求取回；接口固定返回最近约 127 个交易日）。

与 get_turnover_curve 的区别：后者返回「某一天」的分时曲线（约 241 点），
本方法返回「多天」的日线序列。

| 参数 | 说明 |
|---|---|
| curve_type | 口径，取值同 get_turnover_curve 的 Type（0=沪深两市，1=上证，2=创业板，3=北证，4=沪深京，5=科创板） |
| count | 只取最近 N 天 |
| start/end | 日期范围（优先于 count） |

返回 DataFrame 列：

| 列 | 含义 |
|---|---|
| date | 交易日 |
| amount | 成交额（亿） |

已与 get_turnover_curve(date=...) 的收盘值逐日交叉验证，完全一致。
（本方法只返回 date / amount 两列，不涉及 get_turnover_curve 的历史列名问题。）

### get_market_sentiment()

获取市场情绪概览（涨停跌停、涨跌平盘家数），全部来自 HTTP（Index/GetInfo）。

注意：该请求必须带 apiv 参数。不带 apiv 时服务端只返回 9 个字段（没有 PPJS），
带上后返回 21 个字段，其中 PPJS 就是平盘家数。
旧实现漏了 apiv，取不到平盘家数，只好退回 socket；而 socket 依赖的 kpl_socket
模块并不在本仓库中，import 失败又被 except 静默吞掉，
导致 flat_count 恒为 0、total（涨+跌+平）也是错的。现已修正为纯 HTTP。

返回 dict：

| 字段 | 含义 |
|---|---|
| limit_up | 涨停家数（不含 ST） |
| limit_down | 跌停家数（不含 ST） |
| up_count | 上涨家数 |
| down_count | 下跌家数 |
| flat_count | 平盘家数（来自 PPJS，真实值） |
| total | 总家数 = 涨 + 跌 + 平 |
| seal_rate | 今日封板率(%)（tFengBan） |
| break_rate | 今日破板率(%)（炸板率 = 100 − tFengBan，与 app 展示及历史 ZBL 一致） |
| yest_seal_rate | 昨日封板率(%)（lFengBan） |
| yest_limit_up_rise | 昨日涨停表现(%) |
| yest_lianban_rise | 昨日连板表现(%) |
| strength | 涨跌强度 |

实测（2026-09-17 收盘）：涨 2576 + 跌 2820 + 平 157 = 5553；
涨停 47 / 跌停 1 **不含 ST**（历史接口同日含 ST 为 49 / 2）；
封板率 70.15%（47 涨停 / 67 触板），破板率 29.85%，
与 app 展示（09-16 = 11%、09-17 = 29.85%）及历史接口 ZBL 完全一致。

### get_market_sentiment_history(start=None, end=None, count=30)

获取历史每日涨跌家数（收盘口径）。

开盘啦没有「多日涨跌家数」接口，只能逐日查询
（apphis -> HisLimitResumption/GetPlateInfo_w38?Date=xxx，一天一次请求）。

| 参数 | 说明 |
|---|---|
| start/end | 日期范围 "YYYY-MM-DD"（优先于 count） |
| count | 不传范围时，取最近 N 个交易日（默认 30） |

返回 DataFrame 列：

| 列 | 含义 |
|---|---|
| date | 交易日 |
| up_count | 上涨家数 |
| down_count | 下跌家数 |
| flat_count | 平盘家数，恒为 NaN（接口不提供历史平盘家数） |
| limit_up | 涨停家数（含 ST，比实时接口略多） |
| limit_down | 跌停家数（含 ST，比实时接口略多） |
| break_rate | 破板率(%)（ZBL，炸板率，与 app 展示一致） |
| yest_rise | 昨日涨停表现(%) |

- 周末会被跳过；法定节假日请求返回空数据并被自动剔除
- 平盘家数只有实时接口 get_market_sentiment() 才提供
- 涨停/跌停口径与实时接口不同：历史含 ST（2026-09-17 实测 历史 49/2 vs 实时 47/1）

## 支持的代码

| 类型 | 格式 | 示例 |
|---|---|---|
| A股个股 | 6位数字 / SH+6位 / SZ+6位 | `000938`、`SH600000`、`SZ000001` |
| A股指数 | SH000xxx / SZ399xxx | `SH000001`(上证)、`SZ399001`(深证)、`SZ399006`(创业板) |
| 美股个股 | US:+代码 | `US:SNDK`、`US:AAPL` |
| 港股个股 | HK:+代码 | `HK:00700` |
| 海外指数 | 代码（无前缀） | `IXIC`(纳指)、`DJI`(道指)、`SPX`(标普)、`HSI`(恒指) |

## 限制

1. **美股不支持历史分时**——仅支持当日实时分时，传历史日期会报错
2. **分时不返回成交额**——只有成交量(volume)；日K有成交额(amount)
3. **A股指数的黄线**是不加权指数（反映小盘股），白线(price)是加权指数
4. **ddje 是累计值**——从开盘到当前分钟的大单累计净额（单位：元），仅 A 股个股有值
5. **成交额曲线和情绪数据仅支持 A 股**——美股/港股无此功能
6. **历史涨跌家数只能逐日查询**——上游没有多日接口，get_market_sentiment_history(count=30) 会发出 30 次请求，建议自行加缓存与限速
7. **历史平盘家数拿不到**——get_market_sentiment_history 的 flat_count 恒为 NaN；平盘家数只有实时值
8. **get_turnover_kline 固定返回约 127 个交易日**——接口不支持分页取更早的数据
