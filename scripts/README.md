# scripts/ — 검증·생성 스크립트

pytest는 SQLite로 돌아가고, SQLite는 `SELECT ... FOR UPDATE` 잠금을 무시합니다. 그래서 **pytest가 통과해도 동시 요청에서
돈이 맞는지는 확인되지 않습니다.** 이 폴더의 스크립트가 실제 PostgreSQL에서 그걸 확인합니다
(배경: `docs/DESIGN_CHANGES.md`의 C-017, C-021, C-022, C-023, C-025).

pytest에는 포함되지 않습니다(`testpaths = ["tests"]`). **사람이 직접 실행**합니다.

## 준비

```bash
docker compose up -d --wait
uv run alembic upgrade head
uv run python -m avengers_bank.seed      # 상품 데이터가 필요합니다
```

## 실행

| 스크립트 | 확인하는 것 |
|---|---|
| `pg_charge_concurrency.py` | 동시 충전 30건: 잠금이 있으면 합계가 맞고, 없으면 갱신이 사라진다 (C-021) |
| `pg_transfer_concurrency.py` | 동시 이체: 잔액 경쟁, 1일 한도 경쟁, A→B / B→A 데드락 없음 (C-022) |
| `pg_card_concurrency.py` | 동시 카드 결제: 신용 한도, 체크카드 잔액, 청구서 납부·생성의 "두 번 누름", 섞어서 동시에 (C-023) |
| `pg_close_concurrency.py` | 동시 해지: 같은 예금을 20번 동시에 해지해도 한 번만 나가고, 해지와 입금이 섞여도 해지된 계좌에 돈이 남지 않는다 (C-043) |
| `pg_unique_violation_message.py` | 계좌·카드번호 중복 때 `IntegrityError` 메시지에 `account_num`/`card_num`이 있는지(번호 재시도의 전제), 외래키 오류가 번호 충돌로 오인되지 않는지 (C-020, C-023) |

```bash
uv run python scripts/pg_charge_concurrency.py
uv run python scripts/pg_transfer_concurrency.py
uv run python scripts/pg_card_concurrency.py
uv run python scripts/pg_close_concurrency.py
uv run python scripts/pg_unique_violation_message.py
```

각 스크립트는 통과하면 종료 코드 0, 실패하면 1입니다.

## 읽는 법

- **"대조군"** 은 일부러 잠금을 뺀 상태로 같은 요청을 다시 보냅니다. 거기서 문제(돈이 사라짐, 중복 납부, 데드락)가 **재현돼야**
  이 검증이 실제 문제를 알아볼 수 있다는 뜻입니다. 대조군은 읽기와 쓰기 사이에 짧은 대기를 넣어 경쟁 구간을 넓힙니다.
  실제 요청에서 같은 비율로 일어난다는 뜻은 아닙니다.
- 대조군의 정확한 숫자(예: 사라진 금액)는 실행할 때마다 조금씩 다릅니다. 스크립트는 숫자가 아니라 "문제가 재현됐는가"를 봅니다.
- 서비스 함수를 직접 호출합니다(HTTP를 거치지 않음). 라우터 계층은 확인하지 않습니다.

## 주의

- **개발용 PostgreSQL(127.0.0.1)에서만 실행됩니다.** 다른 호스트면 시작하자마자 끝납니다.
- DB에 `verify_...` 이름의 사용자와 그 계좌·카드·거래내역을 만들고, **끝나면 (실패해도) 지웁니다.** 이전 실행이 중간에 끊겨서
  남긴 같은 이름의 데이터는 시작할 때 먼저 지웁니다. 다른 사용자의 데이터는 건드리지 않습니다.
- 서비스 코드를 바꾼 뒤(특히 `lock_*`, 이체·결제·청구서 처리) 다시 실행해서 확인하세요.

---

## ERD 다이어그램 생성 (`generate_erd_drawio.py`)

현재 SQLAlchemy 모델에서 `docs/AvengersBankDiagram_v2.drawio`를 만듭니다. **DB 연결이 필요 없습니다.** 원본(`AvengersBankDiagram.drawio`)은 건드리지 않습니다.

```bash
uv run python scripts/generate_erd_drawio.py
```

- 모델(테이블·컬럼·외래키)이 바뀌면 다시 실행하세요. 표와 관계선은 모델에서 읽으므로 코드와 어긋나지 않습니다.
- **draw.io에서 표 위치를 손으로 옮기고 저장해도, 다시 생성하면 덮어씁니다.** 위치를 바꾸고 싶으면 스크립트의 `TABLES`(표 이름과 x, y)를 고치세요.
- 새 테이블을 추가하면 `TABLES`에 한글 이름과 위치를 추가해야 합니다(빠뜨리면 스크립트가 오류로 알려 줍니다).
- 노란 칸은 팀 초기 설계에서 바뀐 곳입니다(`NEW_TABLES`, `CHANGED`). 인덱스와 CHECK 제약은 그리지 않습니다.
