// 보존 시각처럼 사용자가 화면 사이에서 맞춰 봐야 하는 시각을 한 형식으로 보인다 (D2a-2 리뷰 R18)
export function formatSavedAt(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}
