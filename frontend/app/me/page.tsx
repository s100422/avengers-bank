"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, ErrorText, Field, Shell } from "@/components/ui";
import { PHONE, PhoneVerify, digits } from "@/components/verify";
import { ApiError, Device, Session, User, api, devices, logout, logoutAll, session } from "@/lib/api";
import { useFreshOnLeave } from "@/lib/fresh";

export default function MePage() {
  return (
    <Shell>
      <Me key={useFreshOnLeave()} />
    </Shell>
  );
}

function Me() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<User>("/users/me").then(setUser).catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <h1 className="mt-4 text-2xl font-semibold">내 정보</h1>
      <ErrorText message={error} />
      {user && (
        <>
          <p className="mt-1 text-slate">아이디 {user.login_id}</p>
          <ProfileForm user={user} onSaved={setUser} />
          <PhoneChangeForm user={user} />
          {/* 내 정보를 못 불러왔으면 비밀번호 변경도 숨긴다 */}
          <PasswordForm />
        </>
      )}
      {user && <Devices />}
      <button
        className="mt-10 w-full rounded-xl border border-line py-3 text-slate hover:text-ink"
        onClick={async () => {
          await logout(); // 서버 세션도 끊는다(실패해도 로그아웃은 진행)
          router.replace("/login");
        }}
      >
        로그아웃
      </button>
      <button
        className="mt-3 w-full rounded-xl py-3 text-sm text-slate underline underline-offset-4 hover:text-ink"
        onClick={async () => {
          if (!confirm("이 기기를 포함해 로그인된 모든 기기에서 로그아웃할까요?")) return;
          try {
            await logoutAll(); // 다른 기기의 세션까지 서버에서 끊는다
            router.replace("/login");
          } catch (e) {
            setError((e as Error).message);
          }
        }}
      >
        모든 기기에서 로그아웃
      </button>
      {user && <Withdrawal user={user} />}
    </>
  );
}

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" }) : "-");

function Devices() {
  const [list, setList] = useState<Device[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    devices.list().then(setList).catch((e) => setError(e.message));
  }, []);

  async function revoke(d: Device) {
    if (!confirm(`'${d.label}' 기기를 해제할까요? 해제하면 이 기기는 다시 문자 인증을 해야 로그인할 수 있습니다.`)) return;
    setError(null);
    try {
      await devices.revoke(d.device_id);
      setList((l) => l && l.filter((x) => x.device_id !== d.device_id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="mt-10">
      <h2 className="text-sm text-slate">로그인한 기기</h2>
      <ErrorText message={error} />
      <ul className="mt-2 space-y-2">
        {list?.map((d) => (
          <li key={d.device_id} className="flex items-center justify-between gap-3 rounded-xl border border-line px-3 py-2.5">
            <div className="min-w-0 text-sm">
              <p className="font-medium">
                {d.label}
                {d.current && <span className="ml-2 rounded-full bg-coral-soft px-2 py-0.5 text-xs font-normal">이 기기</span>}
              </p>
              <p className="text-slate">
                등록일 {fmt(d.created_at)} · 마지막 사용 {fmt(d.last_used_at)}
              </p>
            </div>
            <button onClick={() => revoke(d)} className="min-h-11 shrink-0 text-sm text-slate underline underline-offset-4 hover:text-ink">
              해제
            </button>
          </li>
        ))}
        {list?.length === 0 && <li className="text-sm text-slate">등록된 기기가 없습니다.</li>}
      </ul>
    </section>
  );
}

type Blocker = {
  code: "ACTIVE_DEPOSIT" | "ACTIVE_SAVINGS" | "CHECKING_BALANCE" | "CARD_UNPAID";
  message: string;
  account_type: "checking" | "deposit" | "savings" | null;
  account_id: number | null;
  card_id: number | null;
};

// 막는 사유마다 '그 일을 하러 갈' 화면. 예금·적금 해지는 계좌 상세, 잔액은 이체, 카드 대금은 카드 상세(청구서 납부)
function blockerLink(b: Blocker): [string, string] {
  if (b.code === "CHECKING_BALANCE") return [`/transfer?from=${b.account_id}`, "이체하러 가기"];
  if (b.code === "CARD_UNPAID") return [`/cards/credit/${b.card_id}`, "납부하러 가기"];
  return [`/accounts/${b.account_type}/${b.account_id}`, "해지하러 가기"];
}

/** 회원 탈퇴: 일부러 눈에 덜 띄게 접어 둔다. 펼치면 탈퇴할 수 있는지 서버에 묻는다 */
function Withdrawal({ user }: { user: User }) {
  const [status, setStatus] = useState<{ can_withdraw: boolean; blockers: Blocker[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null); // 등록 번호로 받은 WITHDRAWAL 증표
  const [round, setRound] = useState(0); // 증표가 만료되면 올려서 인증을 처음부터
  const [busy, setBusy] = useState(false);

  async function load() {
    setError(null);
    try {
      setStatus(await api("/users/me/withdrawal"));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (!token) return setError("휴대폰 인증을 먼저 해 주세요.");
    if (!confirm("정말 탈퇴할까요? 탈퇴하면 되돌릴 수 없고, 같은 아이디로 다시 가입할 수 없습니다.")) return;
    setBusy(true);
    setError(null);
    try {
      await api("/users/me/withdrawal", { current_password: f.get("current_password"), phone_verification_token: token });
      // 서버 세션은 이미 모두 끊겼다. 저장된 토큰은 로그인 화면이 지운다(reason=withdrawn): 여기서 지우면
      // 세션 타이머가 '다른 탭 로그아웃'으로 보고 이유 없는 /login으로 먼저 보낼 수 있다
      location.replace("/login?reason=withdrawn");
      return;
    } catch (err) {
      setError((err as Error).message);
      if (err instanceof ApiError && err.code === "INVALID_VERIFICATION_TOKEN") {
        setToken(null);
        setRound((n) => n + 1);
      }
      if (err instanceof ApiError && err.code === "WITHDRAWAL_BLOCKED") load(); // 그사이 입금 등으로 막혔다
    }
    setBusy(false);
  }

  return (
    <details className="mt-16 text-sm text-slate" onToggle={(e) => e.currentTarget.open && !status && load()}>
      <summary className="cursor-pointer underline-offset-4 hover:text-ink hover:underline">회원 탈퇴</summary>
      <div className="mt-3 space-y-3">
        {status && !status.can_withdraw && (
          <>
            <p>아래를 먼저 정리해야 탈퇴할 수 있습니다.</p>
            <ul className="space-y-2">
              {status.blockers.map((b, i) => {
                const [href, label] = blockerLink(b);
                return (
                  <li key={i} className="rounded-xl border border-line p-3">
                    <p className="text-ink">{b.message}</p>
                    <Link href={href} className="mt-1 inline-block text-coral underline underline-offset-4">
                      {label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </>
        )}
        {status?.can_withdraw && (
          <form onSubmit={onSubmit} className="space-y-3">
            <ul className="list-disc space-y-1 pl-5">
              <li>이름·닉네임·휴대폰 번호와 AI 비서 대화 기록은 지워집니다.</li>
              <li>입출금 계좌는 닫히고 카드는 모두 해지됩니다. 닫힌 계좌로는 돈을 받을 수 없습니다.</li>
              <li>거래 내역과 약관 동의 기록은 관련 법에 따라 정해진 기간 동안 보관됩니다.</li>
              <li>같은 아이디({user.login_id})로는 다시 가입할 수 없습니다.</li>
            </ul>
            <Field label="현재 비밀번호" name="current_password" type="password" autoComplete="current-password" required />
            <p>등록된 휴대폰({user.phone})으로 본인 확인을 해 주세요.</p>
            <PhoneVerify
              key={round}
              path="/verification/phone/send-for-me"
              body={{ purpose: "WITHDRAWAL" }}
              devPhone={user.phone}
              onVerified={setToken}
            />
            <Button busy={busy} disabled={!token}>
              탈퇴하기
            </Button>
          </form>
        )}
        <ErrorText message={error} />
      </div>
    </details>
  );
}

function ProfileForm({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const body = { name: f.get("name"), nick_name: f.get("nick_name") || null };
      const saved = await api<User>("/users/me", body, "PATCH");
      onSaved(saved);
      setMsg({ ok: true, text: "저장했습니다." });
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
    setBusy(false);
  }

  return (
    <form onSubmit={onSubmit} className="mt-6 space-y-4">
      <Field label="이름" name="name" defaultValue={user.name} required />
      <Field label="닉네임 (선택)" name="nick_name" defaultValue={user.nick_name ?? ""} />
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-slate" : "text-seal"}`}>{msg.text}</p>}
      <Button busy={busy}>
        정보 저장
      </Button>
    </form>
  );
}

function PhoneChangeForm({ user }: { user: User }) {
  const [phone, setPhone] = useState("");
  const [oldToken, setOldToken] = useState<string | null>(null);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const changed = digits(phone) !== digits(user.phone);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const currentPassword = new FormData(e.currentTarget).get("current_password");
    if (!PHONE.test(phone.trim())) return setMsg("휴대폰 번호를 확인해 주세요.");
    if (!oldToken || !newToken) return setMsg("현재 번호와 새 번호를 모두 인증해 주세요.");
    setBusy(true);
    setMsg(null);
    try {
      await api("/users/me/phone-change", {
        phone: phone.trim(),
        current_password: currentPassword,
        old_phone_verification_token: oldToken,
        new_phone_verification_token: newToken,
      });
      session.clear();
      location.replace("/login");
      return;
    } catch (err) {
      setMsg((err as Error).message);
      if (err instanceof ApiError && err.code === "INVALID_VERIFICATION_TOKEN") {
        setOldToken(null);
        setNewToken(null);
        setRound((n) => n + 1);
      }
    }
    setBusy(false);
  }

  return (
    <form onSubmit={onSubmit} className="mt-10 space-y-4">
      <h2 className="text-sm text-slate">휴대폰 번호 변경</h2>
      <p className="text-sm text-slate">현재 등록된 번호 {user.phone}</p>
      <Field label="새 휴대폰 번호 (010-0000-0000 또는 01000000000)" name="phone" type="tel" inputMode="tel" value={phone} onChange={(e) => { setPhone(e.target.value); setNewToken(null); }} required />
      {changed && (
        <div className="space-y-4">
          <div className="space-y-2">
            <p className="text-sm text-slate">현재 등록된 번호로 본인 확인을 해 주세요.</p>
            <PhoneVerify key={`old:${round}`} path="/verification/phone/send-for-me" body={{ purpose: "CHANGE_PHONE_OLD" }} devPhone={user.phone} onVerified={setOldToken} />
          </div>
          <div className="space-y-2">
            <p className="text-sm text-slate">새 번호로 인증해 주세요.</p>
            <PhoneVerify key={`new:${phone}:${round}`} path="/verification/phone/send-for-me" body={{ phone: phone.trim(), purpose: "CHANGE_PHONE_NEW" }} devPhone={phone.trim()} disabled={!PHONE.test(phone.trim())} onVerified={setNewToken} />
          </div>
          <Field label="현재 비밀번호" name="current_password" type="password" autoComplete="current-password" required />
        </div>
      )}
      {msg && <p role="alert" className="text-sm text-seal">{msg}</p>}
      <Button busy={busy} disabled={!changed || !oldToken || !newToken || !PHONE.test(phone.trim())}>휴대폰 번호 변경</Button>
    </form>
  );
}

function PasswordForm() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    if (f.get("new_password") !== f.get("new_password_confirm")) {
      return setMsg({ ok: false, text: "비밀번호가 일치하지 않습니다." });
    }
    setBusy(true);
    try {
      // 서버가 다른 기기의 세션을 모두 끊고 이 기기용 새 세션을 준다 → 저장된 토큰을 바꾼다
      session.save(
        await api<Session>(
          "/users/me/password",
          { current_password: f.get("current_password"), new_password: f.get("new_password") },
          "PATCH",
        ),
      );
      form.reset();
      setMsg({ ok: true, text: "비밀번호를 바꿨습니다." });
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
    setBusy(false);
  }

  return (
    <form onSubmit={onSubmit} className="mt-10 space-y-4">
      <h2 className="text-sm text-slate">비밀번호 변경</h2>
      <Field label="현재 비밀번호" name="current_password" type="password" autoComplete="current-password" required />
      <Field
        label="새 비밀번호 (8자 이상, 영문·숫자·특수문자 포함)"
        name="new_password"
        type="password"
        autoComplete="new-password"
        minLength={8}
        maxLength={128}
        required
      />
      <Field label="새 비밀번호 확인" name="new_password_confirm" type="password" autoComplete="new-password" required />
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-slate" : "text-seal"}`}>{msg.text}</p>}
      <Button busy={busy}>비밀번호 바꾸기</Button>
    </form>
  );
}
