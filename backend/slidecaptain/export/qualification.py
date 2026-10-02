"""Artifact-bound native renders, signed independent reviews and final copies.

Trust is a local configuration boundary. Key possession proves neither a human
identity nor the truth of a judgment. No browser field can manufacture a native
render, producer provenance or configured trust key.
"""

import hashlib
import hmac
import json
import os
import re
import stat
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from slidecaptain.export import exporter, history, renderer, reviews
from slidecaptain.models.export_qualification import (
    ExportProvenance, ExportQualification, FinalPublication, IndependentReceipt,
    IndependentReviewRecord, IndependentReviewRequest, NativeRenderRecord,
    QualificationRequest, RenderPage,
)


class QualificationConflict(ValueError):
    pass


class QualificationDeckConflict(QualificationConflict):
    pass


_MAX_RECORDS = 1000
_MAX_RECORD_BYTES = 128 * 1024
_MAX_TOTAL_BYTES = 8 * 1024 * 1024
_SHA = re.compile(r'[0-9a-f]{64}')
_TRUST_NOTICE = '독립 검수 신뢰 설정이나 서명을 확인하지 못했습니다. 로컬 검수자 설정과 영수증을 확인해 주세요.'
_CHANGED = '검수 기준이 바뀌었거나 증거 파일을 확인하지 못했습니다. 입력을 보존한 뒤 다시 조회해 주세요.'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_receipt(receipt: IndependentReceipt) -> bytes:
    return json.dumps(receipt.model_dump(mode='json'), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def native_render_fingerprint(record: NativeRenderRecord) -> str:
    manifest = record.model_dump(mode='json', exclude={'render_fingerprint'})
    return hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _registry_keys(registry: dict) -> dict[str, bytes]:
    try:
        if set(registry) != {'version', 'reviewers'} or type(registry['version']) is not int or registry['version'] != 1:
            raise ValueError('Unknown trust version')
        configured = registry['reviewers']
        if not isinstance(configured, dict) or len(configured) > 100:
            raise ValueError('Invalid identities')
        result = {}
        for identity, entry in configured.items():
            if (not isinstance(identity, str) or not identity.strip() or identity != identity.strip()
                    or identity.casefold() == 'slidecaptain' or len(identity) > 200
                    or not isinstance(entry, dict) or set(entry) != {'key_hex', 'role'}
                    or entry['role'] != 'independent' or not isinstance(entry['key_hex'], str)
                    or not re.fullmatch(r'[0-9a-fA-F]{64,128}', entry['key_hex'])
                    or len(entry['key_hex']) % 2):
                raise ValueError('Invalid trust entry')
            result[identity] = bytes.fromhex(entry['key_hex'])
        if len({name.casefold() for name in result}) != len(result) or len(set(result.values())) != len(result):
            raise ValueError('Overlapping trust identity/key')
        return result
    except (KeyError, TypeError, ValueError) as exc:
        raise QualificationConflict(_TRUST_NOTICE) from exc


def verify_signature(receipt: IndependentReceipt, signature: str, registry: dict) -> None:
    keys = _registry_keys(registry)
    if (receipt.reviewer_id.casefold() == 'slidecaptain' or receipt.run_id == receipt.producer_run_id
            or receipt.reviewer_id not in keys or not _SHA.fullmatch(signature)):
        raise QualificationConflict(_TRUST_NOTICE)
    expected = hmac.new(keys[receipt.reviewer_id], canonical_receipt(receipt), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise QualificationConflict(_TRUST_NOTICE)


def load_trust_registry(path: Path | None) -> dict:
    if path is None:
        raise QualificationConflict(_TRUST_NOTICE)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 128 * 1024:
            raise ValueError('Unsafe registry')
        identity = history._directory_identity(path.parent)
        with history._pin_directory(path.parent, identity) as reader:
            raw, _ = history._read_regular(path, reader=reader)
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=history._object)
        _registry_keys(data)
        return data
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise QualificationConflict(_TRUST_NOTICE) from exc


def _event_names(reader, export_id):
    names = []
    with reader.scan() as entries:
        for entry in entries:
            if entry.name.startswith(f'{export_id}.qualification.') and entry.name.endswith('.json'):
                names.append(entry.name)
                if len(names) > _MAX_RECORDS:
                    raise ValueError('Too many qualification records')
    return sorted(names)


def _witness_names(reader, export_id, ignore=None):
    names = []
    with reader.scan() as entries:
        for entry in entries:
            if entry.name.startswith(f'{export_id}.qualification-witness.') and entry.name.endswith('.json'):
                if entry.name != ignore:
                    names.append(entry.name)
                    if len(names) > _MAX_RECORDS:
                        raise ValueError('Too many qualification witnesses')
    return sorted(names)


def _read_events(directory, export_id, reader, ignore_witness=None):
    records, signatures = [], {}
    try:
        names = _event_names(reader, export_id)
        witnesses = _witness_names(reader, export_id, ignore_witness)
        if len(names) != len(witnesses):
            raise ValueError('Missing qualification event/witness pair')
        total = 0
        for sequence, name in enumerate(names, start=1):
            if name != f'{export_id}.qualification.{sequence:08d}.json':
                raise ValueError('Incomplete qualification sequence')
            total += reader.stat(name).st_size
            if reader.stat(name).st_size > _MAX_RECORD_BYTES or total > _MAX_TOTAL_BYTES:
                raise ValueError('Qualification read limit')
            raw, signatures[name] = history._read_regular(directory / name, reader=reader)
            witness_name = f'{export_id}.qualification-witness.{sequence:08d}.json'
            if witnesses[sequence - 1] != witness_name or reader.stat(witness_name).st_size > 4096:
                raise ValueError('Invalid witness sequence/size')
            witness_raw, signatures[witness_name] = history._read_regular(directory / witness_name, reader=reader)
            total += len(witness_raw)
            if total > _MAX_TOTAL_BYTES:
                raise ValueError('Qualification read limit')
            witness = json.loads(witness_raw.decode('utf-8'), object_pairs_hook=history._object)
            data = json.loads(raw.decode('utf-8'), object_pairs_hook=history._object)
            model = NativeRenderRecord if data.get('kind') == 'render' else IndependentReviewRecord
            record = model.model_validate(data, strict=True)
            if (not isinstance(witness, dict)
                    or set(witness) != {'rule_version', 'sequence', 'id', 'event_sha256'}
                    or witness['rule_version'] != 'qualification-witness-v1'
                    or type(witness['sequence']) is not int or witness['sequence'] != sequence
                    or witness['id'] != record.id or witness['event_sha256'] != hashlib.sha256(raw).hexdigest()):
                raise ValueError('Qualification witness mismatch')
            if record.sequence != sequence or datetime.fromisoformat(record.recorded_at).tzinfo is None:
                raise ValueError('Invalid server record identity/time')
            records.append(record)
        if len({item.id for item in records}) != len(records):
            raise ValueError('Duplicate server record')
        if (_event_names(reader, export_id) != names
                or _witness_names(reader, export_id, ignore_witness) != witnesses
                or any(not history._still_same(directory/name, sig, reader)
                                                          for name, sig in signatures.items())):
            raise ValueError('Qualification changed during read')
        return records, 'readable' if records else 'empty'
    except (OSError, ValueError, UnicodeError, RecursionError, AttributeError):
        return [], 'invalid'


def _read_binary(directory, name, reader, limit):
    before = reader.stat(name)
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise QualificationConflict(_CHANGED)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(reader.open(name, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        windows = os.name == 'nt'
        if history._path_fd_signature(opened, windows=windows) != history._path_fd_signature(before, windows=windows):
            raise QualificationConflict(_CHANGED)
        data = stream.read(limit + 1)
        if len(data) > limit or history._signature(os.fstat(stream.fileno())) != history._signature(opened):
            raise QualificationConflict(_CHANGED)
    if not history._still_same(directory / name, history._signature(before), reader):
        raise QualificationConflict(_CHANGED)
    return data


def _read_provenance(directory, export_id, reader, fingerprint, artifact):
    try:
        raw, _ = history._read_regular(directory / f'{export_id}.provenance.json', reader=reader)
        result = ExportProvenance.model_validate(json.loads(raw.decode('utf-8'), object_pairs_hook=history._object), strict=True)
        if result.input_fingerprint != fingerprint or result.artifact_sha256 != artifact:
            return None
        return result
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None


def _render_valid(directory, export_id, record, reader, basis):
    if record.status != 'rendered':
        return record.status
    if record.input_fingerprint != basis.input_fingerprint or record.artifact_sha256 != basis.artifact_sha256:
        return 'stale'
    try:
        if not record.render_fingerprint or record.render_fingerprint != native_render_fingerprint(record):
            return 'unavailable'
        environment = renderer.current_environment()
        if environment['fingerprint'] != record.environment_fingerprint:
            return 'stale'
        if (record.environment.get('fingerprint') != record.environment_fingerprint
                or not record.environment.get('powerpoint_version') or not record.environment.get('powerpoint_build')
                or [page.page for page in record.pages] != list(range(1, basis.slide_count + 1))):
            return 'unavailable'
        for page in record.pages:
            if page.filename != f'{export_id}.render.{record.id}.page{page.page:04d}.png':
                return 'unavailable'
            data = _read_binary(directory, page.filename, reader, renderer.MAX_PAGE_BYTES)
            if (hashlib.sha256(data).hexdigest() != page.sha256
                    or renderer.validate_png(data) != (page.width, page.height)):
                return 'unavailable'
    except (OSError, ValueError):
        return 'unavailable'
    return 'rendered'


def _snapshot(directory, export_id, inputs, reader, trust_path, ignore_witness=None):
    basis = reviews._snapshot(directory, export_id, inputs, reader)
    records, storage = _read_events(directory, export_id, reader, ignore_witness)
    provenance = _read_provenance(directory, export_id, reader, basis.input_fingerprint, basis.artifact_sha256)
    render = next((r for r in reversed(records) if isinstance(r, NativeRenderRecord)), None)
    independent = next((r for r in reversed(records) if isinstance(r, IndependentReviewRecord)), None)
    blockers = []
    if basis.status != 'current':
        blockers.append(basis.reason or '현재 입력과 출력이 일치하지 않습니다.')
    if provenance is None:
        blockers.append('생산 실행 provenance를 확인하지 못했습니다. 현재 버전에서 새 초안을 내보내 주세요.')
    if storage == 'invalid':
        blockers.append('검수 증거 저장소가 손상되었거나 읽기 한도를 초과했습니다. 과거 통과로 대신하지 않습니다.')
    render_status = _render_valid(directory, export_id, render, reader, basis) if render else 'not_run'
    if storage == 'invalid':
        render_status = 'unavailable'
    if render_status != 'rendered':
        blockers.append(render.reason if render and render.reason else '현재 출력의 native PowerPoint 전체 페이지 렌더 증거가 없습니다.')
    independent_status = 'not_run'
    trust_available = False
    try:
        registry = load_trust_registry(trust_path)
        trust_available = bool(_registry_keys(registry))
        if not trust_available:
            raise QualificationConflict(_TRUST_NOTICE)
        if independent:
            verify_signature(independent.receipt, independent.signature, registry)
            receipt = independent.receipt
            if (provenance is None or render_status != 'rendered'
                    or receipt.producer_run_id != provenance.producer_run_id
                    or receipt.input_fingerprint != basis.input_fingerprint or receipt.artifact_sha256 != basis.artifact_sha256
                    or receipt.render_id != render.id or receipt.environment_fingerprint != render.environment_fingerprint
                    or receipt.render_fingerprint != render.render_fingerprint
                    or sorted(receipt.pages) != list(range(1, basis.slide_count + 1))):
                independent_status = 'stale'
            elif (any(v.status != 'passed' for v in receipt.verdicts)
                  or any(not f.resolved and f.severity in ('critical', 'major') for f in receipt.findings)):
                independent_status = 'needs_revision'
            else:
                independent_status = 'passed'
    except QualificationConflict:
        blockers.append(_TRUST_NOTICE)
        if independent:
            independent_status = 'unavailable'
    if storage == 'invalid':
        independent_status = 'unavailable'
    if independent_status != 'passed':
        blockers.append('현재 출력의 다섯 필수 항목과 전체 페이지를 통과한 독립 검수 영수증이 없습니다.')
    if any(item.status == 'needs_revision' for item in basis.categories):
        blockers.append('최신 수동 검수에 수정 필요 판정이 남아 있습니다.')
    _, quality, _ = history._inspect(directory, export_id, inputs.fingerprint, reader=reader)
    if quality is None or any(check.status == 'failed' for check in quality.checks):
        blockers.append('사전 점검에 실패한 항목이 있거나 기록을 확인하지 못했습니다.')
    return ExportQualification(
        export_id=export_id, checked_at=_now(), base_etag=basis.base_etag,
        input_fingerprint=basis.input_fingerprint, artifact_sha256=basis.artifact_sha256, slide_count=basis.slide_count,
        status=basis.status, storage_status=storage, provenance=provenance,
        render_status=render_status, render=render, independent_review_status=independent_status,
        independent_review=independent, final_export_allowed=not blockers,
        can_render=basis.can_record and provenance is not None and storage != 'invalid',
        can_import_review=basis.can_record and provenance is not None and storage != 'invalid' and render_status == 'rendered' and trust_available,
        blockers=list(dict.fromkeys(blockers)),
    ), records


def read_export_qualification(directory: Path, export_id: str, inputs: reviews.ReviewInputs, trust_path: Path | None = None):
    history.validate_export_id(export_id)
    identity = history._directory_identity(directory)
    if identity is None:
        raise history.HistoryNotFound('내보내기 이력을 찾지 못했습니다.')
    with reviews._pin_review_directory(directory, identity) as reader:
        result, _ = _snapshot(directory, export_id, inputs, reader, trust_path)
    if history._directory_identity(directory) != identity:
        raise history.HistoryReadError(_CHANGED)
    return result


def _require_basis(state, request, if_match):
    if state.base_etag is None or if_match.strip('"') != state.base_etag.strip('"'):
        raise QualificationDeckConflict('검수를 시작한 뒤 덱이 바뀌었습니다. 입력을 보존한 뒤 다시 조회해 주세요.')
    if (state.status != 'current' or state.storage_status == 'invalid'
            or state.input_fingerprint != request.expected_input_fingerprint
            or state.artifact_sha256 != request.expected_artifact_sha256):
        raise QualificationConflict(_CHANGED)


@contextmanager
def _mutation(directory, export_id, get_inputs, trust_path, request, if_match):
    history.validate_export_id(export_id)
    identity = history._directory_identity(directory)
    if identity is None:
        raise history.HistoryNotFound('내보내기 이력을 찾지 못했습니다.')
    try:
        with reviews._pin_review_directory(directory, identity) as reader:
            with reviews._review_lock(directory, reader) as lock_signature:
                state, records = _snapshot(directory, export_id, get_inputs(), reader, trust_path)
                _require_basis(state, request, if_match)
                if len(records) >= _MAX_RECORDS:
                    raise QualificationConflict('검수 증거 기록 한도를 초과했습니다.')
                def verify(ignore_witness=None):
                    if (history._directory_identity(directory) != identity
                            or not history._still_same(directory / reviews._LOCK_NAME, lock_signature, reader)):
                        raise QualificationConflict(_CHANGED)
                    latest, latest_records = _snapshot(directory, export_id, get_inputs(), reader, trust_path, ignore_witness)
                    _require_basis(latest, request, if_match)
                    if latest_records != records or latest.provenance != state.provenance:
                        raise QualificationConflict(_CHANGED)
                    return latest
                yield reader, state, records, verify
    except (OSError, reviews.ReviewConflict) as exc:
        raise QualificationConflict(_CHANGED) from exc


def _publish_bytes(directory, reader, name, data, verify):
    temp_name = f'.slidecaptain-qualified-{uuid.uuid4().hex}.tmp'
    fd = reviews._create_regular(reader, temp_name)
    signature = None
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            written_info = os.fstat(stream.fileno())
            signature = history._signature(written_info)
        _, signature = exporter._seal_staged(directory / temp_name, written_info,
                                              hashlib.sha256(data).hexdigest(), reader)
        verify()
        if not history._still_same(directory / temp_name, signature, reader):
            raise QualificationConflict(_CHANGED)
        if reader.fd is not None:
            os.link(temp_name, name, src_dir_fd=reader.fd, dst_dir_fd=reader.fd, follow_symlinks=False)
        else:
            os.link(reader.path / temp_name, reader.path / name, follow_symlinks=False)
        # Detect a source-name substitution during link publication. Linking
        # itself changes ctime, so bind identity/regular mode/size/mtime instead.
        source_info, target_info = reader.stat(temp_name), reader.stat(name)
        expected = (signature[0], signature[1], signature[3], signature[4])
        for info in (source_info, target_info):
            if (not stat.S_ISREG(info.st_mode)
                    or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != expected):
                raise QualificationConflict(_CHANGED)
        published = _read_binary(directory, name, reader, len(data))
        if not hmac.compare_digest(hashlib.sha256(published).hexdigest(), hashlib.sha256(data).hexdigest()):
            raise QualificationConflict(_CHANGED)
        actual_identity = (os.fstat(reader.fd).st_dev, os.fstat(reader.fd).st_ino) if reader.fd is not None else history._directory_identity(reader.path)
        if history._directory_identity(directory) != actual_identity:
            raise QualificationConflict(_CHANGED)
    finally:
        # Retain our hidden staging name. stat-then-unlink is not an atomic
        # ownership operation and could delete a foreign replacement. Cleanup
        # requires a separate, deliberate maintenance operation.
        pass


def _append_record(directory, reader, export_id, record, verify):
    data = (record.model_dump_json(indent=2) + '\n').encode('utf-8')
    total = sum(reader.stat(name).st_size for name in
                [*_event_names(reader, export_id), *_witness_names(reader, export_id)])
    witness_name = f'{export_id}.qualification-witness.{record.sequence:08d}.json'
    witness = {'rule_version': 'qualification-witness-v1', 'sequence': record.sequence,
               'id': record.id, 'event_sha256': hashlib.sha256(data).hexdigest()}
    witness_data = (json.dumps(witness, sort_keys=True, separators=(',', ':')) + '\n').encode()
    if len(data) > _MAX_RECORD_BYTES or total + len(data) + len(witness_data) > _MAX_TOTAL_BYTES:
        raise QualificationConflict('검수 증거 기록 한도를 초과했습니다.')
    # Witness first reserves the sequence. A crash/failed second link leaves an
    # incomplete pair and every ordinary reader fails closed. Only this write's
    # verification may omit its own pending witness while rechecking the basis.
    _publish_bytes(directory, reader, witness_name, witness_data, verify)
    _publish_bytes(directory, reader, f'{export_id}.qualification.{record.sequence:08d}.json', data,
                   lambda: verify(witness_name))


def render_export(directory: Path, export_id: str, request: QualificationRequest, if_match: str,
                  get_inputs, trust_path: Path | None = None):
    # Project lock is owned by the caller. Native execution does not trust any
    # browser renderer/environment fields and receives a checked staging copy.
    with _mutation(directory, export_id, get_inputs, trust_path, request, if_match) as (reader, state, records, verify):
        if not state.can_render:
            raise QualificationConflict('; '.join(state.blockers))
        if len(records) + 2 > _MAX_RECORDS:
            raise QualificationConflict('렌더 시작/완료 증거를 남길 기록 공간이 부족합니다.')
        attempt = NativeRenderRecord(id=uuid.uuid4().hex, sequence=len(records)+1, recorded_at=_now(),
                                     input_fingerprint=request.expected_input_fingerprint,
                                     artifact_sha256=request.expected_artifact_sha256, status='not_run',
                                     reason='렌더를 시작했으나 전체 페이지와 환경을 아직 확인하지 못했습니다.',
                                     environment_fingerprint=None, render_fingerprint=None, environment={}, pages=[])
        _append_record(directory, reader, export_id, attempt, verify)
        # The closure and this operation share the list. Subsequent writes must
        # observe the durable started event, so crashes cannot expose old passes.
        records.append(attempt)
        render_id = uuid.uuid4().hex
        pages, environment = [], {}
        status, reason = 'rendered', None
        try:
            data = _read_binary(directory, f'{export_id}.pptx', reader, renderer.MAX_ARTIFACT_BYTES)
            if hashlib.sha256(data).hexdigest() != request.expected_artifact_sha256:
                raise QualificationConflict(_CHANGED)
            with tempfile.TemporaryDirectory(prefix='slidecaptain-render-') as staging:
                source = Path(staging) / 'input.pptx'
                source.write_bytes(data)
                environment, images = renderer.render_powerpoint(source, Path(staging) / 'pages', state.slide_count)
                if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != request.expected_artifact_sha256:
                    raise renderer.RenderFailed('렌더 입력 사본이 바뀌었습니다.')
                if len(images) != state.slide_count or sum(map(len, images)) > renderer.MAX_TOTAL_BYTES:
                    raise renderer.RenderFailed('native 렌더 페이지 수가 출력과 다릅니다.')
                for number, image in enumerate(images, start=1):
                    width, height = renderer.validate_png(image)
                    name = f'{export_id}.render.{render_id}.page{number:04d}.png'
                    _publish_bytes(directory, reader, name, image, verify)
                    pages.append(RenderPage(page=number, filename=name, sha256=hashlib.sha256(image).hexdigest(), width=width, height=height))
        except renderer.RenderUnavailable as exc:
            status, reason = 'not_run', str(exc)
        except (renderer.RenderFailed, ValueError, OSError) as exc:
            if isinstance(exc, QualificationConflict):
                raise
            status, reason = 'failed', 'PowerPoint 렌더 전체 페이지와 환경을 확인하지 못했습니다.'
        record = NativeRenderRecord(id=render_id, sequence=len(records)+1, recorded_at=_now(),
                                    input_fingerprint=request.expected_input_fingerprint,
                                    artifact_sha256=request.expected_artifact_sha256, status=status, reason=reason,
                                    environment_fingerprint=environment.get('fingerprint') if status == 'rendered' else None,
                                    render_fingerprint=None,
                                    environment=environment if status == 'rendered' else {}, pages=pages if status == 'rendered' else [])
        if status == 'rendered':
            record.render_fingerprint = native_render_fingerprint(record)
        _append_record(directory, reader, export_id, record, verify)
        result, _ = _snapshot(directory, export_id, get_inputs(), reader, trust_path)
        _require_basis(result, request, if_match)
        if result.render != record:
            raise QualificationConflict(_CHANGED)
    return result


def append_independent_review(directory: Path, export_id: str, request: IndependentReviewRequest,
                              if_match: str, get_inputs, trust_path: Path | None = None):
    with _mutation(directory, export_id, get_inputs, trust_path, request, if_match) as (reader, state, records, verify):
        if not state.can_import_review:
            raise QualificationConflict('; '.join(state.blockers))
        verify_signature(request.receipt, request.signature, load_trust_registry(trust_path))
        receipt = request.receipt
        if (receipt.input_fingerprint != state.input_fingerprint or receipt.artifact_sha256 != state.artifact_sha256
                or receipt.producer_run_id != state.provenance.producer_run_id or receipt.render_id != state.render.id
                or receipt.environment_fingerprint != state.render.environment_fingerprint
                or receipt.render_fingerprint != state.render.render_fingerprint
                or sorted(receipt.pages) != list(range(1, state.slide_count+1))
                or any(isinstance(r, IndependentReviewRecord) and r.receipt.run_id == receipt.run_id for r in records)):
            raise QualificationConflict('독립 검수 영수증의 생산/입력/출력/렌더/페이지 기준이 일치하지 않거나 실행 ID가 중복되었습니다.')
        record = IndependentReviewRecord(id=uuid.uuid4().hex, sequence=len(records)+1,
                                         recorded_at=_now(), receipt=receipt, signature=request.signature)
        def verify_review(ignore_witness=None):
            latest = verify(ignore_witness)
            verify_signature(receipt, request.signature, load_trust_registry(trust_path))
            if not latest.can_import_review or latest.render != state.render:
                raise QualificationConflict(_CHANGED)
        _append_record(directory, reader, export_id, record, verify_review)
        result, _ = _snapshot(directory, export_id, get_inputs(), reader, trust_path)
        _require_basis(result, request, if_match)
        if result.independent_review != record:
            raise QualificationConflict(_CHANGED)
    return result


def publish_final(directory: Path, export_id: str, request: QualificationRequest, if_match: str,
                  get_inputs, trust_path: Path | None = None):
    with _mutation(directory, export_id, get_inputs, trust_path, request, if_match) as (reader, state, records, verify):
        if not state.final_export_allowed:
            raise QualificationConflict('; '.join(state.blockers))
        publication_id = uuid.uuid4().hex
        pptx_name = f'{export_id}.final.{publication_id}.pptx'
        receipt_name = f'{export_id}.final.{publication_id}.json'
        data = _read_binary(directory, f'{export_id}.pptx', reader, renderer.MAX_ARTIFACT_BYTES)
        if hashlib.sha256(data).hexdigest() != state.artifact_sha256:
            raise QualificationConflict(_CHANGED)
        publication = FinalPublication(id=publication_id, export_id=export_id, published_at=_now(),
                                       input_fingerprint=state.input_fingerprint, artifact_sha256=state.artifact_sha256,
                                       producer_run_id=state.provenance.producer_run_id, render_id=state.render.id,
                                       review_record_id=state.independent_review.id,
                                       environment_fingerprint=state.render.environment_fingerprint,
                                       pptx_path=str(directory/pptx_name), receipt_path=str(directory/receipt_name),
                                       render=state.render, independent_review=state.independent_review)
        receipt_data = (publication.model_dump_json(indent=2)+'\n').encode()
        if len(receipt_data) > _MAX_RECORD_BYTES:
            raise QualificationConflict('제출 영수증의 128KB 한도를 초과했습니다. 검수 범위와 근거는 보존하며 게시하지 않습니다.')
        def verify_final():
            latest = verify()
            if not latest.final_export_allowed or latest.render != state.render or latest.independent_review != state.independent_review:
                raise QualificationConflict(_CHANGED)
        # The receipt reserves this UUID if the second publication fails. Copy
        # into our own inode so an external edit of the draft cannot alter final.
        _publish_bytes(directory, reader, receipt_name, receipt_data, verify_final)
        _publish_bytes(directory, reader, pptx_name, data, verify_final)
        verify_final()
    return publication
