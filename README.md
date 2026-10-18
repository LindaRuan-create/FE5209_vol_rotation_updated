# FE5209 Volatility Rotation

NUS RMI · FE5209 Financial Econometrics group project. The final strategy funds **90% in a US V2 account and 10% in a Singapore ES3/A35 account once at inception**. Thereafter the accounts operate independently. Their shares of total assets drift with returns and FX; no transfers restore 90/10.

## Run and view the instructor report

For immediate viewing, open **`results/Report.html`** in a browser; no Python installation is needed to read it. Keep the report inside `results` so its CSV download links work.

To recalculate on macOS, double-click `run_all.command`. If the local environment is absent, the launcher creates `.venv` and installs missing project dependencies automatically. This first-time setup requires Python 3.10+ and internet access; subsequent default runs use local data. Alternatively, install using the setup instructions below and use the project interpreter directly:

```bash
.venv/bin/python run_all.py
```

After a successful run, open `results/Report.html`. The macOS launcher attempts to open it automatically. The report includes daily equity and holdings, individual trades and costs, actual sleeve shares, source quote dates, execution statuses, and latest within-sleeve targets.

The default run uses local price snapshots and executes **03 → 02 → 05 → 06 → 07 → 08**. It does not download prices. GARCH fitting, voting across 6,336 parameter sets, and robustness analysis take time. Each stage writes a log under `results/logs`. Execution stops if a stage fails; an existing report is not evidence that the new run succeeded.

```bash
# Download prices first, with backups, then rebuild all outputs.
.venv/bin/python run_all.py --update-data

# Render existing CSV snapshots only; no recalculation or third-party packages.
python3 run_all.py --view-only

# Run accounting and calendar regression tests.
.venv/bin/python -m unittest discover -s tests
```

A generation date is not a price cutoff. Inspect the report's input dates and the `US_quote_date`, `SG_quote_date`, `FX_quote_date`, and status columns. A latest target is a plan for the next valid local session, not a fill.

## Install on a new computer or after moving the folder

Python 3.10 or later is required. A virtual environment is machine- and location-specific. Recreate it in its final directory rather than copying a Mac `.venv` to the teacher's machine.

For a fresh environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_all.py
```

On Windows, use `.venv\Scripts\python` instead of `.venv/bin/python`. Optional activation uses `source .venv/bin/activate` on macOS or `.venv\Scripts\activate` on Windows. Direct interpreter invocation avoids accidentally selecting another Python installation.

If an existing environment belongs to a previous folder path, close its running kernels, move it aside, then create a fresh one:

```bash
mv .venv .venv_old
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The machine-specific `.venv` need not be included in a submission archive. The macOS launcher recreates it when absent; manual setup is also available below. `requirements-lock.txt` records the validated Python 3.14 versions; `requirements.txt` supplies compatible dependency ranges for other Python versions. Do not include `.venv`, old environment copies, or `__pycache__` in the submission archive. `.gitignore` excludes them from Git, but not from an ordinary Finder copy or zip.

## Strategy data flow

| Stage | Role | Main output |
|---|---|---|
| `00_engine.ipynb` | Shared price loading, adjustments, fee rates, periods, and exact fee solver | Functions loaded by other stages |
| `01_data_update.ipynb` | Optional download of US ETFs, Singapore ETFs, and USD/SGD | `data/raw/etf_daily.csv`, `sti_daily.csv` |
| `02_parameter_ensemble.ipynb` | 6,336 parameter votes produce US V0 targets | `ensemble_weights_history.csv` |
| `03_sti_garch.ipynb` | GARCH forecasts produce within-Singapore ES3/A35 targets and research diagnostics | `sti_weights_history.csv`, `sti_*` outputs |
| `05_risk_allocation.ipynb` | Inverse-volatility allocation using 60 US trading returns, producing V1 | `risk_adjusted_weights.csv` |
| `06_bsv_volatility_targeting.ipynb` | 30% annualized volatility target; released risk capital goes to BSV | `v2_weights_history.csv` |
| `07_final_strategy.ipynb` | Historical independent-account evaluation, diversification, and bootstrap | `final_*` tables, signals, figures |
| `08_final_strategy_live.ipynb` | Separate USD 100,000 simulated live-window accounts | `final_live_*` ledgers and report inputs |
| `portfolio_accounting.py` | Shared native-session ledgers, independent funding, local cash, fees, and USD valuation | Used by 05/06 for shared definitions and by 07/08 for execution |
| `run_all.py` | Stage orchestration, logging, and HTML generation | `results/Report.html` |

The raw `etf_daily.csv` includes US ETFs, Singapore ETFs, and FX on a union of market dates. **Both 05 and 06 call `00_engine.load()` to filter US sessions before computing percentage changes.** US holiday rows therefore cannot remove the next valid US return. Only selecting US columns without filtering dates is insufficient. The 60-day lookback, inverse-volatility exponent of 1, and 30% target have not been tuned in this change.

The US signal universe includes SPY, QQQ, TQQQ, UVXY, TECL, SPXL, SQQQ, TECS, and BSV. The traded V2 pool is TQQQ, UVXY, TECL, SPXL, TECS, and BSV. Singapore uses ES3.SI and A35.SI, abbreviated ES3/A35 in the ledger. All execution prices are on a dividend-adjusted basis; fractional adjusted units are allowed.

## Independent account and execution rules

1. At the preceding valuation date, credit 90% of initial USD capital to the US account. Convert the remaining 10% to SGD once, using the latest available prior-to-start FX quote, and credit the Singapore account. There is no subsequent cross-account transfer or implicit borrowing.
2. Each account rebalances daily **within its own assets**, at a valid native source opening, using the latest target dated strictly before that session. A newer known target replaces an older unexecuted target.
3. Source opening prices remain missing where the source has no quote. A missing or invalid opening blocks sleeve trading. A missing closing mark can be carried for provisional valuation; it is not used to approve an earlier opening order. Filled valuation prices never execute.
4. Holdings and local cash remain unchanged on absent source sessions. The consolidated calendar is the union of US and Singapore source-session dates, preserving US-only and Singapore-only changes. Current holdings, actual sleeve shares, and target percentages are separate quantities.
5. Historical sleeve funding starts once at the beginning of the full backtest. It is not reset at the OOS boundary. The live window is a separate experiment initialized again with USD 90,000 and USD 10,000-equivalent SGD.

The latest target report contains `target_within_sleeve`, `current_sleeve_share`, `current_total_weight`, and `indicative_total_weight`. The indicative total weight equals the current account share times its model target; it is not an instruction to restore total-portfolio funding to 90/10. `final_weights_history.csv` retains its historical filename but now records **actual consolidated weight history**, not a sequence of fixed 90/10 global targets.

## Submission metric reference

For submission and presentations, quote historical performance from the **Submission reference: historical IS / OOS metrics** table in `results/Report.html`, generated directly from `results/tables/final_metrics.csv` by 07. For the final combined strategy, select the row `Final V2 + Singapore (initial 90/10; independent sleeves)` and state the period (IS, OOS, or OOS ex-2020). Use the same table for strategy comparisons. These metrics use the shared account ledger, union valuation calendar, and transaction costs. They describe the historical account funded in 2012, with no OOS allocation reset.

Standalone notebook tables from 02/03/05/06 are research diagnostics, not the submission source for final portfolio performance. Their calendars, period slicing, and, in 03, cost and turnover conventions may differ; do not combine their headline metrics with final-table figures. Standardizing the citation source does not change those research calculations.

October tracking is a separate account: quote its results from the **Live tracking summary** table (`results/tables/final_live_summary.csv`), with the actual data cutoff. Do not label October tracking as historical OOS or splice its returns into historical performance.

## Two distinct account histories

| Item | Historical account (07) | October tracking account (08) |
|---|---|---|
| Inception | 2012-08-01 | 2026-10-01 |
| Initial allocation | 90% US / 10% Singapore, once in 2012 | Fresh USD 100,000: USD 90,000 US / USD 10,000-equivalent SGD |
| OOS boundary (2020-01-01) | Carry existing holdings and cash; no reset or new funding | Not applicable |
| Subsequent allocation | Sleeve shares drift; no cross-account transfers | Sleeve shares drift; no cross-account transfers |
| Connection | Continuous historical account across IS and OOS | Separate experiment; does not inherit historical holdings, NAV, or allocation |

OOS performance measures the historical account's return over the OOS window, not a newly funded 90/10 portfolio in 2020. A small Singapore share at the end of historical OOS is therefore consistent with the chosen policy. October may use signals estimated from earlier data, but it begins with new cash and its performance must not be spliced onto the historical equity curve. `portfolio_accounting.py` centralizes the inception and tracking settings.

## FX and valuation

USD/SGD is quoted as local SGD units per USD. Singapore securities and cash are held in SGD. Native ES3/A35 trades and fees are booked in SGD and do not repeatedly convert the whole account at each rebalance.

USD amounts in the trade ledger use the most recent **strictly earlier** daily FX quote as a reporting reference. Columns include `fx_reference`, `fx_reference_date`, `notional_local`, and `cost_local`. This is not an assertion that an intraday FX trade occurred at that rate. Actual local-currency balances drive the ledger.

At each date's closing valuation, SGD securities plus SGD cash are translated using the latest available closing FX. Local price marks can carry forward; their source dates are retained, and FX changes can affect USD value even while the security market has no new quote. These are date-based closing snapshots, not claims of simultaneous US/SGX closing auctions. Missing sessions are not independently certified as holidays; an absent or incomplete source is labeled and cannot trade. A carried quote at the end of the sample must not be presented as a newly confirmed close.

## Periods and costs

| Period | Start | End |
|---|---|---|
| IS | 2012-08-01 | 2019-12-31 |
| OOS | 2020-01-01 | 2026-09-30 |
| OOS ex-2020 | 2021-01-01 | 2026-09-30 |
| Live tracking | 2026-10-01 | 2026-10-20, limited by available data |

05/06 and the final account engine use shared date constants from 00. Signal histories extend into October for tracking; OOS statistics stop at September 30. Final 07 performance and bootstrap returns include the first period session by retaining the preceding close. Older standalone research tables retain their original metric slicing convention and should not be treated as identical account histories.

| Asset | One-way bps |
|---|---:|
| SPY | 0.5 |
| QQQ | 1.5 |
| TQQQ / BSV | 1 |
| UVXY | 6 |
| TECL | 35 |
| SPXL | 16 |
| SQQQ | 3 |
| TECS | 15 |
| ES3 / A35 | 10 |

One basis point is 0.01%. Shared exact fee arithmetic solves costs from actual local trade notionals and after-fee target holdings. Entry costs are included, and there is no forced terminal liquidation. Final US and ES3 buy-and-hold comparators include entry fees and use valid source openings.

Turnover includes both sides of a switch and is not divided by two. Because markets open at different times, final combined turnover divides daily reference-USD trade notionals by preceding total closing NAV, rather than a fictional simultaneous global opening NAV. Annualization uses 252 divided by the number of reported union-session observations. Standalone 03 research still reports ES3-leg turnover and uses its original weight-based fee approximation; it is distinct from the shared final/live account ledger.

## Main outputs

- `results/Report.html`: instructor-facing report; distribute `results` to retain CSV links.
- `results/tables/final_live_daily_positions.csv`: cash, holdings, account shares, source dates, statuses, and equity.
- `results/tables/final_live_trades.csv`: valid-source modeled fills, signal dates, local and USD-reference costs.
- `results/tables/final_live_current_holdings.csv`: current holdings including separate cash accounts.
- `results/tables/final_live_summary.csv`: simulated window performance and latest quote status.
- `results/signals/final_live_next_open_target.csv`: within-account targets for subsequent valid local sessions.
- `results/tables/final_daily_accounts.csv`, `final_historical_trades.csv`: full historical independent-account records.
- `results/figures/final_sleeve_shares.png`: drifting US/Singapore shares.

The submission retains only the current strategy, required price snapshots, reproducible results, dependencies, and tests. Legacy notebooks, fixed-weight helper 04, obsolete `live_oct_*` outputs, internal audit notes, the old baseline Word guide, and empty placeholder directories have been removed. Execution logs and caches are generated locally when needed. `report/contribution.md` is a course-related template that the team must complete before submission.

## Interpretation limits

This is a daily-price simulation, not actual broker trading. Intraday FX fills, settlement, board lots, minimum commissions, liquidity impact, and financing are not modeled. There is no exchange-calendar certification of absent source days. No order executes without an original valid opening quote.

The retrospective A35 quote filter remains disabled because it uses following-day information. Suspicious raw quotes remain a data-quality limitation rather than being silently rewritten. Model-selection bias and the information used to select the overall strategy must be disclosed independently of OOS date boundaries.
