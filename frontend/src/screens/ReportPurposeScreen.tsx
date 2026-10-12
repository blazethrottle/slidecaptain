import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, messageOf, type Deck, type ProjectInfo } from "../api/client";
import { BATCH_DISCARD_CONFIRM, BATCH_READ_ONLY_NOTICE } from "../ui/ActiveJobNotice";
import { Button } from "../ui/Button";
import type { SaveStatus } from "../ui/StatusIndicator";

// 보고 목적 단계 (개정판 D3a-2, 계획 4.1). 입력 항목과 저장 계약은 옛 자료 탭의 "보고 정보"와 같다:
// 저장 순간의 deck prop에 이 화면의 보고 정보만 바꿔 덱 전체를 PUT한다. 유형 드롭다운과 예시 화면, 자동 저장은 D3b다.
export const REPORT_TYPES = [
  ["weekly", "주간 업무 보고"],
  ["business", "일반 업무 보고"],
  ["monthly", "월간 보고"],
  ["data", "데이터 설명 보고"],
  ["research", "리서치 결과 보고"],
  ["project", "프로젝트 보고"],
  ["results", "결과 보고"],
  ["approval", "승인요청"],
  ["strategy", "전략기획"],
  ["ir", "IR Pitch Deck"],
] as const satisfies ReadonlyArray<readonly [Deck["meta"]["report_type"], string]>;
// 빠진 유형이 있으면 타입 검사가 실패한다. 없는 옵션의 값은 브라우저가 첫 옵션으로 보여 사용자가 보는 유형과
// 저장된 유형이 달라진다 (D3b-1 리뷰 R3)
type MissingReportType = Exclude<Deck["meta"]["report_type"], (typeof REPORT_TYPES)[number][0]>;
const reportTypesComplete: [MissingReportType] extends [never] ? true : never = true;
void reportTypesComplete;

// 보고 정보 4필드만 비교한다: preset_overrides는 이 화면이 건드리지 않는 필드라 비교에 넣으면
// 다른 단계가 남긴 변경과 무관하게 흔들릴 수 있다
function metaEqual(a: Deck["meta"], b: Deck["meta"]): boolean {
  return a.title === b.title && a.report_type === b.report_type
    && a.presenter === b.presenter && a.audience === b.audience
    && !!a.report_type_confirmed === !!b.report_type_confirmed;  // 확인 표시도 저장할 값이다 (D3b-1 리뷰 R4)
}

export function ReportPurposeScreen({
  project, deck, onDeckChange, onDirtyChange, onScreenReady, onConflict, onSaveStatusChange, readOnly = false,
  readOnlyNotice = false,
}: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  onDirtyChange?: (dirty: boolean) => void;  // 보고 정보가 저장본과 다르면 참 (창 닫기 경고, 묶음 종결 분기)
  // 부모가 단계를 옮기기 전에 플러시하도록. "declined"는 사용자가 머물기를 골랐다는 뜻이다 (D3a-5)
  onScreenReady?: (flush: (() => Promise<boolean | "declined">) | null) => void;
  onConflict?: () => void;  // 저장이 412를 받으면 부모가 충돌 안내를 띄운다
  onSaveStatusChange?: (status: SaveStatus) => void;  // 상단 머리의 저장 상태 (계획 4.1 저장 상태 출처 표)
  // 이 프로젝트의 장 생성 묶음 중(또는 진행 작업 확인 전)에는 보고 정보를 고치지 않는다. readOnlyNotice는 묶음을
  // 확인했을 때만 안내를 보인다 (D3a-5, 계획 4.4)
  readOnly?: boolean;
  readOnlyNotice?: boolean;
}) {
  const [meta, setMeta] = useState(deck.meta);
  const metaRef = useRef(meta);
  metaRef.current = meta;
  const savedMeta = useRef(deck.meta);       // 마지막으로 서버에 실제 반영된 보고 정보
  const [saving, setSaving] = useState(false);
  const [lastSave, setLastSave] = useState<"ok" | "failed" | "conflict">("ok");
  const saveChain = useRef<Promise<boolean>>(Promise.resolve(true));  // 버튼 저장과 플러시를 한 줄로 직렬화
  const [notice, setNotice] = useState("");
  const [success, setSuccess] = useState("");
  const dirty = !metaEqual(meta, savedMeta.current);

  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    onSaveStatusChange?.({ kind: saving ? "saving" : lastSave === "conflict" ? "conflict"
      : lastSave === "failed" ? "save_failed" : dirty ? "unsaved" : "saved" });
  }, [saving, lastSave, dirty, onSaveStatusChange]);
  // 저장한 뒤 내용을 다시 고치면 지난 성공 안내를 지운다 (D2a-4 리뷰 R1)
  useEffect(() => { setSuccess(""); }, [meta]);

  const doSaveMeta = useCallback(async (target: Deck["meta"]): Promise<boolean> => {
    setSaving(true);
    try {
      const updated = { ...deck, meta: target };
      await api.putDeck(project.name, updated, false);
      savedMeta.current = target;
      onDeckChange(updated);
      setNotice("");
      setLastSave("ok");
      setSuccess("보고 정보를 저장했습니다.");
      onDirtyChange?.(!metaEqual(metaRef.current, savedMeta.current));
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 412) {
        setLastSave("conflict");
        onConflict?.();
      } else {
        setLastSave("failed");
        setNotice(messageOf(e));
      }
      return false;
    } finally {
      setSaving(false);
    }
  }, [project.name, deck, onDeckChange, onDirtyChange, onConflict]);

  // 진행 중 저장 뒤에 이어 붙는다: 버튼 클릭 직후 단계를 옮겨도 같은 내용을 낡은 ETag로 다시 보내지 않는다
  const flushMeta = useCallback((): Promise<boolean> => {
    const next = saveChain.current.then(() => {
      if (metaEqual(metaRef.current, savedMeta.current)) return true;  // 저장할 것이 없다
      return doSaveMeta(metaRef.current);
    });
    saveChain.current = next.catch(() => false);
    return next;
  }, [doSaveMeta]);
  // 떠나기 전 확인. 읽기 전용이면 저장하지 않는다(묶음 중 저장은 묶음의 사슬을 끊는다). 고친 입력이 남았으면 버릴지
  // 묻고, 머물기를 고르면 부모가 실패 안내를 띄우지 않게 "declined"를 돌려준다
  const readOnlyRef = useRef(readOnly);
  readOnlyRef.current = readOnly;
  const leaveGuard = useCallback(async (): Promise<boolean | "declined"> => {
    if (readOnlyRef.current && !metaEqual(metaRef.current, savedMeta.current)) {
      return window.confirm(BATCH_DISCARD_CONFIRM) ? true : "declined";
    }
    return flushMeta();
  }, [flushMeta]);
  const locked = saving || readOnly;

  useEffect(() => {
    onScreenReady?.(leaveGuard);
    return () => onScreenReady?.(null);  // 다음 화면이 이 화면의 낡은 플러시를 들고 있지 않게 한다
  }, [onScreenReady, leaveGuard]);

  return (
    <div className="purpose-screen">
      {notice && <p role="alert">{notice}</p>}
      {/* 저장 알림은 상단 머리의 저장 상태 하나로 모은다. 이 글은 보이기만 한다 (D3a 묶음 리뷰 A2) */}
      {success && !notice && <p className="notice">{success}</p>}
      {readOnly && readOnlyNotice && <p role="status">{BATCH_READ_ONLY_NOTICE}</p>}
      <section>
        <h2>보고 정보</h2>
        <div className="field">
          <label>보고서 제목
            <input aria-label="보고서 제목" value={meta.title} disabled={locked}
              onChange={(e) => setMeta({ ...meta, title: e.target.value })} />
          </label>
        </div>
        <div className="field">
          <label>보고 유형
            <select aria-label="보고 유형" value={meta.report_type} disabled={locked}
              // 유형을 직접 고르면 확인 표시를 함께 저장한다. 단계 목록의 "아직 고르지 않았습니다"가 사실과 맞게
              // 한다 (D3b-1 리뷰 R4). 보고 목적 화면을 다시 짜는 D3b-5가 확인 경로를 정리한다
              onChange={(e) => setMeta({ ...meta, report_type: e.target.value as Deck["meta"]["report_type"],
                report_type_confirmed: true })}>
              {REPORT_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            </select>
          </label>
        </div>
        <div className="field">
          <label>보고자 <span className="hint">(이름 또는 부서. 표지에 표기됩니다)</span>
            <input aria-label="보고자" value={meta.presenter ?? ""} disabled={locked}
              onChange={(e) => setMeta({ ...meta, presenter: e.target.value })} />
          </label>
        </div>
        <div className="field">
          <label>피보고자 <span className="hint">(문서에 적히지 않고, 문체와 상세 수준을 맞추는 데만 씁니다)</span>
            <input aria-label="피보고자" value={meta.audience ?? ""} disabled={locked}
              onChange={(e) => setMeta({ ...meta, audience: e.target.value })} />
          </label>
        </div>
        {/* 주 행동 막대: 화면이 길면 창 아래에 붙어 첫 화면 안에 남는다 (D3a-7 사용자 결정, 계획 6절 배치) */}
        <div className="actions primary-bar">
          <Button variant="primary" onClick={() => void flushMeta()} disabled={locked}>보고 정보 저장</Button>
        </div>
      </section>
    </div>
  );
}
