/* Standalone interaction prototype. All prices, signals and trades are illustrative. */
'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = (value, digits = 2) => Number(value).toLocaleString('zh-CN', {minimumFractionDigits:digits,maximumFractionDigits:digits});
const money = value => '¥' + number(value);
const signed = value => (value > 0 ? '+' : value < 0 ? '−' : '') + number(Math.abs(value));
const round = value => Math.round((value + Number.EPSILON) * 100) / 100;
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
const STORAGE_KEY = 'quant-account-interaction-demo-20261017-v1';
const FEE = .0001;
const ASSETS = {
  sh512890:{name:'红利低波 ETF',fullName:'华泰柏瑞红利低波 ETF',price:1.219,change:.58},
  sh511260:{name:'十年国债 ETF',fullName:'十年国债 ETF',price:135.208,change:-.03},
  sh511010:{name:'国债 ETF',fullName:'国债 ETF',price:122.88,change:.02},
  sz159915:{name:'创业板 ETF',fullName:'易方达创业板 ETF',price:3.008,change:1.26},
  sh588380:{name:'双创50 ETF',fullName:'双创50 ETF',price:1.327,change:1.08},
  sh588000:{name:'科创50 ETF',fullName:'科创50 ETF',price:1.146,change:.89}
};
const STRATEGIES = {
  erp:{name:'红利低波 ERP 择时',short:'红利低波 ERP',tag:'估值择时',desc:'根据股债利差 ERP 的历史分位，在不同估值区间调整红利低波 ETF 仓位；剩余资金保留为现金。',icon:'chart-dots-3'},
  rotation:{name:'攻守动量轮动',short:'攻守动量轮动',tag:'双资产轮动',desc:'比较进攻与防守标的的动量，结合进攻标的均线，决定持有哪一只 ETF。',icon:'switch-horizontal'}
};
const SCENARIOS = {
  closed:{label:'周末休市',date:'2026-10-17',time:'19:29:44',full:'2026-10-17 周六 · 休市',ready:false,note:'当前为休市情境。切换至「尾盘窗口」后可体验模拟执行。'},
  window:{label:'尾盘执行窗口',date:'2026-10-16',time:'14:50:08',full:'2026-10-16 周五 · 尾盘窗口',ready:true,note:'示例行情有效，当前处于 14:45–14:55 模拟执行窗口。'},
  intraday:{label:'盘中预览',date:'2026-10-16',time:'13:30:12',full:'2026-10-16 周五 · 盘中预览',ready:false,note:'盘中清单仅供预览，14:45–14:55 才可执行模拟调仓。'},
  low:{label:'低估加仓信号',date:'2026-10-16',time:'14:50:08',full:'2026-10-16 周五 · ERP 低估',ready:true,note:'演示 ERP 分位升至 85%，策略进入低估区间。'},
  stale:{label:'行情已延迟',date:'2026-10-16',time:'14:38:02',full:'2026-10-16 周五 · 行情延迟',ready:false,note:'报价已延迟 12 分钟。请切换有效行情情境后刷新，重新核对清单。'},
  error:{label:'行情加载失败',date:'2026-10-16',time:'—',full:'2026-10-16 周五 · 行情异常',ready:false,note:'示例行情接口未返回有效报价。切换至「尾盘窗口」后重试。'}
};
let scenario = 'closed', activeTab = 'overview', toastTimer, drawerKind = '', drawerAccount = null;
let refreshing = false, lastFocus = null, memoryOnly = false;
const busyAccounts = new Set();
const stamp = () => `${SCENARIOS[scenario].date} ${SCENARIOS[scenario].time === '—' ? '14:50:08' : SCENARIOS[scenario].time}`;
const uid = () => globalThis.crypto?.randomUUID?.() || `demo-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
const config = type => type === 'erp' ? {low:20,high:80,lowWeight:50,midWeight:75,highWeight:100} : {attack:'sh588380',defense:'sh511010',lookback:20};
function seed(){
  const common = {running:true,auto:false,revision:1,created:'2026-10-16',config:null,funds:[],trades:[],events:[]};
  const accounts = [
    {...common,id:'SIM-0001',name:'红利稳健 01',strategy:'erp',config:config('erp'),initial:100000,netCapital:100000,cash:25031.5,positions:[{symbol:'sh512890',shares:61500,cost:1.219}]},
    {...common,id:'SIM-0002',name:'攻守轮动 01',strategy:'rotation',config:config('rotation'),initial:100000,netCapital:100000,cash:13984,positions:[{symbol:'sh511010',shares:700,cost:122.88}]},
    {...common,id:'SIM-0003',name:'策略试验 01',strategy:'rotation',config:{...config('rotation'),attack:'sz159915',defense:'sh512890'},initial:200000,netCapital:200000,cash:200000,positions:[]}
  ];
  accounts.forEach(a => {
    a.funds=[{id:uid(),time:'2026-10-16 09:00:00',type:'初始资金',amount:a.initial,balance:a.initial}];
    a.events=[{id:uid(),time:'2026-10-16 09:00:00',title:'模拟账户已创建',detail:`绑定「${STRATEGIES[a.strategy].name}」，初始资金 ${money(a.initial)}。`,status:'已完成'}];
    a.trades=a.positions.map(p=>({id:uid(),time:'2026-10-16 14:50:00',action:'买入',symbol:p.symbol,shares:p.shares,price:p.cost,amount:round(p.shares*p.cost),fee:0,source:'初始示例',batch:'SEED'}));
  });
  return {version:1,selected:'SIM-0001',nextId:4,accounts};
}
function load(){
  try {
    const raw=localStorage.getItem(STORAGE_KEY);
    if(!raw) return seed();
    const value=JSON.parse(raw);
    if(value.version!==1||!Array.isArray(value.accounts)||!value.accounts.length||value.accounts.length>100) throw Error('invalid');
    if(!value.accounts.every(a=>a.id&&typeof a.name==='string'&&STRATEGIES[a.strategy]&&a.config&&Number.isFinite(a.cash)&&a.cash>=0&&Number.isFinite(a.netCapital)&&Array.isArray(a.positions)&&a.positions.every(p=>ASSETS[p.symbol]&&Number.isFinite(p.shares)&&p.shares>=0)&&Array.isArray(a.funds)&&Array.isArray(a.trades)&&Array.isArray(a.events))) throw Error('invalid');
    if(!value.accounts.some(a=>a.id===value.selected)) value.selected=value.accounts[0].id;
    value.nextId=Math.max(Number(value.nextId)||4,value.accounts.length+1);
    return value;
  } catch { memoryOnly=true; return seed(); }
}
let state = load();
function save(){try{localStorage.setItem(STORAGE_KEY,JSON.stringify(state));}catch{if(!memoryOnly)toast('浏览器存储不可用，本次操作仅在当前页面保留。');memoryOnly=true;}}
const current = () => state.accounts.find(a=>a.id===state.selected) || state.accounts[0];
const equity = a => round(a.positions.reduce((sum,p)=>sum+p.shares*ASSETS[p.symbol].price,0));
const total = a => round(a.cash+equity(a));
const positionWeight = a => total(a)>0?equity(a)/total(a)*100:0;
function event(a,title,detail,status='已完成'){a.events.unshift({id:uid(),time:stamp(),title,detail,status});}
function target(a){
  if(a.strategy==='erp'){
    const percentile=scenario==='low'?85:20.3;
    const w=percentile<a.config.low?a.config.lowWeight:percentile>a.config.high?a.config.highWeight:a.config.midWeight;
    return {symbol:'sh512890',weight:w,percentile};
  }
  // Illustrative signal only; this does not run the project's strategy engine.
  return {symbol:a.config.attack,weight:100,percentile:null};
}
function plan(a){
  const t=target(a), asset=ASSETS[t.symbol], orders=[];
  let cash=a.cash;
  for(const p of a.positions){
    if(p.symbol!==t.symbol&&p.shares>0){
      const amount=round(p.shares*ASSETS[p.symbol].price),fee=round(amount*FEE);
      orders.push({action:'卖出',symbol:p.symbol,shares:p.shares,price:ASSETS[p.symbol].price,amount,fee});cash=round(cash+amount-fee);
    }
  }
  const held=a.positions.find(p=>p.symbol===t.symbol)?.shares||0;
  const wanted=Math.floor((total(a)*t.weight/100)/(asset.price*100))*100;
  const delta=wanted-held;
  if(delta<0){
    const amount=round(-delta*asset.price),fee=round(amount*FEE);
    orders.push({action:'卖出',symbol:t.symbol,shares:-delta,price:asset.price,amount,fee});cash=round(cash+amount-fee);
  }else if(delta>0){
    let shares=Math.min(delta,Math.floor(cash/(asset.price*(1+FEE)*100))*100);
    while(shares>0&&round(shares*asset.price)+round(round(shares*asset.price)*FEE)>cash)shares-=100;
    if(shares>0){const amount=round(shares*asset.price),fee=round(amount*FEE);orders.push({action:'买入',symbol:t.symbol,shares,price:asset.price,amount,fee});cash=round(cash-amount-fee);}
  }
  return {target:t,orders,fees:round(orders.reduce((s,o)=>s+o.fee,0)),remaining:cash,insufficient:(delta>0&&!orders.some(o=>o.action==='买入'))||(t.weight>0&&wanted===0&&held===0)};
}
function toast(message){clearTimeout(toastTimer);$('#toast').innerHTML=icon('circle-check')+`<span>${esc(message)}</span>`;$('#toast').hidden=false;toastTimer=setTimeout(()=>$('#toast').hidden=true,4300);}
function mountIcons(root=document){root.querySelectorAll('[data-icon]').forEach(el=>{el.innerHTML=icon(el.dataset.icon);});}
function renderAccounts(){
  const q=$('#account-search').value.trim().toLowerCase();
  const list=state.accounts.filter(a=>(a.name+' '+STRATEGIES[a.strategy].name).toLowerCase().includes(q));
  $('#account-count').textContent=state.accounts.length;
  $('#nav-count').textContent=state.accounts.length;
  $('#all-assets').innerHTML=`全部账户资产<b class="num">${money(state.accounts.reduce((s,a)=>s+total(a),0))}</b>`;
  $('#account-list').innerHTML=list.length?list.map(a=>{
    const p=plan(a),selected=a.id===state.selected;
    return `<button class="account-card${selected?' selected':''}" data-account="${esc(a.id)}" aria-pressed="${selected}"><div class="account-card-head"><span>${esc(a.name)}</span><span class="status-dot ${a.running?'running':''}" aria-label="${a.running?'运行中':'已暂停'}"></span></div><div class="account-strategy">${STRATEGIES[a.strategy].short} · ${a.auto?'尾盘自动':'手动执行'}</div><div class="account-card-bottom"><span class="account-card-asset num">${money(total(a))}</span><span class="mini-badge ${p.orders.length&&a.running?'pending':''}">${!a.running?'已暂停':p.insufficient?'待补充资金':p.orders.length?`${p.orders.length} 笔待调仓`:'持仓已对齐'}</span></div></button>`;
  }).join(''):`<div class="list-empty">没有找到“${esc($('#account-search').value)}”。试试其他账户名称或策略名称。</div>`;
}
function render(){renderAccounts();renderWorkspace();mountIcons();$('#scenario').disabled=busyAccounts.size>0;}
function renderWorkspace(){
  const a=current(), value=total(a), pnl=round(value-a.netCapital), ret=a.netCapital>0?pnl/a.netCapital*100:0,p=plan(a);
  $('#workspace').innerHTML=`
    <div class="account-header"><div><div class="account-title-line"><h2>${esc(a.name)}</h2><span class="chip ${a.running?'green':''}"><span class="status-dot ${a.running?'running':''}"></span>${a.running?'运行中':'已暂停'}</span><span class="chip">${a.auto?'尾盘自动':'手动执行'}</span></div><div class="account-id"><span>${esc(a.id)}</span><span>·</span><span>创建于 ${esc(a.created)}</span><span>·</span><span>${STRATEGIES[a.strategy].name}</span></div></div><div class="account-actions"><button class="button compact" data-action="funds">${icon('arrows-transfer-up')}资金管理</button><button class="button compact" data-action="settings">${icon('settings')}账户设置</button></div></div>
    <div class="metrics" aria-label="账户资产概览"><div class="metric"><label>总资产（元）</label><div class="metric-value num">${number(value)}</div><div class="metric-sub">初始资金 ${money(a.initial)}</div></div><div class="metric"><label>累计收益 / 收益率</label><div class="metric-value num ${pnl>0?'positive':pnl<0?'negative':''}">${signed(pnl)}</div><div class="metric-sub num ${pnl>0?'positive':pnl<0?'negative':''}">${signed(ret)}% <span class="muted">· 已剔除出入金</span></div></div><div class="metric"><label>可用资金（元）</label><div class="metric-value num">${number(a.cash)}</div><div class="metric-sub">可用于模拟调仓</div></div><div class="metric"><label>持仓市值（元）</label><div class="metric-value num">${number(equity(a))}</div><div class="metric-sub">${a.positions.filter(p=>p.shares>0).length} 只 ETF</div></div><div class="metric"><label>当前仓位</label><div class="metric-value num">${number(positionWeight(a),1)}<small>%</small></div><div class="weight-track"><span style="width:${Math.min(100,positionWeight(a))}%"></span></div></div></div>
    <div class="tabs" role="tablist" aria-label="账户内容">${[['overview','账户总览'],['trades','成交记录'],['funds','资金流水'],['events','运行记录'],['config','账户设置']].map(([id,label])=>`<button class="tab${activeTab===id?' selected':''}" role="tab" id="tab-${id}" aria-controls="tab-panel" aria-selected="${activeTab===id}" tabindex="${activeTab===id?'0':'-1'}" data-tab="${id}">${label}${id==='trades'&&a.trades.length?`<span class="tab-count">${a.trades.length}</span>`:''}</button>`).join('')}</div>
    <div id="tab-panel" class="tab-content${refreshing?' loading-surface':''}" role="tabpanel" aria-labelledby="tab-${activeTab}" aria-busy="${refreshing}">${activeTab==='overview'?overview(a,p):activeTab==='trades'?trades(a):activeTab==='funds'?funds(a):activeTab==='events'?events(a):settingsPreview(a)}</div>`;
}
function overview(a,p){
  const t=p.target,asset=ASSETS[t.symbol],s=SCENARIOS[scenario];
  return `<div class="overview-grid"><div class="left-content"><section aria-label="当前持仓"><div class="section-heading"><h3>当前持仓</h3><small>按示例价格估值</small></div>${a.positions.some(p=>p.shares>0)?`<div class="table-scroll"><table class="holdings-table"><thead><tr><th>标的 / 代码</th><th class="right">持仓（份）</th><th class="right">参考价</th><th class="right">市值（元）</th></tr></thead><tbody>${a.positions.filter(p=>p.shares>0).map(p=>`<tr><td><b>${ASSETS[p.symbol].name}</b><small>${p.symbol.toUpperCase()}</small></td><td class="right num">${number(p.shares,0)}</td><td class="right num">${number(ASSETS[p.symbol].price,3)}</td><td class="right num">${number(p.shares*ASSETS[p.symbol].price)}</td></tr>`).join('')}</tbody></table></div>`:`<div class="empty-state compact-empty"><div class="empty-icon">${icon('wallet')}</div><h3>资金已就位，等待首次建仓</h3><p>核对右侧策略目标，在尾盘情境执行模拟调仓。</p></div>`}<div class="allocation"><span><i class="legend-dot"></i>持仓 ${number(positionWeight(a),1)}%</span><div class="allocation-bar" aria-hidden="true"><span style="width:${positionWeight(a)}%"></span><i></i></div><span><i class="legend-dot cash"></i>现金 ${number(100-positionWeight(a),1)}%</span></div></section>
    <section class="strategy-section" aria-label="绑定策略"><div class="section-heading"><h3>策略观察</h3><button class="text-button" data-action="settings">调整策略${icon('chevron-right')}</button></div><div class="strategy-name">${icon(STRATEGIES[a.strategy].icon)}${STRATEGIES[a.strategy].name}<span class="chip">${STRATEGIES[a.strategy].tag}</span></div><p>${STRATEGIES[a.strategy].desc}</p>${a.strategy==='erp'?`<div class="signal-row"><div><label>股债利差 ERP</label><strong class="num">10.59%</strong><small>示例因子</small></div><div><label>250 日分位</label><strong class="num">${t.percentile}%</strong><small>${scenario==='low'?'低估区间':'稳健观察区间'}</small></div><div><label>策略目标仓位</label><strong class="num">${t.weight}%</strong><small>剩余资金留现金</small></div></div>`:`<div class="signal-row"><div><label>进攻动量（${a.config.lookback} 日）</label><strong class="num positive">+8.24%</strong><small>${ASSETS[a.config.attack].name}</small></div><div><label>防守动量（${a.config.lookback} 日）</label><strong class="num positive">+0.92%</strong><small>${ASSETS[a.config.defense].name}</small></div><div><label>当前策略目标</label><strong>${asset.name}</strong><small>示例信号 · 进攻</small></div></div>`}<details class="rule-detail"><summary>${icon('chevron-right')}查看策略规则与参数</summary><p>${a.strategy==='erp'?`ERP 分位低于 ${a.config.low}% 时，目标仓位 ${a.config.lowWeight}%；高于 ${a.config.high}% 时，目标仓位 ${a.config.highWeight}%；中间区间为 ${a.config.midWeight}%。调仓数量按 100 份取整。`:`进攻标的 ${ASSETS[a.config.attack].name}（${a.config.attack.toUpperCase()}），防守标的 ${ASSETS[a.config.defense].name}（${a.config.defense.toUpperCase()}），观察周期 ${a.config.lookback} 日。此处固定展示“进攻动量较强且站上均线”的示例信号，未运行真实策略计算。`}</p></details><div class="market-strip"><span class="market-state"><span class="status-dot ${s.ready?'running':scenario==='stale'?'waiting':''}"></span>${esc(s.full)}</span><button class="text-button" data-action="refresh" ${refreshing?'disabled':''}>${icon('refresh')}${refreshing?'正在刷新…':'刷新示例行情'}</button></div></section></div>${decision(a,p)}</div>`;
}
function decision(a,p){
  const s=SCENARIOS[scenario],invalid=scenario==='stale'||scenario==='error',busy=busyAccounts.has(a.id),hasOrders=p.orders.length>0;
  let title,desc,kind='success',glyph='check',label;
  if(!a.running){title='账户已暂停运行';desc='配置与持仓已保留。恢复运行后，再核对当前调仓计划。';kind='warning';glyph='player-pause';}
  else if(invalid){title=scenario==='error'?'暂时无法生成调仓计划':'行情已延迟，等待更新';desc=s.note;kind=scenario==='error'?'error':'warning';glyph='alert-circle';}
  else if(p.insufficient){title='可用资金不足一手';desc='当前资金不足以按 100 份的交易单位完成建仓，可先入金再重新生成清单。';kind='warning';glyph='wallet';}
  else if(hasOrders){title=!a.positions.length?'准备好，开始首次建仓':a.strategy==='erp'?`建议调整至 ${p.target.weight}% 仓位`:'策略信号切换，建议调仓';desc=a.strategy==='erp'?`将红利低波 ETF 调整至目标仓位，剩余资金保留为现金。`:`目标切换为${ASSETS[p.target.symbol].name}，${p.orders.some(o=>o.action==='卖出')?'先卖出原持仓，模拟成交后再买入目标标的。':'按清单建立目标持仓。'}`;kind='';glyph='arrows-exchange';}
  else{title=a.positions.some(p=>p.shares>0)?'持仓已对齐，继续持有':'保持空仓，等待信号';desc=`当前持仓符合「${STRATEGIES[a.strategy].short}」目标，今日无需额外操作。`;}
  const executable=a.running&&s.ready&&!invalid&&hasOrders&&!p.insufficient&&!busy;
  label=busy?'正在模拟撮合…':!a.running?'恢复运行后可执行':invalid?'等待有效行情':p.insufficient?'资金不足，暂不可执行':!hasOrders?'当前无需调仓':s.ready?`执行模拟调仓 · ${p.orders.length} 笔`:scenario==='closed'?'休市，暂不可执行':'等待尾盘执行窗口';
  return `<aside class="decision-panel" aria-label="今日调仓"><div class="section-heading"><h3>今日调仓</h3><span class="decision-time">${icon('clock')}14:45–14:55</span></div><div class="decision-icon ${kind}">${icon(glyph)}</div><div class="decision-title">${title}</div><p class="decision-desc">${desc}</p>${invalid?`<div class="notice amber">下方账户估值沿用示例快照；异常情境不生成可执行清单。</div><button class="button full" data-action="refresh" ${refreshing?'disabled':''}>${icon('refresh')}重试加载示例行情</button>`:`<div class="target-row"><span>当前仓位 <strong class="num">${number(positionWeight(a),1)}%</strong></span>${icon('arrow-right')}<span>策略目标 <strong class="num">${p.target.weight}%</strong></span></div>${hasOrders?`<div class="plan-orders">${p.orders.map(o=>`<div class="plan-order"><span class="order-direction ${o.action==='卖出'?'sell':''}">${o.action==='买入'?'买':'卖'}</span><div class="order-info"><b>${ASSETS[o.symbol].name}</b><small>${number(o.shares,0)} 份 × ${number(o.price,3)}</small></div><div class="order-amount num">${money(o.amount)}<small>${o.action==='买入'&&p.orders.some(v=>v.action==='卖出')?'卖出成交后买入':'预计金额'}</small></div></div>`).join('')}</div><div class="fee-summary"><span>预计费用 ${money(p.fees)}</span><span>成交后现金 ${money(p.remaining)}</span></div>`:`<div class="no-trade">${icon('circle-check')}当前没有待执行委托</div>`}<div class="execution-note">${icon(a.running&&s.ready?'info-circle':'lock')}<span>${!a.running?'账户已暂停，手动和自动执行均已停用。':!hasOrders?'后续信号变化时会生成新的调仓清单。':esc(s.note)}</span></div><button class="button primary full" data-action="execute" ${executable?'':'disabled'}>${busy?'<span class="inline-loading">正在模拟撮合…</span>':icon(hasOrders?'player-play':'check')+label}</button><p class="decision-footnote">仅模拟撮合 · 参考价成交 · 费用万 1</p>`}<div class="run-meta"><span>示例快照 ${esc(s.time)}</span><button class="text-button" data-action="tab-events">运行记录${icon('chevron-right')}</button></div></aside>`;
}
function trades(a){
  return `<div class="record-heading"><div><h3>成交记录</h3><p>每次模拟调仓的买卖明细，按成交时间倒序。</p></div><div class="record-tools"><select id="trade-filter" class="small-select" aria-label="筛选成交方向"><option value="all">全部方向</option><option value="买入">买入</option><option value="卖出">卖出</option></select><button class="button compact" data-action="export-trades" ${a.trades.length?'':'disabled'}>${icon('download')}导出 CSV</button></div></div><div id="trade-table">${tradeTable(a,'all')}</div>`;
}
function tradeTable(a,filter){
  const rows=a.trades.filter(t=>filter==='all'||t.action===filter);
  return rows.length?`<div class="table-scroll"><table class="ledger-table"><thead><tr><th>成交时间</th><th>标的 / 代码</th><th>方向</th><th class="right">数量（份）</th><th class="right">成交价</th><th class="right">金额（元）</th><th class="right">费用</th><th>方式</th></tr></thead><tbody>${rows.map(t=>`<tr><td class="num">${esc(t.time)}</td><td><b>${ASSETS[t.symbol].name}</b><small>${t.symbol.toUpperCase()}</small></td><td class="${t.action==='买入'?'positive':'negative'}">${t.action}</td><td class="right num">${number(t.shares,0)}</td><td class="right num">${number(t.price,3)}</td><td class="right num">${number(t.amount)}</td><td class="right num">${number(t.fee)}</td><td>${esc(t.source)}</td></tr>`).join('')}</tbody></table></div><div class="table-footer">共 ${rows.length} 笔 · 全部为演示成交</div>`:empty('还没有成交记录',filter==='all'?'在账户总览执行一次模拟调仓，成交明细会出现在这里。':'当前筛选条件下没有成交记录。','receipt');
}
function funds(a){return `<div class="record-heading"><div><h3>资金流水</h3><p>记录初始资金与出入金；出入金不会被计作策略收益。</p></div><button class="button compact" data-action="funds">${icon('plus')}出入金</button></div><div class="table-scroll"><table class="ledger-table"><thead><tr><th>时间</th><th>类型</th><th class="right">变动金额（元）</th><th class="right">变动后现金（元）</th><th>状态</th></tr></thead><tbody>${a.funds.map(f=>`<tr><td class="num">${esc(f.time)}</td><td>${f.type}</td><td class="right num ${f.amount>0?'positive':'negative'}">${signed(f.amount)}</td><td class="right num">${number(f.balance)}</td><td><span class="chip green">已入账</span></td></tr>`).join('')}</tbody></table></div><div class="table-footer">净投入 ${money(a.netCapital)} · 可用资金 ${money(a.cash)}</div>`;}
function events(a){return `<div class="record-heading"><div><h3>运行记录</h3><p>保留策略变更、运行状态和调仓执行结果。</p></div><span class="chip">${a.events.length} 条记录</span></div><div class="event-list">${a.events.map(e=>`<div class="event-item"><time class="num">${esc(e.time)}</time><div><b>${esc(e.title)}</b><p>${esc(e.detail)}</p></div><span class="chip ${e.status==='已完成'?'green':e.status==='受阻'?'amber':'blue'}">${esc(e.status)}</span></div>`).join('')}</div>`;}
function settingsPreview(a){return `<div class="record-heading"><div><h3>账户与策略配置</h3><p>配置独立保存于当前账户，切换账户后自动带出。</p></div><button class="button compact" data-action="settings">${icon('edit')}编辑配置</button></div><div class="setting-preview"><section><h3>账户信息</h3><div class="settings-list">${settingLine('账户名称',a.name)}${settingLine('初始资金',money(a.initial))}${settingLine('净投入资金',money(a.netCapital))}${settingLine('执行方式',a.auto?'尾盘自动模拟调仓':'手动执行')}${settingLine('运行状态',a.running?'运行中':'已暂停')}</div></section><section><h3>策略配置</h3><div class="settings-list">${settingLine('绑定策略',STRATEGIES[a.strategy].name)}${a.strategy==='erp'?settingLine('ERP 分位阈值',`${a.config.low}% / ${a.config.high}%`)+settingLine('高估 / 常态 / 低估仓位',`${a.config.lowWeight}% / ${a.config.midWeight}% / ${a.config.highWeight}%`):settingLine('进攻标的',ASSETS[a.config.attack].name)+settingLine('防守标的',ASSETS[a.config.defense].name)+settingLine('观察周期',a.config.lookback+' 日')}${settingLine('执行窗口','14:45–14:55')}${settingLine('演示费用','单边万 1，无最低收费')}</div></section></div><div class="settings-actions"><button class="button" data-action="pause">${icon(a.running?'player-pause':'player-play')}${a.running?'暂停账户运行':'恢复账户运行'}</button><button class="button" data-action="funds">${icon('arrows-transfer-up')}管理资金</button></div><p class="settings-note">更换策略只更新目标与调仓清单，已有持仓会保留。<br>自动模拟仅在此 Demo 打开时，由“切换尾盘情境”或“刷新示例行情”触发；不代表后台定时任务已接入。</p>`;}
const settingLine=(label,value)=>`<div class="settings-line"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;
const empty=(title,desc,glyph='receipt')=>`<div class="empty-state"><div class="empty-icon">${icon(glyph)}</div><h3>${title}</h3><p>${desc}</p></div>`;
function openDrawer(title,subtitle,body,kind){
  lastFocus=document.activeElement;drawerKind=kind;
  $('#drawer-title').textContent=title;$('#drawer-subtitle').textContent=subtitle;$('#drawer-body').innerHTML=body;
  mountIcons($('#drawer'));
  if(!$('#drawer').open)$('#drawer').showModal();
  document.body.style.overflow='hidden';
}
function closeDrawer(){if($('#drawer').open)$('#drawer').close();}
$('#drawer').addEventListener('close',()=>{document.body.style.overflow='';drawerKind='';lastFocus?.isConnected&&lastFocus.focus();});
$('#drawer').addEventListener('click',e=>{if(e.target===$('#drawer')){const r=$('#drawer').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right)closeDrawer();}});
function strategyChoices(selected){return `<div class="strategy-choices">${Object.entries(STRATEGIES).map(([key,s])=>`<label class="strategy-choice"><input type="radio" name="strategy" value="${key}" ${selected===key?'checked':''}><div><strong>${s.name}</strong><p>${s.desc}</p><span class="chip">${s.tag}</span></div></label>`).join('')}</div>`;}
const options=(symbols,selected)=>symbols.map(symbol=>`<option value="${symbol}" ${selected===symbol?'selected':''}>${ASSETS[symbol].name} · ${symbol.slice(2)}</option>`).join('');
function parameterFields(type,c){
  return type==='erp'?`<div class="field-pair"><div class="field"><label for="erp-low">高估区间分位上限（%）</label><input id="erp-low" name="low" type="number" min="0" max="100" step="0.1" value="${c.low}"></div><div class="field"><label for="erp-high">低估区间分位下限（%）</label><input id="erp-high" name="high" type="number" min="0" max="100" step="0.1" value="${c.high}"></div></div><div class="field-pair"><div class="field"><label for="low-weight">高估仓位（%）</label><input id="low-weight" name="lowWeight" type="number" min="0" max="100" value="${c.lowWeight}"></div><div class="field"><label for="mid-weight">常态仓位（%）</label><input id="mid-weight" name="midWeight" type="number" min="0" max="100" value="${c.midWeight}"></div></div><div class="field"><label for="high-weight">低估仓位（%）</label><input id="high-weight" name="highWeight" type="number" min="0" max="100" value="${c.highWeight}"></div><div class="field-error" id="parameter-error" role="alert"></div>`:`<div class="field"><label for="attack">进攻标的</label><select id="attack" name="attack">${options(['sh588380','sz159915','sh588000'],c.attack)}</select></div><div class="field"><label for="defense">防守标的</label><select id="defense" name="defense">${options(['sh511010','sh511260','sh512890'],c.defense)}</select></div><div class="field"><label for="lookback">动量观察周期（交易日）</label><input id="lookback" name="lookback" type="number" min="5" max="120" step="1" value="${c.lookback}"><span class="field-help">5–120 个交易日；Demo 使用固定示例信号。</span></div><div class="field-error" id="parameter-error" role="alert"></div>`;
}
function accountForm(mode='create',preferred='erp'){
  const editing=mode==='settings',a=editing?current():null,type=a?.strategy||preferred,c=a?.config||config(type);drawerAccount=a?.id||null;
  openDrawer(editing?'账户设置':'新增模拟账户',editing?'修改仅作用于当前账户，已有持仓会保留。':'选好策略和资金，创建你的独立模拟试验。',`<form id="account-form" class="drawer-form" novalidate><div class="form-content"><section class="form-section"><div class="form-section-title">基本信息</div><div class="field"><label for="account-name">账户名称</label><input id="account-name" name="name" value="${esc(a?.name||'')}" maxlength="30" placeholder="例如：红利稳健 02" autocomplete="off" aria-describedby="name-error" autofocus><div id="name-error" class="field-error" role="alert"></div></div>${!editing?`<div class="field"><label for="initial-capital">初始模拟资金</label><div class="input-unit"><input id="initial-capital" name="capital" type="number" min="1000" max="1000000000" step="0.01" value="100000" aria-describedby="capital-error"><span>元</span></div><div class="presets" aria-label="常用金额">${[50000,100000,200000,500000].map(v=>`<button type="button" data-preset="${v}" class="${v===100000?'selected':''}">${v/10000} 万</button>`).join('')}</div><span class="field-help">支持 1,000–1,000,000,000 元，后续可单独出入金。</span><div id="capital-error" class="field-error" role="alert"></div></div>`:`<div class="notice">初始资金 ${money(a.initial)} · 当前总资产 ${money(total(a))}<br>追加或取出资金，请使用账户首页的「资金管理」。</div>`}</section><section class="form-section"><div class="form-section-title">选择策略<small>一个账户独立跟随一套策略</small></div>${strategyChoices(type)}<div id="parameter-fields" class="parameter-fields">${parameterFields(type,c)}</div></section><section class="form-section"><div class="form-section-title">执行方式</div><div class="field-row"><div><b>尾盘自动模拟调仓</b><small>默认手动；开启后在尾盘情境自动模拟执行</small></div><label class="switch"><input type="checkbox" id="auto-trade" name="auto" ${a?.auto?'checked':''} aria-label="尾盘自动模拟调仓"><span></span></label></div><p class="field-help">自动演示仅在页面打开时，由切换至尾盘情境或刷新触发。行情异常、休市或账户暂停时不会执行。</p></section>${editing?`<p class="notice amber">保存策略后会重新生成调仓清单；已有持仓不会自动重置。请回到账户总览核对差额后执行。</p>`:''}</div><footer class="form-footer"><span class="footer-hint">浏览器本地保存</span><button type="button" class="button" data-action="close">取消</button><button type="submit" class="button primary">${editing?'保存设置':'创建账户'}</button></footer></form>`,mode);
  const drafts={[type]:{...c}};
  let previous=type;
  $$('input[name="strategy"]').forEach(r=>r.addEventListener('change',()=>{
    drafts[previous]=readConfig(previous,new FormData($('#account-form')));
    previous=r.value;$('#parameter-fields').innerHTML=parameterFields(r.value,drafts[r.value]||config(r.value));
  }));
  $('#account-form').addEventListener('submit',e=>{e.preventDefault();saveAccountForm(editing);});
}
function readConfig(type,fd){return type==='erp'?Object.fromEntries(['low','high','lowWeight','midWeight','highWeight'].map(k=>[k,Number(fd.get(k))])):{attack:fd.get('attack'),defense:fd.get('defense'),lookback:Number(fd.get('lookback'))};}
function fieldError(id,message,input){$('#'+id).textContent=message;if(input){input.setAttribute('aria-invalid','true');input.focus();}}
function saveAccountForm(editing){
  $$('#account-form [aria-invalid]').forEach(el=>el.removeAttribute('aria-invalid'));$$('#account-form .field-error').forEach(el=>el.textContent='');
  const fd=new FormData($('#account-form')),name=String(fd.get('name')).trim(),type=fd.get('strategy'),c=readConfig(type,fd),capital=Number(fd.get('capital'));
  if(!name||name.length>30){fieldError('name-error','请输入 1–30 个字符的账户名称。',$('#account-name'));return;}
  if(state.accounts.some(a=>a.name.toLowerCase()===name.toLowerCase()&&a.id!==drawerAccount)){fieldError('name-error','已有同名账户，请换一个便于区分的名称。',$('#account-name'));return;}
  if(!editing&&(!Number.isFinite(capital)||capital<1000||capital>1e9||Math.abs(capital-round(capital))>1e-6)){fieldError('capital-error','初始资金需在 1,000–1,000,000,000 元之间，最多两位小数。',$('#initial-capital'));return;}
  const inputs=[...$('#parameter-fields').querySelectorAll('input,select')];
  if(inputs.some(el=>!el.value||!el.checkValidity())){fieldError('parameter-error','请按字段范围填写完整参数。',inputs.find(el=>!el.value||!el.checkValidity()));return;}
  if(type==='erp'&&c.low>=c.high){fieldError('parameter-error','高估区间上限必须小于低估区间下限。',$('#erp-low'));return;}
  if(type==='erp'&&(c.lowWeight>c.midWeight||c.midWeight>c.highWeight)){fieldError('parameter-error','仓位应满足：高估仓位 ≤ 常态仓位 ≤ 低估仓位。',$('#low-weight'));return;}
  if(editing){
    const a=state.accounts.find(x=>x.id===drawerAccount);if(!a)return;
    const old=STRATEGIES[a.strategy].name;
    a.name=name;a.strategy=type;a.config=c;a.auto=fd.get('auto')==='on';a.revision++;
    event(a,'账户配置已更新',`策略：${old} → ${STRATEGIES[type].name}；执行方式：${a.auto?'尾盘自动':'手动'}。已有持仓保留。`);
    state.selected=a.id;save();closeDrawer();render();toast('设置已保存，调仓清单已重新生成。');
  }else{
    const a={id:'SIM-'+String(state.nextId++).padStart(4,'0'),name,strategy:type,config:c,initial:capital,netCapital:capital,cash:capital,positions:[],auto:fd.get('auto')==='on',running:true,revision:1,created:SCENARIOS[scenario].date,funds:[{id:uid(),time:stamp(),type:'初始资金',amount:capital,balance:capital}],trades:[],events:[]};
    event(a,'模拟账户已创建',`绑定「${STRATEGIES[type].name}」，初始资金 ${money(capital)}。`);state.accounts.push(a);state.selected=a.id;activeTab='overview';save();closeDrawer();$('#account-search').value='';render();$('#account-list').lastElementChild?.scrollIntoView({block:'nearest',inline:'nearest'});toast('账户已创建，核对调仓清单即可开始。');
  }
}
function fundsForm(){
  const a=current();drawerAccount=a.id;
  openDrawer('资金管理',`${a.name} · 出入金与策略收益分别记录。`,`<form id="fund-form" class="drawer-form" novalidate><div class="form-content"><div class="fund-switch" role="group" aria-label="资金操作"><button type="button" class="selected" data-fund-mode="deposit" aria-pressed="true">模拟入金</button><button type="button" data-fund-mode="withdraw" aria-pressed="false">模拟出金</button></div><input type="hidden" name="mode" value="deposit"><div class="fund-balance"><span>当前可用资金</span><b class="num">${money(a.cash)}</b></div><div class="field"><label for="fund-amount" id="fund-label">入金金额</label><div class="input-unit"><input id="fund-amount" name="amount" type="number" min="0.01" max="1000000000" step="0.01" value="10000" aria-describedby="fund-error" autofocus><span>元</span></div><div class="presets">${[10000,50000,100000].map(v=>`<button type="button" data-fund-preset="${v}" class="${v===10000?'selected':''}">${v/10000} 万</button>`).join('')}</div><div id="fund-error" class="field-error" role="alert"></div></div><p class="notice" id="fund-notice">入金后，可用资金与净投入同步增加，累计收益金额不变。策略会根据新的总资产重新生成清单。</p><div id="fund-preview" class="fund-preview"></div></div><footer class="form-footer"><button type="button" class="button" data-action="close">取消</button><button type="submit" class="button primary" id="fund-submit">确认入金</button></footer></form>`,'funds');
  $('#fund-form').addEventListener('submit',e=>{e.preventDefault();saveFundForm();});
  $('#fund-amount').addEventListener('input',updateFundPreview);updateFundPreview();
}
function updateFundPreview(){
  const a=state.accounts.find(x=>x.id===drawerAccount),amount=Number($('#fund-amount').value)||0,deposit=$('#fund-form [name="mode"]').value==='deposit',delta=deposit?amount:-amount;
  $('#fund-preview').innerHTML=`<div><span>操作后可用资金</span><b class="num">${money(a.cash+delta)}</b></div><div><span>操作后净投入</span><b class="num">${money(a.netCapital+delta)}</b></div><div><span>累计收益金额</span><b class="num">${signed(total(a)-a.netCapital)} 元 · 不受出入金影响</b></div>`;
}
function saveFundForm(){
  const a=state.accounts.find(x=>x.id===drawerAccount),amount=Number($('#fund-amount').value),deposit=$('#fund-form [name="mode"]').value==='deposit';
  $('#fund-error').textContent='';$('#fund-amount').removeAttribute('aria-invalid');
  if(!Number.isFinite(amount)||amount<=0||amount>1e9||Math.abs(amount-round(amount))>1e-6){fieldError('fund-error','请输入 0.01–1,000,000,000 元的金额，最多两位小数。',$('#fund-amount'));return;}
  if(!deposit&&amount>a.cash){fieldError('fund-error',`出金金额超过可用资金 ${money(a.cash)}。如需取出持仓资金，请先完成卖出。`,$('#fund-amount'));return;}
  const delta=deposit?amount:-amount;a.cash=round(a.cash+delta);a.netCapital=round(a.netCapital+delta);a.revision++;
  a.funds.unshift({id:uid(),time:stamp(),type:deposit?'模拟入金':'模拟出金',amount:delta,balance:a.cash});event(a,deposit?'模拟入金已到账':'模拟出金已完成',`${money(amount)}；可用资金 ${money(a.cash)}。`);
  save();closeDrawer();render();toast(`${deposit?'入金':'出金'} ${money(amount)} 已完成，资金流水已更新。`);
}
async function executeAccount(id,source='手动执行'){
  const a=state.accounts.find(x=>x.id===id);if(!a||busyAccounts.has(id))return;
  const p=plan(a),s=SCENARIOS[scenario];
  if(!a.running||!s.ready||!p.orders.length||p.insufficient){if(source==='手动执行')toast('当前不满足执行条件，请核对运行状态、资金与演示情境。');return;}
  const revision=a.revision,scenarioAtStart=scenario,executedAt=stamp(),batch=uid();busyAccounts.add(id);render();
  await new Promise(resolve=>setTimeout(resolve,680));
  if(a.revision!==revision||scenario!==scenarioAtStart||!state.accounts.includes(a)){busyAccounts.delete(id);render();toast('账户配置已变化，已取消本次执行，请重新核对清单。');return;}
  // Apply to a copy; publish the whole simulated batch only after validating cash and positions.
  let cash=a.cash;const positions=a.positions.map(p=>({...p})),rows=[];
  for(const o of p.orders){
    let held=positions.find(v=>v.symbol===o.symbol);
    if(o.action==='卖出'){
      if(!held||held.shares<o.shares){busyAccounts.delete(id);render();toast('持仓发生变化，请刷新清单后重试。');return;}
      held.shares-=o.shares;cash=round(cash+o.amount-o.fee);
    }else{
      if(cash<round(o.amount+o.fee)){busyAccounts.delete(id);render();toast('资金不足，未执行本批次委托。');return;}
      if(!held){held={symbol:o.symbol,shares:0,cost:o.price};positions.push(held);}
      held.cost=(held.cost*held.shares+o.amount+o.fee)/(held.shares+o.shares);held.shares+=o.shares;cash=round(cash-o.amount-o.fee);
    }
    rows.push({...o,id:uid(),time:executedAt,source,batch});
  }
  a.cash=cash;a.positions=positions.filter(p=>p.shares>0);a.trades.unshift(...rows);a.revision++;
  event(a,'模拟调仓已完成',`${source}，${rows.length} 笔成交，费用 ${money(p.fees)}；现金与持仓已更新。`);
  busyAccounts.delete(id);save();render();$('#workspace').classList.remove('focus-flash');void $('#workspace').offsetWidth;$('#workspace').classList.add('focus-flash');toast(`${a.name}：${rows.length} 笔模拟成交已完成。`);
}
async function runAutomatic(){if(!SCENARIOS[scenario].ready)return;for(const a of [...state.accounts])if(a.auto&&a.running&&plan(a).orders.length)await executeAccount(a.id,'尾盘自动');}
async function refresh(){
  if(refreshing)return;refreshing=true;renderWorkspace();await new Promise(r=>setTimeout(r,550));refreshing=false;
  const a=current(),invalid=['error','stale'].includes(scenario);
  event(a,invalid?'示例行情刷新受阻':'示例行情已刷新',SCENARIOS[scenario].note,invalid?'受阻':'已完成');save();render();
  toast(invalid?'当前仍是异常演示情境，可切换至「尾盘窗口」重试。':'示例快照已刷新，调仓清单已重新核对。');if(!invalid)await runAutomatic();
}
function help(){openDrawer('快速体验','完整体验账户创建、资金配置与执行闭环。',`<div class="form-content">${[['新增一个账户','点击右上角「新增模拟账户」，填写名称、金额，选择策略和执行方式。无需分步跳转。'],['体验一次调仓','点击底部「体验一次调仓」，进入有待执行清单的账户与尾盘情境。核对后点击执行。'],['查看执行结果','成交后现金、持仓与收益同步更新；在「成交记录」「资金流水」「运行记录」查看完整过程。'],['调整策略与资金','账户设置可换策略和调整参数；资金管理支持入金、出金。出入金不会被算成收益。'],['体验边界状态','底部情境可切换休市、盘中、ERP 低估、行情延迟和行情异常。暂停账户可停止手动及自动执行。']].map(([t,d],i)=>`<div class="help-step"><span>${i+1}</span><div><h3>${t}</h3><p>${d}</p></div></div>`).join('')}<p class="notice">此 Demo 使用示例报价和固定信号；仅验证交互，不代表真实回测、真实交易或后台自动运行。浏览器本地保存演示账户，可在页面底部恢复初始演示。</p><button class="button primary full" data-action="try-trade">${icon('player-play')}体验一次调仓</button></div>`,'help');}
function library(){openDrawer('可选策略','沿用当前项目已支持的两类模拟调仓策略。',`<div class="form-content">${Object.entries(STRATEGIES).map(([type,s])=>`<section class="library-item"><h3>${icon(s.icon)} ${s.name}</h3><span class="chip">${s.tag}</span><p>${s.desc}</p><div class="settings-line"><span>主要配置</span><b>${type==='erp'?'ERP 分位阈值、分区仓位':'进攻 / 防守 ETF、动量周期'}</b></div><button class="button" data-create-strategy="${type}" style="margin-top:16px">${icon('plus')}使用此策略创建账户</button></section>`).join('')}<p class="settings-note">因子实验与模型回测保留研究入口；当前 Demo 未将其包装成可执行的模拟交易策略。</p></div>`,'library');}
function resetDemo(){openDrawer('恢复初始演示','将清除本浏览器中本版本 Demo 的自建账户和操作记录。',`<div class="form-content"><p class="notice amber">恢复后回到 3 个示例账户。此操作只影响本 Demo 的浏览器记录，请先导出需要保留的成交数据。</p><div class="settings-actions"><button class="button" data-action="close">保留当前数据</button><button class="button danger" data-action="confirm-reset">确认恢复初始演示</button></div></div>`,'reset');}
function exportTrades(){
  const a=current(),filter=$('#trade-filter')?.value||'all',rows=a.trades.filter(t=>filter==='all'||t.action===filter),safe=v=>{const t=String(v);return '"'+(/^[=+@-]/.test(t)?"'":'')+t.replace(/"/g,'""')+'"';};
  const lines=[['账户','成交时间','标的','代码','方向','数量(份)','成交价','金额(元)','费用(元)','方式'],...rows.map(t=>[a.name,t.time,ASSETS[t.symbol].name,t.symbol,t.action,t.shares,t.price,t.amount,t.fee,t.source])];
  const blob=new Blob(['\uFEFF'+lines.map(row=>row.map(safe).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=`${a.name.replace(/[\\/:*?"<>|]/g,'_')}_演示成交记录.csv`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(`已导出 ${rows.length} 笔演示成交记录。`);
}
document.addEventListener('click',async e=>{
  const accountButton=e.target.closest('[data-account]');
  if(accountButton){state.selected=accountButton.dataset.account;activeTab='overview';save();render();return;}
  const tab=e.target.closest('[data-tab]');if(tab){activeTab=tab.dataset.tab;renderWorkspace();$('#tab-'+activeTab)?.focus();return;}
  const preset=e.target.closest('[data-preset]');if(preset){$('#initial-capital').value=preset.dataset.preset;$$('[data-preset]').forEach(b=>b.classList.toggle('selected',b===preset));return;}
  const fundPreset=e.target.closest('[data-fund-preset]');if(fundPreset){$('#fund-amount').value=fundPreset.dataset.fundPreset;$$('[data-fund-preset]').forEach(b=>b.classList.toggle('selected',b===fundPreset));updateFundPreview();return;}
  const fundMode=e.target.closest('[data-fund-mode]');if(fundMode){const deposit=fundMode.dataset.fundMode==='deposit';$('#fund-form [name="mode"]').value=fundMode.dataset.fundMode;$$('[data-fund-mode]').forEach(b=>{b.classList.toggle('selected',b===fundMode);b.setAttribute('aria-pressed',String(b===fundMode));});$('#fund-label').textContent=deposit?'入金金额':'出金金额';$('#fund-submit').textContent=deposit?'确认入金':'确认出金';$('#fund-notice').textContent=deposit?'入金后，可用资金与净投入同步增加，累计收益金额不变。策略会根据新的总资产重新生成清单。':'仅可取出可用资金，不会自动卖出持仓。出金与策略收益分别记账。';$('#fund-error').textContent='';updateFundPreview();return;}
  const strategy=e.target.closest('[data-create-strategy]');if(strategy){accountForm('create',strategy.dataset.createStrategy);return;}
  const button=e.target.closest('[data-action]');if(!button||button.disabled)return;
  switch(button.dataset.action){
    case 'home':activeTab='overview';render();break;
    case 'create':accountForm();break;
    case 'settings':accountForm('settings');break;
    case 'funds':fundsForm();break;
    case 'close':closeDrawer();break;
    case 'help':help();break;
    case 'library':library();break;
    case 'refresh':await refresh();break;
    case 'execute':await executeAccount(current().id);break;
    case 'export-trades':exportTrades();break;
    case 'pause':{const a=current();a.running=!a.running;a.revision++;event(a,a.running?'账户已恢复运行':'账户已暂停',a.running?'恢复策略监控，可在有效窗口核对并执行清单。':'手动和自动模拟调仓均暂停，已有持仓与配置保留。');save();render();toast(a.running?'账户已恢复运行。':'账户已暂停，配置与持仓已保留。');break;}
    case 'tab-events':activeTab='events';renderWorkspace();break;
    case 'try-trade':{closeDrawer();const a=state.accounts.find(a=>a.running&&!a.auto&&plan(a).orders.length)||state.accounts.find(a=>a.running&&plan(a).orders.length);if(a)state.selected=a.id;scenario='window';$('#scenario').value='window';activeTab='overview';save();render();$('#workspace').scrollIntoView({block:'start',behavior:'smooth'});toast(a?'已切换至尾盘情境，请核对清单后点击执行。':'已切换尾盘情境；可新建账户，体验首次建仓。');break;}
    case 'reset':resetDemo();break;
    case 'confirm-reset':if(busyAccounts.size){toast('请等待当前模拟撮合完成后恢复。');break;}state=seed();scenario='closed';activeTab='overview';$('#scenario').value='closed';$('#account-search').value='';save();closeDrawer();render();toast('已恢复 3 个初始演示账户。');break;
  }
});
document.addEventListener('change',e=>{
  if(e.target.id==='trade-filter')$('#trade-table').innerHTML=tradeTable(current(),e.target.value);
});
document.addEventListener('input',e=>{
  const form=e.target.closest('#account-form');
  if(form){
    if(e.target.id==='account-name')$('#name-error').textContent='';
    if(e.target.id==='initial-capital'){$('#capital-error').textContent='';$$('[data-preset]').forEach(b=>b.classList.toggle('selected',Number(b.dataset.preset)===Number(e.target.value)));}
    if(e.target.closest('#parameter-fields'))$('#parameter-error').textContent='';
    e.target.removeAttribute('aria-invalid');
  }
  if(e.target.id==='fund-amount'){$('#fund-error').textContent='';e.target.removeAttribute('aria-invalid');$$('[data-fund-preset]').forEach(b=>b.classList.toggle('selected',Number(b.dataset.fundPreset)===Number(e.target.value)));}
});
document.addEventListener('keydown',e=>{
  const tab=e.target.closest('[data-tab]');if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  e.preventDefault();const tabs=['overview','trades','funds','events','config'],index=tabs.indexOf(activeTab);activeTab=e.key==='Home'?tabs[0]:e.key==='End'?tabs.at(-1):tabs[(index+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length];renderWorkspace();$('#tab-'+activeTab).focus();
});
$('#account-search').addEventListener('input',renderAccounts);
$('#scenario').addEventListener('change',async e=>{scenario=e.target.value;render();await runAutomatic();});
$('.page-heading').after($('.demo-toolbar'));
render();
if(memoryOnly)setTimeout(()=>toast('本地演示记录不可读取，已载入初始示例。'),300);
globalThis.quantDemo = {getState:()=>JSON.parse(JSON.stringify(state)),getScenario:()=>scenario};
