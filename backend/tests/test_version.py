"""버전 단일 출처 검증 (태스크 D2-1).

`slidecaptain.__version__` 이 유일한 버전 값이고, `pyproject.toml` 은 그 값을 동적으로
읽으며, FastAPI 앱과 OpenAPI 문서도 같은 값을 노출하는지 확인한다.
"""

import re
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

import slidecaptain
from slidecaptain.server.app import create_app

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def test_version_format():
    assert VERSION_PATTERN.match(slidecaptain.__version__)


def test_pyproject_declares_dynamic_version():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data["project"]
    assert "version" in project.get("dynamic", [])
    assert "version" not in project


def test_app_and_openapi_expose_same_version(store):
    app = create_app(store)
    assert app.version == slidecaptain.__version__
    schema = app.openapi()
    assert schema["info"]["version"] == slidecaptain.__version__


def test_installed_package_metadata_matches_version():
    """worktree 가 빌린 가상환경은 main 클론의 정적 메타데이터를 읽으므로 이 테스트는
    setuptools dynamic 메커니즘 자체의 검증이 아니다. 그 검증은 관통(D2-6)의 새 클론
    설치가 유일하며, 여기서는 값이 어긋나지 않는지만 확인한다.
    """
    try:
        installed_version = metadata.version("slidecaptain")
    except metadata.PackageNotFoundError:
        pytest.skip("slidecaptain 패키지가 설치돼 있지 않습니다")
    assert installed_version == slidecaptain.__version__
