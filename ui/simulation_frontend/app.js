'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = (value, digits = 2) => (value == null || !Number.isFinite(Number(value))) ? '—' : Number(value).toLocaleString('zh-CN', {minimumFractionDigits:digits,maximumFractionDigits:digits});
const money = value => value == null ? '—' : '¥' + number(value);
const signed = value => value == null ? '—' : (value > 0 ? '+' : value < 0 ? '−' : '') + number(Math.abs(value));
const round = value => Math.round((value + Number.EPSILON) * 100) / 100;
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
let ASSETS = {}, navigationOnly = false;
const STRATEGIES = {
  erp:{name:'红利低波 ERP 择时',short:'红利低波 ERP',tag:'估值择时',desc:'根据股债利差 ERP 的历史分位，在不同估值区间调整红利低波 ETF 仓位；剩余资金可选现金或十年国债 ETF（511260）。',icon:'chart-dots-3'},
  compound:{name:'复合攻守轮动',short:'复合攻守轮动',tag:'动量+估值防守',desc:'动量突破负责进攻，结合红利低波与国债 ETF 做动态防守，适合按复合攻守轮动逻辑观察和执行。',icon:'chart-arrows-vertical'},
  rotation:{name:'攻守动量轮动',short:'攻守动量轮动',tag:'双资产轮动',desc:'比较进攻与防守标的的动量，结合进攻标的均线，决定持有哪一只 ETF。',icon:'switch-horizontal'}
};

let state = {accounts:[],selected:null}, activeTab='overview', toastTimer, drawerKind='', drawerAccount=null;
let lastFocus=null, drawerRevision=null, pending=null, queuedNavigation=null, lastResponse=null, market={}, worker={}, refreshing=false;
const uid=()=>crypto.randomUUID();
const config=type=>type==='erp'?{low:20,high:35,lowWeight:0,midWeight:50,highWeight:100,defense:"cash"}:type==='compound'?{attack:'sz159915',divDefense:'sh512890',bondDefense:'sh511260',lookback:20,executionMode:'next_open',useBias:true,useTrend:true,overheat:20,neutral:35}:{attack:'sh588380',defense:'sh511010',lookback:20};
const current=()=>state.accounts.find(a=>a.id===state.selected)||state.accounts[0];
const total=a=>a.portfolio.total;
const equity=a=>a.portfolio.market_value;
const positionWeight=a=>a.portfolio.weight==null?null:a.portfolio.weight*100;
const plan=a=>a.plan;
const bridge=(type,data={})=>parent.postMessage({isStreamlitMessage:true,type,...data},'*');
function send(action,data={}){
 if(pending){if(action==='navigate')queuedNavigation={action,data};return;}
 pending={requestId:uid(),action,...data};
 document.body.classList.add('request-pending');
 $$('#drawer button[type="submit"], [data-action="execute"]').forEach(b=>b.disabled=true);
 bridge('streamlit:setComponentValue',{value:pending,dataType:'json'});
}
function toast(message){clearTimeout(toastTimer);$('#toast').innerHTML=icon('circle-check')+`<span>${esc(message)}</span>`;$('#toast').hidden=false;toastTimer=setTimeout(()=>$('#toast').hidden=true,4300);}
function mountIcons(root=document){root.querySelectorAll('[data-icon]').forEach(el=>{el.innerHTML=icon(el.dataset.icon);});}
function renderAccounts(){
  const q=$('#account-search').value.trim().toLowerCase();
  const list=state.accounts.filter(a=>(a.name+' '+STRATEGIES[a.strategy].name).toLowerCase().includes(q));
  const isAfter=Boolean(market.is_after_close||market.label==='盘后复核'||market.label==='休市');
  $('#account-count').textContent=state.accounts.length;
  $('#nav-count').textContent=state.accounts.length;
  $('#all-assets').innerHTML=`全部账户资产<b class="num">${money(state.accounts.some(a=>total(a)==null)?null:state.accounts.reduce((s,a)=>s+total(a),0))}</b>`;
  $('#account-list').innerHTML=list.length?list.map(a=>{
    const p=plan(a),selected=a.id===state.selected;
    const targetSymbol=p.target?.symbol;
    const targetName=ASSETS[targetSymbol]?.name||p.target?.name||targetSymbol||'—';
    const targetWeight=p.target?.weight!=null?number(p.target.weight,0)+'%':'—';
    const pendingCount=p.orders?.length||0;
    const tomorrowBrief=a.strategy==='erp'&&a.config?.defense!=='sh511260'&&p.target?.weight===0?'现金 100%':`${targetName} ${targetWeight}`;
    return `<button class="account-card${selected?' selected':''}" data-account="${esc(a.id)}" aria-pressed="${selected}"><div class="account-card-head"><span>${esc(a.name)}</span><span class="status-dot ${a.running?'running':''}" aria-label="${a.running?'运行中':'已暂停'}"></span></div><div class="account-strategy">${STRATEGIES[a.strategy].short} · ${a.auto?(a.config.executionMode==='next_open'?'次日开盘自动':'尾盘自动'):'手动执行'}</div><div class="account-tomorrow-pill"><span class="pill-label">${isAfter?'明日目标':'当前目标'}</span><strong class="pill-target">${esc(tomorrowBrief)}</strong></div><div class="account-card-bottom"><span class="account-card-asset num">${money(total(a))}</span><span class="mini-badge ${pendingCount&&a.running?'pending':''}">${!a.running?'已暂停':p.insufficient?'待补充资金':p.error?'信号待更新':pendingCount?(isAfter?`明日待调仓 ${pendingCount} 笔`:`${pendingCount} 笔待调仓`):(isAfter?'明日持仓对齐':'持仓已对齐')}</span></div></button>`;
  }).join(''):`<div class="list-empty">没有找到“${esc($('#account-search').value)}”。试试其他账户名称或策略名称。</div>`;
}

function renderDataSync(){
 const job=worker.pipeline||{},busy=job.syncing||pending?.action==='sync-data';
 $('#data-asof').textContent=job.data_asof?`回测数据截至 ${job.data_asof}`:'回测数据待同步';
 $('#data-sync-message').textContent=busy?`正在同步历史数据${job.target?' · 目标 '+job.target:''}，完成后更新回测结束日期。`:job.message||'同步历史日线、指数估值与国债利率。';
 const button=$('[data-action="sync-data"]');button.disabled=busy||!!pending;
 button.innerHTML=icon('download')+`<span${busy?' class="inline-loading"':''}>${busy?'正在同步…':'同步回测数据'}</span>`;
}
function render(){const filter=$('#trade-filter')?.value;renderAccounts();renderWorkspace();renderDataSync();if(filter&&$('#trade-filter')){$('#trade-filter').value=filter;$('#trade-table').innerHTML=tradeTable(current(),filter);}mountIcons();$('#worker-state').textContent=(worker.pipeline?.status||'后台任务未启动')+' · 查看任务状态';}
function renderWorkspace(){
  const a=current();
 if(!a){$('#workspace').innerHTML=empty('还没有模拟账户','点击右上角「新增模拟账户」，选择策略和初始资金即可开始。','wallet');return;}
 const value=total(a),pnl=a.portfolio.pnl,ret=a.netCapital>0&&pnl!=null?pnl/a.netCapital*100:null,p=plan(a);
  $('#workspace').innerHTML=`
    <div class="account-header"><div><div class="account-title-line"><h2>${esc(a.name)}</h2><span class="chip ${a.running?'green':''}"><span class="status-dot ${a.running?'running':''}"></span>${a.running?'运行中':'已暂停'}</span><span class="chip">${a.auto?(a.config.executionMode==='next_open'?'次日开盘自动':'尾盘自动'):'手动执行'}</span></div><div class="account-id"><span>${esc(a.id)}</span><span>·</span><span>创建于 ${esc(a.created)}</span><span>·</span><span>${STRATEGIES[a.strategy].name}</span></div></div><div class="account-actions"><button class="button compact" data-action="funds">${icon('arrows-transfer-up')}资金管理</button></div></div>
    <div class="metrics" aria-label="账户资产概览"><div class="metric"><label>总资产（元）</label><div class="metric-value num">${number(value)}</div><div class="metric-sub">初始资金 ${money(a.initial)}</div></div><div class="metric"><label>累计收益 / 收益率</label><div class="metric-value num ${pnl>0?'positive':pnl<0?'negative':''}">${signed(pnl)}</div><div class="metric-sub num ${pnl>0?'positive':pnl<0?'negative':''}">${signed(ret)}% <span class="muted">· 已剔除出入金</span></div></div><div class="metric"><label>可用资金（元）</label><div class="metric-value num">${number(a.cash)}</div><div class="metric-sub">可用于模拟调仓</div></div><div class="metric"><label>持仓市值（元）</label><div class="metric-value num">${number(equity(a))}</div><div class="metric-sub">${a.positions.filter(p=>p.shares>0).length} 只 ETF</div></div><div class="metric"><label>当前仓位</label><div class="metric-value num">${number(positionWeight(a),1)}<small>%</small></div><div class="weight-track"><span style="width:${Math.min(100,positionWeight(a))}%"></span></div></div></div>
    <div class="tabs" role="tablist" aria-label="账户内容">${[['overview','账户总览'],['trades','成交记录'],['funds','资金流水'],['events','运行记录'],['config','策略与设置']].map(([id,label])=>`<button class="tab${activeTab===id?' selected':''}" role="tab" id="tab-${id}" aria-controls="tab-panel" aria-selected="${activeTab===id}" tabindex="${activeTab===id?'0':'-1'}" data-tab="${id}">${label}${id==='trades'&&a.trades.length?`<span class="tab-count">${a.trades.length}</span>`:''}</button>`).join('')}</div>
    <div id="tab-panel" class="tab-content${refreshing?' loading-surface':''}" role="tabpanel" aria-labelledby="tab-${activeTab}" aria-busy="${refreshing}">${activeTab==='overview'?overview(a,p):activeTab==='trades'?trades(a):activeTab==='funds'?funds(a):activeTab==='events'?events(a):settingsPreview(a)}</div>`;
}
function trades(a){
  const old=a.legacyOpening;
  const opening=old?`<section class="notice amber"><strong>历史建仓资料 · 旧账户持仓快照</strong><p>快照时间：${esc(old.asof)}（不是买入时间）。${esc(old.note)}</p><p>${old.positions.map(p=>`${esc(ASSETS[p.symbol]?.name||p.symbol)}（${esc(p.symbol.toUpperCase())}）：${number(p.shares,0)} 份`).join('；')}；当时现金 ${money(old.cash)}。</p><p>下方及 CSV 仅列已保存的成交回报，历史快照不计入成交笔数。</p></section>`:'';
  return `<div class="record-heading"><div><h3>成交记录</h3><p>每次模拟调仓的买卖明细，按成交时间倒序。</p></div><div class="record-tools"><select id="trade-filter" class="small-select" aria-label="筛选成交方向"><option value="all">全部方向</option><option value="买入">买入</option><option value="卖出">卖出</option></select><button class="button compact" data-action="export-trades" ${a.trades.length?'':'disabled'}>${icon('download')}导出 CSV</button></div></div>${opening}<div id="trade-table">${tradeTable(a,'all')}</div>`;
}
function tradeTable(a,filter){
  const rows=a.trades.filter(t=>filter==='all'||t.action===filter);
  return rows.length?`<div class="table-scroll"><table class="ledger-table"><thead><tr><th>成交时间</th><th>标的 / 代码</th><th>方向</th><th class="right">数量（份）</th><th class="right">成交价</th><th class="right">金额（元）</th><th class="right">费用</th><th>方式</th></tr></thead><tbody>${rows.map(t=>`<tr><td class="num">${esc(t.time)}</td><td><b>${(ASSETS[t.symbol]?.name||t.symbol)}</b><small>${esc(t.symbol.toUpperCase())}</small></td><td class="${t.action==='买入'?'positive':'negative'}">${esc(t.action)}</td><td class="right num">${number(t.shares,0)}</td><td class="right num">${number(t.price,3)}</td><td class="right num">${number(t.amount)}</td><td class="right num">${number(t.fee)}</td><td>${esc(t.source)}</td></tr>`).join('')}</tbody></table></div><div class="table-footer">共 ${rows.length} 笔 · 参考价模拟成交</div>`:empty('还没有成交记录',filter==='all'?'在账户总览执行一次模拟调仓，成交明细会出现在这里。':'当前筛选条件下没有成交记录。','receipt');
}
function funds(a){return `<div class="record-heading"><div><h3>资金流水</h3><p>记录初始资金与出入金；出入金不会被计作策略收益。</p></div><button class="button compact" data-action="funds">${icon('plus')}出入金</button></div><div class="table-scroll"><table class="ledger-table"><thead><tr><th>时间</th><th>类型</th><th class="right">变动金额（元）</th><th class="right">变动后现金（元）</th><th>状态</th></tr></thead><tbody>${a.funds.map(f=>`<tr><td class="num">${esc(f.time)}</td><td>${esc(f.type)}</td><td class="right num ${f.amount>0?'positive':'negative'}">${signed(f.amount)}</td><td class="right num">${number(f.balance)}</td><td><span class="chip green">已入账</span></td></tr>`).join('')}</tbody></table></div><div class="table-footer">净投入 ${money(a.netCapital)} · 可用资金 ${money(a.cash)}</div>`;}
function events(a){return `<div class="record-heading"><div><h3>运行记录</h3><p>保留策略变更、运行状态和调仓执行结果。</p></div><span class="chip">${a.events.length} 条记录</span></div><div class="event-list">${a.events.map(e=>`<div class="event-item"><time class="num">${esc(e.time)}</time><div><b>${esc(e.title)}</b><p>${esc(e.detail)}</p></div><span class="chip ${e.status==='已完成'?'green':e.status==='受阻'?'amber':'blue'}">${esc(e.status)}</span></div>`).join('')}</div>`;}
function settingsPreview(a){return `<div class="record-heading"><div><h3>账户与策略配置</h3><p>配置独立保存于当前账户，切换账户后自动带出。</p></div><button class="button compact" data-action="settings">${icon('edit')}编辑配置</button></div><div class="setting-preview"><section><h3>账户信息</h3><div class="settings-list">${settingLine('账户名称',a.name)}${settingLine('初始资金',money(a.initial))}${settingLine('净投入资金',money(a.netCapital))}${settingLine('执行方式',a.auto?(a.config.executionMode==='next_open'?'次日开盘自动调仓':'尾盘自动模拟调仓'):'手动执行')}${settingLine('运行状态',a.running?'运行中':'已暂停')}</div></section><section><h3>策略配置</h3><div class="settings-list">${settingLine('绑定策略',STRATEGIES[a.strategy].name)}${a.strategy==='erp'?settingLine('防守资产',a.config.defense==='sh511260'?'十年国债 ETF（511260.SH）':'现金（不计息）')+settingLine('ERP 分位阈值',`${a.config.low}% / ${a.config.high}%`)+settingLine('高估 / 常态 / 低估仓位',`${a.config.lowWeight}% / ${a.config.midWeight}% / ${a.config.highWeight}%`):a.strategy==='compound'?settingLine('进攻标的',ASSETS[a.config.attack]?.name||a.config.attack)+settingLine('防守底仓',ASSETS[a.config.divDefense||'sh512890']?.name||'红利低波 ETF')+settingLine('避险防守',ASSETS[a.config.bondDefense||'sh511260']?.name||'十年国债 ETF')+settingLine('动量周期',a.config.lookback+' 日')+settingLine('ERP 防守阈值',`${a.config.overheat||20}% / ${a.config.neutral||35}%`)+settingLine('超买止盈与生命线',`${a.config.useBias!==false?'已开启':'关闭'} / ${a.config.useTrend!==false?'已开启':'关闭'}`):settingLine('进攻标的',ASSETS[a.config.attack]?.name||a.config.attack)+settingLine('防守标的',ASSETS[a.config.defense]?.name||a.config.defense)+settingLine('观察周期',a.config.lookback+' 日')}${settingLine('执行窗口',a.config.executionMode==='next_open'?'09:30–09:35':'14:45–14:55')}${settingLine('模拟佣金',`单边万 ${number(a.feeRate*10000,1)}，无最低收费`)}</div></section></div><div class="settings-actions"><button class="button" data-action="pause">${icon(a.running?'player-pause':'player-play')}${a.running?'暂停账户运行':'恢复账户运行'}</button><button class="button" data-action="funds">${icon('arrows-transfer-up')}管理资金</button></div><p class="settings-note">更换策略只更新目标与调仓清单，已有持仓会保留。<br>自动模拟由独立本地进程运行，需要电脑保持运行。关闭浏览器不影响已启动进程；电脑休眠时会暂停检查。</p>`;}
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
const options=(symbols,selected)=>symbols.map(symbol=>`<option value="${symbol}" ${selected===symbol?'selected':''}>${ASSETS[symbol]?.name||symbol} · ${symbol.slice(2)}</option>`).join('');
function parameterFields(type,c){
  if(type==='erp'){
    return `<div class="field"><label for="execution-mode">策略执行时点</label><select id="execution-mode" name="executionMode"><option value="tail" ${c.executionMode!=='next_open'?'selected':''}>尾盘实时信号 · 14:45–14:55</option><option value="next_open" ${c.executionMode==='next_open'?'selected':''}>前日收盘信号 · 次日开盘价</option></select><span class="field-help">开盘模式在 09:30–09:35 按当天开盘价模拟；错过不补单。</span></div><div class="field"><label for="erp-defense">防守资产</label><select id="erp-defense" name="defense"><option value="cash" ${c.defense!=='sh511260'?'selected':''}>现金（不计息）</option><option value="sh511260" ${c.defense==='sh511260'?'selected':''}>十年国债 ETF（511260.SH）</option></select><span class="field-help">红利目标仓位以外的资金用于防守；保存后更新调仓清单，按现有执行窗口成交。</span></div><div class="field-pair"><div class="field"><label for="erp-low">高估区间分位上限（%）</label><input id="erp-low" name="low" type="number" min="0" max="100" step="0.1" value="${c.low}"></div><div class="field"><label for="erp-high">低估区间分位下限（%）</label><input id="erp-high" name="high" type="number" min="0" max="100" step="0.1" value="${c.high}"></div></div><div class="field-pair"><div class="field"><label for="low-weight">高估仓位（%）</label><input id="low-weight" name="lowWeight" type="number" min="0" max="100" value="${c.lowWeight}"></div><div class="field"><label for="mid-weight">常态仓位（%）</label><input id="mid-weight" name="midWeight" type="number" min="0" max="100" value="${c.midWeight}"></div></div><div class="field"><label for="high-weight">低估仓位（%）</label><input id="high-weight" name="highWeight" type="number" min="0" max="100" value="${c.highWeight}"></div><div class="field-error" id="parameter-error" role="alert"></div>`;
  }
  if(type==='compound'){
    return `<div class="field"><label for="attack">进攻标的</label><select id="attack" name="attack">${options(['sz159915','sh588380','sh588000','sh510300','sh510500'],c.attack||'sz159915')}</select><span class="field-help">成长/弹性宽基；负责动量突破与超买锁利。</span></div><div class="field-pair"><div class="field"><label for="div-defense">防守底仓标的</label><select id="div-defense" name="divDefense">${options(['sh512890','sh510880'],c.divDefense||'sh512890')}</select><span class="field-help">ERP 估值低吸配置</span></div><div class="field"><label for="bond-defense">避险防守标的</label><select id="bond-defense" name="bondDefense">${options(['sh511260','sh511010','sh511090'],c.bondDefense||'sh511260')}</select><span class="field-help">ERP 估值过热避险</span></div></div><div class="field-pair"><div class="field"><label for="lookback">动量观察周期（交易日）</label><input id="lookback" name="lookback" type="number" min="5" max="120" step="1" value="${c.lookback||20}"></div><div class="field"><label for="execution-mode">策略执行时点</label><select id="execution-mode" name="executionMode"><option value="next_open" ${c.executionMode==='next_open'?'selected':''}>前日收盘信号 · 次日开盘价</option><option value="tail" ${c.executionMode==='tail'?'selected':''}>当日尾盘实时信号 (14:45–14:55)</option></select></div></div><details class="fee-settings" open><summary>复合轮动优化参数（阶梯超买止盈、生命线过滤与 ERP 阈值）</summary><div class="field-pair" style="margin-top:8px;"><div class="field"><label for="overheat">ERP 过热高抛阈值（%）</label><input id="overheat" name="overheat" type="number" min="5" max="40" step="1" value="${c.overheat||20}"><span class="field-help">低于此分位全配国债避险</span></div><div class="field"><label for="neutral">ERP 低吸满仓阈值（%）</label><input id="neutral" name="neutral" type="number" min="15" max="60" step="1" value="${c.neutral||35}"><span class="field-help">高于此分位满配红利底仓</span></div></div><div class="field-row" style="margin-top:10px;"><div><b>BIAS 极值五档超买止盈</b><small>偏离率达 15%/18%/21%/25% 阶梯减速，防守资金转入 ERP</small></div><label class="switch"><input type="checkbox" id="use-bias" name="useBias" ${c.useBias!==false?'checked':''} aria-label="启用极值超买止盈"><span></span></label></div><div class="field-row" style="margin-top:8px;"><div><b>MA60 中长期生命线过滤</b><small>要求价格站上 60 日均线方可进攻，杜绝熊市假突破磨损</small></div><label class="switch"><input type="checkbox" id="use-trend" name="useTrend" ${c.useTrend!==false?'checked':''} aria-label="启用 MA60 趋势过滤"><span></span></label></div></details><div class="field-error" id="parameter-error" role="alert"></div>`;
  }
  return `<div class="field"><label for="attack">进攻标的</label><select id="attack" name="attack">${options(['sh588380','sz159915','sh588000'],c.attack)}</select></div><div class="field"><label for="defense">防守标的</label><select id="defense" name="defense">${options(['sh511010','sh511260','sh512890'],c.defense)}</select></div><div class="field"><label for="lookback">动量观察周期（交易日）</label><input id="lookback" name="lookback" type="number" min="5" max="120" step="1" value="${c.lookback}"><span class="field-help">5–120 个交易日；根据实际历史数据与行情计算。</span></div><div class="field-error" id="parameter-error" role="alert"></div>`;
}
function accountForm(mode='create',preferred='rotation',beforeExecution=false){
  const editing=mode==='settings',a=editing?current():null,type=a?.strategy||preferred,c=a?.config||config(type);drawerAccount=a?.id||null;drawerRevision=a?.revision||null;
  openDrawer(editing?(beforeExecution?'执行前调整策略':'账户设置'):'新增模拟账户',editing?(beforeExecution?'保存为此账户的后续配置，并重新生成调仓清单。':'修改仅作用于当前账户，已有持仓会保留。'):'填写名称和金额，选择策略后即可创建。默认手动执行。',`<form id="account-form" class="drawer-form" novalidate><div class="form-content"><section class="form-section"><div class="form-section-title">基本信息</div><div class="field"><label for="account-name">账户名称</label><input id="account-name" name="name" value="${esc(a?.name||'')}" maxlength="30" placeholder="例如：红利稳健 02" autocomplete="off" aria-describedby="name-error" autofocus><div id="name-error" class="field-error" role="alert"></div></div>${!editing?`<div class="field"><label for="initial-capital">初始模拟资金</label><div class="input-unit"><input id="initial-capital" name="capital" type="number" min="1000" max="1000000000" step="0.01" value="100000" aria-describedby="capital-error"><span>元</span></div><div class="presets" aria-label="常用金额">${[50000,100000,200000,500000].map(v=>`<button type="button" data-preset="${v}" class="${v===100000?'selected':''}">${v/10000} 万</button>`).join('')}</div><span class="field-help">支持 1,000–1,000,000,000 元，后续可单独出入金。</span><div id="capital-error" class="field-error" role="alert"></div></div>`:`<div class="notice">初始资金 ${money(a.initial)} · 当前总资产 ${money(total(a))}<br>追加或取出资金，请使用账户首页的「资金管理」。</div>`}</section><section class="form-section"><div class="form-section-title">选择策略<small>选择下方一种，参数可直接调整</small></div>${strategyChoices(type)}<div id="parameter-fields" class="parameter-fields">${parameterFields(type,c)}</div></section><section class="form-section"><details class="fee-settings"><summary>交易费用 · 单边万 ${number(a?a.feeRate*10000:1,1)}，可调整</summary><div class="field"><label for="fee-rate">单边模拟佣金（万分之）</label><input id="fee-rate" name="fee" type="number" min="0" max="100" step="0.1" value="${a?a.feeRate*10000:1}"><span class="field-help">ETF 免印花税；无最低佣金，不模拟滑点或部分成交。</span><div id="fee-error" class="field-error" role="alert"></div></div></details><div class="form-section-title">执行方式</div><div class="field-row"><div><b>自动模拟调仓</b><small>默认手动；可开启交易日自动模拟调仓</small></div><label class="switch"><input type="checkbox" id="auto-trade" name="auto" ${a?.auto?'checked':''} aria-label="尾盘自动模拟调仓"><span></span></label></div><p class="field-help">后台进程独立检查，需要电脑保持运行。行情异常、休市或账户暂停时不会执行。</p></section>${editing?`<p class="notice amber">保存策略后会重新生成调仓清单；已有持仓不会自动重置。请回到账户总览核对差额后执行。${a?.auto?'已开启自动调仓，后续自动任务也会使用新参数。':''}</p>`:''}</div><footer class="form-footer"><span class="footer-hint">账户配置独立保存</span><button type="button" class="button" data-action="close">取消</button><button type="submit" class="button primary">${editing?(beforeExecution?'保存并更新清单':'保存设置'):'创建账户'}</button></footer></form>`,mode);
  if(beforeExecution){$('#parameter-fields').scrollIntoView({block:'center'});$('#parameter-fields input, #parameter-fields select')?.focus({preventScroll:true});}
  const drafts={[type]:{...c}};
  let previous=type;
  $$('input[name="strategy"]').forEach(r=>r.addEventListener('change',()=>{
    drafts[previous]=readConfig(previous,new FormData($('#account-form')));
    previous=r.value;$('#parameter-fields').innerHTML=parameterFields(r.value,drafts[r.value]||config(r.value));
  }));
  $('#account-form').addEventListener('submit',e=>{e.preventDefault();saveAccountForm(editing);});
}
function readConfig(type,fd){
  if(type==='erp'){
    return {...Object.fromEntries(['low','high','lowWeight','midWeight','highWeight'].map(k=>[k,Number(fd.get(k))])),defense:fd.get('defense')||'cash',executionMode:fd.get('executionMode')||'tail'};
  }
  if(type==='compound'){
    return {
      attack: fd.get('attack'),
      divDefense: fd.get('divDefense')||'sh512890',
      bondDefense: fd.get('bondDefense')||'sh511260',
      lookback: Number(fd.get('lookback')),
      executionMode: fd.get('executionMode')||'next_open',
      useBias: fd.get('useBias')==='on',
      useTrend: fd.get('useTrend')==='on',
      overheat: Number(fd.get('overheat')||20),
      neutral: Number(fd.get('neutral')||35)
    };
  }
  return {attack:fd.get('attack'),defense:fd.get('defense'),lookback:Number(fd.get('lookback'))};
}
function fieldError(id,message,input){input?.closest('details')?.setAttribute('open','');$('#'+id).textContent=message;if(input){input.setAttribute('aria-invalid','true');input.focus();}}
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
  if(type==='compound'&&c.overheat>=c.neutral){fieldError('parameter-error','ERP 过热高抛阈值必须小于低吸满仓阈值。',$('#overheat'));return;}

  const fee=Number(fd.get('fee'));
  if(!Number.isFinite(fee)||fee<0||fee>100){fieldError('fee-error','佣金须在万 0–万 100 之间。',$('#fee-rate'));return;}
  send(editing?'configure':'create',{accountId:drawerAccount,revision:drawerRevision,name,strategy:type,config:c,capital,auto:fd.get('auto')==='on',feeRate:fee/10000});
}
function fundsForm(){
  const a=current();drawerAccount=a.id;drawerRevision=a.revision;
  openDrawer('资金管理',`${a.name} · 出入金与策略收益分别记录。`,`<form id="fund-form" class="drawer-form" novalidate><div class="form-content"><div class="fund-switch" role="group" aria-label="资金操作"><button type="button" class="selected" data-fund-mode="deposit" aria-pressed="true">模拟入金</button><button type="button" data-fund-mode="withdraw" aria-pressed="false">模拟出金</button></div><input type="hidden" name="mode" value="deposit"><div class="fund-balance"><span>当前可用资金</span><b class="num">${money(a.cash)}</b></div><div class="field"><label for="fund-amount" id="fund-label">入金金额</label><div class="input-unit"><input id="fund-amount" name="amount" type="number" min="0.01" max="1000000000" step="0.01" value="10000" aria-describedby="fund-error" autofocus><span>元</span></div><div class="presets">${[10000,50000,100000].map(v=>`<button type="button" data-fund-preset="${v}" class="${v===10000?'selected':''}">${v/10000} 万</button>`).join('')}</div><div id="fund-error" class="field-error" role="alert"></div></div><p class="notice" id="fund-notice">入金后，可用资金与净投入同步增加，累计收益金额不变。策略会根据新的总资产重新生成清单。</p><div id="fund-preview" class="fund-preview"></div></div><footer class="form-footer"><button type="button" class="button" data-action="close">取消</button><button type="submit" class="button primary" id="fund-submit">确认入金</button></footer></form>`,'funds');
  $('#fund-form').addEventListener('submit',e=>{e.preventDefault();saveFundForm();});
  $('#fund-amount').addEventListener('input',updateFundPreview);updateFundPreview();
}
function updateFundPreview(){
  const a=state.accounts.find(x=>x.id===drawerAccount),amount=Number($('#fund-amount').value)||0,deposit=$('#fund-form [name="mode"]').value==='deposit',delta=deposit?amount:-amount;
  $('#fund-preview').innerHTML=`<div><span>操作后可用资金</span><b class="num">${money(a.cash+delta)}</b></div><div><span>操作后净投入</span><b class="num">${money(a.netCapital+delta)}</b></div><div><span>累计收益金额</span><b class="num">${signed(a.portfolio.pnl)} 元 · 不受出入金影响</b></div>`;
}
function saveFundForm(){
  const a=state.accounts.find(x=>x.id===drawerAccount),amount=Number($('#fund-amount').value),deposit=$('#fund-form [name="mode"]').value==='deposit';
  $('#fund-error').textContent='';$('#fund-amount').removeAttribute('aria-invalid');
  if(!Number.isFinite(amount)||amount<=0||amount>1e9||Math.abs(amount-round(amount))>1e-6){fieldError('fund-error','请输入 0.01–1,000,000,000 元的金额，最多两位小数。',$('#fund-amount'));return;}
  if(!deposit&&amount>a.cash){fieldError('fund-error',`出金金额超过可用资金 ${money(a.cash)}。如需取出持仓资金，请先完成卖出。`,$('#fund-amount'));return;}

  send('funds',{accountId:a.id,revision:drawerRevision,amount,withdraw:!deposit});
}

function exportTrades(){
  const a=current(),filter=$('#trade-filter')?.value||'all',rows=a.trades.filter(t=>filter==='all'||t.action===filter),safe=v=>{const t=String(v??'');return '"'+(/^[=+@-]/.test(t)?"'":'')+t.replace(/"/g,'""')+'"';};
  const lines=[['账户','成交时间','标的','代码','方向','数量(份)','成交价','金额(元)','费用(元)','方式'],...rows.map(t=>[a.name,t.time,ASSETS[t.symbol].name,t.symbol,t.action,t.shares,t.price,t.amount,t.fee,t.source])];
  const blob=new Blob(['\uFEFF'+lines.map(row=>row.map(safe).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=`${a.name.replace(/[\\/:*?"<>|]/g,'_')}_模拟成交记录.csv`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(`已导出 ${rows.length} 笔模拟成交记录。`);
}
document.addEventListener('click',async e=>{
  if(navigationOnly){
    const target=e.target.closest('[data-research], [data-action="home"]');
    if(target){e.preventDefault();pending=null;send('navigate',{mode:target.dataset.research||'模拟账户'});}
    return;
  }
  const earlyResearch=e.target.closest('[data-research]');if(earlyResearch){send('navigate',{mode:earlyResearch.dataset.research});return;}
  if(pending&&e.target.closest('[data-action], [data-account], [data-research], [data-create-strategy]'))return;
  const accountButton=e.target.closest('[data-account]');
  if(accountButton){state.selected=accountButton.dataset.account;activeTab='overview';render();send('select',{accountId:state.selected});return;}
  const research=e.target.closest('[data-research]');if(research){send('navigate',{mode:research.dataset.research});return;}
  const tab=e.target.closest('[data-tab]');if(tab){activeTab=tab.dataset.tab;renderWorkspace();$('#tab-'+activeTab)?.focus();return;}
  const preset=e.target.closest('[data-preset]');if(preset){$('#initial-capital').value=preset.dataset.preset;$$('[data-preset]').forEach(b=>b.classList.toggle('selected',b===preset));return;}
  const fundPreset=e.target.closest('[data-fund-preset]');if(fundPreset){$('#fund-amount').value=fundPreset.dataset.fundPreset;$$('[data-fund-preset]').forEach(b=>b.classList.toggle('selected',b===fundPreset));updateFundPreview();return;}
  const fundMode=e.target.closest('[data-fund-mode]');if(fundMode){const deposit=fundMode.dataset.fundMode==='deposit';$('#fund-form [name="mode"]').value=fundMode.dataset.fundMode;$$('[data-fund-mode]').forEach(b=>{b.classList.toggle('selected',b===fundMode);b.setAttribute('aria-pressed',String(b===fundMode));});$('#fund-label').textContent=deposit?'入金金额':'出金金额';$('#fund-submit').textContent=deposit?'确认入金':'确认出金';$('#fund-notice').textContent=deposit?'入金后，可用资金与净投入同步增加，累计收益金额不变。策略会根据新的总资产重新生成清单。':'仅可取出可用资金，不会自动卖出持仓。出金与策略收益分别记账。';$('#fund-error').textContent='';updateFundPreview();return;}
  const button=e.target.closest('[data-action]');if(!button||button.disabled)return;
  switch(button.dataset.action){
    case 'home':activeTab='overview';render();break;
    case 'create':accountForm();break;
    case 'settings':accountForm('settings');break;
    case 'execution-settings':accountForm('settings','rotation',true);break;
    case 'funds':fundsForm();break;
    case 'close':closeDrawer();break;
    case 'help':help();break;
    case 'tasks':{
      const job=worker.pipeline||{};
      openDrawer('数据与后台任务','开机补齐数据；信号预生成，执行前按实时行情复核。',`<div class="form-content"><p class="notice">${esc(job.message||'请双击启动量化研究台脚本，启动后台任务。')}</p><p>检查时间：${esc(job.heartbeat||'尚未检查')}</p><p>尾盘自动进程：${worker.alive?'运行中':'未运行'}</p>${Object.entries(job.jobs||{}).map(([name,v])=>`<div class="library-item"><h3>${esc(name)}</h3><p>${esc(v.status)} · 数据截至 ${esc(v.asof||'未知')}</p>${v.error?`<p>${esc(v.error)}</p>`:''}</div>`).join('')}<h3>账户信号</h3>${Object.entries(job.signals||{}).map(([id,v])=>`<p>${esc(id)} · ${esc(v.status)} · ${esc(v.generated_at)}${v.error?' · '+esc(v.error):''}</p>`).join('')}<p class="settings-note">预生成信号是盘中参考，不是成交承诺。休市、数据未齐或错过尾盘窗口不执行；手动账户仍需确认。</p></div>`,'tasks');break;
    }
    case 'refresh':send('refresh');break;
    case 'sync-data':send('sync-data');renderDataSync();break;
    case 'execute':{const a=current();if(a.plan.canExecute)send('execute',{accountId:a.id,planId:a.plan.id});break;}
    case 'export-trades':exportTrades();break;
    case 'pause':{const a=current();send('pause',{accountId:a.id,revision:a.revision,running:!a.running});break;}
    case 'tab-events':activeTab='events';renderWorkspace();break;

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
function erpObservations(a){
 const o=a.observation||{}, live=o.live, confirmed=o.confirmed;
 const symbols=['sh512890',a.config.defense==='sh511260'?'sh511260':null].filter(Boolean);
 const rows=symbols.map(symbol=>{const q=state.assets?.[symbol]||{}, up=Number(q.chgPct)>=0;return `<tr><td><b>${esc(q.name||symbol)}</b><small>${esc(symbol.toUpperCase())}</small></td><td class="right num">${number(q.price,3)}</td><td class="right num ${up?'positive':'negative'}">${q.chgPct==null?'—':(up?'+':'')+number(q.chgPct,2)+'%'}</td><td class="right num">${number(q.prevClose,3)}</td></tr>`}).join('');
 const card=(sig,title,note)=>`<div class="signal-compact"><div class="signal-compact-head"><h4>${title}</h4><small>${esc(note)}</small></div><div class="signal-kpis"><div><label>ERP</label><strong>${number(sig?.erp)}%</strong></div><div><label>历史分位</label><strong>${number(sig?.erp_pct*100,1)}%</strong></div><div><label>红利目标</label><strong>${number(sig?.weight*100,0)}%</strong></div></div></div>`;
 return `<div class="erp-dashboard"><div class="erp-dashboard-head"><div><h3>策略信号与执行目标</h3><p>实时预估用于盘中判断，确认信号用于自动执行。</p></div><span class="chip">${esc(o.quoteTime||'行情待更新')}</span></div><div class="quote-panel"><div class="section-heading"><h4>目标标的实时行情</h4><button class="text-button" data-action="refresh">${icon('refresh')}刷新</button></div><div class="table-scroll"><table class="holdings-table quote-table"><thead><tr><th>标的 / 代码</th><th class="right">最新价</th><th class="right">涨跌幅</th><th class="right">昨收</th></tr></thead><tbody>${rows||'<tr><td colspan="4">暂无目标行情</td></tr>'}</tbody></table></div></div><div class="signal-grid">${card(live,'盘中实时预估',`行情时间 ${o.quoteTime||'未知'}`)}${card(confirmed,'前日收盘确认',`信号日期 ${confirmed?.historical_asof||'未知'}`)}</div><div class="allocation-rule"><div class="section-heading"><h4>目标阈值与仓位</h4><button class="text-button" data-action="settings">调整${icon('chevron-right')}</button></div><div class="threshold-row"><span>ERP 分位</span><b>≤ ${number(a.config.low,0)}%</b><b>${number(a.config.low,0)}%–${number(a.config.high,0)}%</b><b>> ${number(a.config.high,0)}%</b></div><div class="threshold-row target-weights"><span>红利仓位</span><strong>${number(a.config.lowWeight,0)}%</strong><strong>${number(a.config.midWeight,0)}%</strong><strong>${number(a.config.highWeight,0)}%</strong></div><div class="defense-note">其余资金：${a.config.defense==='sh511260'?'十年国债 ETF（511260.SH）':'现金（不计息）'} · 执行：${a.config.executionMode==='next_open'?'前日确认 → 次日开盘':'盘中预估 → 尾盘执行'}</div></div></div>`;
}
function compoundObservations(a,p){
 const o=a.observation||{}, live=o.live, confirmed=o.confirmed, sig=p.signal;
 const atk=a.config.attack, div=a.config.divDefense||'sh512890', bond=a.config.bondDefense||'sh511260';
 const card=(s,title,note)=>{
  const isAtk=s?.is_attack, wAtk=s?.weights?.[atk]??0, wDiv=s?.weights?.[div]??0, wBond=s?.weights?.[bond]??0;
  let targetBrief='—';
  if(isAtk){
    targetBrief=wAtk>=1?`${esc(ASSETS[atk]?.name||atk)} 100%`:`${esc(ASSETS[atk]?.name||'进攻')} ${number(wAtk*100,0)}% + 防守 ${number((1-wAtk)*100,0)}%`;
  }else{
    if(wBond>=1) targetBrief=`${esc(ASSETS[bond]?.name||bond)} 100%`;
    else if(wDiv>=1) targetBrief=`${esc(ASSETS[div]?.name||div)} 100%`;
    else targetBrief=`${esc(ASSETS[div]?.name||'红利')} 50% · ${esc(ASSETS[bond]?.name||'国债')} 50%`;
  }
  return `<div class="signal-compact"><div class="signal-compact-head"><h4>${title}</h4><small>${esc(note)}</small></div><div class="signal-kpis"><div><label>ERP 真实值</label><strong>${number(s?.erp)}%</strong></div><div><label>历史分位</label><strong>${number(s?.erp_pct*100,1)}%</strong></div><div><label>目标配置</label><strong style="font-size:15px;">${targetBrief}</strong></div></div><div class="signal-subline" style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;padding-top:8px;border-top:1px dashed var(--line);font-size:11px;color:var(--muted);"><span>进攻动量: <b class="num ${s?.tech_mom>=0?'positive':'negative'}">${signed(s?.tech_mom*100,2)}%</b></span><span>偏离率 BIAS: <b class="num">${signed(s?.tech_bias*100,2)}%</b></span><span class="chip ${isAtk?'green':''}">${isAtk?(wAtk<1?`超买止盈 (${number(wAtk*100,0)}%)`:'全仓进攻'):'全面防守'}</span></div></div>`;
 };
 return `<div class="erp-dashboard"><div class="erp-dashboard-head"><div><h3>复合攻守策略信号与执行目标</h3><p>动量突破进攻 + 极值超买止盈 + 全局防守由 ERP 股债利差动态接管。</p></div><span class="chip">${esc(o.quoteTime||'行情待更新')}</span></div>${quotePanel(a)}<div class="signal-grid">${card(live,'盘中实时预估',`行情时间 ${o.quoteTime||'未知'}`)}${card(confirmed,'前日收盘确认',`信号日期 ${confirmed?.historical_asof||'未知'}`)}</div><div class="allocation-rule"><div class="section-heading"><h4>当前资产目标组合</h4><button class="text-button" data-action="settings">调整${icon('chevron-right')}</button></div><div class="threshold-row target-weights"><span><b>${esc(ASSETS[atk]?.name||'进攻标的')}</b>: <strong>${number((sig?.weights?.[atk]??0)*100,0)}%</strong></span><span><b>${esc(ASSETS[div]?.name||'防守底仓')}</b>: <strong>${number((sig?.weights?.[div]??0)*100,0)}%</strong></span><span><b>${esc(ASSETS[bond]?.name||'避险国债')}</b>: <strong>${number((sig?.weights?.[bond]??0)*100,0)}%</strong></span></div><div class="defense-note">观察周期：${a.config.lookback} 日 · 执行：${a.config.executionMode==='next_open'?'前日确认 → 次日开盘':'当日尾盘实时执行'} · 优化：${a.config.useBias!==false?'BIAS超买止盈':'—'} / ${a.config.useTrend!==false?'MA60生命线过滤':'—'}</div></div></div>`;
}
function quotePanel(a){
 const symbols=a.strategy==='erp'?['sh512890',a.config.defense==='sh511260'?'sh511260':null].filter(Boolean):a.strategy==='compound'?[a.config.attack,a.config.divDefense||'sh512890',a.config.bondDefense||'sh511260']:[a.config.attack,a.config.defense];
 const rows=[...new Set(symbols)].map(symbol=>{const q=state.assets?.[symbol]||{},up=Number(q.chgPct)>=0;return `<tr><td><b>${esc(q.name||symbol)}</b><small>${esc(symbol.toUpperCase())}</small></td><td class="right num">${number(q.price,3)}</td><td class="right num ${up?'positive':'negative'}">${q.chgPct==null?'—':(up?'+':'')+number(q.chgPct,2)+'%'}</td><td class="right num">${number(q.prevClose,3)}</td></tr>`}).join('');
 return `<div class="quote-panel"><div class="section-heading"><h4>目标标的实时行情</h4><button class="text-button" data-action="refresh">${icon('refresh')}刷新</button></div><div class="table-scroll"><table class="holdings-table quote-table"><thead><tr><th>标的 / 代码</th><th class="right">最新价</th><th class="right">涨跌幅</th><th class="right">昨收</th></tr></thead><tbody>${rows||'<tr><td colspan="4">暂无目标行情</td></tr>'}</tbody></table></div></div>`;
}
function overview(a,p){
 const sig=p.signal,weight=positionWeight(a),asset=ASSETS[p.target.symbol];
 const positions=a.positions.length?`<div class="table-scroll"><table class="holdings-table"><thead><tr><th>标的 / 代码</th><th class="right">持仓 / 可卖</th><th class="right">参考价</th><th class="right">市值（元）</th><th class="right" title="标的市值 ÷ 当前持仓总市值，不含现金">占总仓位</th></tr></thead><tbody>${a.positions.map(v=>`<tr><td><b>${esc(ASSETS[v.symbol]?.name||v.symbol)}</b><small>${esc(v.symbol.toUpperCase())}</small></td><td class="right num">${number(v.shares,0)}<small>可卖 ${number(v.sellable,0)}</small></td><td class="right num">${number(v.price,3)}</td><td class="right num">${number(v.value)}</td><td class="right num">${v.value!=null&&equity(a)>0?number(v.value/equity(a)*100,1)+'%':'—'}</td></tr>`).join('')}</tbody></table></div>`:`<div class="empty-state compact-empty"><div class="empty-icon">${icon('wallet')}</div><h3>资金已就位，等待首次建仓</h3><p>核对策略目标，在有效执行窗口执行模拟调仓。</p></div>`;
 const signals=!sig?`<p class="notice amber">${esc(p.error||'当前无法取得有效信号，请刷新行情重试。')}</p>`:a.strategy==='erp'?erpObservations(a):a.strategy==='compound'?compoundObservations(a,p):`${quotePanel(a)}<div class="signal-row"><div><label>进攻动量（${a.config.lookback} 日）</label><strong class="num ${sig.tech.mom>=0?'positive':'negative'}">${signed(sig.tech.mom*100)}%</strong><small>${esc(ASSETS[a.config.attack]?.name)}</small></div><div><label>防守动量（${a.config.lookback} 日）</label><strong class="num ${sig.defensive.mom>=0?'positive':'negative'}">${signed(sig.defensive.mom*100)}%</strong><small>${esc(ASSETS[a.config.defense]?.name)}</small></div><div><label>当前策略目标</label><strong>${esc(asset?.name||'—')}</strong><small>${sig.is_attack?'进攻条件全部成立':'切换至防守标的'}</small></div></div>`;
 const rules=a.strategy==='erp'?`ERP 分位 ≤ ${a.config.low}% 时，目标仓位 ${a.config.lowWeight}%；≤ ${a.config.high}% 时为 ${a.config.midWeight}%；高于 ${a.config.high}% 时为 ${a.config.highWeight}%。`:a.strategy==='compound'?`进攻动量突破且站上生命线时进攻，超买区按 BIAS 五档阶梯压降仓位；防守资金统一由策略二 ERP 股债利差接管（≤${a.config.overheat||20}% 国债 100%，${a.config.overheat||20}%~${a.config.neutral||35}% 红利 50%+国债 50%，>${a.config.neutral||35}% 红利 100%）。`:`进攻动量 > 0、进攻价格 > ${a.config.lookback} 日均线、进攻动量 > 防守动量，三者同时成立时持有进攻标的，否则切换至防守标的。`;
 return `<div class="overview-grid"><div class="left-content"><section aria-label="当前持仓"><div class="section-heading"><h3>当前持仓</h3><small>按最新取得报价估值</small></div>${positions}<div class="allocation"><span><i class="legend-dot"></i>持仓 ${number(weight,1)}%</span><div class="allocation-bar"><span style="width:${weight||0}%"></span><i></i></div><span><i class="legend-dot cash"></i>现金 ${number(weight==null?null:100-weight,1)}%</span></div></section><section class="strategy-section"><div class="section-heading"><h3>策略观察</h3><button class="text-button" data-action="settings">修改策略${icon('chevron-right')}</button></div><div class="strategy-name">${icon(STRATEGIES[a.strategy].icon)}${STRATEGIES[a.strategy].name}<span class="chip">${STRATEGIES[a.strategy].tag}</span></div><p>${STRATEGIES[a.strategy].desc}</p>${signals}<details class="rule-detail"><summary>${icon('chevron-right')}查看策略规则与参数</summary><p>${rules}<br>历史指标截至 ${esc(sig?.historical_asof||'未知')}。权益 ETF 当日买入次日可卖；国债 ETF 按 T+0 模拟。</p></details><div class="market-strip"><span class="market-state"><span class="status-dot ${market.ready?'running':''}"></span>${esc(market.full)}</span><button class="text-button" data-action="refresh">${icon('refresh')}刷新行情</button></div></section></div>${decision(a,p)}</div>`;
}
function decision(a,p){
 const isAfter=Boolean(market.is_after_close||market.label==='盘后复核'||market.label==='休市');
 const has=p.orders.length>0;
 const openOrTail=a.config.executionMode==='next_open'?'开盘':'尾盘';
 const windowTime=a.config.executionMode==='next_open'?'09:30–09:35':'14:45–14:55';
 const targetSymbol=p.target?.symbol||'';
 const targetName=ASSETS[targetSymbol]?.name||p.target?.name||targetSymbol||'—';
 const targetWeightNum=p.target?.weight!=null?round(Number(p.target.weight)):0;
 const currentWeightNum=positionWeight(a)!=null?round(Number(positionWeight(a))):0;
 const deltaWeight=round(targetWeightNum-currentWeightNum);
 const deltaText=Math.abs(deltaWeight)<0.1?'持仓对齐':(deltaWeight>0?`+${number(deltaWeight,1)}%`:`${signed(deltaWeight,1)}%`);
 const deltaClass=deltaWeight>0.1?'positive':deltaWeight<-0.1?'negative':'neutral';

 const title=!a.running?'账户已暂停运行':p.error?'暂时无法生成调仓计划':p.insufficient?'可用资金不足一手':has?(!a.positions.length?(isAfter?'准备就绪 · 明日首次建仓':'准备好，开始首次建仓'):a.strategy==='erp'?(isAfter?`建议明日调整至 ${number(p.target.weight,0)}% 仓位`:`建议调整至 ${number(p.target.weight,0)}% 仓位`):(isAfter?'策略信号切换 · 明日执行调仓':'策略信号切换，建议调仓')):a.positions.length?(isAfter?'持仓已对齐 · 明日继续持有':'持仓已对齐，继续持有'):(isAfter?'保持空仓 · 等待明日新信号':'保持空仓，等待信号');
 const description=!a.running?'配置与持仓已保留。恢复运行后，再核对当前调仓计划。':p.signal?.description||p.error||(isAfter?'盘后已完成复核，已生成次日调仓计划。':'等待有效信号后生成调仓清单。');

 let compoundWeights='';
 if(a.strategy==='compound'&&p.target?.weights){
   const atk=a.config.attack||'sz159915';
   const div=a.config.divDefense||'sh512890';
   const bond=a.config.bondDefense||'sh511260';
   const wAtk=p.target.weights[atk]??0;
   const wDiv=p.target.weights[div]??0;
   const wBond=p.target.weights[bond]??0;
   compoundWeights=`<div class="target-subweights"><div class="subweight-item ${wAtk>0?'active':''}"><small>进攻 (${esc(ASSETS[atk]?.name||'创业板')})</small><b>${number(wAtk,0)}%</b></div><div class="subweight-item ${wDiv>0?'active':''}"><small>底仓 (${esc(ASSETS[div]?.name||'红利低波')})</small><b>${number(wDiv,0)}%</b></div><div class="subweight-item ${wBond>0?'active':''}"><small>避险 (${esc(ASSETS[bond]?.name||'十年国债')})</small><b>${number(wBond,0)}%</b></div></div>`;
 }

 const targetBlock=p.signal?`<div class="tomorrow-target-card ${isAfter?'after-close-card':''}"><div class="target-card-header"><span class="target-badge">${isAfter?'明日目标标的与仓位':'策略当前目标'}</span><span class="target-date">${isAfter?(market.next_session?`下一交易日 (${market.next_session})`:'明日交易日'):'今日盘中'}</span></div><div class="target-main-row"><div class="target-asset-cell"><label>${isAfter?'明日目标标的':'目标标的'}</label><div class="asset-title-group"><strong class="asset-name">${esc(targetName)}</strong><span class="code-chip">${esc(targetSymbol.toUpperCase())}</span></div></div><div class="target-weight-cell"><label>${isAfter?'明日目标仓位':'目标仓位'}</label><div class="target-weight-num num">${number(targetWeightNum,0)}%</div></div></div><div class="target-compare-bar"><div class="compare-labels"><span>当前持仓 <strong>${number(currentWeightNum,1)}%</strong></span><span class="compare-arrow">${icon('arrow-right')}</span><span>${isAfter?'明日目标':'策略目标'} <strong>${number(targetWeightNum,0)}%</strong></span><span class="delta-chip ${deltaClass}">${esc(deltaText)}</span></div><div class="mini-track"><span class="target-fill" style="width:${Math.min(100,Math.max(0,targetWeightNum))}%"></span></div></div>${compoundWeights}</div>`:'';

 const ordersBlock=has?`<div class="plan-orders"><div class="plan-orders-heading"><span>${isAfter?'明日计划调仓委托':'待执行调仓委托'}</span><small>${p.orders.length} 笔 · 参考收盘价估算</small></div>${p.orders.map(o=>`<div class="plan-order"><span class="order-direction ${o.action==='卖出'?'sell':''}">${esc(o.action)}</span><div class="order-info"><b>${esc(o.name)}</b><small>${number(o.shares,0)} 份 × ${number(o.price,3)}</small><small class="order-status-chip">${esc(o.status)}</small></div><div class="order-amount num">${money(o.amount)}<small>费用 ${money(o.fee)}</small></div></div>`).join('')}</div><div class="fee-summary"><span>预计费用 ${money(p.fees)}</span><span>成交后现金 ${money(p.remaining)}</span></div>`:!p.error?`<div class="no-trade tomorrow-no-trade">${icon('circle-check')}<div><b>${isAfter?'明日持仓已对齐，无需调仓':'当前没有待执行委托'}</b><p>${isAfter?`持仓与策略目标完全对齐，明日继续持有 ${esc(targetName)}（${number(targetWeightNum,0)}% 仓位）。`:'后续信号变化时会生成新的调仓清单。'}</p></div></div>`:'';

 const canExecute=!isAfter&&p.canExecute&&!pending;
 const executeBtnText=pending?.action==='execute'?'正在校验并模拟撮合…':!a.running?'恢复运行后可执行':p.error?'等待有效行情':isAfter?(a.auto?`已开启明日${openOrTail}自动调仓 (${windowTime})`:`等待明日${openOrTail}执行 (${windowTime})`):!has?'当前无需调仓':p.canExecute?`执行模拟调仓 · ${p.orders.length} 笔`:market.label==='休市'?'休市，暂不可执行':'执行条件尚未满足';

 return `<aside class="decision-panel ${isAfter?'after-close':''}" aria-label="${isAfter?'明日调仓计划':'今日调仓'}"><div class="section-heading"><div class="heading-group"><h3>${isAfter?'明日调仓计划':'今日调仓'}</h3><span class="chip ${isAfter?'blue':'green'}">${isAfter?'盘后已确认':'实时监控'}</span></div><span class="decision-time">${icon('clock')}${isAfter?'明日 ':''}${windowTime}</span></div><div class="decision-icon ${!a.running||p.error?'warning':has?'':'success'}">${icon(!a.running?'player-pause':p.error?'alert-circle':has?'arrows-exchange':'check')}</div><div class="decision-title">${esc(title)}</div><p class="decision-desc"><b>${isAfter?'收盘确认依据：':'决策依据：'}</b>${esc(description)}</p>${targetBlock}${ordersBlock}<div class="execution-note">${icon(canExecute?'info-circle':'lock')}<span>${esc(isAfter?(p.reasons.find(r=>r.includes('明日'))||`收盘后已完成复核，明日模拟执行窗口为 ${windowTime}（${openOrTail}撮合）。`):(p.reasons[0]||'提交时会重新校验行情、资金与持仓。'))}</span></div>${p.reasons.length>1?`<details class="rule-detail conditions"><summary>${icon('chevron-right')}查看全部执行条件（${p.reasons.length} 项）</summary>${p.reasons.map(r=>`<p>${esc(r)}</p>`).join('')}</details>`:''}<button class="button full execution-settings" data-action="execution-settings">${icon('settings')}调整策略参数</button><button class="button primary full execution-btn ${isAfter?'after-close-btn':''}" data-action="execute" ${canExecute?'':'disabled'}>${icon(isAfter?'clock':'player-play')}${esc(executeBtnText)}</button><p class="decision-footnote">${isAfter?`盘后已复核 · 参考收盘价估算 · 单边佣金万 ${number(a.feeRate*10000,1)}`:`参考价模拟成交 · 单边佣金万 ${number(a.feeRate*10000,1)}`}</p><div class="run-meta"><span>${esc(market.label)} · ${esc(market.time)}</span><button class="text-button" data-action="tab-events">运行记录${icon('chevron-right')}</button></div><details class="rule-detail quote-details"><summary>${icon('chevron-right')}${isAfter?'本日收盘行情快照':'本次行情快照'}</summary>${Object.entries(p.quoteTimes).map(([symbol,time])=>`<p>${esc(ASSETS[symbol]?.name||symbol)} · ${esc(time)}</p>`).join('')}</details></aside>`;
}
function help(){openDrawer('操作说明','账户、策略、资金与执行结果始终对应。',`<div class="form-content">${[['创建账户','填写名称、金额，选择策略和执行方式。新账户默认手动。'],['核对并执行','在账户设置的早盘或尾盘窗口核对清单后执行；行情、持仓或账户变化时需刷新后重新核对。'],['调整策略与资金','设置中调整策略不会重置持仓。资金管理支持出入金，单独记账。'],['开启自动模拟','自动进程与浏览器独立，需要电脑保持运行；休市、行情异常或账户暂停时不执行。'],['查看记录','成交、资金与运行记录分别保存，成交支持 CSV 导出。']].map(([t,d],i)=>`<div class="help-step"><span>${i+1}</span><div><h3>${t}</h3><p>${d}</p></div></div>`).join('')}<p class="notice">使用实际行情进行参考价模拟成交，不连接券商。ETF 免印花税，无最低佣金；不模拟滑点或部分成交。累计收益率为相对净投入的简单比例。</p></div>`,'help');}
window.addEventListener('message',e=>{
 if(e.source!==parent||e.data?.type!=='streamlit:render')return;
 if(e.data.args.navigationOnly){
   navigationOnly=true;pending=null;document.body.classList.add('navigation-only');
   $$('.nav-item').forEach(b=>{const active=b.dataset.research===e.data.args.mode;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');b.setAttribute('title',b.textContent.trim());});
   bridge('streamlit:setFrameHeight',{height:window.innerWidth>250?154:window.innerHeight});
   return;
 }
 const {snapshot,response}=e.data.args;
 if(!snapshot)return;
 ASSETS=snapshot.assets;market=snapshot.market;worker=snapshot.worker;
 const selected=state.selected;
 state={accounts:snapshot.accounts,selected:snapshot.accounts.some(a=>a.id===selected)?selected:snapshot.selected,assets:snapshot.assets||{}};
  if(response&&response.requestId!==lastResponse){
  lastResponse=response.requestId;
  if(pending?.requestId===response.requestId){pending=null;document.body.classList.remove('request-pending');
   if(response.ok&&['create','configure','funds'].includes(response.action)){closeDrawer();if(response.accountId)state.selected=response.accountId;if(response.action==='configure')activeTab='overview';if(response.action==='create'){activeTab='overview';$('#account-search').value='';}}
   if(!response.ok&&$('#drawer').open){let box=$('#server-error');if(!box){box=document.createElement('p');box.id='server-error';box.className='notice amber';box.setAttribute('role','alert');$('#drawer .form-content').prepend(box);}box.textContent=response.message;box.scrollIntoView({block:'nearest'});}
   if(response.message&&!response.silent)toast(response.message);
  }
 }
 render();
 if(!pending)$$('#drawer button[type="submit"]').forEach(b=>b.disabled=false);
 if(!pending&&queuedNavigation){const next=queuedNavigation;queuedNavigation=null;send(next.action,next.data);}
});
mountIcons();
bridge('streamlit:componentReady',{apiVersion:1});
bridge('streamlit:setFrameHeight',{height:900});
let lastPoll=Date.now();
setInterval(()=>{if(!navigationOnly&&!pending&&!$('#drawer').open&&!document.hidden&&Date.now()-lastPoll>=(worker.pipeline?.syncing?3000:30000)){lastPoll=Date.now();send('refresh',{silent:true});}},3000);
