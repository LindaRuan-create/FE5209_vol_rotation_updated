# FE5209 Volatility Rotation

NUS RMI · FE5209 Financial Econometrics group project (ReReRe)

## 1. The strategy in one paragraph

Every day after the US close, the SPY 120-day moving average gives the broad direction, then each ETF's RSI is run through a decision tree to pick the ETF to hold on the next trading day. Trades are executed at the T+1 open.

**Final strategy = US V2 (30% target volatility) + CPI overlay (US sleeve) + Singapore sleeve (ES3 GARCH + A35).** From 2012-08-01 the capital is split **90% / 10%**; the two accounts then run independently, and the Singapore share is reset to 10% only when it drifts more than **±1 percentage point** away from 10% (threshold rule, see Account rules).

| Layer | File | What it does |
|---|---|---|
| V0 parameter vote | `02_parameter_ensemble` | 7 parameters, 6,336 combinations in total; each combination casts 1 vote per day, and the share of votes = the position weight |
| V1 volatility-based allocation | `05_risk_allocation` | V0 weight ÷ each ETF's past 60-day volatility (α = 1), then normalised |
| V2 30% target volatility | `06_bsv_volatility_targeting` | When the V1 portfolio's forecast volatility exceeds 30%, risky assets are scaled down proportionally and the excess is parked in BSV |
| CPI overlay (US sleeve) | `09_cpi_overlay` | After a hot CPI release (actual YoY above forecast) in a regime where the market reacts to CPI, the TQQQ target is swapped into UVXY for 3 trading days (opens of days 1–3) and the account is rebalanced back to the unhedged V2 target at the closing price of day 3 |
| Singapore sleeve | `03_sti_garch` | GARCH forecasts ES3's volatility for tomorrow; ES3 weight = min(target volatility / forecast volatility, 1), and the rest is held in A35 |

Instruments: SPY, QQQ and SQQQ are used for signals; the US sleeve trades TQQQ, UVXY, TECL, SPXL, TECS and BSV; the Singapore sleeve trades ES3.SI (SPDR STI ETF) and A35.SI (ABF Singapore Bond Index Fund).

## 2. How to run

**Results only:** open `results/Report.html` in a browser; no Python needed. Keep the report next to the `results/` folder, otherwise the CSV download links inside it will not work.

**Recompute (Python 3.10+; the first run needs internet to install dependencies):**

- Windows: double-click `run_all.bat`
- macOS: double-click `run_all.command`
- Command line:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt      # on Windows use .venv\Scripts\python
.venv/bin/python run_all.py                  # recompute everything from local data and build results/Report.html
.venv/bin/python run_all.py --update-data    # download the latest prices first (old files are backed up), then recompute
python run_all.py --view-only                # no recomputation; build the report from the existing CSVs
.venv/bin/python -m unittest discover -s tests   # accounting rule tests
```

`run_all.py` runs the stages in the order **03 → 02 → 05 → 06 → 07 → 08 → 09**. `data/raw/cpi_yoy.csv` is required: 07 and 08 load the CPI rule defined in 09, and 09 adds the with / without comparison tables. Each step's log is written to `results/logs/`, and the run stops at the first step that fails. The 6,336-combination vote and the monthly GARCH re-estimation are slow, so a full run takes a few minutes.

You can also open the notebooks one by one in Jupyter / PyCharm and use Restart Kernel → Run All, in the same order. `.venv` is tied to the machine; recreate it on a new computer instead of copying it.

## 3. Files and data flow

```text
data/raw/etf_daily.csv ─┬─> 02 V0 vote ─> 05 V1 ─> 06 V2 ─┐
                        │                                  ├─> 07 historical backtest (2012-08 ~ 2026-09-30)
data/raw/sti_daily.csv ─┴─> 03 Singapore GARCH ────────────┤
                                                           └─> 08 live simulation (2026-10-01 ~ 10-20)
```

| File | Purpose | Main outputs |
|---|---|---|
| `pipeline/00_engine.ipynb` | Shared engine: instruments, cost table, IS/OOS dates, price loading, RSI decision tree, exact fees, performance metrics | Imported by the other files |
| `pipeline/1_data/01_data_update.ipynb` | Optional: download US ETFs, ES3, A35 and USD/SGD | `data/raw/etf_daily.csv`, `sti_daily.csv` |
| `pipeline/2_signals/02_parameter_ensemble.ipynb` | V0 | `results/signals/ensemble_weights_history.csv` |
| `pipeline/2_signals/03_sti_garch.ipynb` | Singapore sleeve (ARCH test, model selection, forecast evaluation, backtest) | `sti_weights_history.csv`, `results/tables/sti_*.csv` |
| `pipeline/2_signals/05_risk_allocation.ipynb` | V1 and robustness checks | `risk_adjusted_weights.csv`, `risk_*.csv` |
| `pipeline/2_signals/06_bsv_volatility_targeting.ipynb` | V2 and target-volatility sensitivity | `v2_weights_history.csv` |
| `pipeline/3_results/07_final_strategy.ipynb` | Historical backtest of the final strategy, diversification, bootstrap | `results/tables/final_*.csv`, `results/figures/final_*.png` |
| `pipeline/3_results/08_final_strategy_live.ipynb` | October live-simulation ledger | `final_live_*.csv` |
| `pipeline/2_signals/09_cpi_overlay.ipynb` | CPI overlay rule (loaded by 07 and 08), with / without comparison, and two optional evidence cells (how the switch and the hedge settings were set; off by default) | `v2_cpi_overlay_weights_history.csv`, `cpi_overlay_*.csv` |
| `portfolio_accounting.py` | Bookkeeping for the two independent accounts: trades, cash, fees, FX; plus an optional "rebalance back at the closing price on specified dates only" (used for the CPI hedge exit) | Imported by 07, 08, 09 |
| `data/raw/cpi_yoy.csv` | Forecast and actual CPI year-over-year (maintained by hand; add one row after each release) | 09 |
| `run_all.py` / `run_all.bat` / `run_all.command` | One-click run and report generation | `results/Report.html` |
| `tests/test_accounting.py` | Regression tests for the accounting rules | — |
| `tests/test_cpi_overlay.py` | Tests for the CPI overlay and the close-price exit | — |

**Numbers to quote:** for the final strategy's historical performance use `results/tables/final_metrics.csv` (also shown in `Report.html`), the row named `Final V2 + CPI overlay + Singapore (90/10 start; ±1pt threshold)` (the row `V2 + Singapore ..., no CPI overlay` is the same strategy without the overlay, for comparison), and state IS / OOS / OOS ex-2020. The tables from 02, 03, 05 and 06 are research diagnostics; their calendars and cost conventions may differ, so do not mix them with the final table. For October live results use `final_live_summary.csv`; it is a separate account and must not be chained onto the historical equity curve.

## 4. Key assumptions

**Time split** (defined in `00_engine`)

| Period | Start | End |
|---|---|---|
| IS | 2012-08-01 | 2019-12-31 |
| OOS | 2020-01-01 | 2026-09-30 |
| OOS ex-2020 | 2021-01-01 | 2026-09-30 |
| Live simulation | 2026-10-01 | 2026-10-20 (subject to actual data) |

The strategy and its parameters were fixed using results up to and including 2026-09-30 only.

**Account rules** (`portfolio_accounting.py`)

1. Initial allocation: 90% of the money goes into the US account in USD, and 10% is converted to SGD at the last exchange rate before the start and put into the Singapore account.
   **Threshold reset (±1pt):** at each close, if the Singapore share of total value differs from 10% by more than 1 percentage point (|share − 10%| > 1pt), a flag is set. On the first later date on which both markets have a valid opening price and a known signal, cash is moved between the two accounts at the opening so that the Singapore share goes back to 10% of total opening value (converted at the prior FX reference; the FX conversion cost is 0 in the baseline), and then each sleeve rebalances to its own target. Between resets there are no transfers and the two sides drift with returns. The `no rebalance` rows in `final_metrics.csv` are the variant without this rule.
2. Each account trades only at the valid opening price of its own market, using the latest target weights obtained from the previous trading day's close (or earlier), and rebalances to the target every day.
3. If the opening price is missing, no trade is made. A missing closing price may be valued at the last known price, but a stale price is never used to trade.
4. Singapore holdings, cash and fees are booked in SGD; for valuation they are converted to USD at that day's closing exchange rate.
5. The historical account (07) runs continuously from 2012-08-01; IS and OOS are two segments of the same account and nothing is reset on 2020-01-01. The October live simulation (08) opens a fresh account with USD 100,000.

**Transaction costs** (one-way, 1 bp = 0.01%)

| SPY | QQQ | TQQQ | BSV | UVXY | TECL | SPXL | SQQQ | TECS | ES3 | A35 |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.5 | 1.5 | 1 | 1 | 6 | 35 | 16 | 3 | 15 | 10 | 10 |

Fees are computed exactly on the traded amount (`00_engine.rebalance_exact`). All prices are dividend- and split-adjusted, and fractional shares are allowed. Turnover counts both buys and sells and is not divided by 2.

## 5. Limitations

- This is a simulation on daily prices, not real broker execution. Intraday FX conversion, settlement, minimum lot sizes, minimum commissions, market impact and financing are not modelled.
- Days with missing data were not checked one by one for whether the market was actually closed; if the last day uses a carried-forward price, it does not represent a new closing price.
- ES3 has many zero-return days in 2012–2017 (coarse quote precision); A35 traded thinly in the early years and has suspicious quotes. The A35 cleaning rule that uses next-day prices is off by default, and the suspicious quotes are kept as a data limitation.
- The strategy structure and parameters were chosen after looking at historical results, so there is selection bias; even though the OOS dates are clearly separated, this must be stated explicitly.
- **CPI overlay (09).** The economic prior is that after the COVID recovery the market started to react to CPI releases; the specific rule values (previous YoY ≥ 3%, 16-event window, hit rate ≥ 70%, 3-day hold, 100% of TQQQ into UVXY) were set after looking at the data, so the OOS result is **not** a clean out-of-sample test. It triggers only 9 times (none in IS), most of the gain comes from 2023, 2024 and the October 2026 release, and maximum drawdown is not reduced. The exit is executed at the closing price (live trading would need a closing-auction order) with no slippage. The row `no CPI overlay` in `final_metrics.csv` shows the strategy without it.
- The ±1pt threshold reset moves cash between the two accounts and assumes a zero FX conversion cost in the baseline; in practice the transfers would incur conversion costs and settlement delays. Without the reset (`no rebalance` rows), the Singapore share drifts and is diluted by the US sleeve, so the total portfolio ends up close to pure V2.

`report/contribution.md` is a template for the division of work; each member fills in their own row before submission.
