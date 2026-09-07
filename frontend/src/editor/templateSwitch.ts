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
    case "callout":
      // 밴드는 문장 하나뿐이다: bullet_box/summary의 conclusion과 같은 "그 장의 결론 한 줄"
      // 의미이므로 같은 자리로 담아 다른 템플릿의 결론과 오갈 수 있게 한다
      return { conclusion: slots.text, bullets: [], dropped: [] };
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
    case "callout":
      // 결론은 소실이 아니라 밴드 문장으로 이사한다(dropConclusion 을 부르지 않는다). 불릿과
      // 각주는 밴드에 담을 자리가 없어 소실 목록에 오른다
      dropBullets();
      dropFootnote();
      return { slots: { template: "callout", text: conclusion, tone: "surface1" }, dropped };
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
