import type { Bullet, Deck, Slots, TemplateName } from "../api/client";

type Currency = {
  conclusion?: string;
  bullets: Bullet[];  // 생성 타입 그대로 쓴다: level이 필수 필드라 손으로 만든 유사 타입은 tsc가 거부한다
  footnote?: string;
  dropped: string[];  // 어느 템플릿으로 가든 옮길 수 없는 원본 내용
};

function collect(slots: Slots): Currency {
  switch (slots.template) {
    case "bullet_box":
      return { conclusion: slots.conclusion, bullets: slots.bullets ?? [],
        footnote: slots.footnote || undefined, dropped: [] };
    case "summary":
      return { conclusion: slots.conclusion, bullets: slots.points ?? [], dropped: [] };
    case "compare2": {
      const dropped: string[] = [];
      if (slots.left.heading) dropped.push(`왼쪽 카드 소제목 "${slots.left.heading}"`);
      if (slots.right.heading) dropped.push(`오른쪽 카드 소제목 "${slots.right.heading}"`);
      return { conclusion: slots.conclusion,
        bullets: [...(slots.left.bullets ?? []), ...(slots.right.bullets ?? [])], dropped };
    }
    case "table":
      return { bullets: [], footnote: slots.footnote || undefined, dropped: ["표 내용 전체"] };
    case "cover":
      return { bullets: [], dropped: ["표지 내용 전체"] };
    case "divider":
      return { bullets: [], dropped: ["간지 내용 전체"] };
  }
}

export function switchTemplate(slots: Slots, to: TemplateName): { slots: Slots; dropped: string[] } {
  if (slots.template === to) return { slots, dropped: [] };
  const c = collect(slots);
  const dropped = [...c.dropped];
  const conclusion = c.conclusion ?? "";
  const footnote = c.footnote ?? "";
  const dropBullets = () => { if (c.bullets.length > 0) dropped.push(`불릿 ${c.bullets.length}개`); };
  const dropConclusion = () => { if (conclusion) dropped.push(`결론 "${conclusion}"`); };
  const dropFootnote = () => { if (footnote) dropped.push(`각주 "${footnote}"`); };
  switch (to) {
    case "bullet_box":
      return { slots: { template: "bullet_box", bullets: c.bullets, conclusion, footnote }, dropped };
    case "summary":
      dropFootnote();
      return { slots: { template: "summary", conclusion, points: c.bullets }, dropped };
    case "compare2":
      dropFootnote();
      return { slots: { template: "compare2", conclusion,
        left: { heading: "", bullets: c.bullets }, right: { heading: "", bullets: [] } }, dropped };
    case "table":
      dropBullets();
      dropConclusion();
      return { slots: { template: "table", columns: ["구분", "내용"], rows: [["", ""]], footnote }, dropped };
    case "cover":
      dropBullets(); dropConclusion(); dropFootnote();
      return { slots: { template: "cover", title: "", subtitle: "", date: "" }, dropped };
    case "divider":
      dropBullets(); dropConclusion(); dropFootnote();
      return { slots: { template: "divider", section_no: "", section_title: "" }, dropped };
  }
}

export function applyTemplateSwitch(deck: Deck, chapterId: string, to: TemplateName):
  { deck: Deck; dropped: string[] } {
  const slide = deck.slides.find((s) => s.chapter_id === chapterId);
  const result = slide ? switchTemplate(slide.slots, to) : null;
  const next: Deck = {
    ...deck,
    structure: { chapters: deck.structure.chapters.map((ch) =>
      ch.id === chapterId ? { ...ch, template: to } : ch) },
    slides: result
      ? deck.slides.map((s) => (s.chapter_id === chapterId ? { ...s, slots: result.slots } : s))
      : deck.slides,
  };
  return { deck: next, dropped: result?.dropped ?? [] };
}
