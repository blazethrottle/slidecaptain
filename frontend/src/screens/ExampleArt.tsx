// 보고 유형 예시 그림 (개정판 D3b-6, 계획 4.6). 시안(docs/design/2026-10-02-revision-wireframe.html)의 representativePages를
// 실행해 옮겼다. 색은 styles.css의 예시 토큰(--example-*)으로 칠하고, 화살표 기호와 중점은 선과 글로 바꿨다. 모든 수치와
// 인용은 합성 예시다. 이 파일에는 직접 색을 쓰지 않는다(디자인 토큰 검사가 확인한다)
import type { ReactElement } from "react";
import type { ReportType } from "./reportPurpose";

type ExamplePage = { page: string; description: string; art: ReactElement };

export const EXAMPLE_PAGES: Record<ReportType, ExamplePage> = {
  weekly: {
    page: "이번 주 업무 현황",
    description: "주간 업무 보고 예시: 완료, 진행 중, 지원 필요 상태 보드와 다음 주 우선순위",
    art: <>
      <text x="36" y="35" fontSize="13" fill="var(--example-muted)" fontWeight="600">WEEKLY / 10월 1주</text>
      <text x="36" y="76" fontSize="29" fill="var(--example-ink)" fontWeight="700">완료한 일과 남은 이슈를 한눈에</text>
      <rect x="36" y="109" width="230" height="217" rx="12" fill="var(--example-gray-subtle)"/>
      <rect x="36" y="109" width="230" height="6" rx="2" fill="var(--example-green)"/>
      <text x="52" y="146" fontSize="19" fill="var(--example-green)" fontWeight="600">완료</text>
      <text x="216" y="146" fontSize="22" fill="var(--example-green)" fontWeight="700">8건</text>
      <rect x="48" y="165" width="206" height="37" rx="6" fill="var(--example-paper)"/>
      <text x="60" y="190" fontSize="16" fill="var(--example-ink)" fontWeight="400">고객 인터뷰 정리</text>
      <rect x="48" y="211" width="206" height="37" rx="6" fill="var(--example-paper)"/>
      <text x="60" y="236" fontSize="16" fill="var(--example-ink)" fontWeight="400">주간 실적 집계</text>
      <rect x="48" y="257" width="206" height="37" rx="6" fill="var(--example-paper)"/>
      <text x="60" y="282" fontSize="16" fill="var(--example-ink)" fontWeight="400">운영 가이드 개정</text>
      <rect x="285" y="109" width="230" height="217" rx="12" fill="var(--example-gray-subtle)"/>
      <rect x="285" y="109" width="230" height="6" rx="2" fill="var(--example-blue)"/>
      <text x="301" y="146" fontSize="19" fill="var(--example-blue)" fontWeight="600">진행 중</text>
      <text x="465" y="146" fontSize="22" fill="var(--example-blue)" fontWeight="700">2건</text>
      <rect x="297" y="165" width="206" height="37" rx="6" fill="var(--example-paper)"/>
      <text x="309" y="190" fontSize="16" fill="var(--example-ink)" fontWeight="400">대시보드 검증</text>
      <rect x="297" y="211" width="206" height="37" rx="6" fill="var(--example-paper)"/>
      <text x="309" y="236" fontSize="16" fill="var(--example-ink)" fontWeight="400">신규 담당자 교육</text>
      <rect x="534" y="109" width="230" height="217" rx="12" fill="var(--example-gray-subtle)"/>
      <rect x="534" y="109" width="230" height="6" rx="2" fill="var(--example-amber)"/>
      <text x="550" y="146" fontSize="19" fill="var(--example-amber)" fontWeight="600">지원 필요</text>
      <text x="714" y="146" fontSize="22" fill="var(--example-amber)" fontWeight="700">1건</text>
      <rect x="546" y="165" width="206" height="37" rx="6" fill="var(--example-paper)"/>
      <text x="558" y="190" fontSize="16" fill="var(--example-ink)" fontWeight="400">승인 일정 확인</text>
      <rect x="36" y="344" width="728" height="61" rx="12" fill="var(--example-ink)"/>
      <text x="53" y="370" fontSize="15" fill="var(--example-blue-on-dark)" fontWeight="600">다음 주 우선순위</text>
      <text x="53" y="394" fontSize="18" fill="var(--example-paper)" fontWeight="400">① 운영 적용, ② 사용자 피드백 수집, ③ 개선안 확정</text>
    </>,
  },
  business: {
    page: "업무 흐름과 병목",
    description: "일반 업무 보고 예시: 접수, 검토, 처리, 완료 단계의 업무 흐름과 병목, 후속 조치",
    art: <>
      <text x="36" y="35" fontSize="13" fill="var(--example-muted)" fontWeight="600">BUSINESS UPDATE</text>
      <text x="36" y="76" fontSize="29" fill="var(--example-ink)" fontWeight="700">검토 대기 구간을 줄여 업무 흐름을 개선</text>
      <text x="36" y="109" fontSize="16" fill="var(--example-muted)" fontWeight="400">처리 단계별 현황 / 합성 업무 사례</text>
      <rect x="36" y="144" width="164" height="130" rx="12" fill="var(--example-blue-subtle)"/>
      <text x="54" y="174" fontSize="16" fill="var(--example-muted)" fontWeight="600">01</text>
      <text x="54" y="212" fontSize="25" fill="var(--example-ink)" fontWeight="700">접수</text>
      <text x="54" y="249" fontSize="16" fill="var(--example-ink)" fontWeight="400">요청 12건</text>
      <line x1="203" y1="207" x2="221" y2="207" stroke="var(--example-muted)" strokeWidth="3"/>
      <path d="M214 201 L221 207 L214 213" fill="none" stroke="var(--example-muted)" strokeWidth="3"/>
      <rect x="224" y="144" width="164" height="130" rx="12" fill="var(--example-amber-subtle)"/>
      <text x="242" y="174" fontSize="16" fill="var(--example-muted)" fontWeight="600">02</text>
      <text x="242" y="212" fontSize="25" fill="var(--example-ink)" fontWeight="700">검토</text>
      <text x="242" y="249" fontSize="16" fill="var(--example-ink)" fontWeight="400">검토 대기 3건</text>
      <line x1="391" y1="207" x2="409" y2="207" stroke="var(--example-muted)" strokeWidth="3"/>
      <path d="M402 201 L409 207 L402 213" fill="none" stroke="var(--example-muted)" strokeWidth="3"/>
      <rect x="412" y="144" width="164" height="130" rx="12" fill="var(--example-blue-subtle)"/>
      <text x="430" y="174" fontSize="16" fill="var(--example-muted)" fontWeight="600">03</text>
      <text x="430" y="212" fontSize="25" fill="var(--example-ink)" fontWeight="700">처리</text>
      <text x="430" y="249" fontSize="16" fill="var(--example-ink)" fontWeight="400">담당 배정 완료</text>
      <line x1="579" y1="207" x2="597" y2="207" stroke="var(--example-muted)" strokeWidth="3"/>
      <path d="M590 201 L597 207 L590 213" fill="none" stroke="var(--example-muted)" strokeWidth="3"/>
      <rect x="600" y="144" width="164" height="130" rx="12" fill="var(--example-green-subtle)"/>
      <text x="618" y="174" fontSize="16" fill="var(--example-muted)" fontWeight="600">04</text>
      <text x="618" y="212" fontSize="25" fill="var(--example-ink)" fontWeight="700">완료</text>
      <text x="618" y="249" fontSize="16" fill="var(--example-ink)" fontWeight="400">결과 공유 8건</text>
      <line x1="306" y1="280" x2="306" y2="307" stroke="var(--example-amber-line)" strokeWidth="3"/>
      <rect x="36" y="312" width="728" height="93" rx="12" fill="var(--example-gray-faint)"/>
      <text x="56" y="345" fontSize="20" fill="var(--example-amber)" fontWeight="600">병목: 검토 일정이 담당자별로 분산</text>
      <text x="56" y="380" fontSize="18" fill="var(--example-ink)" fontWeight="400">후속 조치: 주 2회 공동 검토 시간을 정하고 처리 기준을 공유</text>
    </>,
  },
  monthly: {
    page: "목표 대비 실적",
    description: "월간 보고 예시: 핵심 지표 세 개, 월별 매출 추이, 목표 대비 달성률",
    art: <>
      <text x="36" y="35" fontSize="13" fill="var(--example-muted)" fontWeight="600">MONTHLY PERFORMANCE</text>
      <text x="36" y="76" fontSize="29" fill="var(--example-ink)" fontWeight="700">성장 흐름은 유지, 전환율 개선이 다음 과제</text>
      <rect x="36" y="104" width="234" height="96" rx="12" fill="var(--example-surface)"/>
      <text x="52" y="130" fontSize="15" fill="var(--example-muted)" fontWeight="400">월간 매출</text>
      <text x="52" y="167" fontSize="29" fill="var(--example-blue)" fontWeight="700">1.2억</text>
      <text x="151" y="185" fontSize="13" fill="var(--example-muted)" fontWeight="400">목표 대비 96%</text>
      <rect x="283" y="104" width="234" height="96" rx="12" fill="var(--example-surface)"/>
      <text x="299" y="130" fontSize="15" fill="var(--example-muted)" fontWeight="400">활성 고객</text>
      <text x="299" y="167" fontSize="29" fill="var(--example-blue)" fontWeight="700">2,400</text>
      <text x="398" y="185" fontSize="13" fill="var(--example-muted)" fontWeight="400">전월 대비 +12%</text>
      <rect x="530" y="104" width="234" height="96" rx="12" fill="var(--example-surface)"/>
      <text x="546" y="130" fontSize="15" fill="var(--example-muted)" fontWeight="400">전환율</text>
      <text x="546" y="167" fontSize="29" fill="var(--example-blue)" fontWeight="700">4.8%</text>
      <text x="645" y="185" fontSize="13" fill="var(--example-muted)" fontWeight="400">목표 5.0%</text>
      <text x="36" y="235" fontSize="18" fill="var(--example-ink)" fontWeight="600">매출 추이</text>
      <line x1="52" y1="345" x2="438" y2="345" stroke="var(--example-line)" strokeWidth="2"/>
      <rect x="64" y="332" width="29" height="13" rx="3" fill="var(--example-blue-muted)"/>
      <text x="64" y="368" fontSize="13" fill="var(--example-muted)" fontWeight="400">5월</text>
      <rect x="116" y="314" width="29" height="31" rx="3" fill="var(--example-blue-muted)"/>
      <text x="116" y="368" fontSize="13" fill="var(--example-muted)" fontWeight="400">6월</text>
      <rect x="168" y="296" width="29" height="49" rx="3" fill="var(--example-blue-muted)"/>
      <text x="168" y="368" fontSize="13" fill="var(--example-muted)" fontWeight="400">7월</text>
      <rect x="220" y="278" width="29" height="67" rx="3" fill="var(--example-blue-muted)"/>
      <text x="220" y="368" fontSize="13" fill="var(--example-muted)" fontWeight="400">8월</text>
      <rect x="272" y="260" width="29" height="85" rx="3" fill="var(--example-blue-muted)"/>
      <text x="272" y="368" fontSize="13" fill="var(--example-muted)" fontWeight="400">9월</text>
      <rect x="324" y="242" width="29" height="103" rx="3" fill="var(--example-blue)"/>
      <text x="324" y="368" fontSize="13" fill="var(--example-muted)" fontWeight="400">10월</text>
      <text x="468" y="235" fontSize="18" fill="var(--example-ink)" fontWeight="600">목표 대비 달성률</text>
      <text x="468" y="275" fontSize="16" fill="var(--example-ink)" fontWeight="400">매출</text>
      <rect x="533" y="258" width="172" height="17" rx="4" fill="var(--example-track)"/>
      <rect x="533" y="258" width="139.2" height="17" rx="4" fill="var(--example-blue)"/>
      <text x="716" y="273" fontSize="14" fill="var(--example-ink)" fontWeight="400">96%</text>
      <text x="468" y="318" fontSize="16" fill="var(--example-ink)" fontWeight="400">고객</text>
      <rect x="533" y="301" width="172" height="17" rx="4" fill="var(--example-track)"/>
      <rect x="533" y="301" width="156.6" height="17" rx="4" fill="var(--example-green)"/>
      <text x="716" y="316" fontSize="14" fill="var(--example-ink)" fontWeight="400">108%</text>
      <text x="468" y="361" fontSize="16" fill="var(--example-ink)" fontWeight="400">전환</text>
      <rect x="533" y="344" width="172" height="17" rx="4" fill="var(--example-track)"/>
      <rect x="533" y="344" width="139.2" height="17" rx="4" fill="var(--example-blue)"/>
      <text x="716" y="359" fontSize="14" fill="var(--example-ink)" fontWeight="400">96%</text>
      <text x="36" y="413" fontSize="17" fill="var(--example-blue)" fontWeight="600">다음 달: 고객 유입 확대보다 전환 단계의 이탈 감소에 집중</text>
    </>,
  },
  data: {
    page: "지표의 관계와 해석",
    description: "데이터 설명 보고 예시: 응답 시간과 만족도의 산점도, 강조한 관측값, 관계와 해석의 한계",
    art: <>
      <text x="36" y="35" fontSize="13" fill="var(--example-muted)" fontWeight="600">DATA EXPLAINER</text>
      <text x="36" y="76" fontSize="29" fill="var(--example-ink)" fontWeight="700">응답 시간과 만족도의 관계를 살펴봅니다</text>
      <text x="45" y="121" fontSize="15" fill="var(--example-muted)" fontWeight="400">만족도 (점)</text>
      <line x1="76" y1="146" x2="76" y2="353" stroke="var(--example-axis)" strokeWidth="2"/>
      <line x1="76" y1="353" x2="505" y2="353" stroke="var(--example-axis)" strokeWidth="2"/>
      <line x1="76" y1="180" x2="505" y2="180" stroke="var(--example-grid)" strokeWidth="2"/>
      <line x1="76" y1="230" x2="505" y2="230" stroke="var(--example-grid)" strokeWidth="2"/>
      <line x1="76" y1="280" x2="505" y2="280" stroke="var(--example-grid)" strokeWidth="2"/>
      <line x1="76" y1="330" x2="505" y2="330" stroke="var(--example-grid)" strokeWidth="2"/>
      <circle cx="98" cy="182" r="6" fill="var(--example-point)" opacity="0.9"/>
      <circle cx="124" cy="163" r="6" fill="var(--example-point)" opacity="0.9"/>
      <circle cx="158" cy="209" r="6" fill="var(--example-point)" opacity="0.9"/>
      <circle cx="199" cy="203" r="6" fill="var(--example-point)" opacity="0.9"/>
      <circle cx="214" cy="226" r="6" fill="var(--example-point)" opacity="0.9"/>
      <circle cx="252" cy="216" r="6" fill="var(--example-point)" opacity="0.9"/>
      <circle cx="300" cy="257" r="6" fill="var(--example-point)" opacity="0.9"/>
      <circle cx="323" cy="240" r="6" fill="var(--example-point)" opacity="0.9"/>
      <circle cx="363" cy="292" r="9" fill="var(--example-point-highlight)" opacity="0.9"/>
      <circle cx="387" cy="271" r="6" fill="var(--example-point)" opacity="0.9"/>
      <circle cx="422" cy="316" r="6" fill="var(--example-point)" opacity="0.9"/>
      <circle cx="471" cy="326" r="6" fill="var(--example-point)" opacity="0.9"/>
      <path d="M97 164 L470 326" stroke="var(--example-blue)" strokeWidth="3" strokeDasharray="7 6" fill="none"/>
      <text x="89" y="378" fontSize="14" fill="var(--example-muted)" fontWeight="400">짧음</text>
      <text x="330" y="378" fontSize="14" fill="var(--example-muted)" fontWeight="400">응답 시간(길수록 오른쪽)</text>
      <rect x="538" y="127" width="226" height="111" rx="12" fill="var(--example-blue-subtle)"/>
      <text x="556" y="161" fontSize="20" fill="var(--example-blue)" fontWeight="700">관측된 관계</text>
      <text x="556" y="191" fontSize="17" fill="var(--example-ink)" fontWeight="400">응답 시간이 길수록</text>
      <text x="556" y="219" fontSize="17" fill="var(--example-ink)" fontWeight="400">만족도가 낮은 경향</text>
      <rect x="538" y="255" width="226" height="111" rx="12" fill="var(--example-amber-subtle)"/>
      <text x="556" y="289" fontSize="20" fill="var(--example-amber)" fontWeight="700">해석의 한계</text>
      <text x="556" y="319" fontSize="16" fill="var(--example-ink)" fontWeight="400">상관관계는 인과관계를</text>
      <text x="556" y="347" fontSize="16" fill="var(--example-ink)" fontWeight="400">보장하지 않습니다</text>
      <text x="36" y="414" fontSize="15" fill="var(--example-muted)" fontWeight="400">범위: 합성 고객 사례 12건  /  관계 설명을 위한 예시</text>
    </>,
  },
  research: {
    page: "발견과 근거",
    description: "리서치 결과 보고 예시: 핵심 발견, 인터뷰 근거 두 개, 시사점",
    art: <>
      <text x="36" y="35" fontSize="13" fill="var(--example-muted)" fontWeight="600">RESEARCH FINDINGS</text>
      <text x="36" y="76" fontSize="29" fill="var(--example-ink)" fontWeight="700">도입을 막는 것은 기능보다 초기 설정의 부담</text>
      <rect x="36" y="113" width="245" height="284" rx="12" fill="var(--example-ink)"/>
      <text x="58" y="151" fontSize="17" fill="var(--example-blue-on-dark)" fontWeight="600">핵심 발견</text>
      <text x="58" y="202" fontSize="29" fill="var(--example-paper)" fontWeight="700">초기 설정을</text>
      <text x="58" y="246" fontSize="29" fill="var(--example-paper)" fontWeight="700">끝내지 못한</text>
      <text x="58" y="290" fontSize="29" fill="var(--example-paper)" fontWeight="700">사용자가 이탈</text>
      <text x="58" y="365" fontSize="17" fill="var(--example-blue-on-dark)" fontWeight="400">인터뷰와 행동 관찰</text>
      <rect x="305" y="113" width="459" height="92" rx="12" fill="var(--example-surface)"/>
      <text x="324" y="145" fontSize="23" fill="var(--example-blue)" fontWeight="600">“무엇부터 입력할지 모르겠어요.”</text>
      <text x="324" y="180" fontSize="15" fill="var(--example-muted)" fontWeight="400">합성 인터뷰 A  /  최초 사용 단계</text>
      <rect x="305" y="220" width="459" height="92" rx="12" fill="var(--example-surface)"/>
      <text x="324" y="252" fontSize="21" fill="var(--example-blue)" fontWeight="600">“샘플이 있으면 따라 할 수 있겠어요.”</text>
      <text x="324" y="287" fontSize="15" fill="var(--example-muted)" fontWeight="400">합성 인터뷰 B  /  입력 방법 탐색</text>
      <line x1="320" y1="333" x2="744" y2="333" stroke="var(--example-line)" strokeWidth="2"/>
      <text x="324" y="365" fontSize="19" fill="var(--example-green)" fontWeight="600">시사점: 첫 입력에 예시와 안내를 함께 제공</text>
      <text x="324" y="396" fontSize="14" fill="var(--example-muted)" fontWeight="400">탐색적 발견: 전체 사용자로 일반화하기 전 추가 검증</text>
    </>,
  },
  project: {
    page: "일정과 마일스톤",
    description: "프로젝트 보고 예시: 작업별 일정표, 현재 시점 표시, 확인이 필요한 위험 항목",
    art: <>
      <text x="36" y="35" fontSize="13" fill="var(--example-muted)" fontWeight="600">PROJECT STATUS</text>
      <text x="36" y="76" fontSize="29" fill="var(--example-ink)" fontWeight="700">출시 목표는 유지, 검증 일정은 재조정 필요</text>
      <text x="37" y="119" fontSize="16" fill="var(--example-muted)" fontWeight="400">작업 / 담당</text>
      <text x="240" y="119" fontSize="16" fill="var(--example-muted)" fontWeight="400">1주</text>
      <text x="326" y="119" fontSize="16" fill="var(--example-muted)" fontWeight="400">2주</text>
      <text x="412" y="119" fontSize="16" fill="var(--example-muted)" fontWeight="400">3주</text>
      <text x="498" y="119" fontSize="16" fill="var(--example-muted)" fontWeight="400">4주</text>
      <text x="584" y="119" fontSize="16" fill="var(--example-muted)" fontWeight="400">5주</text>
      <text x="670" y="119" fontSize="16" fill="var(--example-muted)" fontWeight="400">6주</text>
      <line x1="226" y1="139" x2="226" y2="342" stroke="var(--example-grid-strong)" strokeWidth="2"/>
      <line x1="312" y1="139" x2="312" y2="342" stroke="var(--example-grid-strong)" strokeWidth="2"/>
      <line x1="398" y1="139" x2="398" y2="342" stroke="var(--example-grid-strong)" strokeWidth="2"/>
      <line x1="484" y1="139" x2="484" y2="342" stroke="var(--example-grid-strong)" strokeWidth="2"/>
      <line x1="570" y1="139" x2="570" y2="342" stroke="var(--example-grid-strong)" strokeWidth="2"/>
      <line x1="656" y1="139" x2="656" y2="342" stroke="var(--example-grid-strong)" strokeWidth="2"/>
      <line x1="742" y1="139" x2="742" y2="342" stroke="var(--example-grid-strong)" strokeWidth="2"/>
      <text x="37" y="170" fontSize="18" fill="var(--example-ink)" fontWeight="400">기획 / 기획팀</text>
      <rect x="228" y="149" width="166" height="27" rx="4" fill="var(--example-green)"/>
      <text x="37" y="219" fontSize="18" fill="var(--example-ink)" fontWeight="400">개발 / 개발팀</text>
      <rect x="314" y="198" width="252" height="27" rx="4" fill="var(--example-blue)"/>
      <text x="37" y="268" fontSize="18" fill="var(--example-ink)" fontWeight="400">검증 / 운영팀</text>
      <rect x="486" y="247" width="166" height="27" rx="4" fill="var(--example-amber-bar)"/>
      <text x="37" y="317" fontSize="18" fill="var(--example-ink)" fontWeight="400">출시 / 전체</text>
      <rect x="658" y="296" width="80" height="27" rx="4" fill="var(--example-blue-muted)"/>
      <line x1="483" y1="137" x2="483" y2="344" stroke="var(--example-red)" strokeWidth="3"/>
      <text x="450" y="363" fontSize="14" fill="var(--example-red)" fontWeight="600">현재 시점</text>
      <rect x="36" y="380" width="728" height="40" rx="12" fill="var(--example-amber-subtle)"/>
      <text x="52" y="406" fontSize="17" fill="var(--example-amber)" fontWeight="600">확인 필요: 검증 환경 준비가 늦어져 담당 확정과 일정 조정을 요청</text>
    </>,
  },
  results: {
    page: "목표 대비 결과",
    description: "결과 보고 예시: 목표와 실제 결과 비교, 잘된 점과 다음에 바꿀 점",
    art: <>
      <text x="36" y="35" fontSize="13" fill="var(--example-muted)" fontWeight="600">RESULTS REVIEW</text>
      <text x="36" y="76" fontSize="29" fill="var(--example-ink)" fontWeight="700">목표를 넘긴 성과와 다음 실행의 교훈</text>
      <rect x="36" y="111" width="344" height="180" rx="12" fill="var(--example-surface)"/>
      <text x="56" y="145" fontSize="18" fill="var(--example-muted)" fontWeight="400">목표</text>
      <text x="56" y="204" fontSize="44" fill="var(--example-muted)" fontWeight="600">100명</text>
      <text x="56" y="263" fontSize="17" fill="var(--example-muted)" fontWeight="400">행사 참여자</text>
      <line x1="388" y1="198" x2="424" y2="198" stroke="var(--example-axis)" strokeWidth="3"/>
      <path d="M417 192 L424 198 L417 204" fill="none" stroke="var(--example-axis)" strokeWidth="3"/>
      <rect x="432" y="111" width="332" height="180" rx="12" fill="var(--example-green-subtle)"/>
      <text x="454" y="145" fontSize="18" fill="var(--example-green)" fontWeight="400">실제 결과</text>
      <text x="454" y="204" fontSize="44" fill="var(--example-green)" fontWeight="700">128명</text>
      <text x="454" y="263" fontSize="20" fill="var(--example-green)" fontWeight="600">목표의 128% 달성</text>
      <text x="36" y="334" fontSize="19" fill="var(--example-ink)" fontWeight="700">잘된 점</text>
      <text x="36" y="370" fontSize="18" fill="var(--example-ink)" fontWeight="400">사전 안내 개선으로 참여 확대</text>
      <text x="432" y="334" fontSize="19" fill="var(--example-ink)" fontWeight="700">다음 실행에서 바꿀 점</text>
      <text x="432" y="370" fontSize="18" fill="var(--example-ink)" fontWeight="400">현장 대기 시간을 줄이는 동선 설계</text>
      <line x1="36" y1="391" x2="764" y2="391" stroke="var(--example-line)" strokeWidth="2"/>
      <text x="36" y="416" fontSize="15" fill="var(--example-muted)" fontWeight="400">비교 기준과 집계 범위를 맞춘 뒤 달성 여부를 판단합니다.</text>
    </>,
  },
  approval: {
    page: "대안 비교와 승인 범위",
    description: "승인요청 예시: 두 대안의 비교표, 추천안과 조건, 승인 요청",
    art: <>
      <text x="36" y="35" fontSize="13" fill="var(--example-muted)" fontWeight="600">DECISION REQUEST</text>
      <text x="36" y="76" fontSize="29" fill="var(--example-ink)" fontWeight="700">대안 B로 추진하는 것을 요청합니다</text>
      <rect x="36" y="111" width="488" height="47" rx="6" fill="var(--example-ink)"/>
      <text x="52" y="141" fontSize="18" fill="var(--example-paper)" fontWeight="600">평가 기준</text>
      <text x="238" y="141" fontSize="18" fill="var(--example-paper)" fontWeight="600">대안 A</text>
      <text x="390" y="141" fontSize="18" fill="var(--example-paper)" fontWeight="600">대안 B</text>
      <rect x="368" y="164" width="156" height="176" rx="6" fill="var(--example-green-subtle)"/>
      <text x="52" y="195" fontSize="17" fill="var(--example-ink)" fontWeight="400">초기 비용</text>
      <text x="237" y="195" fontSize="17" fill="var(--example-muted)" fontWeight="400">낮음</text>
      <text x="389" y="195" fontSize="17" fill="var(--example-green)" fontWeight="600">중간</text>
      <line x1="36" y1="209" x2="524" y2="209" stroke="var(--example-line)" strokeWidth="2"/>
      <text x="52" y="238" fontSize="17" fill="var(--example-ink)" fontWeight="400">도입 속도</text>
      <text x="237" y="238" fontSize="17" fill="var(--example-muted)" fontWeight="400">빠름</text>
      <text x="389" y="238" fontSize="17" fill="var(--example-green)" fontWeight="600">보통</text>
      <line x1="36" y1="252" x2="524" y2="252" stroke="var(--example-line)" strokeWidth="2"/>
      <text x="52" y="281" fontSize="17" fill="var(--example-ink)" fontWeight="400">확장성</text>
      <text x="237" y="281" fontSize="17" fill="var(--example-muted)" fontWeight="400">제한적</text>
      <text x="389" y="281" fontSize="17" fill="var(--example-green)" fontWeight="600">높음</text>
      <line x1="36" y1="295" x2="524" y2="295" stroke="var(--example-line)" strokeWidth="2"/>
      <text x="52" y="324" fontSize="17" fill="var(--example-ink)" fontWeight="400">운영 부담</text>
      <text x="237" y="324" fontSize="17" fill="var(--example-muted)" fontWeight="400">높음</text>
      <text x="389" y="324" fontSize="17" fill="var(--example-green)" fontWeight="600">낮음</text>
      <line x1="36" y1="338" x2="524" y2="338" stroke="var(--example-line)" strokeWidth="2"/>
      <rect x="548" y="111" width="216" height="231" rx="12" fill="var(--example-blue-subtle)"/>
      <text x="568" y="149" fontSize="24" fill="var(--example-blue)" fontWeight="700">추천: 대안 B</text>
      <text x="568" y="187" fontSize="18" fill="var(--example-ink)" fontWeight="400">성장에 대응하고</text>
      <text x="568" y="216" fontSize="18" fill="var(--example-ink)" fontWeight="400">반복 운영을 줄임</text>
      <text x="568" y="264" fontSize="16" fill="var(--example-muted)" fontWeight="600">조건</text>
      <text x="568" y="299" fontSize="17" fill="var(--example-ink)" fontWeight="400">단계별 도입과 검증</text>
      <rect x="36" y="368" width="728" height="52" rx="12" fill="var(--example-blue)"/>
      <text x="55" y="400" fontSize="19" fill="var(--example-paper)" fontWeight="600">승인 요청: 추진 방향 및 초기 검증 단계의 자원 배정</text>
    </>,
  },
  strategy: {
    page: "전략과 실행 로드맵",
    description: "전략기획 예시: 전략 방향과 세 단계 실행 로드맵",
    art: <>
      <text x="36" y="35" fontSize="13" fill="var(--example-muted)" fontWeight="600">STRATEGIC ROADMAP</text>
      <text x="36" y="76" fontSize="29" fill="var(--example-ink)" fontWeight="700">핵심 고객에 집중해 반복 가능한 성장 구조를 만듭니다</text>
      <rect x="36" y="109" width="728" height="60" rx="12" fill="var(--example-ink)"/>
      <text x="55" y="146" fontSize="22" fill="var(--example-paper)" fontWeight="600">전략 방향: 고객 집중, 제품 표준화, 파트너 확장</text>
      <line x1="110" y1="301" x2="706" y2="220" stroke="var(--example-blue)" strokeWidth="5"/>
      <circle cx="104" cy="290" r="16" fill="var(--example-blue)" stroke="var(--example-paper)" strokeWidth="5"/>
      <text x="70" y="198" fontSize="16" fill="var(--example-blue)" fontWeight="700">01 / 기반</text>
      <text x="70" y="337" fontSize="21" fill="var(--example-ink)" fontWeight="600">핵심 고객 검증</text>
      <text x="70" y="367" fontSize="16" fill="var(--example-muted)" fontWeight="400">가설과 지표 확정</text>
      <circle cx="350" cy="257" r="16" fill="var(--example-blue)" stroke="var(--example-paper)" strokeWidth="5"/>
      <text x="316" y="198" fontSize="16" fill="var(--example-blue)" fontWeight="700">02 / 반복</text>
      <text x="316" y="304" fontSize="21" fill="var(--example-ink)" fontWeight="600">제공 방식 표준화</text>
      <text x="316" y="334" fontSize="16" fill="var(--example-muted)" fontWeight="400">운영의 재현성 확보</text>
      <circle cx="596" cy="224" r="16" fill="var(--example-blue)" stroke="var(--example-paper)" strokeWidth="5"/>
      <text x="562" y="198" fontSize="16" fill="var(--example-blue)" fontWeight="700">03 / 확장</text>
      <text x="562" y="271" fontSize="21" fill="var(--example-ink)" fontWeight="600">파트너와 시장 확대</text>
      <text x="562" y="301" fontSize="16" fill="var(--example-muted)" fontWeight="400">성장 조건 검증</text>
      <rect x="36" y="380" width="728" height="40" rx="12" fill="var(--example-surface)"/>
      <text x="54" y="406" fontSize="17" fill="var(--example-blue)" fontWeight="600">각 단계의 통과 조건을 확인한 뒤 다음 투자와 실행을 결정</text>
    </>,
  },
  ir: {
    page: "제품 가치와 성장 기회",
    description: "IR Pitch Deck 예시: 제품 가치 메시지, 초기 고객 반복 사용의 성장 곡선, 투자 메시지",
    art: <>
      <rect x="0" y="0" width="800" height="450" rx="0" fill="var(--example-ir-bg)"/>
      <rect x="505" y="0" width="295" height="450" rx="0" fill="var(--example-ir-panel)"/>
      <text x="36" y="40" fontSize="13" fill="var(--example-ir-text-faint)" fontWeight="600">IR PITCH DECK  /  SYNTHETIC EXAMPLE</text>
      <text x="36" y="115" fontSize="39" fill="var(--example-paper)" fontWeight="700">업무의 복잡함을</text>
      <text x="36" y="166" fontSize="39" fill="var(--example-paper)" fontWeight="700">성장의 기회로.</text>
      <text x="36" y="209" fontSize="18" fill="var(--example-ir-text-muted)" fontWeight="400">팀이 중요한 일에 집중하도록 돕는 운영 플랫폼</text>
      <rect x="36" y="250" width="352" height="119" rx="12" fill="var(--example-ir-card)"/>
      <text x="55" y="283" fontSize="16" fill="var(--example-ir-accent)" fontWeight="600">제품 가치</text>
      <text x="55" y="317" fontSize="21" fill="var(--example-paper)" fontWeight="600">흩어진 업무를 하나의 실행 흐름으로</text>
      <text x="55" y="349" fontSize="16" fill="var(--example-ir-text-muted)" fontWeight="400">구독 수익 구조  /  조직 단위 확장</text>
      <text x="537" y="72" fontSize="14" fill="var(--example-ir-accent)" fontWeight="600">TRACTION</text>
      <text x="537" y="110" fontSize="23" fill="var(--example-paper)" fontWeight="700">초기 고객의 반복 사용</text>
      <line x1="537" y1="310" x2="761" y2="310" stroke="var(--example-ir-line)" strokeWidth="2"/>
      <path d="M538 291 C568 290 579 273 609 265 S649 234 679 210 S721 160 759 149" fill="none" stroke="var(--example-ir-accent)" strokeWidth="5"/>
      <circle cx="538" cy="291" r="5" fill="var(--example-ir-accent)"/>
      <circle cx="609" cy="265" r="5" fill="var(--example-ir-accent)"/>
      <circle cx="679" cy="210" r="5" fill="var(--example-ir-accent)"/>
      <circle cx="759" cy="149" r="5" fill="var(--example-ir-accent)"/>
      <text x="536" y="340" fontSize="18" fill="var(--example-ir-text-muted)" fontWeight="400">검증에서 반복, 성장으로</text>
      <text x="36" y="415" fontSize="18" fill="var(--example-ir-accent)" fontWeight="600">NEXT  /  제품 고도화와 시장 검증에 투자</text>
      <text x="537" y="415" fontSize="13" fill="var(--example-ir-text-faint)" fontWeight="400">개념 곡선, 실제 실적 아님</text>
    </>,
  },
};

// 예시 그림 하나. 모든 그림의 오른쪽 위에 "예시" 표시가 있다. 대체 텍스트는 유형과 그림의 특징을 밝힌 설명이다 (리뷰 U9).
// 그림 안의 화살표 기호와 중점은 낭독과 글꼴 대체에서 뜻이 흐려지지 않도록 선과 글로 바꿨다 (D3b-6 리뷰 R8)
export function ExampleArt({ type, className }: { type: ReportType; className?: string }) {
  const { description, art } = EXAMPLE_PAGES[type];
  return (
    <svg viewBox="0 0 800 450" role="img" aria-label={description} className={className}>
      <rect width="800" height="450" fill="var(--example-paper)" />
      {art}
      <rect x="696" y="12" width="68" height="30" rx="6" fill="var(--example-amber-subtle)" />
      <text x="730" y="33" fontSize="15" fontWeight="700" textAnchor="middle" fill="var(--example-amber)">예시</text>
    </svg>
  );
}
