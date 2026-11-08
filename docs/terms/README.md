# 약관 자료와 Claude 구현 계약

작성일: 2026-11-07 (Asia/Seoul). 문서 형식 버전: 1.

## 작업 소유권

- Codex: 이 디렉터리의 문서, 상품 매핑, 출처, 평가 질문 작성.
- Claude: 앱 코드, DB 모델·마이그레이션, 로더·발행·임베딩·검색, 동의 API/UI, 테스트.
- Claude는 이 디렉터리의 본문을 임의로 수정하지 않는다. 추가 fixture는 tests/fixtures/terms/에 둔다.
- 기존 변경 중인 다른 파일은 보존한다. MCP는 이번 범위에 없다.

## 읽을 파일

- `corpus/**/*.md`: 약관 후보 문서. 이 경로만 문서 로더의 입력으로 삼는다.
- `manifest.json`: 상품과 적용 문서의 정확한 연결. 스키마 버전 1.
- `sources.md`: 공식 참고 자료와 열람 범위. 사용자 약관 검색 인덱스에 넣지 않는다.
- `evaluation.json`: 검색 평가용 질문. 사용자 약관 검색 인덱스에 넣지 않는다.
- `IMPLEMENTATION_NOTES.md`: 코드와 상품 소개의 차이. 사용자 검색 인덱스에 넣지 않는다.

## MD front matter 계약

각 문서는 UTF-8, LF 줄바꿈, YAML front matter로 작성한다. JSON은 YAML의 부분집합이므로 front matter 내부의 JSON 객체도 허용한다. JSON/YAML safe parser를 사용한다.

```yaml
---
schema_version: 1
document_key: "ab.deposit.rules"
title: "어벤져스 예금 이용약관"
version: "1.0.0"
status: "draft"
effective_from: null
language: "ko"
demo_only: true
document_type: "category_terms"
product_kinds: ["deposit"]
source_ids: ["SRC-DEPOSIT"]
reviewed_on: "2026-11-07"
---
```

`document_type`: `common_terms`, `category_terms`, `product_terms` 중 하나.
`product_kinds`: `checking`, `deposit`, `savings`, `credit`, `debit`의 배열.
`status`: 작성물은 모두 `draft`. 실제 동의용 발행은 별도의 명시적인 발행 명령에서 처리한다.
`effective_from`: 초안은 null. 발행 시 시행일을 정하고 DB 버전을 고정한다. 작성일을 시행일로 간주하지 않는다.
`(document_key, version)`이 문서의 고유 키다. 동일 키의 발행된 본문 덮어쓰기는 금지한다.

본문 헤딩은 `## [section-id] 제목` 형식이다. `section-id`는 소문자 영문·숫자·하이픈이며 문서 안에서 고유하다. Markdown 기본 슬러그에 의존하지 말고 렌더러가 해당 ID를 안전하게 앵커로 생성한다. 예: `## [early-close] 중도해지`.

로더는 BOM/CRLF를 정규화한 본문을 보존하고 SHA-256을 계산한다. 표시·동의·인용은 동일 DB 스냅샷을 참조한다. front matter와 개발용 파일은 본문 임베딩에서 제외한다. 각 청크에는 문서 키·버전·조항 ID·원문 위치를 저장한다.

## manifest 계약

루트는 `schema_version`, `documents`, `products`를 가진다.
documents 항목: `document_key`, `version`, `path`(이 디렉터리 기준 상대경로).
products 항목: `product_code`, `kind`, `seed_name`, `terms`.
terms 항목: `document_key`, `version`, `required`, `order`.

`product_code`는 자료 연결용으로 새로 정의한 안정적인 코드이며 아직 기존 DB 필드가 아니다. 최초 연결 때만 `(kind, seed_name)`을 기존 상품과 정확히 대조하고, 이후 DB의 안정적인 매핑으로 저장한다. 0개 또는 2개 이상 매칭되면 실패시킨다. DB 삽입 순서로 product_id를 추정하지 않는다. 새로운 상품을 조용히 기존 상품에 연결하지 않는다.

manifest에 선언된 공통 안내 + 종류별 약관 + 해당 상품 문서를 적용 집합으로 사용한다. 필수 여부는 MD가 아닌 manifest의 상품 연결에 둔다. 누락된 참조·종류 불일치·중복·경로 이탈은 오류다.

## Claude가 문서 완성 전에 구현할 내용

1. 위 형식의 작은 테스트 fixture를 `tests/fixtures/terms/`에 작성한다.
2. 문서 검증·불변 버전 저장·상품 매핑·명시적 발행을 구현한다.
3. 가입과 필수 동의 저장을 동일 트랜잭션으로 처리한다. 오래된 약관 집합 제출은 재동의를 요구한다. 기존 가입에는 동의 이력을 소급 생성하지 않는다.
4. Gemini 임베딩 어댑터, 조항 기반 청킹, 재실행 가능한 색인과 검색을 구현한다. 모델명과 차원은 공식 문서로 확인하고 설정으로 분리한다.
5. `search_product_terms`와 `get_terms_section`을 기존 Tool 레지스트리에 추가한다. 서버가 현재/가입 당시 적용 버전을 결정한다.
6. 기존 채팅 응답의 이체 action을 유지하면서 검증된 citations를 추가한다. 검색되지 않은 출처를 모델이 생성할 수 없게 한다.
7. 가입 화면의 전문 열람·미선택 체크박스·필수 동의 검증·버전 변경 시 초기화, 가입 당시 약관 보기 UI를 구현한다.
8. Fake 모델·임베딩으로 먼저 검증한다. 실제 문서가 들어오면 같은 파이프라인으로 검증·색인한다.

초안은 기본 사용자 검색·가입 동의에서 제외하고, 테스트용 draft preview 경로는 운영과 분리한다. 문서 발행과 색인 완료는 별도 상태다. 최신 문서가 색인되지 않았다고 과거 버전을 대신 답하지 않는다. AI 장애 중에도 전문 열람·가입 동의는 가능해야 한다.

## 자료의 성격

실제 금융사 약관 전문 복제본이 아니다. 공식 자료의 주제와 구조를 참고하고 현재 저장소 동작을 근거로 새로 작성한 학습용 문서다. 공식 자료의 실제 금리·법정 보호·책임 조항을 AvengersBank 약정으로 편입하지 않는다. 상품 설명에만 있는 기능을 실제 제공 기능으로 답하지 않는다.
