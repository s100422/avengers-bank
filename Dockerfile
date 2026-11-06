# 운영용 이미지 (C-052). 로컬 개발은 uv run fastapi dev를 쓴다.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# 의존성과 소스를 설치한다 (lock 파일 그대로, 개발용 패키지 제외)
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# 마이그레이션·시드를 이 이미지에서 일회성으로 실행하기 위해 alembic도 넣는다
COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --system --uid 10001 app
USER app
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# --proxy-headers: Caddy가 넘겨 주는 X-Forwarded-For로 실제 접속 IP를 읽는다 (로그인 실패 제한이 IP별로 센다, C-040).
# '*'는 이 컨테이너 포트를 Caddy만 접근하는 내부 네트워크에만 열었을 때 안전하다 (docker-compose.prod.yml).
# 워커는 1개: 로그인 실패 횟수를 프로세스 메모리에서 세기 때문이다 (C-040).
CMD ["uvicorn", "avengers_bank.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
