"""Transactional simulation accounts; legacy JSON files remain untouched."""
import contextlib
import datetime as dt
import json
import math
import os
import sqlite3
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = {"rotation": "攻守动量轮动", "compound_rotation": "复合攻守轮动", "dividend_erp": "红利低波 ERP 择时"}
ATTACKS = {"sz159915", "sh588380", "sh588000", "sh510300", "sh510500"}
DIV_DEFENSES = {"sh512890", "sh510880"}
BOND_DEFENSES = {"sh511260", "sh511010", "sh511090"}
DEFENSES = {"sh511010", "sh511260", "sh512890", "sh510880", "sh511090"}


def now():
    return dt.datetime.now(SHANGHAI)


def timestamp():
    return now().isoformat(timespec="seconds")


def defaults(strategy, legacy=False):
    if strategy == "dividend_erp":
        return {"threshold_low": .20, "threshold_high": .35,
                "weight_low": .50 if legacy else 0.0, "weight_mid": .75 if legacy else .50, "weight_high": 1.0, "defensive_asset": "cash", "execution_mode": "tail"}
    if strategy == "compound_rotation":
        return {
            "tech_symbol": "sz159915", "div_symbol": "sh512890", "bond_symbol": "sh511260",
            "lookback_window": 20, "execution_mode": "next_open",
            "use_bias_exit": True, "use_trend_filter": True,
            "th_overheat": 0.20, "th_neutral": 0.35
        }
    return {"tech_symbol": "sh588380", "def_symbol": "sh511010", "lookback_window": 20}


class AccountError(ValueError):
    pass


class _Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def amount(value, minimum=.01, maximum=1_000_000_000):
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise AccountError("请输入有效金额。")
    if not math.isfinite(result) or not minimum <= result <= maximum or abs(result - round(result, 2)) > 1e-6:
        raise AccountError(f"金额须为 {minimum:,.2f}–{maximum:,.2f} 元，最多两位小数。")
    return round(result, 2)


def validate_config(strategy, config):
    if strategy not in STRATEGIES:
        raise AccountError("请选择已支持的模拟策略。")
    config = dict(config)
    if strategy == "dividend_erp":
        config.setdefault("defensive_asset", "cash")
        config.setdefault("execution_mode", "tail")
    elif strategy == "compound_rotation":
        # 兼容旧配置中的单一 def_symbol
        if "def_symbol" in config and "bond_symbol" not in config:
            def_s = config.pop("def_symbol")
            if def_s in DIV_DEFENSES:
                config["div_symbol"] = def_s
            else:
                config["bond_symbol"] = def_s
        config.setdefault("div_symbol", "sh512890")
        config.setdefault("bond_symbol", "sh511260")
        config.setdefault("lookback_window", 20)
        config.setdefault("execution_mode", "next_open")
        config.setdefault("use_bias_exit", True)
        config.setdefault("use_trend_filter", True)
        config.setdefault("th_overheat", 0.20)
        config.setdefault("th_neutral", 0.35)

    expected = defaults(strategy)
    if set(config) != set(expected):
        raise AccountError("策略参数不完整，请重新填写。")
    if strategy == "rotation":
        if config["tech_symbol"] not in ATTACKS or config["def_symbol"] not in DEFENSES:
            raise AccountError("请选择支持的进攻与防守 ETF。")
        n = config["lookback_window"]
        if not isinstance(n, (int, float)) or not math.isfinite(n) or int(n) != n or not 5 <= n <= 120:
            raise AccountError("动量周期须为 5–120 个交易日。")
    elif strategy == "compound_rotation":
        if config["tech_symbol"] not in ATTACKS:
            raise AccountError("请选择支持的进攻 ETF。")
        if config["div_symbol"] not in DIV_DEFENSES:
            raise AccountError("请选择支持的防守底仓（红利类）ETF。")
        if config["bond_symbol"] not in BOND_DEFENSES:
            raise AccountError("请选择支持的避险防守（国债类）ETF。")
        n = config["lookback_window"]
        if not isinstance(n, (int, float)) or not math.isfinite(n) or int(n) != n or not 5 <= n <= 120:
            raise AccountError("动量周期须为 5–120 个交易日。")
        if config["execution_mode"] not in ("tail", "next_open"):
            raise AccountError("请选择尾盘实时或次日开盘执行。")
        th_o = float(config["th_overheat"])
        th_n = float(config["th_neutral"])
        if not (0.01 <= th_o < th_n <= 0.99):
            raise AccountError("ERP 阈值须满足：0 < 过热高抛阈值 < 低吸满仓阈值 < 100%。")
    else:
        if config["execution_mode"] not in ("tail", "next_open"):
            raise AccountError("请选择尾盘实时或次日开盘执行。")
        if config["defensive_asset"] not in ("cash", "sh511260"):
            raise AccountError("防守资产请选择现金或十年国债 ETF（511260）。")
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for k, v in config.items() if k not in ("defensive_asset", "execution_mode")):
            raise AccountError("分位阈值与仓位须在 0%–100% 之间。")
        if config["threshold_low"] >= config["threshold_high"]:
            raise AccountError("高估分位上限必须小于低估分位下限。")
        if not config["weight_low"] <= config["weight_mid"] <= config["weight_high"]:
            raise AccountError("仓位须满足：高估仓位 ≤ 常态仓位 ≤ 低估仓位。")
    return dict(config)


class SimulationStore:
    def __init__(self, profile_dir=None):
        self.directory = Path(profile_dir or os.environ.get("QUANT_PROFILE_DIR", ROOT / "data/user_profile"))
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "simulation.sqlite3"
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                  payload TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS entries (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                  account_id TEXT NOT NULL REFERENCES accounts(id), kind TEXT NOT NULL,
                  time TEXT NOT NULL, payload TEXT NOT NULL, dedupe_key TEXT UNIQUE);
                CREATE INDEX IF NOT EXISTS account_entries ON entries(account_id, kind, seq);
                CREATE TABLE IF NOT EXISTS receipts (
                  request_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
        self._migrate()

    def connect(self):
        conn = sqlite3.connect(str(self.path), timeout=15, factory=_Connection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextlib.contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _decode(row):
        if row is None:
            raise AccountError("账户不存在，请重新选择。")
        return {**json.loads(row["payload"]), "id": row["id"], "name": row["name"], "revision": row["revision"]}

    def get(self, account_id, conn=None):
        if conn is not None:
            return self._decode(conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())
        with self.connect() as db:
            return self.get(account_id, db)

    def list_accounts(self):
        with self.connect() as conn:
            return [self._decode(r) for r in conn.execute("SELECT * FROM accounts ORDER BY rowid")]

    def _insert(self, conn, account):
        try:
            conn.execute("INSERT INTO accounts VALUES (?,?,?,?)", (account["id"], account["name"], json.dumps(account, ensure_ascii=False), account["revision"]))
        except sqlite3.IntegrityError:
            raise AccountError("已有同名账户，请换一个便于区分的名称。")

    def _update(self, conn, account, expected_revision):
        account["updated_at"] = timestamp()
        account["revision"] = expected_revision + 1
        try:
            cursor = conn.execute("UPDATE accounts SET name=?, payload=?, revision=? WHERE id=? AND revision=?", (account["name"], json.dumps(account, ensure_ascii=False), account["revision"], account["id"], expected_revision))
        except sqlite3.IntegrityError:
            raise AccountError("已有同名账户，请使用其他名称。")
        if cursor.rowcount != 1:
            raise AccountError("账户已被其他操作更新，请刷新后重试。")

    @staticmethod
    def entry(conn, account_id, kind, data, dedupe_key=None, time=None):
        conn.execute("INSERT OR IGNORE INTO entries(id,account_id,kind,time,payload,dedupe_key) VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), account_id, kind, time or timestamp(), json.dumps(data, ensure_ascii=False), dedupe_key))

    def legacy_opening_snapshot(self, account):
        """Original migration evidence, never synthesize fills from a position balance."""
        name = account.get('legacy_name')
        if not name:
            return None
        source = self.directory / 'simulated_accounts.json'
        try:
            old = json.loads(source.read_text()).get(name)
            if not isinstance(old, dict):
                return None
            positions = []
            for symbol_key, shares_key in [('holding_symbol', 'holding_amount'), ('bond_symbol', 'bond_amount')]:
                symbol, shares = old.get(symbol_key), old.get(shares_key, 0)
                if symbol and isinstance(shares, (int, float)) and math.isfinite(shares) and shares > 0 and int(shares) == shares:
                    positions.append({'symbol': str(symbol).lower(), 'shares': int(shares)})
            if not positions:
                return None
            return {'asof': old.get('updated_at', '未知'), 'positions': positions,
                    'cash': old.get('cash_available'), 'source': source.name,
                    'note': ('此持仓与旧版账户 3 的预置初始化值一致，不是可核实的策略买入；旧版代码预置 61,500 份红利及现金 25,031.50 元。' if name == '模拟实盘 3 号 (红利低波ERP择时高抛低吸)' and positions == [{'symbol': 'sh512890', 'shares': 61500}] and old.get('cash_available') == 25031.5 else '旧账户持仓快照，不是成交回报；无法据此确认首次买入的时间、价格和费用。')}
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def entries(self, account_id, kind, limit=1000):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM entries WHERE account_id=? AND kind=? ORDER BY seq DESC LIMIT ?", (account_id, kind, limit))
            return [{**json.loads(r["payload"]), "id": r["id"], "timestamp": r["time"]} for r in rows]

    def record_event(self, account_id, title, detail, status="已完成", dedupe_key=None):
        with self.transaction() as conn:
            self.entry(conn, account_id, "event", {"title": title, "detail": detail, "status": status}, dedupe_key)

    def create(self, name, initial, strategy, config, auto=False, fee_rate=.0001):
        name = str(name).strip()
        if not name or len(name) > 30:
            raise AccountError("账户名称须为 1–30 个字符。")
        initial = amount(initial, minimum=1000)
        config = validate_config(strategy, config)
        if not math.isfinite(fee_rate) or not 0 <= fee_rate <= .01:
            raise AccountError("费率须在 0–100 万分点之间。")
        account = {"id": "SIM-" + uuid.uuid4().hex[:12].upper(), "name": name, "revision": 1,
                   "initial_capital": initial, "net_capital": initial, "cash_available": initial,
                   "strategy_type": strategy, "parameters": config, "auto_trade": bool(auto),
                   "running": True, "fee_rate": fee_rate, "positions": [], "created_at": timestamp(),
                   "updated_at": timestamp(), "settings_version": 1}
        with self.transaction() as conn:
            self._insert(conn, account)
            self.entry(conn, account["id"], "fund", {"type": "初始资金", "amount": initial, "balance": initial})
            self.entry(conn, account["id"], "event", {"title": "模拟账户已创建", "detail": f"绑定{STRATEGIES[strategy]}，初始资金 ¥{initial:,.2f}。", "status": "已完成"})
        return account

    def configure(self, account_id, revision, name, strategy, config, auto, fee_rate):
        name = str(name).strip()
        if not name or len(name) > 30:
            raise AccountError("账户名称须为 1–30 个字符。")
        config = validate_config(strategy, config)
        if not math.isfinite(fee_rate) or not 0 <= fee_rate <= .01:
            raise AccountError("费率须在 0–100 万分点之间。")
        with self.transaction() as conn:
            a = self.get(account_id, conn)
            if a["revision"] != revision:
                raise AccountError("账户配置已变化，请关闭面板并重新打开。")
            previous = STRATEGIES[a["strategy_type"]]
            a.update(name=name, strategy_type=strategy, parameters=config, auto_trade=bool(auto), fee_rate=fee_rate)
            a["settings_version"] += 1
            self._update(conn, a, revision)
            self.entry(conn, account_id, "event", {"title": "账户配置已更新", "detail": f"{previous} → {STRATEGIES[strategy]}；{'尾盘自动' if auto else '手动执行'}。已有持仓保留。", "status": "已完成"})

    def transfer(self, account_id, revision, value, withdraw=False, request_id=None):
        value = amount(value)
        request_id = request_id or str(uuid.uuid4())
        with self.transaction() as conn:
            receipt = conn.execute("SELECT account_id,result FROM receipts WHERE request_id=?", (request_id,)).fetchone()
            if receipt:
                saved = json.loads(receipt["result"])
                if receipt["account_id"] != account_id or saved["amount"] != (-value if withdraw else value):
                    raise AccountError("请求标识与资金操作不一致，请重新提交。")
                return saved
            a = self.get(account_id, conn)
            if a["revision"] != revision:
                raise AccountError("账户资金已变化，请关闭面板后重新核对。")
            if withdraw and value > a["cash_available"]:
                raise AccountError(f"出金超过可用现金 ¥{a['cash_available']:,.2f}；请先完成卖出。")
            delta = -value if withdraw else value
            a["cash_available"] = round(a["cash_available"] + delta, 2)
            a["net_capital"] = round(a["net_capital"] + delta, 2)
            self._update(conn, a, revision)
            kind = "模拟出金" if withdraw else "模拟入金"
            self.entry(conn, account_id, "fund", {"type": kind, "amount": delta, "balance": a["cash_available"]})
            self.entry(conn, account_id, "event", {"title": kind + "已完成", "detail": f"¥{value:,.2f}；现金 ¥{a['cash_available']:,.2f}。", "status": "已完成"})
            result = {"amount": delta, "balance": a["cash_available"]}
            conn.execute("INSERT INTO receipts VALUES(?,?,?)", (request_id, account_id, json.dumps(result)))
            return result

    def set_running(self, account_id, revision, running):
        with self.transaction() as conn:
            a = self.get(account_id, conn)
            if a["revision"] != revision:
                raise AccountError("账户已变化，请刷新后重试。")
            a["running"] = bool(running)
            self._update(conn, a, revision)
            self.entry(conn, account_id, "event", {"title": "账户已恢复运行" if running else "账户已暂停", "detail": "配置和持仓均已保留。", "status": "已完成"})

    def metadata(self, key, value=None):
        with self.connect() as conn:
            if value is not None:
                conn.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))
                return value
            row = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def receipt(self, key):
        with self.connect() as conn:
            r = conn.execute("SELECT result FROM receipts WHERE request_id=?", (key,)).fetchone()
            return json.loads(r[0]) if r else None

    def _migrate(self):
        with self.transaction() as conn:
            if conn.execute("SELECT 1 FROM metadata WHERE key='legacy_migration' ").fetchone():
                return
            source = self.directory / "simulated_accounts.json"
            legacy = json.loads(source.read_text()) if source.exists() else {}
            if not isinstance(legacy, dict):
                raise AccountError("旧账户文件格式异常，已停止导入；原文件未改动。")
            logs_path = self.directory / "simulated_trades.json"
            logs = json.loads(logs_path.read_text()) if logs_path.exists() else []
            if not isinstance(logs, list):
                raise AccountError("旧成交流水格式异常，已停止导入；原文件未改动。")
            mapping = {}
            for name, old in legacy.items():
                strategy = old.get("strategy_type", "rotation")
                if strategy not in STRATEGIES:
                    raise AccountError(f"旧账户 {name} 的策略类型未知，未执行迁移。")
                parameters = defaults(strategy, legacy=True)
                for key in ("tech_symbol", "def_symbol", "lookback_window"):
                    if key in parameters and key in old:
                        parameters[key] = old[key]
                validate_config(strategy, parameters)
                positions = []
                for symbol, shares in ((old.get("holding_symbol"), old.get("holding_amount", 0)), (old.get("bond_symbol"), old.get("bond_amount", 0))):
                    if shares:
                        if not symbol or int(shares) != shares or shares < 0:
                            raise AccountError("旧账户持仓异常，已停止迁移。")
                        positions.append({"symbol": symbol.lower(), "shares": int(shares), "lots": [{"shares": int(shares), "date": now().date().isoformat()}]})
                a = {"id": "SIM-" + uuid.uuid4().hex[:12].upper(), "name": name, "revision": 1,
                     "initial_capital": amount(old.get("initial_capital", 100000), minimum=0),
                     "net_capital": amount(old.get("net_capital", old.get("initial_capital", 100000)), minimum=0),
                     "cash_available": amount(old.get("cash_available", 0), minimum=0),
                     "strategy_type": strategy, "parameters": parameters, "auto_trade": bool(old.get("auto_trade", False)),
                     "running": True, "fee_rate": .0003, "positions": positions, "settings_version": 1,
                     "created_at": old.get("created_at", timestamp()), "updated_at": timestamp(), "legacy_name": name}
                self._insert(conn, a)
                mapping[name] = a["id"]
                self.entry(conn, a["id"], "fund", {"type": "迁移期初快照", "amount": 0, "balance": a["cash_available"]})
                self.entry(conn, a["id"], "event", {"title": "旧账户已导入", "detail": "原资金、持仓及显式策略配置已保留；旧文件未改动。历史出入金未记录，净投入暂沿用旧初始资金。", "status": "已完成"})
            for row in reversed(logs):
                account_id = mapping.get(row.get("account"))
                if account_id:
                    self.entry(conn, account_id, "trade", {**row, "source": "旧流水导入", "fee": None}, time=row.get("timestamp", timestamp()))
            conn.execute("INSERT INTO metadata VALUES('legacy_migration',?)", (json.dumps({"at": timestamp(), "count": len(mapping), "source": str(source)}),))
