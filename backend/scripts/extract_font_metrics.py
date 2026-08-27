"""맑은 고딕(레귤러, 볼드) 폭 수치를 패키지 자산 JSON으로 추출한다 (Windows에서 1회 실행)."""

from pathlib import Path

from slidecaptain.metrics.font_metrics import FontMetrics

OUT = Path(__file__).resolve().parents[1] / "slidecaptain" / "metrics" / "assets" / "malgun_metrics.json"

if __name__ == "__main__":
    metrics = FontMetrics.from_ttf("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/malgunbd.ttf")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(metrics.to_json(), encoding="utf-8")
    print(f"저장: {OUT}")
    print(f"레귤러 한글 균일 폭={metrics.regular.hangul_uniform_width}, 볼드={metrics.bold.hangul_uniform_width}")
