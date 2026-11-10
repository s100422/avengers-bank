import { AccountNotification, HISTORY_TYPE, won } from "@/lib/api";

export function notificationText(item: AccountNotification) {
  const [label, outgoing] = HISTORY_TYPE[item.type] ?? [item.type, false];
  const person = item.counterpart_name?.trim();
  const accountNumber = item.counterpart_account;
  let title: string;
  if (item.type === "INTERBANK_REFUND") title = `타행 이체 환불 ${won(item.amount)} 입금`;
  else if (item.type === "CARD_PAYMENT") title = `${person ?? "가맹점"}에서 ${won(item.amount)} 결제`;
  else if (item.type === "CARD_BILL_PAYMENT") title = `${person ?? "카드"} 대금 ${won(item.amount)} 출금`;
  else if (person) title = `${person}${outgoing ? "에게" : "에게서"} ${won(item.amount)} ${outgoing ? "출금" : "입금"}`;
  else if (accountNumber) title = `${accountNumber} 계좌${outgoing ? "로" : "에서"} ${won(item.amount)} ${outgoing ? "출금" : "입금"}`;
  else title = `${label} ${won(item.amount)} ${outgoing ? "출금" : "입금"}`;
  const account = item.account_nickname
    ? `${item.account_nickname} (${item.account_num})`
    : item.account_num;
  return { title, body: `${account} · 거래 후 잔액 ${won(item.balance_after)}` };
}
