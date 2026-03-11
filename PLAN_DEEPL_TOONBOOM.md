# Toon Boom Harmony 엑셀 번역 기획안 (DeepL API Free)

## 1. 개요

- **목적**: Toon Boom Harmony 제작 문서(영문 엑셀)의 지정 컬럼을 한글로 번역하되, 기술 용어의 일관성을 유지한다.
- **대상 문서**: Scene List, 노드 구조 설명, Retake/Feedback 시트 등 제작 관리용 `.xlsx` 파일.
- **핵심 원칙**: 자연스러운 번역보다 제작 현장 용어의 정확성과 일관성을 우선한다.

## 1.1 샘플 문서 분석 반영 사항

- **샘플 파일**: `HH0304-Episodic_Lead_Sheet_LIVE_Yeson.xlsx`
- **구조 특징**:
  - 단일 시트(`Sheet1`), 총 43개 컬럼
  - 실제 테이블 헤더는 **13행**(`SHOT CODE` 포함 43개 헤더)
  - 1~12행은 에피소드 요약/팀 집계/카테고리 블록(번역 대상 아님)
  - 일부 헤더는 줄바꿈 포함(`TEAM COMPLETING\nANIM ROUGH`)
- **기획 반영 포인트**:
  - 데이터 시작행 자동 탐지 규칙에 `SHOT CODE` 기준 추가
  - 요약 블록(1~12행) 자동 제외
  - 노트성 컬럼 중심 번역, ID/코드/티어/팀명 컬럼 기본 제외

## 2. 기준 체계

- **용어 기준 원천**: Toon Boom 공식 문서(`docs.toonboom.com`)와 Harmony UI 명칭, 미국 2D 애니메이션 제작사 실무 전문용어.
- **우선 고정 용어**:
  - `Node View`
  - `Cutter`
  - `Peg`
  - `Deformer`
  - `Composite`
  - `Xsheet`
  - `Drawing Substitution`
- **약어 정책**: `BG`, `LO`, `FX`, `O.S.`, `SFX`, `CU`, `MS`, `WS` 등 스튜디오 약어는 규칙으로 고정(원문 유지 또는 사전 정의 한글 확장).

## 3. 번역 아키텍처

### 3.1 처리 파이프라인

1. **Load**: 원문 엑셀 파일 로드 후 시트/컬럼 메타데이터 수집
2. **Detect Header/Data Start**: `SHOT CODE` 컬럼 헤더가 있는 행을 헤더행으로 확정(샘플 기준 13행), 그 이전 요약행은 번역 제외
3. **Auto Select Columns**: 텍스트 비율, 평균 길이, 비번역 패턴 비율, 헤더 키워드(`NOTES`, `NOTE`)를 기준으로 번역 후보 컬럼 자동 추천
4. **Extract**: 자동 추천 결과에서 확정된 번역 대상 컬럼만 추출
5. **Normalize**: 공백, 줄바꿈, 비교 키 표준화
6. **Exclude**: 코드형 토큰(씬 ID, 컷 ID, 파일명, 숫자 전용 값) 제외
7. **Glossary Pre-pass**: API 호출 전 앱 내부 용어 고정 규칙 우선 적용
8. **Deduplicate**: 중복 문장 제거 후 고유 문장만 번역
9. **Translate**: DeepL API Free로 고유 문장 번역
10. **Cache**: 원문-번역문 매핑을 로컬 캐시에 저장
11. **Fill-back**: 번역 결과를 원본 전체 행에 재적용
12. **Export**: 번역 결과 파일 및 QA/Audit 산출물 저장

### 3.2 구조 선택 이유

- Dedup + Cache로 무료 한도 내 문자 사용량을 최소화한다.
- 앱 내부 용어 고정으로 짧은 기술 용어의 문맥 오역 위험을 줄인다.
- Fill-back으로 반복 문구에 대해 항상 동일 결과를 보장한다.

## 4. DeepL Free 운영 설계

- **플랜**: DeepL API Free
- **엔드포인트**: `https://api-free.deepl.com`
- **한도**: 월 500,000자(원문 기준)
- **용어집**: DeepL Glossary API + 로컬 용어 고정 규칙 병행
- **사용량 제어**:
  - 실행 전/후 `/usage` 조회
  - 예상 사용량이 임계치 초과 시 배치 분할 또는 실행 중단

## 5. 데이터 처리 규칙

- **입력 포맷**: MVP 기준 `.xlsx` 전용
- **컬럼 선택 방식**:
  - 기본: 자동 선택 모드(번역 우선 후보 컬럼 추천)
  - 보정: 사용자가 추천 결과에서 제외/추가 가능
  - 규칙: 수치형/ID형/코드형/팀명/티어 컬럼은 기본 제외
  - 샘플 우선 번역 후보: `P(ANIMATION)`, `S(COMP - OS NOTE)`, `T(COMP - PB NOTE)`, `Y(NOTES)`, `AC(NOTES)`, `AO(NOTES)`, `AP(PRINCESS BENTO NOTE)`
  - 샘플 기본 제외 후보: `A(SHOT CODE)`, `U(STARTING FILE)`, `V(SHOT CLASSIFICATION)`, `W/X(TEAM COMPLETING)`, `AN(COMP TIER)`, `Z(TEAM)`, 숫자 집계 컬럼(`#`, `FRAME COUNT`, `SECS`, `DURATION`)
- **출력 파일**:
  - `translated.xlsx` (원본 + 번역 컬럼, 예: `Technical Notes_KR`)
  - `translation_audit.xlsx` (원문, 번역문, 용어집 적용 여부, 캐시 히트, 제외 사유)
  - `usage_report.json` (실행 전/후 사용량, 처리 건수, 오류 요약)
- **보존 요구사항**:
  - 시트 구조, 행 순서, 수식, 비대상 컬럼 불변
  - 빈 셀 유지
  - 줄바꿈 의미 보존

## 6. 용어집 거버넌스

### 6.1 용어 수집 출처

- Toon Boom 공식 매뉴얼/레퍼런스 페이지
- 미국 2D 애니메이션 제작사에서 사용하는 제작 파이프라인/피드백 시트 전문용어
- 내부 제작팀 승인 번역 관례

### 6.2 운영 정책

- 핵심 용어는 모두 용어집 등록 후 QA에서 고정 번역 여부 검증
- 동일 의미의 표현 차이(`Retake Note`, `Revision Note`, `Pickup`)는 대표 표제어로 정규화 후 번역
- 하나의 원문 용어에 후보 번역이 여러 개면 표준 번역 1개만 채택
- 용어집 변경 시 버전 증가 및 변경 이력 기록

### 6.3 초기 파일 형식

- `glossary.tsv` (`source<TAB>target`)
- `exclude_patterns.yaml` (비번역 패턴)

## 7. 예외 처리 및 안정성

- **재시도 정책**: 일시적 API 오류에 대해 지수 백오프 적용
- **실패 격리**: 실패 행은 누락하지 않고 리뷰 필요 상태로 마킹
- **오류 분류**:
  - 입력 오류(파일/시트/컬럼 없음)
  - 인증 오류(API 키 누락/오류)
  - 한도/요율 제한 오류
  - 출력 저장 오류
- **보안**:
  - API 키는 환경변수(`.env`)로만 주입
  - 민감 원문 전체를 평문 로그로 남기지 않음

## 8. 품질 보증(QA)

- **자동 검증**:
  - 헤더행 탐지 정확성 검증(`SHOT CODE` 행을 기준으로 데이터 블록 시작)
  - 1~12행 요약 블록 미번역 검증(샘플 기준)
  - 필수 용어가 고정 번역으로 반영되는지 확인
  - 제외 패턴이 번역되지 않았는지 확인
  - 처리 전/후 행 수 불일치 여부 확인
- **수동 검수**:
  - 시트별 5~10% 샘플 검수
  - 경고/오류 마킹 행 전수 검토
- **수용 기준**:
  - 대상 컬럼 번역 완료
  - 핵심 용어 일관성 100%
  - 워크북 무결성 유지

## 9. MVP 산출물

- 컬럼 지정형 엑셀 번역 CLI 도구
- 엑셀 로드 후 번역 대상 컬럼 자동 선택(추천) 기능
- 설정 파일(`.env.example`, `glossary.tsv`, `exclude_patterns.yaml`)
- 결과 산출물(`translated.xlsx`, `translation_audit.xlsx`, `usage_report.json`)
- 운영 가이드(`README`)

## 9.1 구현 구조화 규칙(필수)

- **단일 파일 금지**: 모든 로직을 `main.py` 하나에 몰아서 구현하지 않는다.
- **모듈 분리 기준**:
  - `main.py`: CLI 인자 파싱 + 파이프라인 호출만 담당
  - `pipeline.py`: 단계 오케스트레이션만 담당
  - `excel_io.py`: 엑셀 로드/저장, 헤더 탐지, 범위 추출
  - `column_selector.py`: 자동 컬럼 추천 로직
  - `preprocess.py`: 정규화/제외 패턴/중복 제거
  - `translator_deepl.py`: DeepL 호출/재시도/사용량 조회
  - `glossary.py`: 용어집 적용/정규화
  - `cache.py`: 캐시 저장/조회
  - `audit.py`: QA 및 감사 리포트 생성
- **의존 방향**: `main -> pipeline -> domain modules` 단방향 유지, 모듈 간 순환 참조 금지

## 9.2 코드 수정 앵커 규칙(필수)

- 코드 수정 시 검색 가능한 앵커를 함수/블록 상단에 명시한다.
- **앵커 형식**: `[ANCHOR:<MODULE>_<PURPOSE>]`
- **권장 예시**:
  - `[ANCHOR:MAIN_CLI_ENTRY]`
  - `[ANCHOR:PIPELINE_RUN]`
  - `[ANCHOR:EXCEL_DETECT_HEADER_ROW]`
  - `[ANCHOR:COLUMN_SELECTOR_SCORE]`
  - `[ANCHOR:PREPROCESS_DEDUP]`
  - `[ANCHOR:DEEPL_TRANSLATE_BATCH]`
  - `[ANCHOR:GLOSSARY_APPLY_LOCK]`
  - `[ANCHOR:AUDIT_EXPORT_REPORT]`
- 앵커명은 중복 없이 유지하고, 리팩터링 시 동일 의미의 앵커를 가능한 유지한다.

## 10. 3일 MVP 일정

- **Day 1**: 입출력/전처리 구현(추출, 정규화, 제외, 중복 제거)
- **Day 2**: DeepL 연동, 용어집 적용, 캐시, 재적용(Fill-back) 구현
- **Day 3**: QA 리포트, 예외 처리 보강, 실데이터 리허설

## 11. 리스크 및 대응

- **리스크**: 짧고 모호한 용어 오역
  - **대응**: API 전후 앱 내부 용어 고정 규칙 강제
- **리스크**: 대용량 파일 처리 시 무료 한도 초과
  - **대응**: 사전 사용량 예측, Dedup, Cache, 배치 분할
- **리스크**: 제작 식별자(ID) 오번역
  - **대응**: 제외 정규식 강화 + Audit 경고 표시

## 12. 최종 의사결정

- 번역 엔진은 **DeepL API Free**를 기본으로 사용한다.
- 용어 기준은 **Toon Boom 공식 매뉴얼 + 미국 2D 애니메이션 실무 전문용어**를 기준으로 한다.
- 운영 안정성은 **Dedup + Cache + Audit** 3축으로 확보한다.
