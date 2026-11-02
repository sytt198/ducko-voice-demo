#!/usr/bin/env python3
"""Start/reuse the localhost demo and open a normal browser. No installation."""
import argparse
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import webbrowser

from healthcheck import check_server


ROOT = Path(__file__).resolve().parent


@contextmanager
def launch_guard(port):
    """A process-scoped OS lock prevents two double-clicks from racing."""
    folder = ROOT / '.local'
    folder.mkdir(exist_ok=True)
    lock = (folder / f'launch-{port}.lock').open('a+b')
    acquired = False
    try:
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            pass
        yield acquired
    finally:
        if acquired:
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def port_in_use(port):
    with socket.socket() as sock:
        sock.settimeout(.5)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def start(args):
    status = check_server(args.port)
    if not status['ok']:
        if port_in_use(args.port):
            print('This port is occupied by another service. Nothing was stopped.')
            print('Try: start_demo.cmd --port 8771')
            return 1
        if not (ROOT / 'server.py').is_file() or not (ROOT / 'index.html').is_file():
            print('The complete demo folder is required; do not move this launcher alone.')
            return 1
        state_dir = ROOT / '.local'
        state_dir.mkdir(exist_ok=True)
        environment = os.environ.copy()
        vendor = ROOT / '.asr-vendor'
        if vendor.is_dir() and importlib.util.find_spec('vosk') is None:
            environment['PYTHONPATH'] = str(vendor) + (os.pathsep + environment['PYTHONPATH'] if environment.get('PYTHONPATH') else '')
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        log_path = state_dir / f'server-{args.port}.log'
        with log_path.open('ab') as log:
            process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'server.py'), '--port', str(args.port)],
                cwd=str(ROOT), env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=flags, start_new_session=os.name != 'nt')
        for _ in range(40):
            if process.poll() is not None:
                print('The server stopped during startup. Check:', log_path)
                return 1
            status = check_server(args.port, timeout=.5)
            if status['ok']:
                break
            time.sleep(.25)
        if not status['ok']:
            print('The server did not become ready. Check:', log_path)
            return 1
        (state_dir / f'server-{args.port}.json').write_text(json.dumps({'pid': process.pid, 'port': args.port, 'python': sys.executable}), encoding='utf-8')
        print('Started local server PID', process.pid)
    else:
        print('Reusing the existing DUCKO service. No second server was started.')
    print(status['url'])
    print('Local speech languages:', ', '.join(status.get('asr_languages', [])) or 'not installed')
    if not status.get('asr_available'):
        print('Python recognition is not installed; the page can load its browser speech model on first use.')
    else:
        print('Use a normal Edge, Chrome or Firefox window. Click Tap to speak and allow the microphone.')
    if not args.no_browser:
        if not webbrowser.open(status['url'], new=2):
            print('Open the URL above in your browser manually.')
    return 0


def main():
    parser = argparse.ArgumentParser(description='Launch the DUCKO microphone demo locally')
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--no-browser', action='store_true', help='Only prepare/check the service')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Port must be between 1024 and 65535')
    with launch_guard(args.port) as acquired:
        if not acquired:
            print('Another launcher is already starting this port. Wait for its browser window.')
            return 0
        return start(args)


if __name__ == '__main__':
    raise SystemExit(main())
