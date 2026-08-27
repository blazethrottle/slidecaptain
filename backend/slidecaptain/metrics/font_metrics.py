"""글자 폭 데이터: 실제 폰트의 advance width로 줄바꿈 지점을 결정론적으로 계산한다 (설계서 5.2).

폭 공식: width_pt = advance / unitsPerEm * font_size_pt
레귤러(malgun.ttf)와 볼드(malgunbd.ttf)는 영문 폭이 다르므로 두 벌을 따로 잰다.
"""

import json
from importlib import resources
from pathlib import Path

HANGUL_START = 0xAC00
HANGUL_END = 0xD7A3

# ASCII 전체 + 자주 나오는 기호 (엔대시, 줄임표, 원화)
_COLLECT_CODEPOINTS = list(range(0x20, 0x7F)) + [0x2013, 0x2026, 0x20A9]

_MALGUN = Path("C:/Windows/Fonts/malgun.ttf")
_MALGUN_BOLD = Path("C:/Windows/Fonts/malgunbd.ttf")


class FaceMetrics:
    """폭 데이터 한 벌 (레귤러 또는 볼드)."""

    def __init__(
        self,
        upem: int,
        widths: dict[int, int],
        hangul_uniform_width: int | None,
        fallback_width: int,
    ) -> None:
        self.upem = upem
        self.widths = widths
        self.hangul_uniform_width = hangul_uniform_width
        self.fallback_width = fallback_width

    def _advance(self, codepoint: int) -> int:
        if HANGUL_START <= codepoint <= HANGUL_END and self.hangul_uniform_width is not None:
            return self.hangul_uniform_width
        return self.widths.get(codepoint, self.fallback_width)

    def width_pt(self, text: str, font_pt: float) -> float:
        units = sum(self._advance(ord(ch)) for ch in text)
        return units / self.upem * font_pt

    @classmethod
    def from_ttf_file(cls, path: str | Path) -> "FaceMetrics":
        from fontTools.ttLib import TTFont

        font = TTFont(str(path))
        upem = font["head"].unitsPerEm
        cmap = font.getBestCmap()
        hmtx = font["hmtx"]

        widths: dict[int, int] = {}
        for cp in _COLLECT_CODEPOINTS:
            glyph = cmap.get(cp)
            if glyph is not None:
                widths[cp] = hmtx[glyph][0]

        # 한글 음절 폭: 전부 같으면 값 하나로 압축, 다르면 전체 표를 보관
        hangul_widths = {
            cp: hmtx[cmap[cp]][0] for cp in range(HANGUL_START, HANGUL_END + 1) if cp in cmap
        }
        distinct = set(hangul_widths.values())
        if len(distinct) == 1:
            hangul_uniform = distinct.pop()
        else:
            hangul_uniform = None
            widths.update(hangul_widths)

        fallback = hangul_uniform if hangul_uniform is not None else max(distinct)
        return cls(upem, widths, hangul_uniform, fallback)

    def to_dict(self) -> dict:
        return {
            "upem": self.upem,
            "widths": {str(k): v for k, v in self.widths.items()},
            "hangul_uniform_width": self.hangul_uniform_width,
            "fallback_width": self.fallback_width,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FaceMetrics":
        return cls(
            upem=data["upem"],
            widths={int(k): v for k, v in data["widths"].items()},
            hangul_uniform_width=data["hangul_uniform_width"],
            fallback_width=data["fallback_width"],
        )


class FontMetrics:
    """레귤러와 볼드 폭 데이터 묶음."""

    def __init__(self, regular: FaceMetrics, bold: FaceMetrics) -> None:
        self.regular = regular
        self.bold = bold

    def face(self, bold: bool) -> FaceMetrics:
        return self.bold if bold else self.regular

    @classmethod
    def from_ttf(cls, regular_path: str | Path, bold_path: str | Path) -> "FontMetrics":
        return cls(
            regular=FaceMetrics.from_ttf_file(regular_path),
            bold=FaceMetrics.from_ttf_file(bold_path),
        )

    @classmethod
    def from_bundled(cls) -> "FontMetrics":
        raw = resources.files("slidecaptain.metrics").joinpath("assets/malgun_metrics.json").read_text("utf-8")
        data = json.loads(raw)
        return cls(
            regular=FaceMetrics.from_dict(data["regular"]),
            bold=FaceMetrics.from_dict(data["bold"]),
        )

    @classmethod
    def load_default(cls) -> "FontMetrics":
        """폰트 파일이 있으면 실측, 없으면 번들 수치 (코어의 OS 무관 동작 보장)."""
        if _MALGUN.exists() and _MALGUN_BOLD.exists():
            return cls.from_ttf(_MALGUN, _MALGUN_BOLD)
        return cls.from_bundled()

    def to_json(self) -> str:
        return json.dumps(
            {"regular": self.regular.to_dict(), "bold": self.bold.to_dict()},
            ensure_ascii=True,
        )
