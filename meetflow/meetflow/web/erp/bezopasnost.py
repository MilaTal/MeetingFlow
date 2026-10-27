"""Вход по логину и паролю (решение 19.09.26; логин — часть адреса до «@», 05.10.26) — примитивы безопасности.

Пароли — `hashlib.scrypt` из стандартной библиотеки (без новых зависимостей):
уникальная соль на пользователя, параметры хранятся вместе с хэшем, поэтому
их можно усилить позже, не ломая старые пароли. Токен сессии — 32 случайных
байта; в БД лежит только SHA-256 токена, сам токен есть только в HttpOnly-
cookie у пользователя (утечка БД не даёт входа под чужой сессией).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
MIN_PASSWORD_LENGTH = 10
# Логин — часть адреса до «@» (решение владельца 05.10.26). Раньше требовался полный email вида
# name@company.ru: администратор, вносящий команду, знает логины людей, но не обязан помнить домен, и
# ввод «ipetrukevich» отвергался с требованием адреса. Теперь просят ровно то, что человек знает.
# Только ASCII и с буквы/цифры: кириллические «двойники» (а, е, о) и невидимые символы в логине
# приводили бы к двум неразличимым на вид учётным записям.
_LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,199}$")

# Нет похожих символов (0/O, 1/l/I) — временный пароль диктуют голосом и печатают руками.
_TEMP_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Постоянное по времени сравнение. Для несуществующего пользователя
    вызывается с фиктивным хэшем (`DUMMY_HASH`), чтобы время ответа не
    выдавало, есть ли такой логин."""
    try:
        scheme, n, r, p, salt_b64, digest_b64 = (stored or DUMMY_HASH).split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        got = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected) and stored is not None


DUMMY_HASH = hash_password("dummy-password-for-timing-only")


def login_local_part(value: str | None) -> str:
    """Логин человека — часть адреса до «@». Полный адрес принимается тоже и приводится к логину:
    администратор может вставить адрес целиком, и это не должно быть ошибкой — но хранится и
    сравнивается всегда одна форма, иначе «Иванов@company.ru» и «иванов» завели бы две записи."""
    return (value or "").strip().lower().split("@", 1)[0]


def normalize_login(login: str | None) -> str:
    return login_local_part(login)


LOGIN_HINT = ("Логин — часть адреса до «@», например ipetrukevich: латинские буквы, цифры, "
              "точка, дефис или подчёркивание.")


def validate_login(login: str) -> str | None:
    """Возвращает текст ошибки или None. Полный адрес тоже принимается — из него берётся логин."""
    value = login_local_part(login)
    if len(value) > 200 or not _LOGIN_RE.match(value):
        return "Укажите логин. " + LOGIN_HINT
    return None


def validate_email(email: str) -> str | None:
    """Оставлено ради совместимости вызовов: правило теперь то же, что у логина (05.10.26)."""
    return validate_login(email)


_COMMON_PASSWORD_PARTS = ("qwerty", "password", "welcome", "letmein", "admin", "12345", "111111", "йцукен", "пароль", "iloveyou", "monkey", "abc123")


def validate_new_password(password: str, login: str | None = None) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Пароль слишком короткий — минимум {MIN_PASSWORD_LENGTH} символов"
    if password.isdigit():
        return "Пароль не должен состоять только из цифр"
    local = login_local_part(login)
    if local and password.lower() == local:
        return "Пароль не должен совпадать с логином"
    lowered = password.lower()
    if any(bad in lowered for bad in _COMMON_PASSWORD_PARTS):
        return "Слишком распространённый пароль — придумайте другой"
    if len(local) >= 4 and local in password.lower():
        return "Пароль не должен содержать логин — придумайте другой"
    if len(set(password)) < 4:
        return "Пароль слишком простой — используйте больше разных символов"
    return None


def generate_temp_password(length: int = 12) -> str:
    """Временный пароль, выдаваемый администратором; пользователь обязан
    сменить его при первом входе."""
    return "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(length))


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
