# FE5209 Volatility Rotation

NUS RMI · FE5209 Financial Econometrics 小组项目（ReReRe）

## 1. 策略一句话

每天美股收盘后，用 SPY 120 日均线判断大方向，再看各 ETF 的 RSI，按决策树选出下一交易日持有的 ETF，T+1 开盘执行。

**最终策略 = 美股 V2（目标波动 30%）+ 新加坡部分（ES3 GARCH + A35）**，2012-08-01 起按 **90% / 10% 一次性**分配资金，之后两个账户各自运作、互不转账。

| 层 | 文件 | 做什么 |
|---|---|---|
| V0 参数投票 | `02_parameter_ensemble` | 7 个参数共 6,336 组，每组每天投 1 票，得票比例 = 仓位 |
| V1 按波动率分配 | `05_risk_allocation` | V0 仓位 ÷ 各 ETF 过去 60 日波动率（α = 1）后归一 |
| V2 目标波动 30% | `06_bsv_volatility_targeting` | V1 组合预测波动超过 30% 时等比例缩小风险资产，多出的钱放 BSV |
| 新加坡部分 | `03_sti_garch` | GARCH 预测 ES3 明日波动，ES3 仓位 = min(目标波动 / 预测波动, 1)，其余持有 A35 |

标的：信号用 SPY、QQQ、SQQQ；美股交易 TQQQ、UVXY、TECL、SPXL、TECS、BSV；新加坡交易 ES3.SI（SPDR STI ETF）和 A35.SI（ABF Singapore Bond Index Fund）。

## 2. 怎么运行

**只看结果：** 用浏览器打开 `results/Report.html`，不需要装 Python。报告要和 `results/` 文件夹放在一起，里面的 CSV 下载链接才有效。

**重新计算（需要 Python 3.10+，第一次需要联网装依赖）：**

- Windows：双击 `run_all.bat`
- macOS：双击 `run_all.command`
- 命令行：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt      # Windows 用 .venv\Scripts\python
.venv/bin/python run_all.py                  # 用本地数据重算全部结果，生成 results/Report.html
.venv/bin/python run_all.py --update-data    # 先下载最新价格（会备份旧文件），再重算
python run_all.py --view-only                # 不重算，只用现有 CSV 生成报告
.venv/bin/python -m unittest discover -s tests   # 记账规则测试
```

`run_all.py` 按 **03 → 02 → 05 → 06 → 07 → 08** 的顺序运行，每一步的日志写在 `results/logs/`，任何一步出错就停止。6,336 组投票和 GARCH 每月重估比较慢，完整跑一次需要几分钟。

也可以在 Jupyter / PyCharm 里逐个打开 notebook，Restart Kernel 后 Run All，顺序同上。`.venv` 和机器绑定，换电脑要重新建，不要拷贝。

## 3. 文件和数据流

```text
data/raw/etf_daily.csv ─┬─> 02 V0 投票 ─> 05 V1 ─> 06 V2 ─┐
                        │                                  ├─> 07 历史回测 (2012-08 ~ 2026-09-30)
data/raw/sti_daily.csv ─┴─> 03 新加坡 GARCH ───────────────┤
                                                           └─> 08 实盘模拟 (2026-10-01 ~ 10-20)
```

| 文件 | 作用 | 主要输出 |
|---|---|---|
| `pipeline/00_engine.ipynb` | 公共引擎：标的、成本表、IS/OOS 日期、读价格、RSI 决策树、精确手续费、绩效指标 | 被其他文件调用 |
| `pipeline/1_data/01_data_update.ipynb` | 可选：下载美股 ETF、ES3、A35 和 USD/SGD | `data/raw/etf_daily.csv`、`sti_daily.csv` |
| `pipeline/2_signals/02_parameter_ensemble.ipynb` | V0 | `results/signals/ensemble_weights_history.csv` |
| `pipeline/2_signals/03_sti_garch.ipynb` | 新加坡部分（ARCH 检验、模型选择、预测评估、回测） | `sti_weights_history.csv`、`results/tables/sti_*.csv` |
| `pipeline/2_signals/05_risk_allocation.ipynb` | V1 和稳健性检验 | `risk_adjusted_weights.csv`、`risk_*.csv` |
| `pipeline/2_signals/06_bsv_volatility_targeting.ipynb` | V2 和目标波动敏感性 | `v2_weights_history.csv` |
| `pipeline/3_results/07_final_strategy.ipynb` | 最终策略历史回测、分散化、bootstrap | `results/tables/final_*.csv`、`results/figures/final_*.png` |
| `pipeline/3_results/08_final_strategy_live.ipynb` | 10 月实盘模拟账本 | `final_live_*.csv` |
| `portfolio_accounting.py` | 两个独立账户的记账：成交、现金、手续费、汇率 | 被 07、08 调用 |
| `run_all.py` / `run_all.bat` / `run_all.command` | 一键运行和生成报告 | `results/Report.html` |
| `tests/test_accounting.py` | 记账规则回归测试 | — |

**要引用的数字：** 最终策略的历史绩效看 `results/tables/final_metrics.csv`（`Report.html` 里也有），行名 `Final V2 + Singapore (initial 90/10; independent sleeves)`，注明 IS / OOS / OOS ex-2020。02、03、05、06 自己的表是研究诊断，日历、成本口径可能不同，不要和最终表混用。10 月实盘看 `final_live_summary.csv`，它是单独的账户，不能接在历史净值后面。

## 4. 关键假设

**时间划分**（定义在 `00_engine`）

| 区间 | 起 | 止 |
|---|---|---|
| IS | 2012-08-01 | 2019-12-31 |
| OOS | 2020-01-01 | 2026-09-30 |
| OOS ex-2020 | 2021-01-01 | 2026-09-30 |
| 实盘模拟 | 2026-10-01 | 2026-10-20（以实际数据为准） |

策略和参数只依据 2026-09-30 及以前的结果确定。

**账户规则**（`portfolio_accounting.py`）

1. 开始时一次性分配：90% 美元进美股账户，10% 按开始前最后一个汇率换成新元进新加坡账户。之后**不转账、不调回 90/10**，两边比例随涨跌漂移。
2. 每个账户只在自己市场的有效开盘价成交，用前一个交易日（或更早）收盘得到的最新目标仓位，每天调回目标。
3. 开盘价缺失就不成交。缺失的收盘价可以沿用旧价估值，但旧价不能用来成交。
4. 新加坡的持仓、现金和手续费都用新元记账；估值时按当日收盘汇率换成美元。
5. 历史账户（07）从 2012-08-01 连续运行，IS 和 OOS 是同一账户的两段，2020-01-01 不重置。10 月实盘（08）用 10 万美元重新开一个账户。

**交易成本**（单边，1 bp = 0.01%）

| SPY | QQQ | TQQQ | BSV | UVXY | TECL | SPXL | SQQQ | TECS | ES3 | A35 |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.5 | 1.5 | 1 | 1 | 6 | 35 | 16 | 3 | 15 | 10 | 10 |

手续费按实际成交金额精确计算（`00_engine.rebalance_exact`）。所有价格是除权复权价，允许零碎股。换手率计算买卖两边，不除以 2。

## 5. 局限

- 这是基于日线价格的模拟，不是真实券商成交。没有模拟日内换汇、结算、最小交易单位、最低佣金、冲击成本和融资。
- 缺数据的日子没有逐一核对是否真的休市；最后一天如果用的是沿用价，不代表新的收盘价。
- ES3 在 2012–2017 年零收益日较多（报价精度较粗）；A35 早年成交清淡，有可疑报价。用到次日价格的 A35 清洗规则默认关闭，可疑报价作为数据局限保留。
- 策略结构和参数是在看过历史结果后选定的，存在选择偏差，即使 OOS 日期划分清楚也要单独说明。
- 新加坡账户不调回 10%，比例会随时间被美股稀释，总组合的结果接近纯 V2。

`report/contribution.md` 是分工表模板，提交前每位组员填写自己的一行。
