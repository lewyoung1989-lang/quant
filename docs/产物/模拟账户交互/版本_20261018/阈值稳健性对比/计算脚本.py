import json
from pathlib import Path
import pandas as pd,numpy as np
from strategies.dividend_lowvol_swing_backtest import run_simulation
out=Path('docs/产物/模拟账户交互/版本_20261018/阈值稳健性对比');out.mkdir(exist_ok=True)
raw=pd.read_csv('docs/产物/模拟账户交互/版本_20261018/核对用行情指标快照.csv',index_col=0,parse_dates=True)
def calc(low,high,cost=.0003):
 return run_simulation(raw,th_overheat=low,th_neutral=high,w_overheat=0.0,w_neutral=.5,w_undervalue=1.0,cost_rate=cost)
def stats(r):
 n=r.s2_erp_nav;daily=n.pct_change().fillna(0);years=(n.index[-1]-n.index[0]).days/365.25
 return dict(total=float(n.iloc[-1]/n.iloc[0]-1),annual=float((n.iloc[-1]/n.iloc[0])**(1/years)-1),drawdown=float((n/n.cummax()-1).min()),vol=float(daily.std()*np.sqrt(250)),trades=int((r.s2_turnover>0).sum()),equity_exposure=float(r.s2_actual_weight.mean()))
a=calc(.25,.35);b=calc(.2,.4)
yearly=pd.DataFrame({name:(1+r.s2_erp_nav.pct_change().fillna(0)).groupby(r.index.year).prod()-1 for name,r in [('25/35',a),('20/40',b)]});yearly['差值']=yearly['25/35']-yearly['20/40'];yearly.to_csv(out/'分年收益.csv')
grid=[]
for lo in [.15,.20,.25,.30]:
 for hi in [.30,.35,.40,.45]:
  if lo>=hi:continue
  r=calc(lo,hi);grid.append(dict(low=lo,high=hi,**stats(r)))
pd.DataFrame(grid).to_csv(out/'邻近参数.csv',index=False)
stress=[]
for fee in [.0003,.0006,.001]:
 stress.append(dict(cost=fee,A=stats(calc(.25,.35,fee)),B=stats(calc(.2,.4,fee))))
diff=a.s2_weight!=b.s2_weight
bands=pd.cut(raw.erp_pct.reindex(a.index).shift(1),[-np.inf,.2,.25,.35,.4,np.inf],right=True)
counts=bands.value_counts(sort=False).astype(int).to_dict()
rolling={}
for days in [250,500,750]:
 ar=a.s2_erp_nav.pct_change(days);br=b.s2_erp_nav.pct_change(days);valid=(ar-br).dropna();rolling[str(days)]={'windows':len(valid),'A_win_fraction':float((valid>0).mean()),'median_difference':float(valid.median()),'worst_difference':float(valid.min()),'best_difference':float(valid.max())}
# Paired log return contribution shows whether advantage depends on a few years.
logs=pd.DataFrame({'A':np.log(a.s2_erp_nav).diff().fillna(0),'B':np.log(b.s2_erp_nav).diff().fillna(0)})
contribution=(logs.A-logs.B).groupby(logs.index.year).sum()
res=dict(start=str(a.index[0].date()),end=str(a.index[-1].date()),days=len(a),A=stats(a),B=stats(b),different_target_days=int(diff.sum()),signal_band_days={str(k):v for k,v in counts.items()},yearly=yearly.to_dict('index'),log_advantage_by_year=contribution.to_dict(),rolling=rolling,grid=grid,stress=stress)
(out/'计算结果.json').write_text(json.dumps(res,ensure_ascii=False,indent=2));pd.DataFrame({'25/35':a.s2_erp_nav,'20/40':b.s2_erp_nav,'25/35仓位':a.s2_weight,'20/40仓位':b.s2_weight}).to_csv(out/'净值与仓位.csv')
print(json.dumps({k:v for k,v in res.items() if k!='grid'},ensure_ascii=False,indent=2));print(pd.DataFrame(grid).pivot(index='low',columns='high',values='annual').round(4).to_string())
