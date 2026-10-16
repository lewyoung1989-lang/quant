#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓管理与实盘调仓清单生成服务 (Rebalance Service)
持久化本地存储用户的持仓状态 (JSON)，
并结合目标标的、当前报价与资金，生成精确到手(100股)的调仓执行清单。
"""

import os
import sys
sys.path.append(".")
import json
import datetime
from pathlib import Path
from strategies.signals import compute_rotation_signal
from data.etf_pool import ETF_POOL

CONFIG_DIR = Path("./data/user_profile")
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SIM_ACCOUNTS_FILE = CONFIG_DIR / "simulated_accounts.json"
TRADE_LOG_FILE = CONFIG_DIR / "simulated_trades.json"

def get_all_accounts():
    """获取所有模拟仓位账户字典"""
    if SIM_ACCOUNTS_FILE.exists():
        try:
            with open(SIM_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    default_accounts = {
        "模拟实盘 1 号 (创业板+红利低波)": {
            "initial_capital": 100000.0,
            "holding_symbol": "sh512890",
            "holding_amount": 80000,
            "cash_available": 2160.0,
            "created_at": "2026-10-10",
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        },
        "模拟实盘 2 号 (双创50+国债ETF)": {
            "initial_capital": 100000.0,
            "holding_symbol": "sh511010",
            "holding_amount": 700,
            "cash_available": 1484.1,
            "created_at": "2026-10-10",
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        },
        "模拟实盘 3 号 (红利低波ERP择时高抛低吸)": {
            "initial_capital": 100000.0,
            "holding_symbol": "sh512890",
            "holding_amount": 61500,
            "bond_symbol": "sh511260",
            "bond_amount": 0,
            "cash_available": 25031.5,
            "strategy_type": "dividend_erp",
            "auto_trade": True,
            "created_at": "2026-10-16",
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    }
    if SIM_ACCOUNTS_FILE.exists():
        try:
            with open(SIM_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                accs = json.load(f)
            if "模拟实盘 3 号 (红利低波ERP择时高抛低吸)" not in accs:
                accs["模拟实盘 3 号 (红利低波ERP择时高抛低吸)"] = default_accounts["模拟实盘 3 号 (红利低波ERP择时高抛低吸)"]
                save_all_accounts(accs)
            return accs
        except Exception:
            pass

    save_all_accounts(default_accounts)
    return default_accounts

def save_all_accounts(accs_dict):
    """保存所有模拟仓位"""
    with open(SIM_ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accs_dict, f, ensure_ascii=False, indent=2)

def get_current_position(account_name="模拟实盘 1 号 (创业板+红利低波)"):
    """读取指定模拟仓位状态"""
    accs = get_all_accounts()
    if account_name not in accs:
        # 如果不存在则自动创建 10 万本金模拟盘
        accs[account_name] = {
            "initial_capital": 100000.0,
            "holding_symbol": "",
            "holding_amount": 0,
            "cash_available": 100000.0,
            "created_at": datetime.date.today().strftime("%Y-%m-%d"),
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_all_accounts(accs)
    return accs[account_name]

def save_current_position(pos_dict, account_name="模拟实盘 1 号 (创业板+红利低波)"):
    """保存指定模拟仓位状态"""
    accs = get_all_accounts()
    pos_dict["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    accs[account_name] = pos_dict
    save_all_accounts(accs)

def record_trade_log(account_name, action, symbol, shares, price, amount, reason=""):
    """记录模拟调仓流水"""
    logs = []
    if TRADE_LOG_FILE.exists():
        try:
            with open(TRADE_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []
            
    logs.insert(0, {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account": account_name,
        "action": action,
        "symbol": symbol,
        "shares": shares,
        "price": price,
        "amount": amount,
        "reason": reason
    })
    with open(TRADE_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs[:500], f, ensure_ascii=False, indent=2)

def get_trade_logs(account_name=None):
    """读取模拟调仓流水"""
    if TRADE_LOG_FILE.exists():
        try:
            with open(TRADE_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
                if account_name:
                    return [l for l in logs if l.get("account") == account_name]
                return logs
        except Exception:
            pass
    return []

def generate_rebalance_plan(
    tech_symbol="sz159915",
    def_symbol="sh512890",
    lookback_window=20,
    account_name="模拟实盘 1 号 (创业板+红利低波)"
):
    """
    根据最新量化信号与实际持仓，生成执行清单
    """
    signal = compute_rotation_signal(tech_symbol, def_symbol, lookback_window)
    pos = get_current_position(account_name)

    cur_sym = pos.get("holding_symbol", "").lower()
    cur_shares = int(pos.get("holding_amount", 0))
    cash = float(pos.get("cash_available", 0.0))

    target_sym = signal["target_symbol"].lower()
    tech_price = signal["tech"]["price"]
    def_price = signal["defensive"]["price"]

    # 当前总资产估算 (若当前持仓是国债或其他标的，动态获取其最新现价)
    if cur_sym == tech_symbol:
        cur_unit_price = tech_price
    elif cur_sym == def_symbol:
        cur_unit_price = def_price
    elif cur_sym:
        from data.realtime_fetcher import fetch_realtime_quotes
        q_extra = fetch_realtime_quotes([cur_sym])
        cur_unit_price = q_extra.get(cur_sym, {}).get("price", 1.0)
    else:
        cur_unit_price = 0.0

    market_value = cur_shares * cur_unit_price
    total_assets = market_value + cash

    # 调仓指令建模
    orders = []
    summary_action = "继续持有"
    can_execute = True
    reason = ""

    target_name = ETF_POOL.get(target_sym, target_sym).split()[0]
    cur_name = ETF_POOL.get(cur_sym, cur_sym).split()[0] if cur_sym else "空仓"
    is_new_signal = signal.get("is_new_signal", False)

    # 预留万分之三佣金准备建仓预算
    target_price = tech_price if target_sym == tech_symbol else def_price
    buy_budget = cash * 0.9995
    est_shares = int((buy_budget / target_price) // 100) * 100 if target_price > 0 else 0
    cost_est = est_shares * target_price
    setup_order = {
        "symbol": target_sym,
        "name": target_name,
        "shares": est_shares,
        "price": target_price,
        "est_amount": cost_est
    }

    # 场景 1: 实际持仓已经与策略目标一致
    if cur_sym == target_sym and cur_shares > 0:
        summary_action = f"✅ 继续持有【{target_name}】· 信号未变盘"
        reason = f"当前持仓与策略目标完全一致 ({target_name})，今日无新变盘信号，继续保持现有持仓。"
        orders.append({
            "action": "持有",
            "symbol": target_sym,
            "name": target_name,
            "shares": cur_shares,
            "price": cur_unit_price,
            "est_amount": market_value,
            "status": "保持不动"
        })

    # 场景 2: 空仓状态
    elif cur_shares == 0 or not cur_sym:
        if is_new_signal:
            summary_action = f"🔥 今日触发新变盘信号 · 建仓买入【{target_name}】"
            reason = f"今日策略检测到全新的变盘切换信号（目标标的为【{target_name}】），生成首次建仓买入委托。"
            orders.append({
                "action": "买入",
                "symbol": target_sym,
                "name": target_name,
                "shares": est_shares,
                "price": target_price,
                "est_amount": cost_est,
                "status": "新信号建仓买入"
            })
        else:
            summary_action = f"⚪ 保持空仓观望 · 今日无新变盘信号"
            reason = f"当前策略延续【{target_name}】防守周期，今日进攻与防守信号未发生切换。建议保持空仓观望，等待下一次新变盘信号出现。"
            orders.append({
                "action": "空仓观望",
                "symbol": target_sym,
                "name": target_name,
                "shares": 0,
                "price": target_price,
                "est_amount": 0.0,
                "status": "等待新信号"
            })

    # 场景 3: 持有旧标的 -> 先卖出全部旧标的，再买入新目标标的 (100% 攻守轮动)
    else:
        summary_action = f"🔄 调仓：卖出【{cur_name}】➜ 买入【{target_name}】"
        sell_p = cur_unit_price
        sell_amount = cur_shares * sell_p
        
        # 卖出后资金秒级 T+0 可用
        post_sell_cash = (cash + sell_amount) * 0.9995  # 扣除卖出佣金
        target_price = tech_price if target_sym == tech_symbol else def_price
        est_buy_shares = int((post_sell_cash / target_price) // 100) * 100
        buy_amount = est_buy_shares * target_price

        reason = (
            f"轮动信号发生切换 (目标变更为【{target_name}】)。\n"
            f"建议于 14:45~14:50 先全额卖出【{cur_name}】(预估回款 ¥{sell_amount:.2f})，"
            f"资金到账后立即全额买入约 {est_buy_shares} 股【{target_name}】完成闭环轮动。"
        )

        orders.append({
            "step": 1,
            "action": "卖出",
            "symbol": cur_sym,
            "name": cur_name,
            "shares": cur_shares,
            "price": sell_p,
            "est_amount": sell_amount,
            "status": "先全额卖出"
        })
        orders.append({
            "step": 2,
            "action": "买入",
            "symbol": target_sym,
            "name": target_name,
            "shares": est_buy_shares,
            "price": target_price,
            "est_amount": buy_amount,
            "status": "卖出成交后全额买入"
        })

    return {
        "signal": signal,
        "position": pos,
        "summary_action": summary_action,
        "can_execute": can_execute,
        "reason": reason,
        "orders": orders,
        "setup_order": setup_order,
        "portfolio": {
            "current_holding_symbol": cur_sym,
            "current_holding_name": cur_name,
            "current_shares": cur_shares,
            "market_value": market_value,
            "cash": cash,
            "total_assets": total_assets
        }
    }

def execute_simulated_rebalance(
    account_name,
    tech_symbol="sz159915",
    def_symbol="sh512890",
    lookback_window=20,
    force_auto=False
):
    """
    自动执行指定模拟账户的调仓撮合
    :param force_auto: 若为 True，无视时间窗口强制撮合；默认 False 严格限制 14:45~14:55
    :return: dict 包含执行状态、执行信息、成交记录
    """
    plan = generate_rebalance_plan(tech_symbol, def_symbol, lookback_window, account_name=account_name)
    orders = plan["orders"]
    port = plan["portfolio"]
    pos = plan["position"]
    init_capital = float(pos.get("initial_capital", 100000.0))

    executed_trades = []

    # 严格交易时间窗口检查：只有在 14:45 ~ 14:55 (或者手动点击强制执行) 才能触发交易
    now = datetime.datetime.now()
    is_window = (now.hour == 14 and 45 <= now.minute <= 55)
    
    if not is_window and not force_auto:
        return {
            "success": False,
            "executed": False,
            "in_window": False,
            "message": f"⏳ 尚未到尾盘执行窗口 (当前时间 {now.strftime('%H:%M:%S')})。系统已严格锁定，将在每日 14:45 ~ 14:55 自动执行调仓撮合。",
            "plan": plan
        }

    # 检查是否有买入或卖出动作
    has_trade = any(o["action"] in ["买入", "卖出"] for o in orders)
    if not has_trade:
        return {
            "success": True,
            "executed": False,
            "in_window": is_window,
            "message": f"【{account_name}】当前持仓与策略目标一致，继续持有无需调仓。",
            "plan": plan
        }

    # 执行模拟平仓与建仓
    sells = [o for o in orders if o["action"] == "卖出"]
    for s in sells:
        record_trade_log(account_name, "卖出平仓", s["symbol"], s["shares"], s["price"], s["est_amount"], reason="量化轮动信号切换")
        executed_trades.append(s)

    buys = [o for o in orders if o["action"] == "买入"]
    last_b = buys[-1] if buys else None
    if last_b:
        remain_cash = port['total_assets'] - last_b['est_amount']
        save_current_position({
            "initial_capital": init_capital,
            "holding_symbol": last_b["symbol"],
            "holding_amount": int(last_b["shares"]),
            "cash_available": max(0.0, round(remain_cash, 2))
        }, account_name=account_name)
        record_trade_log(account_name, "买入建仓", last_b["symbol"], last_b["shares"], last_b["price"], last_b["est_amount"], reason="量化轮动信号切换")
        executed_trades.append(last_b)

    return {
        "success": True,
        "executed": True,
        "message": f"【{account_name}】调仓执行完成！已切换至持有 {last_b['name']} ({last_b['shares']} 股)。",
        "trades": executed_trades,
        "plan": plan
    }

def generate_dividend_rebalance_plan(
    account_name="模拟实盘 3 号 (红利低波ERP择时高抛低吸)",
    etf_symbol="sh512890",
    bond_symbol="sh511260"
):
    """
    根据红利低波策略二 (ERP 股债利差估值大波段高抛低吸) 生成每日盘中/尾盘调仓执行清单
    """
    import pandas as pd
    from strategies.dividend_lowvol_swing_backtest import load_or_sync_data, compute_indicators
    from data.realtime_fetcher import fetch_realtime_quotes

    # 1. 抓取标的最新实时行情
    quotes = fetch_realtime_quotes([etf_symbol, bond_symbol])
    q_etf = quotes.get(etf_symbol, {})
    q_bond = quotes.get(bond_symbol, {})

    # 2. 读取历史指标基线
    raw_df = compute_indicators(load_or_sync_data())
    last_row = raw_df.iloc[-1]

    # 获取价格
    hist_close = last_row["close"]
    cur_etf_price = q_etf.get("price", hist_close)
    if cur_etf_price <= 0:
        cur_etf_price = hist_close

    cur_bond_price = q_bond.get("price", last_row.get("bond_close", 135.0))
    if cur_bond_price <= 0:
        cur_bond_price = last_row.get("bond_close", 135.0)

    # 动态估算实时 PE 与 ERP
    price_ratio = (cur_etf_price / hist_close) if hist_close > 0 else 1.0
    rt_pe = last_row["pe"] * price_ratio
    rt_rate_10y = last_row["rate_10y"]
    rt_ey = (1.0 / rt_pe) * 100.0 if rt_pe > 0 else 0.0
    rt_erp = rt_ey - rt_rate_10y

    # 滚动 250 日分位数测算
    recent_erp = raw_df["erp"].iloc[-250:].copy()
    recent_erp_with_rt = pd.concat([recent_erp, pd.Series([rt_erp])])
    rt_erp_pct = float(pd.Series(recent_erp_with_rt).rank(pct=True).iloc[-1])

    # 3. 策略目标仓位确定
    # erp_pct <= 0.20 -> 50% 仓位 (估值高位过热，高抛减半)
    # 0.20 < erp_pct <= 0.35 -> 75% 仓位 (温和高估，中性减至 75%)
    # erp_pct > 0.35 -> 100% 满仓 (低估极具性价比，低吸满仓)
    if rt_erp_pct <= 0.20:
        target_weight = 0.50
        status_label = "🔥 估值过热区 (ERP ≤ 20%) · 目标仓位 50%"
        trigger_desc = f"当前 ERP 分位数仅为 {rt_erp_pct*100:.1f}% (低于 20% 高抛阈值)，红利性价比偏低，应将仓位压降至 50%，其余资金配置国债生息避险。"
    elif rt_erp_pct <= 0.35:
        target_weight = 0.75
        status_label = "🟡 估值温和偏高 (20% < ERP ≤ 35%) · 目标仓位 75%"
        trigger_desc = f"当前 ERP 分位数为 {rt_erp_pct*100:.1f}% (处于 20%~35% 观察带)，建议维持稳健 75% 仓位，保持 25% 现金/国债对冲。"
    else:
        target_weight = 1.00
        status_label = "🟢 极具性价比 (ERP > 35%) · 目标仓位 100%"
        trigger_desc = f"当前 ERP 分位数为 {rt_erp_pct*100:.1f}% (高于 35% 极具吸引力)，股息率利差充裕，建议 100% 满仓配置华泰低波红利。"

    # 4. 读取账户当前资产与持仓
    pos = get_current_position(account_name)
    holding_sym = pos.get("holding_symbol", etf_symbol).lower()
    holding_shares = int(pos.get("holding_amount", 0))
    cash = float(pos.get("cash_available", 0.0))
    bond_shares = int(pos.get("bond_amount", 0))

    etf_mv = holding_shares * cur_etf_price
    bond_mv = bond_shares * cur_bond_price
    total_assets = etf_mv + bond_mv + cash
    if total_assets <= 0:
        total_assets = float(pos.get("initial_capital", 100000.0))
        cash = total_assets

    cur_etf_weight = (etf_mv / total_assets) if total_assets > 0 else 0.0

    # 5. 测算调仓委托
    target_etf_mv = total_assets * target_weight
    target_shares = int((target_etf_mv / cur_etf_price) // 100) * 100 if cur_etf_price > 0 else 0
    delta_shares = target_shares - holding_shares

    orders = []
    summary_action = "保持现有持仓"
    reason = ""

    # 判断是否需要调仓 (阈值 100 股)
    if delta_shares >= 100:
        # 需要加仓 (低吸买入 512890)
        buy_amount = delta_shares * cur_etf_price
        summary_action = f"🔼 低吸加仓：买入【华泰低波红利】约 {delta_shares:,} 股至 {int(target_weight*100)}% 仓位"
        reason = f"{trigger_desc} 当前持有 {cur_etf_weight*100:.1f}% 仓位，需加仓 {abs(target_weight - cur_etf_weight)*100:.1f}%。"

        # 如果需要卖出部分国债换取现金
        if cash < buy_amount and bond_shares > 0:
            need_cash = buy_amount - cash
            sell_bond_shares = int((need_cash / cur_bond_price) // 10) * 10 + 10
            sell_bond_shares = min(sell_bond_shares, bond_shares)
            if sell_bond_shares > 0:
                orders.append({
                    "step": 1,
                    "action": "卖出",
                    "symbol": bond_symbol,
                    "name": "十年国债ETF",
                    "shares": sell_bond_shares,
                    "price": cur_bond_price,
                    "est_amount": sell_bond_shares * cur_bond_price,
                    "status": "释放对冲现金"
                })

        orders.append({
            "step": len(orders) + 1,
            "action": "买入",
            "symbol": etf_symbol,
            "name": "华泰低波红利ETF",
            "shares": delta_shares,
            "price": cur_etf_price,
            "est_amount": buy_amount,
            "status": "低吸加仓"
        })

    elif delta_shares <= -100:
        # 需要减仓 (高抛卖出 512890)
        sell_shares = abs(delta_shares)
        sell_amount = sell_shares * cur_etf_price
        summary_action = f"🔻 高抛减仓：卖出【华泰低波红利】约 {sell_shares:,} 股，压降至 {int(target_weight*100)}% 仓位"
        reason = f"{trigger_desc} 当前持仓过高 ({cur_etf_weight*100:.1f}%)，需减仓 {abs(cur_etf_weight - target_weight)*100:.1f}% 锁定浮盈。"

        orders.append({
            "step": 1,
            "action": "卖出",
            "symbol": etf_symbol,
            "name": "华泰低波红利ETF",
            "shares": sell_shares,
            "price": cur_etf_price,
            "est_amount": sell_amount,
            "status": "高抛减仓"
        })

        # 卖出回款可选买入十年国债 ETF 对冲生息
        est_buy_bond = int((sell_amount * 0.9995 / cur_bond_price) // 10) * 10
        if est_buy_bond >= 10:
            orders.append({
                "step": 2,
                "action": "买入",
                "symbol": bond_symbol,
                "name": "十年国债ETF",
                "shares": est_buy_bond,
                "price": cur_bond_price,
                "est_amount": est_buy_bond * cur_bond_price,
                "status": "闲置对冲生息"
            })
    else:
        # 无需变动
        summary_action = f"✅ 保持当前 {int(cur_etf_weight*100)}% 稳健仓位 · 无需调仓"
        reason = f"{trigger_desc} 当前持有 {cur_etf_weight*100:.1f}% 华泰低波红利，与策略目标仓位 ({int(target_weight*100)}%) 吻合，今日无需调仓下单。"
        orders.append({
            "action": "持有",
            "symbol": etf_symbol,
            "name": "华泰低波红利ETF",
            "shares": holding_shares,
            "price": cur_etf_price,
            "est_amount": etf_mv,
            "status": f"保持 {int(cur_etf_weight*100)}% 仓位"
        })

    setup_order = {
        "symbol": etf_symbol,
        "name": "华泰低波红利ETF",
        "shares": target_shares,
        "price": cur_etf_price,
        "est_amount": target_shares * cur_etf_price
    }

    signal_info = {
        "strategy": "dividend_erp",
        "target_weight": target_weight,
        "status_label": status_label,
        "etf": {
            "symbol": etf_symbol,
            "name": "华泰低波红利ETF",
            "price": cur_etf_price,
            "chg_pct": q_etf.get("chg_pct", 0.0),
            "age_seconds": q_etf.get("age_seconds", 0),
            "quote_time": q_etf.get("quote_time", datetime.datetime.now().strftime("%H:%M:%S")),
        },
        "bond": {
            "symbol": bond_symbol,
            "name": "十年国债ETF",
            "price": cur_bond_price,
            "chg_pct": q_bond.get("chg_pct", 0.0),
            "age_seconds": q_bond.get("age_seconds", 0)
        },
        "indicators": {
            "pe": rt_pe,
            "rate_10y": rt_rate_10y,
            "ey": rt_ey,
            "erp": rt_erp,
            "erp_pct": rt_erp_pct,
            "threshold_sell": 0.20,
            "threshold_neutral": 0.35,
            "threshold_buy": 0.80
        },
        "conditions": {
            "overheat": {
                "name": "估值过热预警线 (ERP ≤ 20% · 仓位压降至 50%)",
                "passed": rt_erp_pct <= 0.20,
                "diff": (rt_erp_pct - 0.20) * 100
            },
            "neutral": {
                "name": "估值温和观察带 (20% < ERP ≤ 35% · 维持 75% 仓位)",
                "passed": 0.20 < rt_erp_pct <= 0.35,
                "diff": (rt_erp_pct - 0.35) * 100
            },
            "attractive": {
                "name": "极具性价比配置线 (ERP > 35% · 满仓 100% 低吸)",
                "passed": rt_erp_pct > 0.35,
                "diff": (rt_erp_pct - 0.35) * 100
            }
        }
    }

    return {
        "signal": signal_info,
        "position": pos,
        "summary_action": summary_action,
        "can_execute": True,
        "reason": reason,
        "orders": orders,
        "setup_order": setup_order,
        "portfolio": {
            "current_holding_symbol": etf_symbol,
            "current_holding_name": "华泰低波红利ETF",
            "current_shares": holding_shares,
            "market_value": etf_mv,
            "bond_symbol": bond_symbol,
            "bond_name": "十年国债ETF",
            "bond_shares": bond_shares,
            "bond_value": bond_mv,
            "cash": cash,
            "total_assets": total_assets,
            "current_weight": cur_etf_weight,
            "target_weight": target_weight
        }
    }

def execute_dividend_simulated_rebalance(
    account_name="模拟实盘 3 号 (红利低波ERP择时高抛低吸)",
    etf_symbol="sh512890",
    bond_symbol="sh511260",
    force_auto=False
):
    """
    自动执行红利低波ERP策略模拟账户调仓撮合
    """
    plan = generate_dividend_rebalance_plan(account_name, etf_symbol, bond_symbol)
    orders = plan["orders"]
    port = plan["portfolio"]
    pos = plan["position"]
    init_capital = float(pos.get("initial_capital", 100000.0))

    executed_trades = []
    now = datetime.datetime.now()
    is_window = (now.hour == 14 and 45 <= now.minute <= 55)

    if not is_window and not force_auto:
        return {
            "success": False,
            "executed": False,
            "in_window": False,
            "message": f"⏳ 尚未到尾盘执行窗口 (当前时间 {now.strftime('%H:%M:%S')})。系统已严格锁定，将在每日 14:45 ~ 14:55 自动执行调仓撮合。",
            "plan": plan
        }

    has_trade = any(o["action"] in ["买入", "卖出"] for o in orders)
    if not has_trade:
        return {
            "success": True,
            "executed": False,
            "in_window": is_window,
            "message": f"【{account_name}】当前持仓与策略目标一致，继续持有无需调仓。",
            "plan": plan
        }

    cur_shares = pos.get("holding_amount", 0)
    cur_bond = pos.get("bond_amount", 0)
    cur_cash = pos.get("cash_available", 0.0)

    for o in orders:
        if o["action"] == "卖出":
            record_trade_log(account_name, "高抛卖出", o["symbol"], o["shares"], o["price"], o["est_amount"], reason=f"红利低波ERP择时调仓 ({o['status']})")
            if o["symbol"] == etf_symbol:
                cur_shares -= o["shares"]
            elif o["symbol"] == bond_symbol:
                cur_bond -= o["shares"]
            cur_cash += o["est_amount"] * 0.9997  # 扣除万分之三费率
            executed_trades.append(o)

    for o in orders:
        if o["action"] == "买入":
            record_trade_log(account_name, "低吸买入", o["symbol"], o["shares"], o["price"], o["est_amount"], reason=f"红利低波ERP择时调仓 ({o['status']})")
            if o["symbol"] == etf_symbol:
                cur_shares += o["shares"]
            elif o["symbol"] == bond_symbol:
                cur_bond += o["shares"]
            cur_cash -= o["est_amount"] * 1.0003
            executed_trades.append(o)

    save_current_position({
        "initial_capital": init_capital,
        "holding_symbol": etf_symbol,
        "holding_amount": max(0, int(cur_shares)),
        "bond_symbol": bond_symbol,
        "bond_amount": max(0, int(cur_bond)),
        "cash_available": max(0.0, round(cur_cash, 2)),
        "strategy_type": "dividend_erp",
        "auto_trade": pos.get("auto_trade", True)
    }, account_name=account_name)

    return {
        "success": True,
        "executed": True,
        "message": f"【{account_name}】红利低波ERP调仓撮合完成！目标仓位已校准为 {int(port['target_weight']*100)}%。",
        "trades": executed_trades,
        "plan": plan
    }

if __name__ == "__main__":
    plan = generate_rebalance_plan("sz159915", "sh512890", 20)
    print("=== 今日尾盘调仓执行计划 ===")
    print(f"核心结论: {plan['summary_action']}")
    print(f"执行说明: {plan['reason']}")
    print("清单明细:")
    for o in plan["orders"]:
        print(f"  -> [{o['action']}] {o['name']} ({o['symbol']}): {o['shares']} 股 @ 现价 ¥{o['price']:.3f} 预估金额: ¥{o['est_amount']:.2f}")

    print("\n=== 策略二: 红利低波ERP调仓执行计划 ===")
    div_plan = generate_dividend_rebalance_plan()
    print(f"核心结论: {div_plan['summary_action']}")
    print(f"执行说明: {div_plan['reason']}")
    for o in div_plan["orders"]:
        print(f"  -> [{o['action']}] {o['name']} ({o['symbol']}): {o['shares']} 股 @ 现价 ¥{o['price']:.3f} 预估金额: ¥{o['est_amount']:.2f}")
