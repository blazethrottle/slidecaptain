"""OpenAPI 스키마를 backend/openapi.json으로 덤프한다.

실행: backend 폴더에서 .venv/Scripts/python.exe scripts/dump_openapi.py
프런트 타입 생성까지 한 번에 하려면 이어서:
  npm --prefix ../frontend run generate-types
  (최초 1회는 frontend 폴더 안에서 npm install을 먼저 실행해야 한다)
"""

import json
import tempfile
from pathlib import Path

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore

with tempfile.TemporaryDirectory() as tmp:
    schema = create_app(FileProjectStore(tmp)).openapi()

out = Path(__file__).resolve().parent.parent / "openapi.json"
out.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"기록 완료: {out}")
