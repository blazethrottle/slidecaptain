import { useEffect, useState } from "react";
import { api, messageOf, type Deck, type Preset } from "../api/client";
import { setPresetOverride } from "./slotOps";

const FONT_FIELDS = [
  ["title_pt", "제목 크기(pt)", 12],
  ["body_pt", "본문 크기(pt)", 12],
  ["box_pt", "강조 박스 크기(pt)", 12],
  ["footnote_pt", "각주 크기(pt)", 9],
] as const;
const COLOR_FIELDS = [
  ["text", "본문 색"], ["accent", "강조 색"], ["box_fill", "강조 박스 배경"],
] as const;

function overrideOf(deck: Deck, group: string, key: string): number | string | undefined {
  const groups = deck.meta.preset_overrides as Record<string, Record<string, number | string>> | undefined;
  return groups?.[group]?.[key];
}

export function DesignPanel({ deck, onApply }: {
  deck: Deck;
  onApply: (edit: (d: Deck) => Deck) => void;
}) {
  const [preset, setPreset] = useState<Preset | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.getPreset().then(setPreset).catch((e) => setError(messageOf(e)));
  }, []);
  if (error) return <p role="alert">{error}</p>;
  if (preset === null) return <p>디자인 값을 불러오는 중...</p>;

  const fontValue = (key: string) =>
    Number(overrideOf(deck, "font_roles", key)
      ?? (preset.font_roles as unknown as Record<string, number>)[key]);
  const colorValue = (key: string) =>
    String(overrideOf(deck, "colors", key)
      ?? (preset.colors as unknown as Record<string, string>)[key]);

  return (
    <details className="design-panel">
      <summary>디자인 값 (이 덱에만 적용)</summary>
      {FONT_FIELDS.map(([key, label, min]) => (
        <label key={key}>{label}
          {/* 값 기반 key: 언두 등으로 덱이 바뀌면 리마운트되어 표시값이 항상 덱 상태를 따른다 */}
          <input key={`${key}:${fontValue(key)}`} aria-label={label} type="number" min={min} step={0.5}
            defaultValue={fontValue(key)}
            onBlur={(e) => {
              const v = Number(e.target.value);
              if (Number.isFinite(v) && v >= min && v !== fontValue(key)) {
                onApply((d) => setPresetOverride(d, "font_roles", key, v));
              }
            }} />
        </label>
      ))}
      {COLOR_FIELDS.map(([key, label]) => (
        <label key={key}>{label}
          {/* 값 기반 key: 언두 등으로 덱이 바뀌면 리마운트되어 표시값이 항상 덱 상태를 따른다 */}
          <input key={`${key}:${colorValue(key)}`} aria-label={label} type="color" defaultValue={`#${colorValue(key)}`}
            onBlur={(e) => {
              // 색 선택기는 드래그 중 change를 연사한다: 확정(blur) 시점에만 반영해 언두와 저장을 지킨다
              const hex = e.target.value.replace("#", "").toUpperCase();
              if (hex !== colorValue(key).toUpperCase()) {
                onApply((d) => setPresetOverride(d, "colors", key, hex));
              }
            }} />
        </label>
      ))}
      <p className="hint">글자 크기 하한(본문 12pt, 각주 9pt)보다 작게는 저장되지 않습니다. 프리셋 자체에 저장하는 기능은 다음 단계에서 제공합니다.</p>
    </details>
  );
}
