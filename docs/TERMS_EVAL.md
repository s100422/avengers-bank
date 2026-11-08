# 약관 검색 오프라인 평가

- 실행 종류: **REAL (Gemini API)**
- 임베딩: gemini-embedding-001, 768차원 / 청커 sec-v1
- 문서 21개, 청크 123개, top_k=3, min_score=0.6
- 점수는 코사인 유사도이며 정답 확률이 아니다.

## 요약

| 항목 | 값 |
|---|---|
| answer_cases | 24 |
| hit@1 | 23 |
| hit@3 | 24 |
| contamination | 0 |
| insufficient_detected | 1/1 |
| answer_cases_wrongly_insufficient | 0 |
| clarify_product_routed | 1/1 |
| lookup_owned_agreement_routed | 1/1 |
| cases_ok | 27/27 |

## 임계값 스윕 (terms_min_score 조정용)

| 임계값 | 답변 사례 중 기대 조항이 임계값 이상 | 근거 부족 사례 중 거절 |
|---|---|---|
| 0.30 | 24/24 | 0/1 |
| 0.35 | 24/24 | 0/1 |
| 0.40 | 24/24 | 0/1 |
| 0.45 | 24/24 | 0/1 |
| 0.50 | 24/24 | 0/1 |
| 0.55 | 24/24 | 0/1 |
| 0.60 | 24/24 | 1/1 |
| 0.65 | 21/24 | 1/1 |
| 0.70 | 15/24 | 1/1 |
| 0.75 | 7/24 | 1/1 |
| 0.80 | 0/24 | 1/1 |

## 사례별

| id | 기대 동작 | 결과 | 기대 조항 순위(임계값 무시) | 기대 조항 점수 | 최고 점수 | 상위 결과 |
|---|---|---|---|---|---|---|
| T01 | answer_with_citation | OK | 1 | 0.756 | 0.756 | ab.checking.rules#limits (0.756)<br>ab.checking.rules#transfer (0.685)<br>ab.common#amount-date (0.667) |
| T02 | answer_with_citation | OK | 1 | 0.687 | 0.687 | ab.checking.rules#interest (0.687)<br>ab.product.checking-basic#demo-limitations (0.659)<br>ab.product.checking-basic#conditions (0.660) |
| T03 | answer_with_citation | OK | 1 | 0.727 | 0.727 | ab.product.checking-salary#demo-limitations (0.727)<br>ab.checking.rules#closing (0.655)<br>ab.product.checking-salary#preamble (0.656) |
| T04 | answer_with_citation | OK | 1 | 0.758 | 0.758 | ab.deposit.rules#early-close (0.758)<br>ab.product.deposit-basic#early-close-example (0.708)<br>ab.deposit.rules#closing (0.715) |
| T05 | answer_with_citation | OK | 1 | 0.736 | 0.736 | ab.deposit.rules#maturity (0.736)<br>ab.deposit.rules#interest (0.671)<br>ab.product.deposit-basic#early-close-example (0.667) |
| T06 | answer_with_citation | OK | 1 | 0.719 | 0.719 | ab.deposit.rules#funding (0.719)<br>ab.deposit.rules#closing (0.658)<br>ab.product.deposit-basic#demo-limitations (0.643) |
| T07 | answer_with_citation | OK | 1 | 0.754 | 0.754 | ab.product.deposit-star#demo-limitations (0.754)<br>ab.product.deposit-star#product (0.690)<br>ab.product.deposit-star#preamble (0.688) |
| T08 | answer_with_citation | OK | 1 | 0.731 | 0.731 | ab.product.deposit-mobile#demo-limitations (0.731)<br>ab.product.deposit-mobile#preamble (0.688)<br>ab.product.deposit-mobile#product (0.672) |
| T09 | answer_with_citation | OK | 2 | 0.706 | 0.729 | ab.savings.rules#schedule (0.729)<br>ab.savings.rules#opening (0.706)<br>ab.savings.rules#funding (0.664) |
| T10 | answer_with_citation | OK | 1 | 0.753 | 0.753 | ab.savings.rules#schedule (0.753)<br>ab.savings.rules#maturity (0.727)<br>ab.savings.rules#opening (0.698) |
| T11 | answer_with_citation | OK | 1 | 0.759 | 0.759 | ab.product.savings-flexible#early-close-example (0.759)<br>ab.savings.rules#early-close (0.703)<br>ab.product.savings-flexible#conditions (0.739) |
| T12 | answer_with_citation | OK | 1 | 0.694 | 0.694 | ab.product.savings-youth#demo-limitations (0.694)<br>ab.savings.rules#opening (0.640)<br>ab.savings.rules#funding (0.628) |
| T13 | answer_with_citation | OK | 1 | 0.622 | 0.622 | ab.product.savings-youth#demo-limitations (0.622)<br>ab.product.savings-youth#conditions (0.615) |
| T14 | answer_with_citation | OK | 1 | 0.680 | 0.680 | ab.credit.rules#payment (0.680)<br>ab.credit.rules#bill-payment (0.640)<br>ab.credit.rules#issuance (0.606) |
| T15 | answer_with_citation | OK | 1 | 0.647 | 0.647 | ab.product.credit-premium#demo-limitations (0.647)<br>ab.product.credit-premium#preamble (0.622)<br>ab.product.credit-premium#product (0.614) |
| T16 | answer_with_citation | OK | 1 | 0.651 | 0.651 | ab.product.credit-shopping#demo-limitations (0.651)<br>ab.credit.rules#bill-payment (0.605)<br>ab.credit.rules#payment (0.608) |
| T17 | answer_with_citation | OK | 1 | 0.731 | 0.731 | ab.product.credit-travel#demo-limitations (0.731)<br>ab.credit.rules#benefits (0.670)<br>ab.product.credit-travel#applicable-terms (0.638) |
| T18 | answer_with_citation | OK | 1 | 0.720 | 0.720 | ab.credit.rules#due-date (0.720)<br>ab.credit.rules#billing (0.676)<br>ab.credit.rules#issuance (0.635) |
| T19 | answer_with_citation | OK | 1 | 0.674 | 0.674 | ab.credit.rules#bill-payment (0.674)<br>ab.credit.rules#payment (0.671)<br>ab.credit.rules#status (0.634) |
| T20 | answer_with_citation | OK | 1 | 0.751 | 0.751 | ab.credit.rules#status (0.751)<br>ab.credit.rules#payment (0.672)<br>ab.credit.rules#bill-payment (0.661) |
| T21 | answer_with_citation | OK | 1 | 0.773 | 0.773 | ab.debit.rules#history (0.773)<br>ab.debit.rules#payment (0.704)<br>ab.product.debit-basic#conditions (0.695) |
| T22 | answer_with_citation | OK | 1 | 0.668 | 0.668 | ab.product.debit-nori#demo-limitations (0.668)<br>ab.debit.rules#benefits (0.618)<br>ab.debit.rules#payment (0.616) |
| T23 | answer_with_citation | OK | 1 | 0.648 | 0.648 | ab.product.debit-travel#demo-limitations (0.648)<br>ab.debit.rules#benefits (0.630)<br>ab.product.debit-travel#applicable-terms (0.604) |
| T24 | answer_with_citation | OK | 1 | 0.700 | 0.700 | ab.debit.rules#payment (0.700)<br>ab.product.debit-basic#conditions (0.648)<br>ab.debit.rules#benefits (0.621) |
| T25 | clarify_product | OK | need_product | - | - | - |
| T26 | insufficient_evidence | OK | - | - | 0.594 |  |
| T27 | lookup_owned_agreement | OK | my_contract | - | 0.658 | ab.product.deposit-basic#applicable-terms (0.658)<br>ab.deposit.rules#preamble (0.656)<br>ab.deposit.rules#opening (0.645) |
