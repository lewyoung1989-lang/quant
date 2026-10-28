"""Live signal adapters and validated, atomic paper execution for the account workspace."""
import copy
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

from services.simulation_store import AccountError, ROOT, SHANGHAI, now, timestamp

ASSETS = {
    "sh512890": "红利低波 ETF", "sh511260": "十年国债 ETF", "sh511010": "国债 ETF",
    "sz159915": "创业板 ETF", "sh588380": "双创50 ETF", "sh588000": "科创50 ETF",
    "sh510880": "红利 ETF", "sh511090": "三十年国债 ETF",
    "sh510300": "沪深300 ETF", "sh510500": "中证500 ETF",
}
T_ZERO = {"sh511010", "sh511260", "sh511090"}
QUOTE_MAX_AGE = 90


def local_time(value=None):
    value = value or now()
    return value.replace(tzinfo=SHANGHAI) if value.tzinfo is None else value.astimezone(SHANGHAI)


def is_session(day):
    if day.weekday() >= 5:
        return False
    path = ROOT / f"configs/trading_calendar_{day.year}.json"
    if not path.exists():
        return None
    calendar = json.loads(path.read_text())
    if calendar.get("year") != day.year:
        return None
    return not any(start <= day.isoformat() <= end for start, end in calendar["closed_ranges"])


def next_session(day):
    for i in range(1, 25):
        candidate = day + dt.timedelta(days=i)
        if is_session(candidate):
            return candidate.isoformat()
    return None


def market_status(at=None, mode="tail"):
    at = local_time(at)
    trading = is_session(at.date())
    opening = mode == "next_open"
    window = "09:30–09:35（使用当日开盘价，错过不补单）" if opening else "14:45–14:55"
    inside = (dt.time(9,30) <= at.time().replace(tzinfo=None) < dt.time(9,35)) if opening else (dt.time(14,45) <= at.time().replace(tzinfo=None) < dt.time(14,56))
    next_day = next_session(at.date())
    is_after = (trading and at.time().replace(tzinfo=None) >= dt.time(15, 0)) or (not trading)
    if trading is None:
        return {"ready": False, "label": "交易日历待更新", "reason": f"缺少 {at.year} 年交易所日历，暂停执行。", "is_after_close": False, "next_session": next_day, "session_date": at.date().isoformat()}
    if not trading:
        return {"ready": False, "label": "休市", "reason": f"当前为休市日，已生成下一交易日（{next_day}）调仓计划。", "is_after_close": True, "next_session": next_day, "session_date": at.date().isoformat()}
    if not inside:
        label = "盘中预览" if at.hour < 15 else "盘后复核"
        reason = f"模拟执行窗口为交易日 {window}。" if at.hour < 15 else f"今日已收盘，模拟执行窗口为明日（{next_day}）{window}。"
        return {"ready": False, "label": label, "reason": reason, "is_after_close": is_after, "next_session": next_day, "session_date": at.date().isoformat()}
    return {"ready": True, "label": "早盘执行窗口" if opening else "尾盘执行窗口", "reason": "执行前仍需校验行情与持仓。", "is_after_close": False, "next_session": next_day, "session_date": at.date().isoformat()}


def previous_session(day):
    for i in range(1, 25):
        candidate = day - dt.timedelta(days=i)
        if is_session(candidate):
            return candidate.isoformat()
    return None


def symbols_for(account):
    p = account["parameters"]
    if account["strategy_type"] == "compound_rotation":
        symbols = {p["tech_symbol"], p.get("div_symbol", "sh512890"), p.get("bond_symbol", p.get("def_symbol", "sh511260"))}
    else:
        symbols = {p["tech_symbol"], p["def_symbol"]} if account["strategy_type"] == "rotation" else {"sh512890", "sh511260"}
    return sorted(symbols | {p["symbol"] for p in account["positions"] if p["shares"]})


def fetch_quotes(symbols):
    from data.realtime_fetcher import fetch_realtime_quotes
    return fetch_realtime_quotes(symbols) if symbols else {}


def positive_price(quote):
    try:
        price = float(quote.get("price", 0))
        return price if math.isfinite(price) and price > 0 else None
    except (ValueError, TypeError):
        return None


def quote_issues(quotes, symbols, at):
    problems, times = [], []
    for symbol in symbols:
        q = quotes.get(symbol, {})
        if positive_price(q) is None:
            problems.append(f"{ASSETS.get(symbol, symbol)}缺少有效报价")
            continue
        try:
            raw = str(q.get("quote_time", ""))
            when = local_time(dt.datetime.fromisoformat(raw))
            age = (at - when).total_seconds()
            times.append(when)
            if when.date() != at.date() or age > QUOTE_MAX_AGE or age < -2:
                problems.append(f"{ASSETS.get(symbol, symbol)}行情过期或时间异常（{raw}）")
        except (ValueError, TypeError):
            problems.append(f"{ASSETS.get(symbol, symbol)}行情时间不可识别")
    if times and (max(times) - min(times)).total_seconds() > 15:
        problems.append("所需标的的报价时间差超过 15 秒")
    return problems


def portfolio(account, quotes):
    positions, complete, value = [], True, 0.0
    for p in account["positions"]:
        price = positive_price(quotes.get(p["symbol"], {}))
        mv = round(price * p["shares"], 2) if price is not None else None
        complete = complete and mv is not None
        value += mv or 0
        positions.append({**p, "name": ASSETS.get(p["symbol"], p["symbol"]), "price": price, "value": mv,
                          "quote_time": quotes.get(p["symbol"], {}).get("quote_time", "未取得报价")})
    total = round(account["cash_available"] + value, 2) if complete else None
    return {"positions": positions, "market_value": round(value, 2) if complete else None,
            "cash": account["cash_available"], "total": total,
            "weight": value / total if total and complete else 0 if total == 0 else None,
            "pnl": round(total - account["net_capital"], 2) if total is not None else None}


def strategy_signal(account, quotes, at):
    p = account["parameters"]
    if account["strategy_type"] == "compound_rotation":
        from strategies.signals import compute_compound_rotation_signal
        signal_quotes = quotes
        confirmed = p.get("execution_mode") == "next_open"
        if confirmed:
            signal_quotes = {symbol: {**quote, "price": quote.get("prev_close") or quote.get("price")} for symbol, quote in quotes.items()}
        
        # 提取当前防守持仓配比，以驱动 2.5% 不对称防抖状态机
        div_symbol = p.get("div_symbol", "sh512890")
        bond_symbol = p.get("bond_symbol", p.get("def_symbol", "sh511260"))
        div_shares = next((pos["shares"] for pos in account.get("positions", []) if pos["symbol"] == div_symbol), 0)
        bond_shares = next((pos["shares"] for pos in account.get("positions", []) if pos["symbol"] == bond_symbol), 0)
        current_erp_w = 0.0
        if div_shares + bond_shares > 0:
            div_p = float(signal_quotes.get(div_symbol, {}).get("price") or 1.0)
            bond_p = float(signal_quotes.get(bond_symbol, {}).get("price") or 1.0)
            div_val = div_shares * div_p
            bond_val = bond_shares * bond_p
            if div_val + bond_val > 0:
                current_erp_w = div_val / (div_val + bond_val)

        result = compute_compound_rotation_signal(
            tech_symbol=p["tech_symbol"],
            div_symbol=div_symbol,
            bond_symbol=bond_symbol,
            lookback_window=int(p["lookback_window"]),
            use_bias_exit=bool(p.get("use_bias_exit", True)),
            use_trend_filter=bool(p.get("use_trend_filter", True)),
            th_overheat=float(p.get("th_overheat", 0.20)),
            th_neutral=float(p.get("th_neutral", 0.35)),
            erp_delta=float(p.get("erp_delta", 0.025)),
            current_erp_w=current_erp_w,
            live_quotes=signal_quotes,
            as_of=at,
            confirmed=confirmed
        )
        if not result.get("valid"):
            raise AccountError(result.get("error", "复合轮动信号不可用。"))
        return result
    if account["strategy_type"] == "rotation":
        from strategies.signals import compute_rotation_signal
        signal_quotes = quotes
        # 次日开盘模式必须锁定前一交易日收盘信号，不能用今日盘中价格提前改变目标。
        if p.get("execution_mode") == "next_open":
            signal_quotes = {symbol: {**quote, "price": quote.get("prev_close")} for symbol, quote in quotes.items()}
        result = compute_rotation_signal(p["tech_symbol"], p["def_symbol"], int(p["lookback_window"]), live_quotes=signal_quotes, as_of=at)
        if not result.get("valid"):
            raise AccountError(result.get("error", "轮动信号不可用。"))
        return {**result, "weight": 1.0, "description": "进攻动量和均线条件全部成立。" if result["is_attack"] else "进攻条件未全部成立，目标切换至防守标的。"}
    from strategies.dividend_lowvol_swing_backtest import compute_indicators, load_or_sync_data
    import pandas as pd
    raw = compute_indicators(load_or_sync_data())
    raw = raw[raw.index.strftime("%Y-%m-%d") < at.date().isoformat()].dropna(subset=["close", "pe", "rate_10y", "erp"])
    if len(raw) < 60:
        raise AccountError("ERP 历史估值数据不足 60 个交易日。")
    baseline = raw.iloc[-1]
    price = positive_price(quotes.get("sh512890", {}))
    confirmed = p.get("execution_mode") == "next_open"
    pe = float(baseline["pe"]) if confirmed else float(baseline["pe"]) * price / float(baseline["close"])
    rate = float(baseline["rate_10y"])
    if pe <= 0 or not math.isfinite(pe) or not math.isfinite(rate):
        raise AccountError("估值或国债收益率数据无效。")
    erp = 100.0 / pe - rate
    percentile = float(baseline["erp_pct"]) if confirmed else float(pd.concat([raw["erp"].iloc[-250:], pd.Series([erp])]).rank(pct=True).iloc[-1])
    if percentile <= p["threshold_low"]:
        weight, band = p["weight_low"], "高估区间"
    elif percentile <= p["threshold_high"]:
        weight, band = p["weight_mid"], "常态观察带"
    else:
        weight, band = p["weight_high"], "低估区间"
    return {"valid": True, "target_symbol": "sh512890", "weight": weight,
            "historical_asof": raw.index[-1].strftime("%Y-%m-%d"), "erp": erp, "erp_pct": percentile,
            "pe": pe, "rate_10y": rate, "band": band,
            "description": f"ERP 分位 {percentile:.1%}，处于{band}；目标红利仓位 {weight:.0%}，其余目标配置十年国债 ETF（511260）。" if p.get("defensive_asset") == "sh511260" else f"ERP 分位 {percentile:.1%}，处于{band}；目标红利仓位 {weight:.0%}，其余留现金。"}


def sellable(position, day):
    if position["symbol"] in T_ZERO:
        return position["shares"]
    return sum(lot["shares"] for lot in position.get("lots", []) if lot["date"] < day)


def allocation(account, signal, quotes, at):
    """Target-share planning; sale proceeds are explicitly conditional until this atomic paper batch fills."""
    port = portfolio(account, quotes)
    if port["total"] is None:
        raise AccountError("持仓估值不完整，暂不能生成数量清单。")
    if account['strategy_type'] == 'compound_rotation':
        return allocate_multi_asset(account, signal.get('weights', {}), quotes, at, port)
    if account['strategy_type'] == 'dividend_erp' and account['parameters'].get('defensive_asset') == 'sh511260':
        return allocate_erp_bond(account, signal, quotes, at, port)
    target = signal["target_symbol"]
    price = positive_price(quotes.get(target, {}))
    if price is None:
        raise AccountError("目标标的缺少有效报价。")
    wanted = math.floor(port["total"] * signal["weight"] / (price * 100)) * 100
    cash, orders, blocks = account["cash_available"], [], []
    rate = account["fee_rate"]
    held = 0
    for p in account["positions"]:
        held = p["shares"] if p["symbol"] == target else held
        quantity = p["shares"] if p["symbol"] != target else max(0, p["shares"] - wanted)
        if p["symbol"] == target and quantity < 100:
            quantity = 0
        if quantity <= 0:
            continue
        unit = positive_price(quotes.get(p["symbol"], {}))
        gross = round(quantity * unit, 2)
        fee = round(gross * rate, 2)
        available = sellable(p, at.date().isoformat())
        if available < quantity:
            blocks.append(f"{ASSETS.get(p['symbol'], p['symbol'])}需卖 {quantity:,} 份，可卖仅 {available:,} 份（T+1 限制）")
        orders.append({"action": "卖出", "symbol": p["symbol"], "name": ASSETS.get(p["symbol"], p["symbol"]), "shares": quantity, "price": unit, "amount": gross, "fee": fee,
                       "status": "先卖出" if available >= quantity else "T+1 受限"})
        cash = round(cash + gross - fee, 2)
    required = max(0, wanted - held)
    affordable = max(0, math.floor(cash / (price * (1 + rate) * 100)) * 100)
    buy = min(required, affordable)
    while buy > 0 and round(buy * price, 2) + round(round(buy * price, 2) * rate, 2) > cash:
        buy -= 100
    if buy > 0:
        gross = round(buy * price, 2)
        fee = round(gross * rate, 2)
        orders.append({"action": "买入", "symbol": target, "name": ASSETS.get(target, target), "shares": buy, "price": price, "amount": gross, "fee": fee,
                       "status": "卖出成交后买入" if orders else "使用可用现金"})
        cash = round(cash - gross - fee, 2)
    if signal["weight"] > 0 and held == 0 and buy == 0:
        blocks.append("可用资金不足一手，无法完成首次建仓；请先入金。")
    return orders, blocks, cash


def allocate_multi_asset(account, weights, quotes, at, port):
    """Plan multi-asset target weights; keep lot-size remainders as cash and sell before buying."""
    rate = account['fee_rate']
    active_symbols = [s for s, w in weights.items() if w > 0]
    prices = {s: positive_price(quotes.get(s, {})) for s in active_symbols}
    for p in account['positions']:
        if p['symbol'] not in prices:
            prices[p['symbol']] = positive_price(quotes.get(p['symbol'], {}))
    if any(v is None for v in prices.values()):
        raise AccountError('相关标的行情缺失，暂不能生成调仓清单。')
    wanted = {s: math.floor(port['total'] * float(w) / (prices[s] * 100)) * 100 for s, w in weights.items() if prices.get(s) and w > 0}
    cash, orders, blocks = account['cash_available'], [], []
    held = {p['symbol']: p['shares'] for p in account['positions']}
    for p in account['positions']:
        qty = max(0, p['shares'] - wanted.get(p['symbol'], 0))
        if not qty:
            continue
        price = prices[p['symbol']]
        available = sellable(p, at.date().isoformat())
        if available < qty:
            blocks.append(f"{ASSETS.get(p['symbol'], p['symbol'])}需卖 {qty:,} 份，可卖仅 {available:,} 份（T+1 限制）")
        gross = round(qty * price, 2)
        fee = round(gross * rate, 2)
        orders.append(dict(action='卖出', symbol=p['symbol'], name=ASSETS.get(p['symbol'], p['symbol']), shares=qty, price=price, amount=gross, fee=fee, status='先卖出' if available >= qty else 'T+1 受限'))
        cash = round(cash + gross - fee, 2)
        held[p['symbol']] -= qty
    for symbol, goal in wanted.items():
        price = prices[symbol]
        qty = min(max(0, goal - held.get(symbol, 0)), max(0, math.floor(cash / (price * (1 + rate) * 100)) * 100))
        while qty > 0 and round(qty * price, 2) + round(round(qty * price, 2) * rate, 2) > cash:
            qty -= 100
        if qty:
            gross = round(qty * price, 2)
            fee = round(gross * rate, 2)
            orders.append(dict(action='买入', symbol=symbol, name=ASSETS.get(symbol, symbol), shares=qty, price=price, amount=gross, fee=fee, status='调仓资金买入'))
            cash = round(cash - gross - fee, 2)
    if not account['positions'] and not orders and any(w > 0 for w in weights.values()):
        blocks.append('可用资金不足一手，无法完成首次建仓；请先入金。')
    return orders, blocks, cash


def allocate_erp_bond(account, signal, quotes, at, port):
    """Plan both ETF legs; keep lot-size remainders as cash and sell before buying."""
    weights = {'sh512890': float(signal['weight']), 'sh511260': 1-float(signal['weight'])}
    return allocate_multi_asset(account, weights, quotes, at, port)


def build_plan(store, account_id, quotes=None, at=None, signal=None):
    at = local_time(at)
    a = store.get(account_id)
    symbols = symbols_for(a)
    quotes = fetch_quotes(symbols) if quotes is None else quotes
    mode = a["parameters"].get("execution_mode", "tail")
    status = market_status(at, mode)
    reasons = ([] if a["running"] else ["账户已暂停运行。"])
    if not status["ready"]:
        reasons.append(status["reason"])
    pipeline = store.metadata("pipeline")
    if pipeline and (not pipeline.get("ready") or pipeline.get("target") != previous_session(at.date())):
        reasons.append("每日数据任务尚未补齐前一交易日数据，等待更新后再执行。")
    reasons.extend(quote_issues(quotes, symbols, at))
    reasons.extend(f"未配置 {s} 的交易规则，不能执行该持仓。" for s in symbols if s not in ASSETS)
    port = portfolio(a, quotes)
    orders, remaining, error = [], a["cash_available"], None
    try:
        usable_quotes = {}
        for s in symbols:
            q = dict(quotes.get(s, {}))
            p = positive_price(q)
            if p is None and not status["ready"]:
                # 盘前竞价或夜间非决策窗，若实时最新价为0或未就绪，允许回退至昨收价试算
                p = positive_price({'price': q.get('prev_close')})
            if p is None:
                raise AccountError("所需标的行情不完整，请刷新行情后重试。")
            usable_quotes[s] = {**q, 'price': p}
        signal = signal or strategy_signal(a, usable_quotes, at)
        if not signal.get("valid", False):
            raise AccountError(signal.get("error", "策略信号无效。"))
        if signal.get("historical_asof") != previous_session(at.date()):
            reasons.append(f"历史指标截至 {signal.get('historical_asof', '未知')}，未覆盖前一交易日，暂不能执行。")
        execution_quotes = quotes
        if mode == "next_open":
            has_today_open = all(
                positive_price({'price': quotes.get(s, {}).get('open')}) is not None 
                and str(quotes.get(s, {}).get('quote_time', '')).startswith(at.date().isoformat()) 
                for s in symbols
            )
            if status["ready"]:
                if not has_today_open:
                    raise AccountError('当日开盘价尚未发布或日期不符，禁止使用昨收价替代。')
                execution_quotes = {s: {**q, 'price': q.get('open')} for s, q in quotes.items()}
            else:
                execution_quotes = {s: {**q, 'price': q.get('open') if has_today_open else (q.get('prev_close') or q.get('price'))} for s, q in quotes.items()}
        orders, blocks, remaining = allocation(a, signal, execution_quotes, at)
        reasons.extend(blocks)
    except Exception as exc:
        error = str(exc) or "信号计算失败，请检查行情数据。"
        reasons.append(error)
        signal = None
    digest = {"id": a["id"], "revision": a["revision"], "date": at.date().isoformat(), "target": signal and [signal["target_symbol"], signal["weight"]], "orders": orders}
    plan_id = hashlib.sha256(json.dumps(digest, sort_keys=True).encode()).hexdigest()
    return {"id": plan_id, "account_id": a["id"], "revision": a["revision"], "account": a,
            "portfolio": port, "signal": signal, "orders": orders, "remaining_cash": remaining,
            "fees": round(sum(o["fee"] for o in orders), 2), "reasons": list(dict.fromkeys(reasons)),
            "can_execute": bool(orders) and not reasons, "market": status, "error": error,
            "created_at": at.isoformat(timespec="seconds"), "quote_times": {s: quotes.get(s, {}).get("quote_time", "未取得") for s in symbols}}


def execute_plan(store, account_id, expected_plan_id, request_id, automatic=False, quotes=None, at=None, signal=None):
    """UI and worker share every gate. No force flag bypasses sessions, quote quality or account state."""
    receipt = store.receipt(request_id)
    if receipt:
        if receipt.get("account_id") != account_id or receipt.get("plan_id") != expected_plan_id:
            raise AccountError("执行请求与原账户或计划不一致。")
        return {**receipt, "duplicate": True}
    real_clock = at is None
    at = local_time(at)
    plan = build_plan(store, account_id, quotes=quotes, at=at, signal=signal)
    if expected_plan_id != plan["id"]:
        raise AccountError("账户、行情或调仓清单已变化，请刷新后重新核对再执行。")
    if not plan["can_execute"]:
        raise AccountError("；".join(plan["reasons"]) or "当前无需调仓。")
    with store.transaction() as conn:
        receipt = conn.execute("SELECT result FROM receipts WHERE request_id=?", (request_id,)).fetchone()
        if receipt:
            result = json.loads(receipt[0])
            if result.get("account_id") != account_id or result.get("plan_id") != expected_plan_id:
                raise AccountError("执行请求与原账户或计划不一致。")
            return {**result, "duplicate": True}
        a = store.get(account_id, conn)
        if real_clock:
            committed_at = local_time()
            status = market_status(committed_at, a["parameters"].get("execution_mode", "tail"))
            timing = quote_issues({s: {"price": 1, "quote_time": t} for s, t in plan["quote_times"].items()}, list(plan["quote_times"]), committed_at)
            if not status["ready"] or timing:
                raise AccountError("执行时窗口或行情时效发生变化，请刷新清单。")
        if a["revision"] != plan["revision"] or not a["running"] or (automatic and not a["auto_trade"]):
            raise AccountError("账户配置已变化或自动执行已关闭，请重新核对。")
        positions = copy.deepcopy(a["positions"])
        cash = a["cash_available"]
        source = ("次日开盘自动" if a["parameters"].get("execution_mode") == "next_open" else "尾盘自动") if automatic else "手动执行"
        for order in plan["orders"]:
            held = next((p for p in positions if p["symbol"] == order["symbol"]), None)
            if order["action"] == "卖出":
                if not held or sellable(held, at.date().isoformat()) < order["shares"]:
                    raise AccountError("可卖持仓变化，已取消整个模拟批次。")
                left = order["shares"]
                for lot in held["lots"]:
                    if order["symbol"] in T_ZERO or lot["date"] < at.date().isoformat():
                        used = min(left, lot["shares"])
                        lot["shares"] -= used
                        left -= used
                held["lots"] = [lot for lot in held["lots"] if lot["shares"]]
                held["shares"] -= order["shares"]
                cash = round(cash + order["amount"] - order["fee"], 2)
            else:
                cost = round(order["amount"] + order["fee"], 2)
                if cash < cost:
                    raise AccountError("可用资金不足，已取消整个模拟批次。")
                if held is None:
                    held = {"symbol": order["symbol"], "shares": 0, "lots": []}
                    positions.append(held)
                held["shares"] += order["shares"]
                held["lots"].append({"date": at.date().isoformat(), "shares": order["shares"]})
                cash = round(cash - cost, 2)
            store.entry(conn, account_id, "trade", {**order, "source": source, "batch": request_id,
                        "reason": plan["signal"]["description"]}, time=at.isoformat(timespec="seconds"))
        a["positions"] = [p for p in positions if p["shares"]]
        a["cash_available"] = cash
        store._update(conn, a, plan["revision"])
        result = {"success": True, "executed": True, "account_id": account_id, "plan_id": expected_plan_id, "count": len(plan["orders"]), "fees": plan["fees"], "message": f"{len(plan['orders'])} 笔模拟成交已完成，现金与持仓已更新。"}
        store.entry(conn, account_id, "event", {"title": "模拟调仓已完成", "detail": f"{source}；{result['message']} 费用 ¥{plan['fees']:,.2f}。", "status": "已完成"})
        conn.execute("INSERT INTO receipts VALUES(?,?,?)", (request_id, account_id, json.dumps(result, ensure_ascii=False)))
        return result


def worker_tick(store, at=None):
    at = local_time(at)
    status = market_status(at)
    accounts = [a for a in store.list_accounts() if a["auto_trade"] and a["running"]]
    report = {"heartbeat": at.isoformat(), "status": "运行中", "message": status["reason"], "accounts": len(accounts)}
    if is_session(at.date()) and at.time().replace(tzinfo=None) >= dt.time(9,35):
        for account in accounts:
            if account['parameters'].get('execution_mode') == 'next_open':
                key = f"auto:{account['id']}:{at.date().isoformat()}:{account['settings_version']}"
                if not store.receipt(key):
                    store.record_event(account['id'], '早盘窗口已结束', '今日未完成开盘模拟执行；不在尾盘补单，等待下一交易日有效窗口。', '受阻', 'missed:'+key)
    due = [a for a in accounts if market_status(at, a["parameters"].get("execution_mode", "tail"))["ready"]]
    report["message"] = "按账户执行时点检查：次日开盘 09:30–09:35；尾盘 14:45–14:55。"
    if due:
        symbols = sorted({s for a in due for s in symbols_for(a)})
        quotes = fetch_quotes(symbols)
        for a in due:
            key = f"auto:{a['id']}:{at.date().isoformat()}:{a['settings_version']}"
            if store.receipt(key):
                continue
            try:
                plan = build_plan(store, a["id"], quotes=quotes, at=at)
                if not plan["can_execute"]:
                    if plan["reasons"]:
                        store.record_event(a["id"], "自动调仓等待执行条件", "；".join(plan["reasons"]), "受阻", f"blocked:{key}:{at.strftime('%H:%M')}")
                    continue
                execute_plan(store, a["id"], plan["id"], key, automatic=True)
            except Exception as exc:
                store.record_event(a["id"], "自动模拟执行受阻", str(exc), "受阻", f"failure:{key}:{at.strftime('%H:%M')}")
    store.metadata("worker", report)
    return report
