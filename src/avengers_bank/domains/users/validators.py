"""회원 정보 입력 검증. 가입(UserCreate)과 내 정보 수정(UserUpdate)이 같은 규칙을 쓴다.

여기서 내는 ValueError 메시지는 422 응답의 details[].msg 로 그대로 나가므로 완성된 한국어 문장으로 쓴다.
"""

import re
import string
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field

LOGIN_ID_PATTERN = re.compile(r"^[a-z0-9_]{4,20}$")
PHONE_PATTERN = re.compile(r"^01[016789]\d{7,8}$")


def normalize_login_id(value):
    """앞뒤 공백을 지우고 소문자로. 가입·로그인 둘 다 쓴다(로그인은 형식 검사 없이 이것만)."""
    return value.strip().lower() if isinstance(value, str) else value


def check_login_id(value: str) -> str:
    if not LOGIN_ID_PATTERN.fullmatch(value):
        raise ValueError("아이디는 영문 소문자, 숫자, 밑줄(_)만 4~20자로 입력해 주세요.")
    return value


def strip(value):
    return value.strip() if isinstance(value, str) else value


def blank_to_none(value):
    value = strip(value)
    return value or None if isinstance(value, str) else value


def format_phone(value: str) -> str:
    """하이픈·공백을 빼고 휴대폰 번호인지 본 뒤 010-1234-5678 (10자리면 011-123-4567) 모양으로 바꾼다."""
    digits = re.sub(r"[\s-]", "", value)
    if not PHONE_PATTERN.fullmatch(digits):
        raise ValueError("휴대폰 번호를 010-1234-5678 형식으로 입력해 주세요.")
    middle = 7 if len(digits) == 11 else 6
    return f"{digits[:3]}-{digits[3:middle]}-{digits[middle:]}"


def _password_strength(label: str):
    def check(value: str) -> str:
        # 은행 앱처럼 키보드의 영문·숫자·특수문자만 쓴다. 한글은 한/영 전환 실수와 기기마다 다른
        # 유니코드 조합(NFC/NFD) 때문에 같은 비밀번호가 다르게 저장될 수 있어 받지 않는다.
        if any(c not in string.ascii_letters + string.digits + string.punctuation for c in value):
            raise ValueError(f"{label} 영문, 숫자, 특수문자(!@#$ 등)만 사용할 수 있습니다.")
        has_letter = any(c in string.ascii_letters for c in value)
        has_digit = any(c in string.digits for c in value)
        has_special = any(c in string.punctuation for c in value)
        if not (has_letter and has_digit and has_special):
            raise ValueError(f"{label} 영문, 숫자, 특수문자를 모두 포함해야 합니다.")
        return value

    return check


LoginId = Annotated[str, BeforeValidator(normalize_login_id), AfterValidator(check_login_id)]
Name = Annotated[Annotated[str, Field(min_length=1, max_length=50)], BeforeValidator(strip)]
NickName = Annotated[Annotated[str, Field(max_length=50)] | None, BeforeValidator(blank_to_none)]
Phone = Annotated[str, Field(max_length=20), AfterValidator(format_phone)]
NewPassword = Annotated[
    str, Field(min_length=8, max_length=128, repr=False), AfterValidator(_password_strength("비밀번호는"))
]
ChangedPassword = Annotated[
    str, Field(min_length=8, max_length=128, repr=False), AfterValidator(_password_strength("새 비밀번호는"))
]
