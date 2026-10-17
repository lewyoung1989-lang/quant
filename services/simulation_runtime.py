"""Start one local worker per account database; process status is visible in the UI."""
import datetime as dt
import os
import subprocess
import sys

from services.simulation_store import ROOT, SHANGHAI, now


def worker_alive(store):
    state = store.metadata("worker") or {}
    try:
        age = (now() - dt.datetime.fromisoformat(state["heartbeat"]).astimezone(SHANGHAI)).total_seconds()
        if state.get("status") not in ("运行中", "启动中") or not 0 <= age < 120:
            return False
        os.kill(int(state["pid"]), 0)
        return True
    except (KeyError, ValueError, OSError, TypeError):
        return False


def ensure_worker(store):
    if os.environ.get("QUANT_DISABLE_WORKER") == "1" or worker_alive(store):
        return
    if not any(a["auto_trade"] and a["running"] for a in store.list_accounts()):
        return
    with (store.directory / "simulation_worker.log").open("a") as output:
        process = subprocess.Popen([sys.executable, str(ROOT / "scripts/run_simulation_worker.py"), "--profile-dir", str(store.directory.resolve())], cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True)
    store.metadata("worker", {"heartbeat": now().isoformat(), "status": "启动中", "pid": process.pid, "message": "自动模拟进程正在启动。"})
