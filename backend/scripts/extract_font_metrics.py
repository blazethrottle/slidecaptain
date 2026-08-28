"""Noto Sans KR(동봉된 정적 레귤러/볼드 파일) 폭 수치를 패키지 자산 JSON으로 추출한다."""

from pathlib import Path

from slidecaptain.metrics.font_metrics import FontMetrics

ASSETS_DIR = Path(__file__).resolve().parents[1] / "slidecaptain" / "fonts" / "assets"
REGULAR = ASSETS_DIR / "NotoSansKR-Regular.ttf"
BOLD = ASSETS_DIR / "NotoSansKR-Bold.ttf"

OUT = Path(__file__).resolve().parents[1] / "slidecaptain" / "metrics" / "assets" / "noto_sans_kr_metrics.json"

if __name__ == "__main__":
    metrics = FontMetrics.from_ttf(REGULAR, BOLD)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(metrics.to_json(), encoding="utf-8")
    print(f"저장: {OUT}")
    print(f"레귤러 한글 균일 폭={metrics.regular.hangul_uniform_width}, 볼드={metrics.bold.hangul_uniform_width}")
