#!/usr/bin/env python3
"""Idempotent local startup and macOS login registration."""
import argparse
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import time
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
LABEL='com.quant.daily-pipeline'


def install_login():
    if sys.platform!='darwin':
        raise RuntimeError('登录自启动安装目前仅支持 macOS。')
    folder=Path.home()/'Library/LaunchAgents'
    folder.mkdir(parents=True,exist_ok=True)
    logs=ROOT/'data/user_profile';logs.mkdir(parents=True,exist_ok=True)
    payload=dict(Label=LABEL,ProgramArguments=[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/run_daily_pipeline.py')],WorkingDirectory=str(ROOT),RunAtLoad=True,StartInterval=60,StandardOutPath=str(logs/'daily_pipeline.log'),StandardErrorPath=str(logs/'daily_pipeline_error.log'),EnvironmentVariables={'PYTHONUNBUFFERED':'1'})
    path=folder/(LABEL+'.plist')
    content=plistlib.dumps(payload)
    if path.exists() and path.read_bytes()==content:
        check=subprocess.run(['launchctl','print',f'gui/{os.getuid()}/{LABEL}'],capture_output=True)
        if check.returncode==0:return path
    subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{LABEL}'],capture_output=True)
    path.write_bytes(content)
    subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],check=True)
    return path


def healthy():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=2) as r:
            return r.read().strip()==b'ok'
    except Exception:return False


def main():
    parser=argparse.ArgumentParser(description='启动量化研究台及后台任务')
    parser.add_argument('--install-login',action='store_true',help='安装登录自启动的数据与策略任务')
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    os.chdir(ROOT)
    from services.simulation_store import SimulationStore
    from services.simulation_runtime import ensure_worker
    store=SimulationStore()
    if args.install_login:
        print('登录后台任务已安装：',install_login())
    else:
        check=subprocess.run(['launchctl','print',f'gui/{os.getuid()}/{LABEL}'],capture_output=True) if sys.platform=='darwin' else None
        if check is None or check.returncode:
            print('安装本机登录后台任务…')
            install_login()
    ensure_worker(store)
    if not healthy():
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',8501))==0:
                raise RuntimeError('8501 端口被其他服务占用，请先关闭冲突服务。')
        log=(store.directory/'web.log').open('a')
        subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','streamlit','run',str(ROOT/'app.py'),'--server.port=8501','--server.address=127.0.0.1','--server.headless=true'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        for _ in range(30):
            if healthy():break
            time.sleep(1)
        else:raise RuntimeError('网页未能启动，请查看 data/user_profile/web.log')
    print('量化研究台：http://127.0.0.1:8501/\n数据任务：登录后运行；缺失数据自动补齐，执行窗口仍为交易日 14:45–14:55。')
    if not args.no_browser:
        import webbrowser
        webbrowser.open('http://127.0.0.1:8501/')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(f'启动失败：{exc}',file=sys.stderr)
        raise SystemExit(1)
