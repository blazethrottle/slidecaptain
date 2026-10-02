"""Owned desktop service: reserve a port, authenticate every request, watch parent EOF.

The desktop parent supplies session configuration through its child's environment,
not CLI arguments. The only stdout record is a nonsecret readiness message.
"""
import argparse
import asyncio
import json
import os
import socket
import sys
import threading
from pathlib import Path

import uvicorn

from slidecaptain import __version__
from slidecaptain.desktop_processes import ProcessFence
from slidecaptain.__main__ import _find_ui_dir
from slidecaptain.pipeline.connections import AIConnections
from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


async def serve(data_dir: Path):
    fence = ProcessFence()
    token = os.environ.pop("SLIDECAPTAIN_DESKTOP_SESSION", None)
    instance = os.environ.pop("SLIDECAPTAIN_DESKTOP_INSTANCE", None)
    ui = _find_ui_dir()
    if ui is None:
        raise ValueError("Desktop UI is missing; build the frontend before starting.")
    manager = AIConnections(data_dir / "ai-settings.json")
    app = create_app(FileProjectStore(data_dir), ai_connections=manager, static_dir=ui,
                     desktop_session_token=token, desktop_instance_id=instance)
    if token is None or instance is None:
        raise ValueError("Desktop session configuration is required")
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False,
                                          timeout_graceful_shutdown=5))
    loop = asyncio.get_running_loop()
    finished = threading.Event()

    def parent_lifeline():
        # The parent keeps its child's stdin pipe open. EOF also catches SIGKILL
        # of Electron main without trusting a PID that another process may reuse.
        try:
            while sys.stdin.buffer.read(1):
                pass
        except OSError:
            pass
        if finished.is_set():
            return
        loop.call_soon_threadsafe(setattr, server, "should_exit", True)
        # Only this service exits; no system-wide process termination or PID lookup.
        if not finished.wait(10):
            fence.force_exit(1)

    threading.Thread(target=parent_lifeline, daemon=True).start()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    task = None
    try:
        sock.bind(("127.0.0.1", 0))
        sock.setblocking(False)
        port = sock.getsockname()[1]
        task = asyncio.create_task(server.serve(sockets=[sock]))
        while not server.started and not task.done() and not server.should_exit:
            await asyncio.sleep(0.02)
        if server.started and not server.should_exit and not task.done():
            print(json.dumps({"event": "ready", "product": "slidecaptain", "version": __version__,
                              "port": port, "desktop_instance_id": instance, "ui_ready": True}), flush=True)
        await task
    finally:
        finished.set()
        sock.close()
        if task is not None and not task.done():
            server.should_exit = True
            await task
        manager.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "slidecaptain-projects")
    args = parser.parse_args()
    try:
        asyncio.run(serve(args.data_dir))
        return 0
    except (ValueError, OSError):
        print("SlideCaptain desktop service could not start. Check the app installation and data directory.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
