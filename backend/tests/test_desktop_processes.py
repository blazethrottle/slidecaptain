"""Force shutdown must stop children owned by this service, never a foreign group."""
import os
import subprocess
import sys
import time

import pytest


def test_force_shutdown_terminates_owned_child():
    code = '''
import subprocess, sys
from slidecaptain.desktop_processes import ProcessFence
fence = ProcessFence()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
print(child.pid, flush=True)
fence.force_exit(1)
'''
    parent = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True)
    try:
        line = parent.stdout.readline()
        assert line.strip().isdigit()
        pid = int(line)
        parent.wait(timeout=5)
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.GetExitCodeProcess.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if handle:
                try:
                    exit_code = wintypes.DWORD()
                    assert kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                    assert exit_code.value != 259  # STILL_ACTIVE
                finally:
                    kernel.CloseHandle(handle)
        else:
            for _ in range(40):
                result = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
                if not result.stdout.strip() or result.stdout.lstrip().startswith('Z'):
                    break
                time.sleep(.05)
            else:
                pytest.fail('The owned child survived force shutdown')
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
