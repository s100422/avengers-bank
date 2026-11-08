"""관리자 명령 ('고객센터 처리' 흉내): 계좌가 없거나 비밀번호·휴대폰을 모두 잃어 스스로 복구할 수 없는 사용자용.

    uv run python -m avengers_bank.admin unlock <login_id>           로그인 잠금 해제 + 실패 횟수 0
    uv run python -m avengers_bank.admin reset-password <login_id>   새 비밀번호 입력 → 잠금 해제, 모든 세션 폐기

ENABLE_DEV_ENDPOINTS가 꺼진 환경(운영 DB로 보고)에서는 아이디를 한 번 더 입력해야 실행한다.
"""

import argparse
import asyncio
import getpass
import selectors
import sys

from pydantic import BaseModel, ValidationError

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.core.exception_handlers import korean_message
from avengers_bank.domains.users.service import user_service
from avengers_bank.domains.users.validators import NewPassword, normalize_login_id

class _NewPassword(BaseModel):
    password: NewPassword


def check_new_password(login_id: str, password: str) -> str | None:
    """가입과 같은 비밀번호 규칙. 문제가 있으면 한국어 이유, 없으면 None."""
    try:
        _NewPassword(password=password)
    except ValidationError as error:
        return korean_message(error.errors()[0])  # 422 응답과 같은 한국어 문장
    if password.lower() == login_id:
        return "비밀번호는 아이디와 같을 수 없습니다."
    return None


async def unlock(login_id: str) -> bool:
    async with SessionLocal() as db:
        return await user_service.unlock_login(db, login_id)


async def reset_password(login_id: str, new_password: str) -> bool:
    async with SessionLocal() as db:
        return await user_service.reset_password(db, login_id, new_password)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m avengers_bank.admin", description="관리자 명령")
    parser.add_argument("command", choices=["unlock", "reset-password"])
    parser.add_argument("login_id")
    args = parser.parse_args(argv)
    login_id = normalize_login_id(args.login_id)

    if not get_settings().enable_dev_endpoints:
        print("ENABLE_DEV_ENDPOINTS가 꺼져 있습니다: 운영 DB일 수 있습니다.")
        if input(f"정말 '{login_id}'에 {args.command}를 실행하려면 아이디를 다시 입력하세요: ").strip().lower() != login_id:
            sys.exit("취소했습니다.")

    if args.command == "unlock":
        job = unlock(login_id)
        done = "잠금을 해제했습니다."
    else:
        password = getpass.getpass("새 비밀번호: ")
        if (problem := check_new_password(login_id, password)) is not None:
            sys.exit(problem)
        if getpass.getpass("새 비밀번호 확인: ") != password:
            sys.exit("두 비밀번호가 다릅니다.")
        job = reset_password(login_id, password)
        done = "비밀번호를 바꾸고 잠금을 해제했습니다. 모든 기기에서 로그아웃되었습니다."

    async def run() -> bool:
        try:
            return await job
        finally:
            await engine.dispose()

    # Windows에서 psycopg 비동기 모드는 Selector 이벤트 루프가 필요하다 (C-016)
    found = asyncio.run(run(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    if not found:
        sys.exit(f"사용자를 찾을 수 없습니다: {login_id}")
    print(done)


if __name__ == "__main__":
    main()
