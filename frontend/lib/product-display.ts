export type ProductKind = "CHECKING" | "SAVINGS" | "DEPOSIT" | "CREDIT" | "DEBIT";

const productCopy: Record<ProductKind, { name: string; description: string }> = {
  CHECKING: {
    name: "입출금 통장",
    description: "급여 이체와 일상적인 입출금에 편리한 기본 통장이에요.",
  },
  SAVINGS: {
    name: "자유적금",
    description: "매달 꾸준히 모으고 만기에 이자를 받는 적금이에요.",
  },
  DEPOSIT: {
    name: "정기예금",
    description: "목돈을 일정 기간 맡기고 약정 이자를 받는 예금이에요.",
  },
  CREDIT: {
    name: "신용카드",
    description: "일상 결제와 다양한 혜택을 함께 누리는 카드예요.",
  },
  DEBIT: {
    name: "체크카드",
    description: "계좌 잔액 안에서 간편하게 결제하는 카드예요.",
  },
};

const placeholderDescriptions = new Set(["d", "test", "description", "-"]);

export function productName(type: ProductKind, name: string | null | undefined): string {
  const value = name?.trim();
  if (!value || value.toUpperCase() === type) return productCopy[type].name;
  return value;
}

export function productDescription(type: ProductKind, description: string | null | undefined): string {
  const value = description?.trim();
  if (!value || placeholderDescriptions.has(value.toLowerCase())) return productCopy[type].description;
  return value;
}
