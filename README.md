# 开盘啦行情数据统一接口

精简、统一的行情数据接口，自动识别 A股/美股、个股/指数。
全部通过 HTTP API 获取，无需 frida / 模拟器 / 认证。

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

# 成交额预测曲线
df = crawler.get_turnover_curve()                       # 当日实时
df = crawler.get_turnover_curve(date="2026-07-08")      # 历史日期

# 市场情绪
s = crawler.get_market_sentiment()                      # 涨停/跌停/涨跌平盘家数
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
| `curve_type` | 0=全市场（默认），1=沪市，2=深市 |

**返回 DataFrame 列：**

| 列 | 含义 |
|---|---|
| `date` | 交易日 |
| `time` | 时间（09:30-15:00） |
| `amount` | 全市场成交额（亿） |
| `sh_amount` | 沪市成交额（亿） |
| `sz_amount` | 深市成交额（亿） |
| `change_pct` | 相对昨日同期涨幅（%） |
| `desc` | 描述，如 "29137亿(13.66%,增量3502亿)" |

- 交易时间内调用返回截至当前时刻的分时点，盘后返回全天数据（约241点）
- 任意历史日期均可查询

### get_market_sentiment()

获取市场情绪概览（涨停跌停、涨跌平盘家数）。

**返回 dict：**

| 字段 | 含义 |
|---|---|
| `limit_up` | 涨停家数 |
| `limit_down` | 跌停家数 |
| `up_count` | 上涨家数 |
| `down_count` | 下跌家数 |
| `flat_count` | 平盘家数 |
| `total` | 总家数 |

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
