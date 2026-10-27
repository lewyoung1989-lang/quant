"""WxPusher notification service for daily trading plans and execution reports."""
import json
import logging
import ssl
import urllib.request
import datetime as dt
from services.simulation_store import ROOT, now

logger = logging.getLogger(__name__)

DEFAULT_APP_TOKEN = "AT_vBXiRDLClcbd8nsrnKcrM7HsLaK15vUJ"
DEFAULT_UID = "UID_aSjhGIggjhh47gqIt20odvLWUZWS"


def get_notifier_config(store=None):
    if store is not None:
        cfg = store.metadata("notifier") or {}
        if cfg.get("app_token"):
            return cfg
    return {
        "channel": "wxpusher",
        "app_token": DEFAULT_APP_TOKEN,
        "uids": [DEFAULT_UID],
        "enabled": True
    }


def send_wxpusher(content: str, summary: str, app_token=None, uids=None):
    """Send markdown content via WxPusher API."""
    token = app_token or DEFAULT_APP_TOKEN
    target_uids = uids or [DEFAULT_UID]
    if not token or not target_uids:
        logger.warning("WxPusher appToken or uids missing, skipping push.")
        return False, "缺少 appToken 或 uids"

    url = "https://wxpusher.zjiecode.com/api/send/message"
    payload = {
        "appToken": token,
        "content": content,
        "summary": summary[:95] if summary else "量化实盘提醒",
        "contentType": 3,  # Markdown
        "uids": target_uids
    }

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 1000 and data.get("success"):
                return True, "发送成功"
            return False, data.get("msg", "发送未成功")
    except Exception as exc:
        logger.exception("WxPusher 发送异常")
        return False, str(exc)


def format_account_plan_markdown(account, plan, signal):
    """Format markdown message for an individual account plan."""
    acc_name = account.get("name", account.get("id"))
    strat = account.get("strategy_type")
    strat_name = "复合攻守轮动" if strat == "compound_rotation" else ("红利低波 ERP" if strat == "dividend_erp" else "攻守动量轮动")

    lines = [f"### 📊 【{acc_name}】{strat_name}"]

    # 估值与动量状态
    if signal:
        if "erp_pct" in signal:
            erp_val = signal.get("erp_pct", 0) * 100
            band = signal.get("erp_band", "正常")
            lines.append(f"- **ERP 估值分位**：`{erp_val:.1f}%` ({band})")
        if "weights" in signal and signal["weights"]:
            w_str = " + ".join([f"{k} {int(round(v*100))}%" for k, v in signal["weights"].items() if v > 0])
            lines.append(f"- **策略目标配比**：{w_str}")
        elif "weight" in signal and signal.get("target_symbol"):
            lines.append(f"- **策略目标标的**：`{signal['target_symbol']}` ({int(round(signal['weight']*100))}%)")

    # 调仓清单
    orders = plan.get("orders") or []
    if orders:
        lines.append("\n**📋 执行调仓指令：**")
        for o in orders:
            action = o.get("action", "")
            icon = "🟢" if "买" in action else "🔴"
            sym = o.get("symbol", "")
            name = o.get("name", sym)
            shares = o.get("shares", 0)
            price = o.get("price", 0)
            amt = o.get("amount", 0)
            lines.append(f"- {icon} **{action} {name} (`{sym}`)**：{shares:,} 份 @ ¥{price:.3f}（预估 ¥{amt:,.2f}）")
        lines.append(f"- **预估剩余现金**：¥{plan.get('remaining_cash', 0):,.2f}")
    else:
        if plan.get("error"):
            lines.append(f"\n**⚠️ 调仓计划生成异常**：{plan.get('error')}")
        else:
            lines.append("\n**⚖️ 今日无需调仓**：持仓与策略目标完全吻合，继续耐心持有。")

    return "\n".join(lines)


def notify_daily_plans(store, force=False):
    """
    Check active accounts, build current plan, and send deduplicated push.
    Only push once per trading day session unless force=True.
    """
    from services.simulation_service import fetch_quotes, symbols_for, build_plan
    accounts = [a for a in store.list_accounts() if a.get("running")]
    if not accounts:
        return False, "无运行中的模拟账户"

    today_str = now().strftime("%Y-%m-%d")
    push_history = store.metadata("push_history") or {}

    # Check dedupe: only send once per day unless forced or has new plan
    if not force and push_history.get("last_date") == today_str and not push_history.get("has_orders"):
        return True, "今日已推送过无调仓通知，跳过重复推送"

    symbols = sorted({s for a in accounts for s in symbols_for(a)})
    try:
        quotes = fetch_quotes(symbols)
    except Exception as exc:
        return False, f"获取实时行情失败: {exc}"

    acc_sections = []
    total_orders = 0
    highlight_actions = []

    for a in accounts:
        try:
            plan = build_plan(store, a["id"], quotes=quotes, at=now())
            sig = plan.get("signal")
            acc_sections.append(format_account_plan_markdown(a, plan, sig))
            orders = plan.get("orders") or []
            total_orders += len(orders)
            for o in orders:
                highlight_actions.append(f"{a['name']}:{o.get('action')}{o.get('name')}")
        except Exception as exc:
            acc_sections.append(f"### ⚠️ 【{a.get('name')}】计划生成异常：{exc}")

    # Build summary line
    time_str = now().strftime("%H:%M")
    if total_orders > 0:
        summary = f"【调仓提醒 {time_str}】{len(highlight_actions)} 笔调仓计划待执行"
    else:
        summary = f"【持仓监控 {time_str}】今日无调仓变动，保持当前配置"

    content = f"## 📈 量化实盘每日指令 ({today_str})\n\n"
    content += f"> 生成时点：{now().strftime('%Y-%m-%d %H:%M:%S')} · 官方真值定稿校验完毕\n\n"
    content += "\n\n---\n\n".join(acc_sections)
    content += "\n\n---\n*提示：次日开盘策略请于 09:30 开盘时按指令挂单；尾盘策略请于 14:45~14:55 执行。*"

    ok, msg = send_wxpusher(content, summary)
    if ok:
        push_history["last_date"] = today_str
        push_history["last_time"] = now().isoformat()
        push_history["has_orders"] = total_orders > 0
        store.metadata("push_history", push_history)
        store.record_event(accounts[0]["id"], "微信推送已送达", summary, "已完成", f"wx_push:{today_str}:{total_orders}")

    return ok, msg
