"""Missing target PowerPoint can never produce a successful render receipt."""

import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor


def test_missing_native_runtime_fails_closed(tmp_path, monkeypatch):
    from slidecaptain.export import renderer
    monkeypatch.setattr(renderer.sys, 'platform', 'darwin')
    with pytest.raises(renderer.RenderUnavailable, match='PowerPoint'):
        renderer.render_powerpoint(tmp_path/'input.pptx', tmp_path/'pages', 1)


def test_png_validation_rejects_unusable_image():
    from slidecaptain.export.renderer import validate_png
    with pytest.raises(ValueError):
        validate_png(b'not png')


def test_different_project_renders_cannot_enter_native_singleton_together(tmp_path, monkeypatch):
    from slidecaptain.export import renderer
    active = maximum = 0
    guard = threading.Lock()
    monkeypatch.setattr(renderer, '_runtime_paths', lambda: (tmp_path/'PowerPoint', tmp_path/'powershell'))
    def simulated_native(*args):
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with guard:
            active -= 1
        return {}, []
    monkeypatch.setattr(renderer, '_render_powerpoint_unlocked', simulated_native)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(renderer.render_powerpoint,tmp_path/f'{n}.pptx',tmp_path/f'{n}',1) for n in range(2)]
        assert all(result.result() == ({},[]) for result in results)
    assert maximum == 1


def test_native_adapter_never_quits_an_unowned_user_application():
    from slidecaptain.export import renderer
    assert '.Quit(' not in renderer._SCRIPT
    assert '.AutomationSecurity' not in renderer._SCRIPT
