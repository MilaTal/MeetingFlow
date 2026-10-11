"""Учётные записи и вход по паролю — как в Проекте ERP и Планёрке (владелец 11.10.26).

- Пароль — hashlib.scrypt из стандартной библиотеки, соль на каждую запись; сам пароль нигде не хранится и не
  печатается.
- Пять неверных паролей подряд — запись блокируется на 15 минут; с одного адреса больше 20 неудач за 10 минут —
  адрес временно не принимается. Неизвестный логин отвечает так же, как неверный пароль.
- Сессия — случайный токен в cookie; в базе хранится только его sha256. Срок — 12 часов.
- Вход по паролю по умолчанию выключен (тестовый режим: роль выбирается на экране). Включить его можно, только
  подтвердив логин и пароль учётной записи супер-администратора, — иначе после включения войти было бы нечем.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from .store import Store, now

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
MAX_FAILED = 5
LOCK_MINUTES = 15
IP_WINDOW, IP_MAX = 600, 20
SESSION_HOURS = 12
MIN_PASSWORD = 8
AUTH_KEY = "auth_required"


class AuthError(ValueError):
    """Отказ входа или проверки пароля — текст для человека."""


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    d = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(d)}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        _, n, r, p, salt, digest = (stored or "").split("$")
        d = hashlib.scrypt((password or "").encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r),
                           p=int(p), dklen=32)
        return hmac.compare_digest(d, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password(secrets.token_hex(8))   # неизвестный логин тратит то же время, что и проверка пароля


class Accounts:
    def __init__(self, store: Store):
        self.s = store
        self._ip: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    # ------------------------------------------------------------ режим
    def auth_required(self) -> bool:
        return bool(self.s.get_setting(AUTH_KEY, None, False))

    def set_auth_required(self, value: bool, by: str) -> None:
        self.s.set_setting(AUTH_KEY, bool(value), None, by)

    # ------------------------------------------------------------ записи
    def list(self) -> list[dict]:
        return self.s.q("SELECT id, login, full_name, role, active, last_login_at, locked_until, created_at "
                        "FROM accounts ORDER BY id")

    def by_login(self, login: str) -> dict | None:
        rows = self.s.q("SELECT * FROM accounts WHERE login=?", ((login or "").strip().lower(),))
        return rows[0] if rows else None

    def has_super_admin(self) -> bool:
        return bool(self.s.q("SELECT id FROM accounts WHERE role='super_admin' AND active=1 AND password_hash != ''"))

    def save(self, login: str, full_name: str, role: str, password: str) -> dict:
        login = (login or "").strip().lower()
        if not login or any(ch.isspace() for ch in login):
            raise AuthError("Логин — одно слово без пробелов.")
        if len(password or "") < MIN_PASSWORD:
            raise AuthError(f"Пароль — не короче {MIN_PASSWORD} знаков.")
        h = hash_password(password)
        old = self.by_login(login)
        if old:
            self.s.update("accounts", old["id"], full_name=full_name or old["full_name"], role=role, password_hash=h,
                          failed_attempts=0, locked_until=None, active=1)
            return self.by_login(login)
        self.s.insert("accounts", login=login, full_name=full_name or login, role=role, password_hash=h, active=1,
                      failed_attempts=0, created_at=now())
        return self.by_login(login)

    # ------------------------------------------------------------ проверка пароля
    def _ip_blocked(self, ip: str) -> bool:
        q = self._ip[ip]
        while q and q[0] < time.time() - IP_WINDOW:
            q.popleft()
        return len(q) >= IP_MAX

    def check(self, login: str, password: str, ip: str = "") -> dict:
        """Логин и пароль; неудача — AuthError с одной и той же фразой, блокировки считаются."""
        with self._lock:
            if ip and self._ip_blocked(ip):
                raise AuthError("Слишком много неудачных попыток с этого адреса. Повторите через 10 минут.")
            a = self.by_login(login)
            if a and a["locked_until"] and a["locked_until"] > now():
                raise AuthError("Учётная запись временно заблокирована после неверных паролей. Повторите позже.")
            ok = verify_password(password, a["password_hash"] if a else _DUMMY) and bool(a) and bool(a["active"])
            if not ok:
                if ip:
                    self._ip[ip].append(time.time())
                if a:
                    n = int(a["failed_attempts"] or 0) + 1
                    lock = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%dT%H:%M:%S") \
                        if n >= MAX_FAILED else None
                    self.s.update("accounts", a["id"], failed_attempts=0 if lock else n, locked_until=lock)
                raise AuthError("Неверный логин или пароль.")
            self.s.update("accounts", a["id"], failed_attempts=0, locked_until=None)
            return a

    # ------------------------------------------------------------ сессии
    def open_session(self, account: dict) -> str:
        token = secrets.token_urlsafe(32)
        exp = (datetime.now() + timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%dT%H:%M:%S")
        self.s.insert("sessions", token_hash=hashlib.sha256(token.encode()).hexdigest(), account_id=account["id"],
                      created_at=now(), expires_at=exp)
        self.s.update("accounts", account["id"], last_login_at=now())
        return token

    def by_session(self, token: str | None) -> dict | None:
        if not token:
            return None
        rows = self.s.q("SELECT a.* FROM sessions s JOIN accounts a ON a.id = s.account_id WHERE s.token_hash=? "
                        "AND s.expires_at > ? AND a.active=1", (hashlib.sha256(token.encode()).hexdigest(), now()))
        return rows[0] if rows else None

    def close_session(self, token: str | None) -> None:
        if token:
            for r in self.s.q("SELECT id FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)):
                self.s.delete("sessions", r["id"])
