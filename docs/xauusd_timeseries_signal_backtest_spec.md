# 外汇黄金（XAU/USD）时序信号回测规范文档

> 本文档供 Agent 框架参考，定义**单标的时序信号回测**（不是策略回测、也不是截面因子回测）的标准流程、输出指标、图表要求及常见隐患。
> 时序信号回测的核心问题是：**这个信号对未来 N 根 bar 的收益有没有预测能力、预测能力在不同时段/regime 下是否稳定、扣除点差成本后能否实际使用。**
> 不涉及具体止盈止损规则、仓位管理、复杂订单类型；只回答“信号本身是否有 edge”。
>
> 标的：XAU/USD（现货黄金对美元，国际外汇代码 `XAUUSD`，期货代码 `GC=F`）
> 频率：5 分钟（M5）
> 历史长度：≥ 2 年

---

## 〇、数据获取（Agent 必须先完成）

### 0.1 可用的免费数据源（按推荐顺序）

| 来源 | 标的代码 | 时间跨度 | Python 接入 | 备注 |
|------|---------|---------|------------|------|
| **Dukascopy Historical Data Feed** | `XAUUSD` | 2003 至今 | `pip install dukascopy-python` 或 `duka` CLI | **首选**。免费、官方、tick → 重采样到 M5；时间戳为 UTC；价格为银行间报价（bid/ask 分离）|
| **HistData.com** | `XAUUSD` | 2009 至今 | 需手动逐月下载 zip，再用 pandas 合并 | M1 数据 → 重采样到 M5；只有 bid 价 |
| **Kaggle 公开数据集** | `XAU/USD` | 2004 ~ 2025 | `kaggle datasets download novandraanugrah/xauusd-gold-price-historical-data-2004-2024` | 已包含 5m/15m/30m/1h/4h/1D；离线数据，最新月份可能缺失 |
| **yfinance（GC=F 黄金期货）** | `GC=F` | **仅最近 60 天** | `yfinance.download('GC=F', interval='5m')` | ⚠️ 不满足 2 年要求，仅用于实时增量补丁 |

> ⚠️ 注意：**yfinance 不支持 5m 频率回溯 2 年**（intraday 数据上限 60 天）。Agent 必须使用 Dukascopy 或 HistData 作为主数据源。

### 0.2 推荐的下载脚本（Dukascopy 路径）

```python
# 优先方案：dukascopy-python
# pip install dukascopy-python pandas
import dukascopy_python
from datetime import datetime, timezone
import pandas as pd

df = dukascopy_python.fetch(
    instrument=dukascopy_python.INSTRUMENT_FX_METALS_XAU_USD,
    interval=dukascopy_python.INTERVAL_MIN_5,
    offer_side=dukascopy_python.OFFER_SIDE_BID,   # 同时再拉一次 ASK 用于估算点差
    start=datetime(2023, 1, 1, tzinfo=timezone.utc),
    end=datetime(2026, 1, 1, tzinfo=timezone.utc),
)
df.to_parquet("xauusd_m5_bid.parquet")
```

```python
# 备选方案：HistData.com（M1 → 重采样到 M5）
# 手动下载 https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/xauusd/YYYY/MM
# 解压得到 DAT_ASCII_XAUUSD_M1_YYYYMM.csv，列顺序：Datetime; Open; High; Low; Close; Volume
import pandas as pd, glob
m1 = pd.concat([pd.read_csv(f, sep=';', header=None,
                            names=['ts','open','high','low','close','vol'])
                for f in sorted(glob.glob('DAT_ASCII_XAUUSD_M1_*.csv'))])
m1['ts'] = pd.to_datetime(m1['ts'], format='%Y%m%d %H%M%S', utc=True)
m1 = m1.set_index('ts').sort_index()
m5 = m1.resample('5min').agg({'open':'first','high':'max',
                              'low':'min','close':'last','vol':'sum'}).dropna()
m5.to_parquet('xauusd_m5_histdata.parquet')
```

### 0.3 数据完整性检查清单

| 检查项 | 通过标准 |
|--------|---------|
| 时间范围 | ≥ 730 天 |
| Bar 数量 | 约 2 年 × 52 周 × 5 天 × 24 小时 × 12 bar ≈ 150k 根（黄金近 24h 交易，周末除外）|
| 时间戳时区 | 统一存储为 UTC，分析时再转 NY/London |
| 周末缺口 | 周五 ~22:00 UTC 至周日 ~22:00 UTC 应该没有 bar（正常）|
| 节假日缺口 | 圣诞、元旦、感恩节当天数据稀疏（正常）|
| 异常跳价 | `|log(close/close.shift(1))| > 0.05`（5% 单 bar 涨跌）的 bar 标记为可疑 |
| 重复时间戳 | `df.index.duplicated().sum() == 0` |
| 字段完整 | open/high/low/close 均非空，且 `low ≤ open,close ≤ high` |
| 点差估算 | `(ask - bid).median()` 应在 0.15 ~ 0.40 美元/盎司之间（正常黄金点差）|

---

## 一、信号预处理

### 1.1 信号值清洗

| 步骤 | 方法 | 说明 |
|------|------|------|
| 去极值 | 滚动 MAD 或 Winsorize（1%/99% 滚动分位）| 用**滚动**窗口（如过去 1000 根 bar）的分位数，**绝不能用全样本**——否则引入未来函数 |
| 缺失值处理 | 前向填充上限 N 根（如 N=3），超过则视为无信号 | 黄金 24h 交易，正常情况下缺失主要发生在周末/假期 |
| 标准化 | 滚动 Z-Score：`(x - rolling_mean) / rolling_std` | 滚动窗口长度 ≥ 信号本身周期的 5 倍 |
| 平稳性检验 | ADF 检验 | 信号若非平稳（如累积量），必须先差分或归一化 |

### 1.2 信号到仓位的映射方式

时序信号必须明确**信号值如何转化为仓位**，是后续指标计算的前提：

| 映射 | 公式 | 适用场景 |
|------|------|---------|
| 阈值法 | `pos = +1 if signal > θ_long else -1 if signal < θ_short else 0` | 离散事件型信号（突破、形态）|
| 符号法 | `pos = sign(signal)` | 已对称归一化的连续信号 |
| 线性法 | `pos = clip(signal, -1, 1)` | 连续信号、想保留强度 |
| 分位映射 | `pos = 2 * rank_pct(signal, window) - 1` ∈ [-1,1] | 信号分布不对称时 |

> ⚠️ 仓位必须在 **bar t 收盘后**根据 `signal[t]` 决定，并应用于 `bar t+1` 的收益。任何在 t bar 内偷看 close 后再决定仓位的做法都是未来函数。

### 1.3 收益率定义

| 字段 | 定义 | 用途 |
|------|------|------|
| `ret_1` | 单 bar 对数收益 `log(close[t] / close[t-1])` | 累乘/累加更稳定 |
| `fwd_ret_h` | 未来 h 根 bar 的累计对数收益 `log(close[t+h] / close[t])` | 信号在不同持有期的预测能力 |
| `fwd_ret_h_oc` | 未来 h 根 bar 的 open→close 收益 `log(close[t+h] / open[t+1])` | **更现实**，模拟“下一根 bar 开盘进场”的真实成交 |
| 净收益 | `fwd_ret - spread_cost - commission` | 必须报告 |

> 默认采用 `fwd_ret_h_oc` 作为主指标，因为 close-to-close 假设你能在 bar 收盘那一瞬间成交，这在 5m 频率上是有偏的乐观假设。

---

## 二、核心输出指标

### 2.1 信号-未来收益的时序预测力

替代截面 IC，时序信号用以下指标衡量预测力：

| 指标 | 定义 | 判断标准 |
|------|------|---------|
| **预测相关系数** `ρ_pred` | `corr(signal[t], fwd_ret_h[t+1:t+h+1])` 在全样本上的 Pearson | 时序上 \|ρ\| > 0.03 已属可用，> 0.06 较好 |
| **Spearman 等级相关** | 同上但用秩 | 更稳健，应作为主报告值 |
| **t 统计量** | `ρ × sqrt((N-2)/(1-ρ²))` | \|t\| > 2 才有统计显著性；注意自相关会让 t 虚高，需用 **Newey-West HAC 标准误** |
| **滚动相关** | 滚动 1000 根 bar 计算 `ρ_pred` | 输出时间序列，观察是否稳定 |
| **信号自相关** | `corr(signal[t], signal[t-k])` for k=1..50 | 衡量信号本身持续性 → 决定持仓时长 |
| **信号衰减曲线** | `ρ_pred(h)` for h=1,2,5,10,20,50,100 | 找出信号最佳持有期（曲线峰值对应的 h）|

### 2.2 事件研究（Event Study）—— 时序信号的核心可视化

将每次**信号触发**（信号穿越阈值、出现峰值等）视为一个事件，对齐到事件时间 0，观察前后窗口的平均收益。

| 指标 | 定义 | 判断标准 |
|------|------|---------|
| 事件窗口平均累计收益 | `mean(cum_ret[t-W : t+W])` over all events | 触发后曲线持续上行（做多信号）/ 下行（做空信号）才算有效 |
| 事件窗口收益的 95% 置信带 | 用 bootstrap 或事件间的标准误 | 置信带不跨越 0 → 信号显著 |
| 事件后 h 期累计收益分布 | 所有事件的 `fwd_ret_h` 的直方图 | 均值偏离 0 + 中位数同向 = 稳健 |
| 事件命中率 | `P(sign(fwd_ret_h) == expected_direction)` | > 52%（多空对称）已是可用，> 55% 较好 |
| 事件触发频率 | 单位时间触发次数 | 太低（< 每月 5 次）样本量不足；太高（> 每天 50 次）噪声大 |

### 2.3 阈值敏感性 / 分位测试（替代截面分组）

时序信号没有“截面分组”，但可以做**信号值分位 → 未来收益**的分析，本质是时序版的单调性检验：

| 指标 | 定义 | 判断标准 |
|------|------|---------|
| 分位平均收益 | 将信号值按**滚动分位**分到 5 或 10 个 bin，计算每个 bin 内 bar 的 `fwd_ret_h` 均值 | 从最低分位到最高分位应单调递增/递减 |
| 分位收益散点图 | X=信号分位（1~10），Y=对应 bin 的平均 `fwd_ret_h`（含 95% CI 误差棒）| 斜率显著 ≠ 0 |
| 分位单调性 Spearman | 分位序号 vs 分位收益的 Spearman 相关 | \|ρ\| > 0.7 表示较好单调 |
| 极端分位多空收益 | `mean(fwd_ret_h | top decile) - mean(fwd_ret_h | bottom decile)` | 应显著 > 0（多头方向）|
| 极端分位 t 检验 | 上述差异的 Welch's t-test | t > 2 才显著 |

### 2.4 信号 P&L 模拟（必备）

把信号通过 §1.2 的映射转成仓位序列，模拟一条 P&L 曲线（不止盈止损、不复利、不杠杆，纯信号本身的 edge）：

| 指标 | 定义 | 判断标准 |
|------|------|---------|
| 累计收益曲线 | `cumsum(position[t] × ret_1[t+1] - cost[t])` | 应该稳步上升 |
| 年化收益 | `mean(daily_pnl) × 252` | XAU/USD ≈ 每年 250 个交易日 |
| 年化波动 | `std(daily_pnl) × sqrt(252)` | — |
| **Sharpe Ratio** | 年化收益 / 年化波动 | > 0.8 可用，> 1.5 较好（5m 信号）|
| **Sortino Ratio** | 年化收益 / 下行波动 | 通常高于 Sharpe |
| **Calmar Ratio** | 年化收益 / 最大回撤 | > 0.5 可用 |
| 最大回撤 MDD | 净值曲线最大跌幅 | 越小越好 |
| 最大回撤持续时间 | 从峰到再创新高的 bar 数 | — |
| 命中率 | 盈利 bar 数 / 总持仓 bar 数 | > 51% 已不易 |
| 盈亏比 | 平均盈利 bar 收益 / 平均亏损 bar 收益 | > 1.0 配合命中率 50% 即有 edge |
| 期望收益（每 bar）| `mean(pnl_per_bar)` 以 pip 计 | 应 > 单边点差 |
| 换手率 / 翻转率 | `mean(|position[t] - position[t-1]|) / 2` | 直接决定交易成本 |
| **净 Sharpe**（扣点差）| 在 P&L 中扣除 `|Δposition| × spread/2` 后的 Sharpe | **最终判定指标**，必须为正 |

### 2.5 信号的时段（Session）与 Regime 分析

外汇黄金 24h 交易，但流动性集中在伦敦/纽约盘，信号在不同时段表现差异极大，**必须分段评估**：

| 切片维度 | 切法 | 报告内容 |
|---------|------|---------|
| 交易时段 | Sydney (22-00 UTC) / Tokyo (00-08) / London (07-16) / NY (12-21) / Overlap (12-16) | 每段单独的 Sharpe、命中率、信号触发次数 |
| 周内日 | Mon ~ Fri | 周一行情常滞后、周五午后流动性下降 |
| 月度 | 每月一行 | 季节性、月末头寸调整影响 |
| 波动率 regime | 用 ATR(14) 或 realized vol 分高/中/低 3 档 | 信号在高波动 vs 低波动下的表现 |
| 趋势 regime | 用 ADX 或长短均线分趋势/震荡 | 多数动量信号只在趋势中有效 |
| 重要数据公布前后 | NFP、CPI、FOMC ±30 分钟 | 通常应**剔除**这段数据后单独评估，避免单次极端值主导结论 |

### 2.6 稳健性 / Walk-Forward 检验

| 指标 | 定义 | 说明 |
|------|------|------|
| 样本外 Sharpe | 把最后 30% 数据完全冻结，所有参数只用前 70% 拟合 | 样本外 Sharpe ≥ 样本内的 60% 才算稳健 |
| Walk-Forward 滚动测试 | 训练窗 6 个月 → 测试窗 1 个月，滚动前进 | 输出 24 个独立测试段的 Sharpe，看分布而非均值 |
| 参数敏感性 | 主要参数 ±10%、±20%、±50% 扫描 | Sharpe 热力图应该是“高原”而非“尖峰” |
| Bootstrap 置信区间 | 对 P&L 序列做 1000 次有放回抽样 | Sharpe 的 95% CI 下限应 > 0 |
| 反向信号对照 | 直接 `position = -position`，看 Sharpe 是否对称变负 | 若反向也有正 Sharpe，说明原信号是噪声，只是 cost 不对称 |

---

## 三、图表要求

### 3.1 必须输出的图表

#### (1) 价格 + 信号 + 仓位三联图
- 上：XAU/USD 5m K 线（最好截取一个有代表性的 1~2 周窗口）
- 中：信号值时间序列，叠加阈值水平线
- 下：仓位序列（阶梯函数 -1/0/+1 或连续 [-1,1]）
- 用于人工肉眼检验对齐是否正确

#### (2) 累计 P&L 曲线（毛收益 vs 净收益）
- X 轴时间，Y 轴累计 pip 收益
- 两条线：**毛收益**（不扣成本）、**净收益**（扣点差 + 佣金）
- 标注最大回撤区段（阴影）
- 标注 Sharpe / Sortino / MDD 数值

#### (3) 滚动 Sharpe / 滚动预测相关
- X 轴时间，Y 轴 252 个交易日（或 5000 根 bar）滚动 Sharpe
- 配合滚动 `ρ_pred`
- 用于判断信号是否**渐进失效**

#### (4) 事件研究曲线（核心图，必须有）
- X 轴：事件时间偏移 [-W, +W] 根 bar（如 W=50，对应 5m × 50 = 4 小时）
- Y 轴：以事件 t=0 为基准的平均累计收益
- 多空两条曲线分别画
- 加 95% 置信带（bootstrap 或事件间标准误）
- 用于直观回答“信号触发后到底发生什么”

#### (5) 信号衰减图
- X 轴：未来持有期 h（1, 5, 10, 20, 50, 100 根 bar）
- Y 轴：对应的 `ρ_pred(h)`
- 曲线峰值对应最佳持有期，曲线快速衰减 → 适合极短持仓

#### (6) 阈值/分位响应图
- X 轴：信号值的滚动分位（10 个 bin）
- Y 轴：对应 bin 内的平均 `fwd_ret_h`，误差棒为 95% CI
- 应该单调递增/递减，最极端两端差异显著

#### (7) Session 热力图
- 行：周一 ~ 周五
- 列：UTC 0 ~ 23 小时
- 颜色：对应小时-星期格的平均收益或命中率
- 用于发现“某些时段信号特别好/特别差”

#### (8) 回撤水下曲线（Underwater Plot）
- X 轴时间，Y 轴 `equity/equity_peak - 1`
- 比 P&L 曲线更直观地暴露最坏时刻

### 3.2 推荐但非必需

| 图表 | 用途 |
|------|------|
| 信号值分布直方图（叠加滚动窗口的分布）| 检查信号分布是否漂移 |
| 月度收益柱状图 + 月度收益热力图 | 季节性 |
| 持仓时长分布直方图 | 验证信号性质（趋势 vs 反转）|
| 持仓 vs 未持仓 bar 的波动比较 | 信号是否只在高波动时段触发 |
| 信号触发 vs ATR(14) 散点 | 信号是否本质上是 vol breakout |
| Walk-Forward 各窗口 Sharpe 柱状图 | 样本外稳定性 |
| 反向信号 P&L 对比图 | 验证不是噪声 |

---

## 四、常见隐患与陷阱（时序信号专属）

### 4.1 未来函数（Look-Ahead Bias）

**时序回测中最致命的错误**，常见形式：

- **bar 内偷看**：信号用了 `close[t]`，但在 t bar 结束前 close 是未知的。正确做法是用 `signal[t]` 决定 `position[t+1]`，并用 `open[t+1]` 或 `close[t+1]` 作为成交价。
- **全局标准化**：`(x - x.mean()) / x.std()` 使用了全样本统计量。必须用**滚动**或**扩展**窗口。
- **未来分位**：用全样本分位数划阈值。同样必须滚动。
- **重采样错位**：把 M1 重采样到 M5 时，bar 时间戳是 bar 开始还是结束？必须明确，否则错位一个 bar 就是 5 分钟的未来函数。
- **数据本身的未来填充**：节假日缺口若用前向填充会把后面的价格泄露到前面——必须用 NaN 标记或剔除。

**排查方法：**
- 在所有特征计算后统一 `.shift(1)` 一次，确保 `feature[t]` 对应 `target[t+1]`。
- 把数据切成 train（70%）/ test（30%），test 段除了存数据之外，所有计算（标准化、分位、模型拟合）都不能碰。
- 人工拉出几个事件，在 K 线图上看信号亮起的位置，**信号亮起时的那根 bar 不能用其 close**。

### 4.2 点差 / 滑点 / 佣金被忽略

5 分钟级别的黄金信号最容易被点差吃掉：

- 黄金现货零售点差约 **0.15 ~ 0.40 USD/oz**（机构 0.05 ~ 0.10）。
- 一根 5m bar 的平均绝对波动也只有 ~1 ~ 3 USD。
- **每次反向调仓**都要付一次点差。如果信号每小时翻仓 1 次，年化 ~6000 次 × 0.2 USD = 1200 USD/oz 成本，几乎吃光任何 edge。
- 必须报告**毛 Sharpe vs 净 Sharpe**，并明确假设的点差。
- 推荐做点差敏感性：在 spread = 0.1 / 0.2 / 0.3 / 0.5 USD 下分别报 Sharpe。

### 4.3 过拟合

**症状：**
- 样本内 Sharpe > 3 但样本外 < 0.5。
- 参数微调 ±10% Sharpe 大幅波动。
- 信号定义里嵌套多个参数（窗口 1、窗口 2、阈值 1、阈值 2…）。

**防范：**
- 参数 ≤ 3 个，每个都要有金融解释。
- 必做 Walk-Forward，看的是 24 个窗口的 Sharpe 分布，不是均值。
- 参数敏感性热力图必须出。
- 反向信号 Sharpe 对比，确认不是统计噪声。

### 4.4 自相关导致的统计假显著

- 5 分钟数据强自相关，普通 t 检验会把 t 值高估几倍。
- 必须用 **Newey-West HAC** 标准误，或对 P&L 做 **block bootstrap**（block 大小 ≥ 信号自相关 1% 衰减点）。

### 4.5 周末缺口与节假日

- 外汇周末停盘，周一开盘有跳空。信号如果跨周末持仓，跳空会产生不在控制内的损益。
- 处理方式之一：周五最后 1 小时强制平仓，周一开盘后第 X 根 bar 才允许进场。
- 圣诞、新年、感恩节当周流动性极差，建议剔除。
- 必须报告**剔除/不剔除节假日**两个版本的 Sharpe。

### 4.6 重要数据公布的极端 bar

- NFP（每月第一个周五 12:30 UTC）、CPI、FOMC 利率决议、地缘事件这类 bar 在 5m 上常出现 5~20 USD 的瞬时跳动。
- 这种 bar 上的成交几乎不可能按 close 价拿到（实际滑点 1~3 USD）。
- 三种处理：(a) 完全剔除事件 ±30 分钟数据；(b) 把那几根 bar 的成交价改成 worst-fill 价；(c) 分两个版本分别报告。

### 4.7 数据源差异

- Dukascopy / HistData / OANDA / MT5 broker 的 XAU/USD 报价**不完全一致**（不同流动性池）。
- 同一信号在不同源上 Sharpe 可能差 30%。
- 必须明确报告数据源；进阶检验：拿第二个数据源跑同一信号，看相对秩是否一致。

### 4.8 信号稀疏性

- 阈值卡得太严，2 年只触发 30 次：样本不足，置信区间很宽，Sharpe 不可信。
- 经验法则：触发事件 ≥ 200 次才有统计意义。
- 否则要么放宽阈值、要么报告“信号样本不足”而非给出 Sharpe 数字。

### 4.9 收益率累加方式

| 问题 | 影响 | 正确做法 |
|------|------|---------|
| 算术 vs 对数 | 长期累乘时算术收益会高估 | P&L 累加用对数收益更稳定；最终展示时再 `exp(.) - 1` 转算术 |
| 价格类型 | bid / ask / mid 影响 ~0.2 USD | 明确：信号用 mid，成交按方向用 ask（买）/ bid（卖）|
| 时区 | UTC vs broker server time vs NY time | 全流程统一 UTC，画图时再转 |
| 时间戳含义 | bar 开始 or bar 结束 | 推荐统一为 bar 开始时间；信号在 bar 结束才能确定 |

### 4.10 Regime 依赖与渐进失效

- 时序信号比截面因子更容易随市场结构变化而失效（如 2020 黄金高波动行情 vs 2024 低波动）。
- 累计 Sharpe 是“后视”指标，**滚动 Sharpe** 才能看出失效。
- 一旦发现滚动 Sharpe 在最近 3~6 个月持续低于 0，停止使用。
- 推荐为信号做“健康度仪表盘”：滚动相关、滚动 Sharpe、滚动命中率、滚动触发频率。

### 4.11 仓位定义的细节

- `position[t]` 是“在 t 这根 bar 内的持仓”，决定 t bar 的盈亏。
- 因此 `position[t]` 必须基于 `signal[t-1]` 或更早。
- 一个常见的错位 bug：`position = sign(signal)`，导致 `position[t]` 用了 `signal[t]`，等于 bar 内偷看。
- 正确写法：`position = sign(signal).shift(1)` 然后 `pnl[t] = position[t] * ret_1[t]`。

### 4.12 极端单笔交易主导业绩

- 一两次极端 bar 的盈利可能撑起整个回测的 Sharpe。
- 检查方法：把全部 P&L 排序，去掉最大 1% 和最小 1% 后重算 Sharpe；如果 Sharpe 暴跌则不可靠。
- 同样报告**收益偏度**和**最大单 bar 盈亏**。

---

## 五、信号回测报告模板

```
1. 信号概述
   - 信号名称、计算公式、经济/技术逻辑
   - 参数列表及默认值
   - 输入数据：价格类型（mid/bid/ask）、频率、所需历史长度

2. 数据描述
   - 数据源、时间范围、bar 数
   - 缺口/异常处理记录
   - 点差假设（中位数 + 极端值）

3. 信号统计描述
   - 信号值分布（均值、中位数、偏度、峰度）
   - 滚动分布漂移图
   - 信号自相关序列
   - 触发频率（多/空、按月、按时段）

4. 时序预测力
   - ρ_pred（Pearson + Spearman）+ HAC t 统计量
   - 滚动 ρ_pred 时间序列
   - 信号衰减曲线（h=1..100）
   - 阈值响应图（分位收益 + 误差棒）

5. 事件研究
   - 事件窗口曲线（多/空分开）
   - 95% 置信带
   - 事件命中率、平均事件收益分布

6. P&L 模拟
   - 累计 P&L（毛 / 净）
   - 年化收益、波动、Sharpe、Sortino、Calmar、MDD
   - 命中率、盈亏比、换手率
   - 价格 + 信号 + 仓位三联图（代表性窗口）

7. 时段 / Regime 切片
   - Session 热力图
   - 高/中/低波动 regime 分别的 Sharpe
   - 趋势/震荡 regime 分别的 Sharpe
   - 节假日 / NFP 剔除前后对比

8. 稳健性
   - 样本内 vs 样本外 Sharpe
   - Walk-Forward 各窗口 Sharpe 分布
   - 参数敏感性热力图
   - 点差敏感性表格
   - 反向信号对照
   - Bootstrap 95% CI

9. 结论
   - 信号是否有效、稳定、可用
   - 推荐持有期、阈值、适用 session
   - 已知失效条件
   - 推荐的下一步研究方向
```

---

## 六、Agent 执行检查清单

```
□ 数据已下载，时间跨度 ≥ 2 年，bar 数 ≥ 130k
□ 时间戳统一 UTC，无重复，OHLC 字段完整
□ 周末/节假日缺口已检查并记录
□ 点差已估算并写入成本模型
□ 信号计算完成，无 NaN 泄漏
□ 信号已 .shift(1)，与未来收益正确对齐
□ 所有标准化/分位用滚动窗口，无全局未来函数
□ 仓位由 signal[t-1] 决定，pnl[t] = position[t] × ret[t]
□ 毛 Sharpe 与 净 Sharpe 都已报告
□ 事件触发次数 ≥ 200，信号样本充足
□ 信号衰减曲线已绘制，最佳持有期已确定
□ 滚动 Sharpe 无长期负值段
□ Walk-Forward 已完成，各窗口 Sharpe 分布合理
□ 参数敏感性是“高原”而非“尖峰”
□ Newey-West 或 block bootstrap 已用于显著性检验
□ Session、Regime、节假日切片分析已完成
□ 反向信号对照已跑，确认不是噪声
□ 极端 bar 剔除前后 Sharpe 变化已检查
□ 所有必需图表已生成
□ 最终结论已明确说明：可用 / 不可用 / 条件可用
```
