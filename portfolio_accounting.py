"""Independent market sleeves: initial funding (optionally a threshold reset), native-session execution, USD valuation.

US cash stays in USD. Singapore is funded in SGD once using the last FX quote
available before the start. Singapore trades and fees are booked in SGD; USD
trade columns use a strictly earlier daily FX reference, not a claimed FX fill.
Closing marks use the latest available closing FX. Filled prices are marks only.
"""
from dataclasses import dataclass
from pathlib import Path
import contextlib
import io
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def load_definitions(stem):
    path = next((ROOT / 'pipeline').rglob(stem + '.ipynb'))
    namespace = {'__name__': 'pipeline_module'}
    with contextlib.redirect_stdout(io.StringIO()):
        for cell in json.loads(path.read_text(encoding='utf-8'))['cells']:
            if cell['cell_type'] == 'code' and 'pipeline-entry' not in cell.get('metadata', {}).get('tags', []):
                exec(compile(''.join(cell['source']), str(path), 'exec'), namespace)
    return namespace


ENGINE = load_definitions('00_engine')
INITIAL_SG_SHARE = 0.10
# Historical IS/OOS are reporting windows on one continuous account.
HISTORICAL_START = ENGINE['IS_START']
# October tracking is a separately funded experiment, not historical continuation.
LIVE_START = '2026-10-01'
LIVE_END = '2026-10-20'
LIVE_CAPITAL = 100000.0
PERIODS = [('IS', ENGINE['IS_START'], ENGINE['IS_END']),
           ('OOS', ENGINE['OOS_START'], ENGINE['OOS_END']),
           ('OOS ex-2020', '2021-01-01', ENGINE['OOS_END'])]


@dataclass
class Market:
    name: str
    currency: str
    opens: pd.DataFrame
    closes: pd.DataFrame
    fx: pd.Series  # local currency units per USD; USD sleeve uses ones


def _check_dates(frame, label):
    if frame.empty or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f'{label}: expected nonempty, unique, ascending dates.')


def load_markets(csv_path=None):
    """Keep source openings missing. Only valuation, never execution, may carry marks."""
    O, _, _, C = ENGINE['prep'](csv_path)
    us = Market('US', 'USD', O, C, pd.Series(1.0, index=C.index))
    raw_us = pd.read_csv(ENGINE['resolve_csv'](csv_path), header=[0, 1], index_col=0,
                         skiprows=[2], parse_dates=True).sort_index()
    raw_sg = pd.read_csv(ROOT / 'data/raw/sti_daily.csv', index_col=0, parse_dates=True).sort_index()
    _check_dates(raw_sg, 'Singapore source')
    needed = ['open', 'close', 'adj_close', 'bond_open', 'bond_close', 'bond_adj_close', 'usdsgd']
    if not set(needed).issubset(raw_sg):
        raise ValueError('Singapore source requires ES3, A35, and usdsgd data.')
    # Same unfinished-session rule as the Singapore source loader.
    now = pd.Timestamp.now(tz='Asia/Singapore')
    if len(raw_sg) and raw_sg.index[-1].date() >= now.date() and now.hour * 60 + now.minute < 17 * 60 + 30:
        raw_sg = raw_sg.iloc[:-1]
    sg_open, sg_close = pd.DataFrame(index=raw_sg.index), pd.DataFrame(index=raw_sg.index)
    for ticker, prefix in [('ES3', ''), ('A35', 'bond_')]:
        local_close = raw_sg[prefix + 'close']
        adj_close = raw_sg[prefix + 'adj_close']
        opening = raw_sg[prefix + 'open'] * adj_close / local_close
        sg_open[ticker] = opening.where((raw_sg[prefix + 'open'] > 0) & (local_close > 0) & (adj_close > 0))
        sg_close[ticker] = adj_close.where((local_close > 0) & (adj_close > 0))
    fx = raw_sg.usdsgd.copy()
    if ('Close', 'SGD=X') in raw_us:
        fx = fx.combine_first(raw_us['Close']['SGD=X'])
    fx = fx.sort_index().where(lambda s: s > 0).dropna()
    _check_dates(fx, 'FX source')
    sg = Market('Singapore', 'SGD', sg_open, sg_close, fx)
    return us, sg


def read_weights(filename, columns):
    path = ROOT / 'results/signals' / filename
    frame = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    _check_dates(frame, filename)
    if not set(columns).issubset(frame.columns):
        raise ValueError(f'{filename}: missing weight columns.')
    frame = frame.loc[:, columns].astype(float)
    # Warmup rows can be absent, but exported signal rows must be complete.
    if not np.isfinite(frame.to_numpy()).all() or (frame < -1e-10).any().any() or (frame.sum(axis=1) > 1 + 1e-8).any():
        raise ValueError(f'{filename}: invalid or incomplete target weights.')
    return frame


def strategy_weights(us_strategy='v2'):
    us_name = {'v2': 'v2_weights_history.csv', 'v0': 'ensemble_weights_history.csv'}[us_strategy]
    exported = pd.read_csv(ROOT / 'results/signals' / us_name, nrows=1).columns[1:]
    names = [t for t in ENGINE['TICKS'] if t in exported]
    us = read_weights(us_name, names)
    sg = read_weights('sti_weights_history.csv', ['es3_weight', 'a35_weight'])
    return us, sg.rename(columns={'es3_weight': 'ES3', 'a35_weight': 'A35'})


def _asof(series, date, strict=False):
    pos = series.index.searchsorted(pd.Timestamp(date), side='left' if strict else 'right') - 1
    if pos < 0:
        raise ValueError(f'No prior observation available at {date}.')
    return series.index[pos], float(series.iloc[pos])


def common_timeline(markets, start, end=None):
    dates = markets[0].closes.index
    for market in markets[1:]:
        dates = dates.union(market.closes.dropna(how='all').index)
    dates = dates.sort_values()
    start = pd.Timestamp(start)
    end = pd.Timestamp(end) if end is not None else dates.max()
    preceding = dates[dates < start]
    if not len(preceding) or not ((dates >= start) & (dates <= end)).any():
        raise ValueError('Need a pre-start valuation date and at least one tracking date.')
    return dates[(dates >= preceding[-1]) & (dates <= end)]


TRADE_COLUMNS = ['exec_date', 'signal_date', 'ticker', 'sleeve', 'side', 'shares',
                 'price_local', 'price_usd', 'currency', 'notional_local', 'notional_usd',
                 'cost_local', 'cost_usd', 'cost_bps', 'weight_before', 'weight_after',
                 'fx_reference', 'fx_reference_date', 'execution_quote_date', 'note']


class _SleeveRunner:
    """One sleeve's ledger, advanced one date at a time (same maths as before).

    `step(i, d, cash_adjust)` optionally adds a cross-sleeve transfer (local
    currency) to cash immediately before that date's rebalance.
    """

    def __init__(self, market, weights, timeline, capital, rebalance):
        if rebalance not in {'daily', 'on_change', 'buy_hold'}:
            raise ValueError('Unknown rebalance mode.')
        _check_dates(weights, 'Weights')
        names = list(weights.columns)
        if not set(names).issubset(market.opens.columns):
            raise ValueError('Weight columns must have market prices.')
        if capital <= 0:
            raise ValueError('Capital must be positive.')
        self.market, self.weights, self.timeline = market, weights, timeline
        self.names, self.capital, self.rebalance = names, capital, rebalance
        fx_date, funding_fx = _asof(market.fx, timeline[0])
        self.funding_fx, self.funding_fx_date = funding_fx, fx_date
        self.cash = capital * funding_fx
        self.qty = np.zeros(len(names))
        self.rates = np.array([ENGINE['ONE_WAY_BPS'][t] for t in names]) / 1e4
        self.previous_executed = None
        closes = market.closes[names].where(lambda x: x > 0)
        self.marks = closes.reindex(closes.index.union(timeline)).sort_index().ffill().reindex(timeline)
        if self.marks.isna().any().any():
            raise ValueError(f'{market.name}: missing initial valuation price.')
        price_dates = pd.DataFrame(index=closes.index, columns=names)
        for t in names:
            price_dates[t] = pd.Series(closes.index, index=closes.index).where(closes[t].notna())
        self.price_dates = price_dates.reindex(price_dates.index.union(timeline)).sort_index().ffill().reindex(timeline)
        self.rows, self.trades = [], []
        self.epsilon = capital * 1e-12

    def _open_prices(self, d):
        if d not in self.market.opens.index:
            return None
        px = self.market.opens.loc[d, self.names].to_numpy(float)
        return px if (np.isfinite(px).all() and (px > 0).all()) else None

    def ready(self, i, d):
        """True when a trade (and therefore a transfer) can happen on d."""
        if i == 0 or self._open_prices(d) is None:
            return False
        return self.weights.index.searchsorted(d, side='left') - 1 >= 0

    def open_value(self, d):
        """Local-currency account value at the source opening of d."""
        px = self._open_prices(d)
        return None if px is None else float(self.cash + (self.qty * px).sum())

    def step(self, i, d, cash_adjust=0.0):
        market, names, weights = self.market, self.names, self.weights
        total_cost_usd = turnover = notional_usd = 0.0
        signal_date = pd.NaT
        px_all = self._open_prices(d) if i > 0 else None
        if i == 0:
            status = 'Initial funding; no trade'
        elif d not in market.opens.index:
            status = 'No source session; holdings unchanged; carried valuation'
        else:
            px = market.opens.loc[d, names].to_numpy(float)
            valid_open = px_all is not None
            pos = weights.index.searchsorted(d, side='left') - 1
            if not valid_open:
                status = 'Incomplete opening quote; no trade; source date shown'
            elif pos < 0:
                status = 'No signal known before this session; no trade'
            else:
                signal_date = weights.index[pos]
                w = weights.iloc[pos].to_numpy(float)
                if not np.isfinite(w).all() or (w < -1e-10).any() or w.sum() > 1 + 1e-8:
                    raise ValueError(f'{market.name}: invalid signal at {signal_date}.')
                transfer = abs(cash_adjust) > 0
                execute = transfer or self.previous_executed is None or self.rebalance == 'daily' or (
                    self.rebalance == 'on_change' and not np.allclose(w, self.previous_executed, rtol=0, atol=1e-12))
                if not execute:
                    status = 'Hold; no target-triggered trade'
                else:
                    ref_date, ref_fx = _asof(market.fx, d, strict=True)
                    self.cash += cash_adjust  # cross-sleeve transfer, settled before rebalancing
                    current = self.qty * px
                    value = self.cash + current.sum()
                    delta, costs = ENGINE['rebalance_exact'](value, current, w, self.rates)
                    target = current + delta
                    self.qty = target / px
                    self.cash = float(value - target.sum() - costs.sum())
                    if self.cash < -max(self.epsilon, 1e-8):
                        raise AssertionError('A sleeve cannot spend another sleeve\'s cash.')
                    self.cash = max(self.cash, 0.0)
                    for j in np.flatnonzero(np.abs(delta) > self.epsilon):
                        self.trades.append(dict(exec_date=d, signal_date=signal_date, ticker=names[j],
                            sleeve=market.name, side='BUY' if delta[j] > 0 else 'SELL',
                            shares=abs(delta[j]) / px[j], price_local=px[j], price_usd=px[j] / ref_fx,
                            currency=market.currency, notional_local=abs(delta[j]), notional_usd=abs(delta[j]) / ref_fx,
                            cost_local=costs[j], cost_usd=costs[j] / ref_fx, cost_bps=self.rates[j] * 1e4,
                            weight_before=current[j] / value, weight_after=w[j], fx_reference=ref_fx,
                            fx_reference_date=ref_date, execution_quote_date=d,
                            note='SGD trade; USD amounts use prior FX for reporting only' if market.currency=='SGD' else ''))
                    total_cost_usd = costs.sum() / ref_fx
                    notional_usd = np.abs(delta).sum() / ref_fx
                    turnover = np.abs(delta).sum() / value
                    self.previous_executed = w.copy()
                    status = 'Rebalanced at source opening' if notional_usd > self.epsilon else 'At target; no material trade'
                    if transfer:
                        status += '; incl. cross-sleeve transfer'
        mark_fx_date, mark_fx = _asof(market.fx, d)
        values = self.qty * self.marks.loc[d].to_numpy(float)
        nav_local = self.cash + values.sum()
        quote_date = min(pd.Timestamp(x) for x in self.price_dates.loc[d])
        row = dict(date=d, equity=nav_local / mark_fx, cash=self.cash / mark_fx, cash_local=self.cash,
                   equity_local=nav_local, quote_date=quote_date, fx=mark_fx, fx_date=mark_fx_date,
                   status=status, turnover=turnover, cost_usd=total_cost_usd,
                   traded_notional_usd=notional_usd, signal_date=signal_date)
        for j, t in enumerate(names):
            row[t+'_shares'] = self.qty[j]
            row[t+'_value'] = values[j] / mark_fx
            row[t+'_pct'] = values[j] / nav_local
            row[t+'_price_date'] = self.price_dates.loc[d, t]
        self.rows.append(row)
        return row['equity']

    def result(self):
        daily = pd.DataFrame(self.rows).set_index('date')
        trade_frame = pd.DataFrame(self.trades, columns=TRADE_COLUMNS)
        return {'daily': daily, 'trades': trade_frame, 'market': self.market, 'weights': self.weights,
                'capital': self.capital, 'funding_fx': self.funding_fx, 'funding_fx_date': self.funding_fx_date}


def run_sleeve(market, weights, timeline, capital, rebalance='daily'):
    """Self-financing local-currency ledger; only genuine source openings can trade.

    A missing opening blocks sleeve rebalancing for that date. Latest prior target
    replaces any older unexecuted target. A single sleeve never transfers cash;
    cross-sleeve transfers exist only inside run_portfolio(rebalance_band=...).
    """
    runner = _SleeveRunner(market, weights, timeline, capital, rebalance)
    for i, d in enumerate(timeline):
        runner.step(i, d)
    return runner.result()


TRANSFER_COLUMNS = ['exec_date', 'direction', 'usd_to_sg', 'sgd_to_sg', 'fx_reference', 'fx_cost_usd',
                    'sg_share_flagged', 'flag_date', 'sg_share_at_open_before', 'target_sg_share']


def combine_results(us, sg, capital, transfers=None, band=None):
    """Add sleeve account values. Sleeve funding is only ever moved by `transfers`."""
    u, s = us['daily'], sg['daily']
    if not u.index.equals(s.index):
        raise ValueError('Sleeve reports need the same valuation dates.')
    transfers = pd.DataFrame(transfers or [], columns=TRANSFER_COLUMNS)
    daily = pd.DataFrame(index=u.index)
    daily['equity'] = u.equity + s.equity
    daily['cash'] = u.cash + s.cash
    daily['cash_pct'] = daily.cash / daily.equity
    daily['US_equity'] = u.equity
    daily['SG_equity'] = s.equity
    daily['US_sleeve_pct'] = u.equity / daily.equity
    daily['SG_sleeve_pct'] = s.equity / daily.equity
    daily['US_cash'] = u.cash
    daily['SG_cash_usd'] = s.cash
    daily['SG_cash_sgd'] = s.cash_local
    daily['SGD_per_USD'] = s.fx
    daily['FX_quote_date'] = s.fx_date
    daily['US_quote_date'] = u.quote_date
    daily['SG_quote_date'] = s.quote_date
    daily['US_status'], daily['SG_status'] = u.status, s.status
    for result in (us,sg):
        for t in result['weights'].columns:
            daily[t+'_shares'] = result['daily'][t+'_shares']
            daily[t+'_value'] = result['daily'][t+'_value']
            daily[t+'_pct'] = daily[t+'_value'] / daily.equity
    fx_cost = transfers.groupby('exec_date').fx_cost_usd.sum().astype(float).reindex(daily.index).fillna(0.0)
    moved = transfers.groupby('exec_date').usd_to_sg.sum().astype(float).reindex(daily.index).fillna(0.0)
    daily['transfer_to_SG_usd'] = moved
    daily['transfer_cost_usd'] = fx_cost
    daily['cost_usd'] = u.cost_usd + s.cost_usd + fx_cost
    daily['traded_notional_usd'] = u.traded_notional_usd + s.traded_notional_usd
    # Different exchanges open at different times. Use prior total closing NAV,
    # not a fictional simultaneous global opening NAV, as turnover denominator.
    daily['turnover'] = daily.traded_notional_usd / daily.equity.shift(1)
    daily.loc[daily.index[0], 'turnover'] = 0.0
    trades = pd.concat([us['trades'],sg['trades']],ignore_index=True).sort_values(
        ['exec_date','sleeve','ticker']).reset_index(drop=True)
    return {'daily': daily, 'trades': trades, 'transfers': transfers, 'band': band,
            'us': us, 'sg': sg, 'capital': capital}


def run_portfolio(us, sg, us_weights, sg_weights, start, end=None, capital=100000.0,
                  initial_sg_share=INITIAL_SG_SHARE, rebalance='daily',
                  rebalance_band=None, fx_bps=0.0):
    """Two independent sleeves, funded initial_sg_share / (1 - initial_sg_share).

    rebalance_band=None : no cross-sleeve transfer ever (sleeve shares drift).
    rebalance_band=0.01 : threshold rule. At a close, if |SG share - initial_sg_share| > band
        a flag is set (kept until executed). On the first later date on which BOTH
        sleeves have a valid opening and a known signal, the SG account is reset to
        initial_sg_share of total opening value (cash moved between the accounts,
        converted at the prior FX reference), then each sleeve rebalances to its own
        targets. fx_bps is a one-way conversion cost on the amount moved.
    """
    if not 0 < initial_sg_share < 1:
        raise ValueError('Both initial sleeve shares must be positive.')
    if rebalance_band is not None and rebalance_band <= 0:
        raise ValueError('rebalance_band must be positive or None.')
    timeline = common_timeline((us,sg),start,end)
    if rebalance_band is None:
        u = run_sleeve(us,us_weights,timeline,capital*(1-initial_sg_share),rebalance)
        s = run_sleeve(sg,sg_weights,timeline,capital*initial_sg_share,rebalance)
        return combine_results(u,s,capital)
    ru = _SleeveRunner(us, us_weights, timeline, capital*(1-initial_sg_share), rebalance)
    rs = _SleeveRunner(sg, sg_weights, timeline, capital*initial_sg_share, rebalance)
    pending, flag_date, flag_share, transfers = False, None, np.nan, []
    for i, d in enumerate(timeline):
        adj_u = adj_s = 0.0
        if pending and ru.ready(i, d) and rs.ready(i, d):
            ref_date, ref_fx = _asof(sg.fx, d, strict=True)
            v_us = ru.open_value(d)
            v_sg = rs.open_value(d) / ref_fx
            x = initial_sg_share * (v_us + v_sg) - v_sg      # USD that must move into SG (<0: out of SG)
            if abs(x) > capital * 1e-12:
                cost = abs(x) * fx_bps / 1e4
                if x > 0:
                    adj_u, adj_s = -x, (x - cost) * ref_fx
                else:
                    adj_u, adj_s = -x - cost, x * ref_fx
                transfers.append(dict(exec_date=d, direction='US->SG' if x > 0 else 'SG->US',
                    usd_to_sg=x, sgd_to_sg=x * ref_fx, fx_reference=ref_fx, fx_cost_usd=cost,
                    sg_share_flagged=flag_share, flag_date=flag_date,
                    sg_share_at_open_before=v_sg / (v_us + v_sg), target_sg_share=initial_sg_share))
            pending = False
        eu = ru.step(i, d, adj_u)
        es = rs.step(i, d, adj_s)
        share = es / (eu + es)
        if not pending and abs(share - initial_sg_share) > rebalance_band:
            pending, flag_date, flag_share = True, d, share
    return combine_results(ru.result(), rs.result(), capital, transfers, rebalance_band)


def window_equity(eq, start, end):
    """Include the preceding close, so the first session return is not omitted."""
    dates = eq.loc[start:end].index
    if not len(dates):
        return eq.iloc[:0]
    preceding = eq.index[eq.index < dates[0]]
    begin = preceding[-1] if len(preceding) else dates[0]
    return eq.loc[begin:dates[-1]]


def performance(eq, start=None, end=None):
    e = window_equity(eq,start,end) if start is not None else eq
    if len(e)<2:
        return {k:np.nan for k in ['CAGR','Vol','Sharpe','Sortino','MDD','Calmar']}
    return ENGINE['metrics'](e)


def latest_targets(result):
    rows=[]
    d=result['daily'].index[-1]
    for key in ['us','sg']:
        r=result[key];weights=r['weights'];pos=weights.index.searchsorted(d,side='right')-1
        if pos<0:raise ValueError('No latest target available.')
        signal_date=weights.index[pos];local_target=weights.iloc[pos]
        sleeve_share=r['daily'].equity.iloc[-1]/result['daily'].equity.iloc[-1]
        for t,w in local_target.items():
            rows.append(dict(ticker=t,sleeve=r['market'].name,signal_date=signal_date,
                target_within_sleeve=w,current_total_weight=result['daily'][t+'_pct'].iloc[-1],
                current_sleeve_share=sleeve_share,indicative_total_weight=sleeve_share*w,
                execution_rule=('Next valid local source opening; refresh prior-known target; ' + (f"sleeve reset to target only if share leaves the +/-{100*result['band']:.1f}pt band" if result.get('band') else 'no sleeve transfers'))))
    return pd.DataFrame(rows).set_index('ticker')


def holdings(result):
    last=result['daily'].iloc[-1]
    names=list(result['us']['weights'])+list(result['sg']['weights'])
    frame=pd.DataFrame({'shares':[last[t+'_shares'] for t in names],
                        'value_usd':[last[t+'_value'] for t in names],
                        'weight':[last[t+'_pct'] for t in names]},index=names)
    for name,col in [('US_CASH','US_cash'),('SG_CASH','SG_cash_usd')]:
        frame.loc[name]=[np.nan,last[col],last[col]/last.equity]
    frame.index.name='ticker'
    return frame.loc[frame.value_usd.abs()>1e-8]
