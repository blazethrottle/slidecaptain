"""XLSX 추출기 테스트용 픽스처 생성 도구 (태스크 B1).

저장소에 바이너리를 넣지 않고, 테스트가 openpyxl로 그때그때 만든다(계획서 B1). 계산값 캐시가
있는 파일과 정수처럼 보이는 실수(3.0)의 보존은 openpyxl이 자기가 저장할 때 값을 없애거나
정규화하므로, 저장된 zip의 시트 XML을 직접 문자열 치환한 뒤 새 zip으로 다시 묶어 만든다
(계획서 B1 "픽스처는... XML 사후 치환" 절, 적대 리뷰 실측 근거).
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable

import openpyxl

_CENTRAL_DIR_SIGNATURE = b"PK\x01\x02"


def workbook_bytes(build: Callable[[openpyxl.Workbook], None]) -> bytes:
    """새 Workbook을 만들어 build(wb)로 채운 뒤 저장한 바이트를 돌려준다."""
    wb = openpyxl.Workbook()
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def replace_in_member(data: bytes, member: str, *replacements: tuple[str, str]) -> bytes:
    """zip 안 member(예: "xl/worksheets/sheet1.xml")의 텍스트를 순서대로 문자열 치환하고,
    나머지 항목은 그대로 둔 채 새 zip으로 다시 묶는다. 계산값 캐시(빈 <v></v> 를 <v>15</v> 로)와
    3.0 보존(<v>3</v> 를 <v>3.0</v> 로) 픽스처에 쓴다."""
    with zipfile.ZipFile(io.BytesIO(data)) as src:
        names = src.namelist()
        contents = {name: src.read(name) for name in names}
    target = contents[member].decode("utf-8")
    for old, new in replacements:
        target = target.replace(old, new)
    contents[member] = target.encode("utf-8")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            zf.writestr(name, contents[name])
    return out.getvalue()


def corrupt_crc(data: bytes, member: str) -> bytes:
    """member의 압축 방식을 저장(STORED)으로 바꿔 다시 묶은 뒤, 그 데이터의 첫 바이트를
    뒤집는다. 로컬 헤더와 중앙 디렉터리의 CRC와 크기 필드는 그대로 두므로 그 항목을 읽으면
    zipfile이 CRC 불일치(BadZipFile)를 낸다(비압축이라 바이트를 뒤집어도 압축 스트림 자체가
    깨지지 않는다: 압축 상태로 뒤집으면 DEFLATE 해제 자체가 실패해 다른 예외가 난다)."""
    with zipfile.ZipFile(io.BytesIO(data)) as src:
        names = src.namelist()
        contents = {name: src.read(name) for name in names}

    stored = io.BytesIO()
    with zipfile.ZipFile(stored, "w") as zf:
        for name in names:
            compress_type = zipfile.ZIP_STORED if name == member else zipfile.ZIP_DEFLATED
            zf.writestr(name, contents[name], compress_type=compress_type)
    rezipped = stored.getvalue()

    buf = bytearray(rezipped)
    with zipfile.ZipFile(io.BytesIO(rezipped)) as zf:
        info = zf.getinfo(member)
    offset = info.header_offset
    fname_len = int.from_bytes(buf[offset + 26 : offset + 28], "little")
    extra_len = int.from_bytes(buf[offset + 28 : offset + 30], "little")
    data_start = offset + 30 + fname_len + extra_len
    buf[data_start] ^= 0xFF
    return bytes(buf)


def patch_declared_size(data: bytes, member: str, new_size: int) -> bytes:
    """중앙 디렉터리에 기록된 member의 압축 해제 크기(선언 크기)만 new_size로 바꾼다. 실제
    압축 데이터와 로컬 헤더는 그대로라 CRC 검사 없이 크기만 보는 사전 검사(_check_pre_load_limits
    첫 단계)를 통과한 값으로 잡힌다."""
    buf = bytearray(data)
    pos = 0
    target = member.encode("utf-8")
    while True:
        idx = buf.find(_CENTRAL_DIR_SIGNATURE, pos)
        if idx == -1:
            raise ValueError(f"중앙 디렉터리에서 {member}를 찾지 못했습니다")
        fname_len = int.from_bytes(buf[idx + 28 : idx + 30], "little")
        extra_len = int.from_bytes(buf[idx + 30 : idx + 32], "little")
        comment_len = int.from_bytes(buf[idx + 32 : idx + 34], "little")
        name = bytes(buf[idx + 46 : idx + 46 + fname_len])
        if name == target:
            buf[idx + 24 : idx + 28] = new_size.to_bytes(4, "little")
            return bytes(buf)
        pos = idx + 46 + fname_len + extra_len + comment_len


def not_a_zip_bytes() -> bytes:
    return (b"\x00\x01\x02\x03" + "이건 엑셀 파일이 아닙니다".encode("utf-8")) * 4


def zip_without_content_types() -> bytes:
    """유효한 zip이지만 [Content_Types].xml이 없어 xlsx 구조가 아닌 파일(KeyError 유발)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "그냥 평범한 zip 파일입니다")
    return buf.getvalue()


def pseudo_xlsb_bytes() -> bytes:
    """확장자만 xlsx이고 실제로는 바이너리(xlsb류) 컨테이너인 파일을 흉내낸다: [Content_Types].xml과
    _rels/.rels는 있지만 워크북 파트의 콘텐츠 타입이 xlsx가 아닌 xlsb 바이너리 타입이라 openpyxl이
    워크북 파트를 못 찾는다(OSError)."""
    manifest = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="bin" ContentType="application/vnd.ms-excel.sheet.binary.macroEnabled.main"/>'
        '<Override PartName="/xl/workbook.bin" '
        'ContentType="application/vnd.ms-excel.sheet.binary.macroEnabled.main"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.bin"/>'
        "</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", manifest)
        zf.writestr("_rels/.rels", rels)
        zf.writestr(
            "xl/workbook.bin",
            b"\x00\x01\x02" + "real xlsb는 이렇게 생기지 않았지만 zip 구조만 흉내낸다".encode("utf-8"),
        )
    return buf.getvalue()
