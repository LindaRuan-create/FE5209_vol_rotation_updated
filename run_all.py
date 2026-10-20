#!/usr/bin/env python3
"""Rebuild from local data, optionally download first, and produce a portable HTML report."""
import argparse
import contextlib
import csv
import html
import json
import os
from pathlib import Path
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent

def execute(name, definitions=False):
    path = next((ROOT / 'pipeline').rglob(name + '.ipynb'))
    from IPython.display import display
    ns = {'__name__': '__main__', 'display': display}
    for i, cell in enumerate(json.loads(path.read_text(encoding='utf-8'))['cells']):
        if cell['cell_type'] != 'code':
            continue
        if definitions and 'pipeline-entry' in cell.get('metadata', {}).get('tags', []):
            continue
        exec(compile(''.join(cell['source']), f'{path}:cell{i}', 'exec'), ns)
    return ns

def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.reader(f))

def report(view_only=False):
    target = ROOT / 'results' / 'Report.html'
    sections = []
    files = [
        ('Live tracking summary', 'tables/final_live_summary.csv'),
        ('Current holdings', 'tables/final_live_current_holdings.csv'),
        ('Latest within-sleeve targets (next valid local session; not fills)', 'signals/final_live_next_open_target.csv'),
        ('Individual trades since live tracking began', 'tables/final_live_trades.csv'),
        ('Daily equity and positions since live tracking began', 'tables/final_live_daily_positions.csv'),
        ('Submission reference: historical IS / OOS metrics', 'tables/final_metrics.csv'),
    ]
    if (ROOT / 'results' / 'tables' / 'cpi_overlay_metrics.csv').is_file():
        files.append(('CPI overlay: with and without (the final strategy includes the overlay)', 'tables/cpi_overlay_metrics.csv'))
    for title, relative in files:
        p = ROOT / 'results' / relative
        rows = read(p)
        table = ''.join('<tr>' + ''.join(f'<{tag}>{html.escape(v)}</{tag}>' for v in row) + '</tr>'
                        for tag, row in [('th', rows[0])] + [('td', r) for r in rows[1:]])
        sections.append(f'<h2>{title}</h2><p><a href="{relative}">Download CSV</a></p><div><table>{table}</table></div>')
    dates = {}
    for rel in ['data/raw/etf_daily.csv', 'data/raw/sti_daily.csv',
                'results/signals/v2_weights_history.csv', 'results/signals/sti_weights_history.csv',
                'results/tables/final_live_daily_positions.csv']:
        dates[rel] = read(ROOT / rel)[-1][0]
    status = 'Existing snapshot only: not recalculated and may use outdated assumptions.' if view_only else 'Recalculated from local data using the current code.'
    latest = dates['results/tables/final_live_daily_positions.csv']
    text = f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>FE5209 Daily rebalancing report</title>
<style>body{{font:15px system-ui;margin:32px;color:#183047}}h1,h2{{color:#123e58}}div{{overflow:auto;max-height:620px}}table{{border-collapse:collapse;font-size:12px}}td,th{{padding:7px;border:1px solid #d4dee5;white-space:nowrap}}th{{background:#e5eff5;position:sticky;top:0}}.notice{{background:#fff0ce;padding:16px}}a{{color:#12668c}}</style>
<h1>FE5209 Daily rebalancing and data</h1><p>Generated at (Singapore time): {datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')} · Ledger through {latest}</p>
<p class="notice">{status} The data cutoff is not necessarily today. This ledger simulates a tracking window using historical prices; it contains no actual broker executions. The US and Singapore accounts are funded 90%/10% once, then operate independently. Missing source openings never execute; older prices are valuation marks only. Source quote dates and account statuses are reported. Missing sessions are not automatically certified as exchange holidays. Daily FX and adjusted prices remain modeling assumptions, not broker fills.</p>
<p>Initial capital: USD 100,000, split once into USD 90,000 for US assets and the SGD equivalent of USD 10,000 for Singapore. Tracking starts on 2026-10-01 and is planned through 2026-10-20. Each sleeve rebalances only at its own valid source opening using an earlier signal; no later transfers restore 90/10. Local fees equal actual trade notional times the one-way asset rate. Singapore USD trade amounts use a prior FX reference for reporting; closing NAV uses available closing FX. Targets are within each sleeve, not fixed global percentages.</p>
<h2>Which figures to quote in the submission</h2>
<p>Use the <strong>Submission reference: historical IS / OOS metrics</strong> table below, sourced directly from <a href="tables/final_metrics.csv">final_metrics.csv</a>. For final portfolio performance, select <strong>Final V2 + Singapore (initial 90/10; independent sleeves)</strong> and identify the IS, OOS, or OOS ex-2020 period. Use that same table for comparisons; its metrics use the shared account ledger, union valuation calendar, and transaction costs.</p>
<p>02/03/05/06 standalone tables are research diagnostics with potentially different calendar, period slicing, cost, or turnover conventions. Do not mix their headline metrics with final portfolio figures. For the separate October account, quote the Live tracking summary and its actual cutoff; it is not historical OOS performance.</p>
<h2>Account inception and performance interpretation</h2>
<p><strong>Historical account (07):</strong> funded once at 90% US / 10% Singapore from 2012-08-01 and operated continuously. IS and OOS are reporting windows on that same account. Holdings and cash carry into 2020-01-01; the OOS boundary does not reset the allocation or add capital. Historical OOS ends on 2026-09-30.</p>
<p><strong>October tracking account (08):</strong> a separate USD 100,000 account initialized on 2026-10-01 at 90% US / 10% Singapore. It does not inherit historical holdings, NAV, or sleeve allocation. Earlier observations may inform signals. After funding, both sleeves operate independently and their allocation drifts. October tracking returns are not a continuation of the historical account's equity curve.</p>
<h2>Input and output cutoff dates</h2><pre>{html.escape(json.dumps(dates,ensure_ascii=False,indent=2))}</pre>
{''.join(sections)}</html>'''
    target.write_text(text, encoding='utf-8')
    print(f'Report: {target}\nLedger cutoff: {latest}\n{status}')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update-data', action='store_true', help='Download updated raw prices then recalculate all stages')
    parser.add_argument('--view-only', action='store_true', help='Display existing CSV snapshots without third-party dependencies (may be outdated)')
    args = parser.parse_args()
    if args.view_only and args.update_data:
        parser.error('--view-only cannot be combined with --update-data')
    os.chdir(ROOT)
    os.environ['ETF_PROJECT_ROOT'] = str(ROOT)
    os.environ['MPLBACKEND'] = 'Agg'
    if not args.view_only:
        logs = ROOT / 'results' / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        stages = (['01_data_update'] if args.update_data else []) + [
            '03_sti_garch', '02_parameter_ensemble', '05_risk_allocation',
            '06_bsv_volatility_targeting', '07_final_strategy', '08_final_strategy_live']
        if not (ROOT / 'data' / 'raw' / 'cpi_yoy.csv').is_file():
            sys.exit('data/raw/cpi_yoy.csv is missing: the CPI overlay is part of the final strategy (07, 08, 09).')
        stages.append('09_cpi_overlay')              # with / without comparison and the evidence cells; 07 and 08 load its rule
        for stage in stages:
            print(f'Run {stage} …', flush=True)
            with (logs / f'{stage}.log').open('w', encoding='utf-8') as log:
                try:
                    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                        if stage == '01_data_update':
                            execute(stage, definitions=True)['main'](download=True)
                        else:
                            execute(stage)
                except Exception:
                    import traceback
                    traceback.print_exc(file=log)
                    raise RuntimeError(f'{stage} failed. See {log.name}. No new instructor report was generated.') from None
            import matplotlib.pyplot as plt
            plt.close('all')
    report(args.view_only)

if __name__ == '__main__':
    main()
