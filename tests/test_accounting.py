"""Regression tests for calendars, native-session execution and independent funding."""
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import portfolio_accounting as pa


class AccountingTests(unittest.TestCase):
    def market(self,name='Singapore',currency='SGD',missing_day=True,fx_last=1.25):
        dates=pd.date_range('2026-01-01',periods=4)
        sessions=dates[[0,1,3]] if missing_day else dates
        cols=['ES3','A35'] if currency=='SGD' else ['TQQQ','BSV']
        px=pd.DataFrame([[5.,1.],[5.,1.],[5.5,1.]] if missing_day else [[5.,1.],[5.,1.],[6.,1.],[5.5,1.]],index=sessions,columns=cols)
        fx=pd.Series([1.25,1.25,1.25,fx_last],index=dates) if currency=='SGD' else pd.Series(1.,index=dates)
        weights=pd.DataFrame([[.7,.3],[.9,.1],[.6,.4]],index=dates[[0,1,3]],columns=cols)
        return pa.Market(name,currency,px,px.copy(),fx),weights,dates

    def test_actual_notional_fees_and_cash_conservation(self):
        delta,fees=pa.ENGINE['rebalance_exact'](100000,[60000,30000],[.4,.6],[.0035,.001])
        np.testing.assert_allclose(fees,abs(delta)*[.0035,.001])
        np.testing.assert_allclose(np.array([60000,30000])+delta,np.array([.4,.6])*(100000-fees.sum()))
        self.assertAlmostEqual((np.array([60000,30000])+delta).sum()+fees.sum(),100000)

    def test_shared_calendar_retains_return_after_us_holiday(self):
        dates=pd.date_range('2026-01-01',periods=3)
        columns=pd.MultiIndex.from_product([['Open','High','Low','Close','Adj Close'],pa.ENGINE['TICKS']],names=['Price','Ticker'])
        frame=pd.DataFrame(np.tile([50.,np.nan,55.],(len(columns),1)).T,index=dates,columns=columns)
        frame.index.name='Date'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'prices.csv';frame.to_csv(path)
            filtered=pa.ENGINE['load'](path)
        self.assertNotIn(dates[1],filtered.index)
        returns=filtered['Adj Close'].pct_change(fill_method=None)
        np.testing.assert_allclose(returns.loc[dates[2]],.10)
        for stem in ['05_risk_allocation','06_bsv_volatility_targeting']:
            path=next((pa.ROOT/'pipeline').rglob(stem+'.ipynb'))
            self.assertIn("prices = ENGINE['load'](price_path)",path.read_text())

    def test_no_source_session_holds_shares_and_local_cash(self):
        market,w,dates=self.market()
        result=pa.run_sleeve(market,w,dates,700)
        daily,trades=result['daily'],result['trades']
        self.assertTrue((daily.loc[dates[2],['ES3_shares','A35_shares']]==daily.loc[dates[1],['ES3_shares','A35_shares']]).all())
        self.assertEqual(daily.loc[dates[2],'cash_local'],daily.loc[dates[1],'cash_local'])
        self.assertFalse((trades.exec_date==dates[2]).any())
        self.assertEqual(daily.loc[dates[2],'quote_date'],dates[1])
        resumed=trades[trades.exec_date==dates[3]]
        self.assertTrue(len(resumed)>0)
        self.assertTrue((resumed.signal_date==dates[1]).all())
        self.assertTrue((trades.signal_date<trades.exec_date).all())
        self.assertTrue((trades.execution_quote_date==trades.exec_date).all())
        np.testing.assert_allclose(trades.notional_local*trades.cost_bps/1e4,trades.cost_local)

    def test_incomplete_real_opening_is_not_replaced_by_close(self):
        market,w,dates=self.market(missing_day=False)
        market.opens.loc[dates[2],'ES3']=np.nan
        result=pa.run_sleeve(market,w,dates,700)
        self.assertFalse((result['trades'].exec_date==dates[2]).any())
        self.assertIn('Incomplete opening quote',result['daily'].loc[dates[2],'status'])

    def test_no_cross_sleeve_transfers_and_shares_drift(self):
        sg,sw,dates=self.market()
        us,uw,_=self.market('US','USD',False)
        p=pa.run_portfolio(us,sg,uw,sw,dates[1],dates[-1],100000)
        self.assertAlmostEqual(p['daily'].iloc[0].US_sleeve_pct,.9)
        self.assertAlmostEqual(p['daily'].iloc[0].SG_sleeve_pct,.1)
        self.assertTrue((abs(p['daily'].SG_sleeve_pct-.1)>1e-6).any())
        changed_open,changed_close=us.opens.copy(),us.closes.copy()
        changed_open.iloc[2:]*=2
        changed_close.iloc[2:]*=2
        changed_us=pa.Market('US','USD',changed_open,changed_close,us.fx)
        p2=pa.run_portfolio(changed_us,sg,uw,sw,dates[1],dates[-1],100000)
        pd.testing.assert_frame_equal(p['sg']['daily'],p2['sg']['daily'])
        self.assertNotAlmostEqual(p['us']['daily'].equity.iloc[-1],p2['us']['daily'].equity.iloc[-1])
        d=p['daily']
        np.testing.assert_allclose(d.equity,d.US_equity+d.SG_equity)
        np.testing.assert_allclose(d.equity,d.cash+d.filter(regex='_value$').sum(axis=1))
        self.assertIn(dates[2],d.index)  # US-only session retained.

    def test_singapore_only_session_is_retained_and_can_trade(self):
        sg,sw,dates=self.market(missing_day=False)
        us,uw,_=self.market('US','USD',True)
        p=pa.run_portfolio(us,sg,uw,sw,dates[1],dates[-1])
        self.assertIn(dates[2],p['daily'].index)
        t=p['trades']
        self.assertTrue(((t.exec_date==dates[2])&(t.sleeve=='Singapore')).any())
        self.assertFalse(((t.exec_date==dates[2])&(t.sleeve=='US')).any())

    def test_sgd_trades_do_not_use_future_closing_fx(self):
        market,w,dates=self.market(fx_last=1.30)
        result=pa.run_sleeve(market,w,dates,700)
        t=result['trades'];last=t[t.exec_date==dates[-1]]
        self.assertTrue((last.fx_reference==1.25).all())
        self.assertTrue((t.fx_reference_date<t.exec_date).all())
        self.assertEqual(result['daily'].iloc[-1].fx,1.30)
        stable,w,_=self.market(fx_last=1.25)
        stable_result=pa.run_sleeve(stable,w,dates,700)
        np.testing.assert_allclose(result['daily'].filter(regex='_shares$'),stable_result['daily'].filter(regex='_shares$'))

    def test_period_metrics_include_first_session_return(self):
        idx=pd.to_datetime(['2019-12-31','2020-01-02','2020-01-03'])
        eq=pd.Series([100.,110.,110.],index=idx)
        window=pa.window_equity(eq,'2020-01-01','2020-01-03')
        self.assertEqual(window.iloc[0],100.)
        self.assertAlmostEqual(window.iloc[-1]/window.iloc[0]-1,.1)


if __name__=='__main__':unittest.main()
