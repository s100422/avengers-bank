# 약관 동의와 약관 검색(RAG) 운영 안내 (C-075)

약관 문서(`docs/terms/`)는 Codex가 쓰고, 이 문서는 그 문서를 앱에 올리고 검색하는 코드·명령을 설명한다.
문서 형식과 상품 연결 규격은 `docs/terms/README.md`가 기준이다.

## 한눈에 보기

```
docs/terms/manifest.json + corpus/**/*.md   (초안, 작성 원본)
        │ publish (명시적 발행 명령)
        ▼
terms_versions (불변 스냅샷)  ─┬─ product_terms_revisions/items (상품별 적용 집합, revision)
                               ├─ terms_consents (가입 때 서버가 기록한 동의)
                               └─ indexing (별도 명령) → terms_index_generations / entries / chunks (pgvector)
                                                              │
                     가입 화면 ← GET /terms/...               │  search_product_terms / get_terms_section (Agent Tool)
                     가입 API(5종) → 동의 검증·기록           ▼
                                                     채팅 답변 + citations(서버 검증 출처)
```

- 원문 열람·가입 동의는 DB 스냅샷만 쓴다. AI·임베딩이 멈춰도 동작한다.
- 검색용 청크·벡터는 언제든 다시 만들 수 있는 데이터다. 원문·동의 기록을 대신하지 않는다.
- 발행과 색인은 별개 단계다. 발행만 하고 색인하지 않은 새 버전을 검색하면 `TERMS_INDEX_NOT_READY`를 돌려준다(예전 버전으로 대신 답하지 않는다).

## 처음 설정 (로컬)

1. DB 이미지: `docker-compose.yml`이 `pgvector/pgvector:pg17-trixie`를 쓴다. 이전 `postgres:17-trixie`와 같은 PostgreSQL 빌드(17.11, Debian trixie)라서 **기존 볼륨을 그대로 쓴다.** 볼륨을 지우지 말고 `docker compose up -d --wait`로 다시 띄우면 된다.
2. 마이그레이션: `uv run alembic upgrade head` — `CREATE EXTENSION IF NOT EXISTS vector`를 실행한다. DB 소유자 또는 슈퍼유저 권한이 필요하다.
3. 상품 시드: `uv run python -m avengers_bank.seed` (이미 있으면 건너뜀)
4. 발행: 아래 "발행"
5. 색인: 아래 "색인" (`.env`에 `GEMINI_API_KEY` 필요)

운영(RDS 등): pgvector 지원 버전인지 확인하고, 마이그레이션 전에 권한 있는 계정으로 `CREATE EXTENSION vector;`를 한 번 실행한다(RDS는 `rds_superuser` 역할). 운영 DB에는 아직 적용하지 않았다.

## 발행

```bash
uv run python -m avengers_bank.domains.terms.publish --effective-from 2026-11-10 --dry-run
```

```bash
uv run python -m avengers_bank.domains.terms.publish --effective-from 2026-11-10
```

- `--dry-run`은 같은 트랜잭션으로 끝까지 실행한 뒤 롤백한다. 실제로 무엇이 바뀌는지 그대로 보여 준다.
- 검증: manifest·front matter 필수 필드, `demo_only: true`, 조항 헤딩 `## [section-id] 제목`과 ID 중복, corpus 밖 경로, manifest에 없는 corpus 파일, 없는 문서 참조, 상품 종류 불일치, 필수 약관 없는 상품.
- 같은 `(document_key, version)`이 이미 있으면 본문 해시가 같을 때만 통과한다. 내용을 바꿨다면 version을 올려야 한다.
- 상품 연결: `product_code`로 찾고, 처음에는 `(kind, seed_name)`이 정확히 1개일 때만 연결해 `product_code`를 저장한다. 0개·2개 이상이면 실패한다. 삽입 순서·숫자 ID를 쓰지 않는다.
- 상품별 적용 집합(문서·버전·본문 해시·필수·순서)이 바뀐 상품만 새 revision을 만든다. 같은 입력으로 다시 돌리면 아무것도 바뀌지 않는다.
- 현재 집합 어디에도 없는 버전은 `retired`가 된다. 지우지 않는다(과거 동의 기록이 FK로 가리킨다).
- 시행일: 문서의 `effective_from`이 있으면 그 값, 없으면 `--effective-from`.

## 색인

```bash
uv run python -m avengers_bank.domains.terms.indexing --dry-run
```

```bash
uv run python -m avengers_bank.domains.terms.indexing
```

- 색인 세대 = (임베딩 모델, 차원, 청커 버전 `sec-v1`). 설정이 같으면 활성 세대를 이어 쓰고, 이미 `ready`인 버전은 건너뛴다.
- 모델·차원·청커가 바뀌었거나 `--reindex`면 새 세대를 `building`으로 만들고, 모든 버전이 `ready`가 되면 그때 활성화한다(이전 세대는 같은 트랜잭션에서 `retired`).
- 버전 하나씩 "청크 지우고 → 새로 넣고 → ready" 한 트랜잭션. 다시 돌려도 중복이 생기지 않고, 실패한 버전은 다음 실행 때 다시 시도한다.
- 임베딩 API를 기다리는 동안 DB 세션을 열어 두지 않는다.
- `retired` 버전도 색인한다. 가입 당시 약관(`my_contract`) 검색에 필요하기 때문이다.

## 임베딩·청킹·검색 기준

| 항목 | 값 | 근거 |
|---|---|---|
| 임베딩 모델 | `gemini-embedding-001` (`EMBEDDING_MODEL`) | 공식 문서 https://ai.google.dev/gemini-api/docs/embeddings (2026-11-07 확인) |
| 차원 | 768 (`EMBEDDING_DIMENSIONS`), 클라이언트가 L2 정규화 | 3072 이외 차원은 호출 쪽 정규화 필요(공식 문서) |
| 작업 유형 | 문서 `RETRIEVAL_DOCUMENT`, 질의 `RETRIEVAL_QUERY` | 같은 모델·차원으로만 비교한다 |
| 청크 | `## [id]` 조항 단위. 긴 조항만 문단 경계로 나눔(표·목록 항목은 자르지 않음), 앞에 "문서 제목 > 조항 제목" | 실제 문서는 조항이 최대 약 250자라 거의 조항 1개 = 청크 1개 |
| 검색 범위 | 서버가 정한 버전 집합(현재 적용 집합 또는 가입 당시 동의 기록)만 | 상품·버전 필터를 먼저 적용 |
| 순위 | pgvector `<=>` 코사인(정확 검색) + 0.15 × 한국어 글자 bigram 겹침(조항 ID·제목 일치는 1) | 문서가 작아 근사 인덱스 없이 정확 검색 |
| 근거 기준 | 벡터 유사도 ≥ `TERMS_MIN_SCORE`(0.6) | `scripts/eval_terms.py`의 임계값 스윕. 점수는 정답 확률이 아니다 |

`gemini-embedding-2`도 시험했다(검색 품질 같음). 다만 0.6에서 근거 없는 질문을 거르지 못해서(0.65 필요) 001을 유지했다.

## 채팅 출처(citations)

- 검색 결과마다 서버가 `source_id = "{terms_version_id}:{section_id}"`를 붙인다.
- 모델은 답변에 `[[src:12:early-close]]`처럼 표시만 한다. 서버는 표시를 모두 지우고, **이번 요청에서 실제로 검색된** ID만 출처로 만든다. 지어낸 ID·문서 속에 심어 둔 ID는 버린다. 검색만 하고 인용하지 않은 자료는 보이지 않는다.
- 출처 링크는 `/terms/{terms_version_id}#{section_id}` — 그 버전의 그 조항. `agent_messages.citations`에 저장해 대화를 다시 열어도 남는다(`GET /agent/conversations/{id}/messages`).

## 평가

```bash
uv run python scripts/eval_terms.py --out <보고서 파일>.md
```

- `docs/terms/evaluation.json`(27문항)을 **초안 문서 그대로** DB 없이 평가한다. `--fake`는 API 없이 파이프라인만 확인한다(의미 검색이 아니라 점수는 의미 없음).
- 2026-11-07 실제 실행(gemini-embedding-001·768, top_k 3, 임계값 0.6): hit@1 23/24, hit@3 24/24, 다른 상품·버전 섞임 0, 근거 부족 1/1 구분, 답할 수 있는 질문을 잘못 거절 0, 27/27. 자세한 표는 평가 스크립트를 다시 돌려 보고서로 만든다(DESIGN_CHANGES C-075에도 요약이 있다).
- 이 평가는 **검색**만 잰다. 모델 답변 품질은 아래 수동 확인뿐이다.

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/terms/products/{kind}/{product_id}` | 지금 가입할 때 동의할 약관(revision_id, set_hash, items). 없으면 409 `TERMS_NOT_CONFIGURED` |
| GET | `/terms/versions/{terms_version_id}` | 저장된 그 버전 전체 원문 + 조항 목록 |
| GET | `/terms/consents/{kind}/{subject_id}` | 내 계좌·카드의 가입 당시 동의 기록. 기능 도입 전 가입은 `has_record: false` |
| POST | `/accounts/{checking,deposit,savings}`, `/cards/{credit,debit}` | 본문에 `terms: {revision_id, set_hash, agreements: [{terms_version_id, agreed}]}` 필수 |
| GET | `/agent/conversations/{id}/messages` | 대화 다시 열기(출처 포함) |

가입 오류 코드: 409 `TERMS_OUTDATED`(화면을 연 사이 약관 변경 → 다시 불러와 재동의), 409 `TERMS_NOT_CONFIGURED`, 400 `TERMS_REQUIRED_NOT_AGREED`, 400 `TERMS_INVALID`(중복·누락·다른 상품·없는 버전), 422(`terms` 없음, `agreed`가 bool 아님).
