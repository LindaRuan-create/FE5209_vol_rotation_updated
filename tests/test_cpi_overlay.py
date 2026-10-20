"""Tests for the CPI overlay rule (09) and the optional close-price exit in the accounting engine."""
from pathlib import Path
import sys
import unittest
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portfolio_accounting as pa

OV = pa.load_definitions('09_cpi_overlay')


def us_market(n=10, opens=None, closes=None):
    dates = pd.bdate_range('2026-01-05', periods=n)
    cols = ['TQQQ', 'UVXY', 'BSV']
    o = pd.DataFrame(opens if opens is not None else 100.0, index=dates, columns=cols)
    c = pd.DataFrame(closes if closes is not None else 100.0, index=dates, columns=cols)
    return pa.Market('US', 'USD', o, c, pd.Series(1.0, index=dates)), dates, cols


class CloseExitTests(unittest.TestCase):
    def test_close_event_trades_at_close_with_fees_and_reaches_target(self):
        market, dates, cols = us_market()
        market.closes.loc[dates[3], 'TQQQ'] = 110.0        # close differs from the open
        hedged = pd.DataFrame([[0.0, 0.6, 0.4]] * len(dates), index=dates - pd.Timedelta(days=1), columns=cols)
        base_w = np.array([0.6, 0.0, 0.4])
        events = {dates[3]: (dates[2], base_w)}
        res = pa.run_sleeve(market, hedged, dates, 1000.0, close_events=events)
        trades = res['trades']
        close_trades = trades[trades.note.astype(str).str.contains('CPI hedge exit')]
        self.assertTrue((close_trades.exec_date == dates[3]).all())
        self.assertIn('UVXY', set(close_trades.ticker))             # the hedge is sold at the close
        px = close_trades.set_index('ticker').price_local
        self.assertAlmostEqual(px['TQQQ'], 110.0)           # filled at the closing price
        np.testing.assert_allclose(close_trades.notional_local * close_trades.cost_bps / 1e4, close_trades.cost_local)
        row = res['daily'].loc[dates[3]]
        total = row.equity
        self.assertAlmostEqual(row['TQQQ_value'] / total, 0.6, places=6)    # back at the unhedged target after fees
        self.assertAlmostEqual(row['UVXY_value'], 0.0, places=6)

    def test_no_close_events_is_identical_to_before(self):
        market, dates, cols = us_market()
        w = pd.DataFrame([[0.5, 0.1, 0.4]] * len(dates), index=dates - pd.Timedelta(days=1), columns=cols)
        a = pa.run_sleeve(market, w, dates, 1000.0)
        b = pa.run_sleeve(market, w, dates, 1000.0, close_events=None)
        pd.testing.assert_series_equal(a['daily'].equity, b['daily'].equity)
        pd.testing.assert_frame_equal(a['trades'], b['trades'])


class OverlayRuleTests(unittest.TestCase):
    def weights(self, dates):
        return pd.DataFrame({'TQQQ': 0.5, 'UVXY': 0.0, 'BSV': 0.5}, index=dates)

    def test_overlay_moves_weight_for_exactly_hold_days_and_keeps_sums(self):
        dates = pd.bdate_range('2026-01-05', periods=12)
        w = self.weights(dates)
        w_over, events, rows = OV['apply_overlay'](w, [dates[4]], dates, hold_days=3, fraction=1.0)
        changed = (w_over.UVXY > 0)
        # open of dates[4..6] uses rows dated dates[3..5]
        self.assertEqual(list(w_over.index[changed]), list(dates[3:6]))
        np.testing.assert_allclose(w_over.sum(axis=1), w.sum(axis=1))
        self.assertEqual(list(events), [dates[6]])                       # one close exit on the 3rd hedged day
        signal_date, base_w = events[dates[6]]
        self.assertEqual(signal_date, dates[5])
        np.testing.assert_allclose(base_w, w.iloc[5].to_numpy())          # unhedged target of that day

    def test_hedge_without_full_window_has_no_exit_yet(self):
        dates = pd.bdate_range('2026-01-05', periods=6)
        _, events, rows = OV['apply_overlay'](self.weights(dates), [dates[4]], dates, hold_days=3)
        self.assertEqual(events, {})
        self.assertTrue(rows.close_exit.isna().all())

    def market_series(self, gaps):
        dates = pd.bdate_range('2020-01-01', periods=len(gaps) + 1)
        close = pd.Series(100.0, index=dates)
        opn = close.shift(1) * (1 + pd.Series([np.nan] + list(gaps), index=dates))
        opens = pd.DataFrame({'QQQ': opn.fillna(100.0)}); closes = pd.DataFrame({'QQQ': close})
        return dates, opens, closes

    def cpi(self, dates, pairs, yoy):
        rel = dates[1:1 + len(pairs)]
        return pd.DataFrame({'release': rel, 'predicted': [p for p, _ in pairs], 'actual': [a for _, a in pairs]})

    def test_switch_uses_only_earlier_events_and_yoy_level(self):
        n = 30
        gaps = [-0.01] * n                                     # market always gaps down
        dates, opens, closes = self.market_series(gaps)
        pairs = [(3.0, 3.2)] * n                               # always hot (+0.2), actual 3.2 >= 3
        ev = OV['cpi_event_table'](self.cpi(dates, pairs, None), opens, closes, window=16, min_periods=8)
        self.assertTrue(ev.hit_rate.iloc[:8].isna().all())     # not enough earlier events yet
        self.assertFalse(ev.trigger.iloc[:8].any())
        self.assertTrue(ev.trigger.iloc[10:].all())            # hit rate 100%, YoY >= 3
        # the current event's own gap never enters its own hit rate
        opens2 = opens.copy(); opens2.iloc[20] = 200.0
        ev2 = OV['cpi_event_table'](self.cpi(dates, pairs, None), opens2, closes, window=16, min_periods=8)
        self.assertEqual(ev.hit_rate.iloc[19], ev2.hit_rate.iloc[19])
        self.assertEqual(ev.hit_rate.iloc[18], ev2.hit_rate.iloc[18])
        # low inflation never triggers
        low = [(1.8, 2.0)] * n
        ev3 = OV['cpi_event_table'](self.cpi(dates, low, None), opens, closes, window=16, min_periods=8)
        self.assertFalse(ev3.trigger.any())
        # a cool surprise never triggers a hedge
        cool = [(3.4, 3.2)] * n
        ev4 = OV['cpi_event_table'](self.cpi(dates, cool, None), opens, closes, window=16, min_periods=8)
        self.assertFalse(ev4.trigger.any())

    def test_shipped_cpi_file_is_clean(self):
        cpi = OV['load_cpi']()
        self.assertTrue(cpi.release.is_monotonic_increasing and not cpi.release.duplicated().any())
        self.assertTrue(cpi[['predicted', 'actual']].notna().all().all())


if __name__ == '__main__':
    unittest.main()
