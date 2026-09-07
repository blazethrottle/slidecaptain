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
    case "cards": {
      // 카드에는 conclusion/footnote에 대응하는 자리가 없다: 불릿만 모으고 배지, 소제목,
      // 꼬리 라벨은 각 카드별로 소실 목록에 남긴다 (2026-09-07 DB-2)
      const dropped: string[] = [];
      const bullets: Bullet[] = [];
      slots.cards.forEach((card, i) => {
        if (card.badge) dropped.push(`${i + 1}번째 카드 배지 "${card.badge}"`);
        if (card.heading) dropped.push(`${i + 1}번째 카드 소제목 "${card.heading}"`);
        if (card.tail) dropped.push(`${i + 1}번째 카드 꼬리 라벨 "${card.tail}"`);
        bullets.push(...(card.bullets ?? []));
      });
      return { bullets, dropped };
    }
    case "process": {
      // cards의 배지/꼬리와 달리 단계 제목은 순서 목록이라는 점에서 다른 템플릿의 불릿과
      // 같은 자리다: 불릿으로 모아 서로 오갈 수 있게 한다 (2026-09-07 DB-3). 부제와 보조
      // 라벨은 대응하는 자리가 없어 소실 목록에 남긴다.
      const dropped: string[] = [];
      const bullets: Bullet[] = slots.steps.map((step) => ({ text: step.heading, level: 0 }));
      slots.steps.forEach((step, i) => {
        if (step.subtitle) dropped.push(`${i + 1}번째 단계 부제 "${step.subtitle}"`);
        step.notes.forEach((note) => dropped.push(`${i + 1}번째 단계 보조 라벨 "${note}"`));
      });
      return { bullets, dropped };
    }
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
    case "cards": {
      // 결론과 각주는 카드에 담을 자리가 없어 소실 목록에 오른다. 불릿은 최소 카드 수(2개)로
      // 고르게 나눠 담는다: 어느 한쪽에만 몰아넣지 않아야 두 카드 다 편집할 거리가 있다
      dropConclusion();
      dropFootnote();
      const mid = Math.ceil(c.bullets.length / 2);
      const emptyCard = (bullets: Bullet[]) =>
        ({ badge: "", heading: "", bullets, tail: "", emphasis: false });
      return {
        slots: { template: "cards", cards: [
          emptyCard(c.bullets.slice(0, mid)),
          emptyCard(c.bullets.slice(mid)),
        ] },
        dropped,
      };
    }
    case "process": {
      // 결론과 각주는 단계에 담을 자리가 없어 소실 목록에 오른다. 단계 제목은 불릿에서
      // 옮겨 오되, 6개를 넘는 만큼은 자르고(소실 목록에 남긴다), 3개에 못 미치면 빈
      // 제목으로 채운다(최소 개수를 항상 만족시킨다).
      dropConclusion();
      dropFootnote();
      const MIN_STEPS = 3, MAX_STEPS = 6;
      const headings = c.bullets.map((b) => b.text);
      if (headings.length > MAX_STEPS) {
        dropped.push(`단계 ${headings.length - MAX_STEPS}개 (최대 ${MAX_STEPS}개까지만 옮길 수 있음)`);
      }
      const kept = headings.slice(0, MAX_STEPS);
      while (kept.length < MIN_STEPS) kept.push("");
      return {
        slots: { template: "process", steps: kept.map((heading) => ({ heading, subtitle: "", notes: [] })) },
        dropped,
      };
    }
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
