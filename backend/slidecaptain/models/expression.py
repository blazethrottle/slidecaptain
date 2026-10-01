"""Opt-in expressions reference existing facts and exact original text."""

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChartSpec(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,revalidate_instances='always')
    rule_version: Literal['comparison-chart-v1']
    comparison_id: str = Field(pattern=r'^[A-Za-z0-9_-]+$',max_length=64)
    kind: Literal['bar','column']


class TextSpan(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,revalidate_instances='always')
    slot: Literal['eyebrow','subtitle','text','conclusion','bullets']
    index: int | None = Field(default=None,strict=True,ge=0,le=10000)
    start: int = Field(strict=True,ge=0)
    end: int = Field(strict=True,ge=1)
    role: Literal['bold','accent']
    text_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def scope(self):
        if self.end<=self.start or (self.slot=='bullets') != (self.index is not None):
            raise ValueError('강조 범위와 불릿 인덱스를 확인해 주세요.')
        return self


def span_text(slide,span):
    if span.slot in ('eyebrow','subtitle'):
        text=getattr(slide,span.slot)
    elif span.slot=='bullets':
        values=getattr(slide.slots,'bullets',None)
        if values is None or span.index>=len(values):
            raise ValueError('이 문장의 불릿 강조는 지원하지 않습니다.')
        text=values[span.index].text
    else:
        text=getattr(slide.slots,span.slot,None)
    if not isinstance(text,str):
        raise ValueError('지원하는 기존 텍스트 칸을 선택해 주세요.')
    return text


def validate_spans(slide):
    previous={}
    for span in sorted(slide.text_spans,key=lambda item:(item.slot,item.index or 0,item.start)):
        text=span_text(slide,span)
        if span.end>len(text) or hashlib.sha256(text.encode('utf-8')).hexdigest()!=span.text_sha256:
            raise ValueError('강조 기준 문장이 바뀌었거나 범위를 벗어났습니다. 원문을 보존하고 강조를 다시 선택해 주세요.')
        key=(span.slot,span.index)
        if span.start<previous.get(key,0):
            raise ValueError('같은 문장의 강조 범위는 겹칠 수 없습니다.')
        previous[key]=span.end


class ChartPoint(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    evidence_id: str
    label: str
    value: str
    color: str = Field(pattern=r'^[0-9A-Fa-f]{6}$')
    x: float
    y: float
    w: float = Field(ge=0)
    h: float = Field(ge=0)


class ChartPlan(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    rule_version: Literal['comparison-chart-plan-v1']='comparison-chart-plan-v1'
    kind: Literal['bar','column']
    comparison_id: str
    claim_id: str
    definition: str
    unit: str
    conditions: str
    axis_minimum: str
    axis_maximum: str
    plot_x: float
    plot_y: float
    plot_w: float = Field(gt=0)
    plot_h: float = Field(gt=0)
    font_pt: float = Field(ge=12)
    text_color: str = Field(pattern=r'^[0-9A-Fa-f]{6}$')
    points: list[ChartPoint] = Field(min_length=2,max_length=2)


class TextRun(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text: str
    bold: bool
    color: str = Field(pattern=r'^[0-9A-Fa-f]{6}$')
