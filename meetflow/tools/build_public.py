"""Сборка публичного пакета MeetFlow (плагин + приложение) в отдельную папку — письмо ветки «AI агентные скилы»,
строка 23; владелец 10.10.26: «готовь всё как для внешнего, полный комплект; пока тестируем внутри».

Порядок: только файлы из git → раскладка плагина (skills/meetflow, .claude-plugin, evals) → чистка истории из
комментариев и описаний (код не трогается) → замена реальных фамилий вымышленными → поверх — исходники public/ →
сканер внутренних следов, реальных фамилий из рабочих баз и значений ключей из .env.local (значения не выводятся) →
по флагу --test тесты внутри собранного пакета → по флагу --git новый git с одним коммитом. Ничего не пушит.

  python tools/build_public.py <папка вне репозитория> [--test] [--git]

Закрыто владельцем: курс и учебная часть, внутренние проекты и данные (Планёрка, Проект ERP, реальные имена),
история разработки (решения владельца с датами, письма, сессии), СЛУЧАИ.md."""
from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tokenize
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
HOME_DOCS = Path.home() / "Documents"

# --------------------------------------------------------------------------- что не идёт в пакет
EXCLUDE = [re.compile(p) for p in (
    r"^FRAMEWORK_REPORT\.md$", r"^OPERATOR_TODO\.md$", r"^docs/ERP_DECOMPOSITION\.md$",
    r"^docs/METHODOLOGY_10_STEPS\.md$", r"^docs/TEST_LOG\.md$", r"^Описание инструмента",
    r"^skill/meetflow/SKILL\.md$", r"^skill/meetflow/СЛУЧАИ\.md$", r"^skill/meetflow/engine/eval/results/",
    r"^eval/results/", r"^eval/new_theme_cycles/", r"^tools/", r"^public/", r"^\.gitignore$", r"^scripts/run_dev\.ps1$",
    r"^\.gitlab-ci\.yml$", r"^skill/meetflow/engine/\.gitlab-ci\.yml$", r"^eval/README\.md$", r"^docs/ARCHITECTURE\.md$", r"^docs/DEPLOYMENT\.md$",
    r"^docs/DESIGN_SYSTEM\.md$", r"^docs/CONNECTOR_SPEC\.md$", r"^eval/guard/measure_(?:real|classifier)\.py$",
)]
# раскладка: скилл и движок — в папку плагина
MOVE = [(re.compile(r"^skill/meetflow/"), "skills/meetflow/")]
# имена тестов, рассказывающие историю, — нейтральные
RENAME = {
    "tests/test_letter01_critical.py": "tests/test_critical_rules.py",
    "tests/test_letters_22_24.py": "tests/test_people_rules.py",
    "tests/test_letters_27_29.py": "tests/test_assignee_rules.py",
    "tests/test_letter30_task_first.py": "tests/test_task_first.py",
    "tests/test_letter_skills_0910.py": "tests/test_skill_header_raw_log.py",
    "tests/test_llm_routes_0910.py": "tests/test_llm_routes.py",
    "tests/test_decision14_new_person.py": "tests/test_new_person.py",
    "tests/test_package01.py": "tests/test_package.py",
    "tests/test_review_fixes.py": "tests/test_regressions.py",
    "tests/test_review_findings_cards.py": "tests/test_verify_cards.py",
    "tests/test_cycle_findings_0910.py": "tests/test_new_theme.py",
    "tests/test_letter02_stage2.py": "tests/test_assignment_rules.py",
    "tests/test_letter01_stage3.py": "tests/test_core_rules.py",
    "skills/meetflow/engine/tests/test_review_fixes.py": "skills/meetflow/engine/tests/test_regressions.py",
    "skills/meetflow/engine/tests/test_resheniya_vladelca_0910.py": "skills/meetflow/engine/tests/test_assignee_rules.py",
}
TEXT = {".py", ".json", ".md", ".yaml", ".yml", ".js", ".css", ".html", ".txt", ".toml", ".ps1", ".sh", ".cfg", ".ini",
        "", ".example"}

# Реальных фамилий в исходниках нет: заменены вымышленными в самом репозитории (владелец 10.10.26: «убирай все
# фамилии — строго»). Сканер сверяет пакет и репозиторий с фамилиями из рабочих баз, сами фамилии не выводит.

# --------------------------------------------------------------------------- история: удаляется целыми единицами
# Помеченный комментарий, описание (docstring), абзац, строка таблицы, пункт списка уходят целиком. Правка внутри
# предложения оставляла обрывки: независимая вычитка пакета 10.10.26 нашла их 46 при чистом сканере.
MARK = re.compile("|".join([
    r"владел(?:ец|ьц\w*)\b(?!\s+(?:тематики|данных))", r"FRAMEWORK_REPORT|OPERATOR_TODO|TEST_LOG|METHODOLOGY|ERP_DECOMP",
    r"screen-check|fix-verify|speech-catch|corporate-style|project-briefing|манифест",
    r"\bкурс\w*", r"\bурок\w*", r"\bзанят\w*\s+\d", r"учебн", r"итерац", r"исходн\w*\s+проект", r"проект\w*-пример",
    r"framework", r"\bERP\b", r"(?-i:Планёрк|Планерк)", r"[Пп]исьм\w*", r"\bветк\w*", r"meeting-registry|MeetingFlow",
    r"MilaTal|ITMO|ИТМО|HumanCompiler|СЛУЧАИ", r"\b\d\d\.\d\d\.(?:\d\d|\d{4})\b", r"\b\d\d\.\d\d\b(?![.\d])",
    r"\b\d\d/\d\d?\b", r"находк", r"ревью", r"\b[DRК]\d+\b", r"\bэтап\w*", r"план\w*\s+сведени", r"паспорт",
    r"журнал\w*\s+улучшени|improvement-log", r"\bv\d\.\d", r"Курск|ТМК|Газпром|Титан", r"SKILL\.md|md_to_docx",
    r"[Пп]еренес\w*|[Вв]зят\w*\s+из|относительно\s+ERP|как\s+в\s+базов", r"\bсесси\w*", r"ROUTING|muse-glimmer",
    r"suite_v2|MEETFLOW_SUITE", r"локальн\w+\s+машин|закрыт\w+\s+контур", r"\bДЗ\b|домашн", r"\bвех[аиу]\s+\d",
    r"документ\w*\s+\d\d", r"№\s*\d", r"образцу|прогон\w*\s+(?:ERP|цикл)|цикл\w*\s+\d", r"отклон\w*|раздража",
    r"\bпрогон\w*\s+\d", r"предшествен", r"базов\w+\s+(?:проект|инструмент)", r"вопрос\w*\s+оператору",
    r"_intermediate|digest_", r"\.gitlab-ci", r"приватн", r"\bстарт\w*\s+пилот",
    r"\bпрежн\w*|\bпрежде\b|\bраньше\b|\bнайден\w*|\bбыло:|\bТеперь\b|впустую|не\s+вызывал|никем",
    r"вариант\w*\s+[A-DА-Г]\b|слишком\s+зел|принят\w*\s+в\s+проект|не\s+использованн",
    r"\bпункт\w*\s+\d|\bп\.\s*\d|^#+\s*-*\s*\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?\s*[—:.]|^//\s*\d+\.",
    r"\bловил\w*\s+\d|\d+\s+из\s+\d+|коммит|\b[0-9a-f]{7}\b|make_holdout|отдельн\w+\s+агент|засвеч",
    r"Эльдаб|Альдаб|\bК1\d\b|\bР\d\b",
]), re.I | re.M)
# строки-данные в коде продукта (сообщения, пояснения): только явные следы, скобками
STRMARK = re.compile(r"владел(?:ец|ьц\w*)\b(?!\s+(?:тематики|данных))|[Пп]исьм[оаеу]\s*(?:\d|№|meeting|ветк)|"
                     r"(?-i:Планёрк|Планерк)|Проект\w*\s+ERP|meeting-registry|ITMO|ИТМО|HumanCompiler|"
                     r"\b\d\d\.\d\d\.26\b|FRAMEWORK_REPORT|OPERATOR_TODO|TEST_LOG", re.I)
_PAREN = re.compile(r"\s*\((?:[^()]|\([^()]*\))*\)")
_STR = re.compile(r"^([rRbBuUfF]*)(\"\"\"|\'\'\'|\"|\')(.*)\2$", re.S)


def _paren_strip(text: str) -> str:
    """Только для строк-данных: скобка с явной историей убирается целиком, остальной текст не трогается."""
    return _PAREN.sub(lambda m: "" if STRMARK.search(m.group(0)) else m.group(0), text)


def _drop_comments(src: str) -> str:
    """Подряд идущие строки комментария — одна фраза: метка в любой строке убирает весь блок (иначе соседние строки
    повисали обрывками — вторая вычитка пакета). Строчный комментарий после кода с продолжением ниже — тоже блок."""
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    lines = src.split("\n")
    com = {}                                   # строка → (колонка, только комментарий)
    for t in toks:
        if t.type == tokenize.COMMENT:
            r, c = t.start
            com[r - 1] = (c, not lines[r - 1][:c].strip())
    blocks, cur = [], []
    for i in sorted(com):
        if cur and i == cur[-1] + 1 and com[i][1]:
            cur.append(i)
        else:
            if cur:
                blocks.append(cur)
            cur = [i]
    if cur:
        blocks.append(cur)
    kill, cut = set(), {}
    for b in blocks:
        if any(MARK.search(lines[i][com[i][0]:]) for i in b):
            for i in b:
                if com[i][1]:
                    kill.add(i)
                else:
                    cut[i] = com[i][0]
    return "\n".join(ln[:cut[i]].rstrip() if i in cut else ln for i, ln in enumerate(lines) if i not in kill)


def _drop_docstrings(src: str) -> str:
    tree = ast.parse(src)
    lines = src.split("\n")
    kill, put = set(), {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
            continue
        d = node.body[0]
        if not (isinstance(d, ast.Expr) and isinstance(d.value, ast.Constant) and isinstance(d.value.value, str)
                and MARK.search(d.value.value)):
            continue
        a, b = d.lineno - 1, d.end_lineno - 1
        if lines[a][:d.col_offset].strip() or lines[b][d.end_col_offset:].strip():
            raise SystemExit(f"сборка: описание делит строку с кодом (строка {a + 1}) — правьте точечно")
        kill.update(range(a, b + 1))
        if len(node.body) == 1:          # описание было единственным телом — тело остаётся
            put[a] = " " * d.col_offset + "pass"
    out = []
    for i, ln in enumerate(lines):
        if i in put:
            out.append(put[i])
        elif i not in kill:
            out.append(ln)
    return "\n".join(out)


def _prose_strings(src: str) -> str:
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    off = [0]
    for ln in src.split("\n"):
        off.append(off[-1] + len(ln) + 1)
    edits = []
    for t in toks:
        if t.type == tokenize.STRING and STRMARK.search(t.string):
            m = _STR.match(t.string)
            if m:
                body = _paren_strip(m.group(3))
                if m.group(3).startswith("(") and body.startswith(" "):
                    body = body[1:]
                edits.append((t.start, t.end, f"{m.group(1)}{m.group(2)}{body}{m.group(2)}"))
        elif t.type == getattr(tokenize, "FSTRING_MIDDLE", -1) and STRMARK.search(t.string):
            edits.append((t.start, t.end, _paren_strip(t.string)))
    out = src
    for (sr, sc), (er, ec), new in sorted(edits, reverse=True):
        out = out[:off[sr - 1] + sc] + new + out[off[er - 1] + ec:]
    return out


def clean_py(src: str, prose_strings: bool = True) -> str:
    out = _drop_comments(src)
    ast.parse(out)
    out = _drop_docstrings(out)
    if prose_strings:
        out = _prose_strings(out)
    out = re.sub(r"\n{4,}", "\n\n\n", out)
    out = out.lstrip("\n")
    ast.parse(out)
    return out


def clean_md(text: str) -> str:
    """Абзац, пункт списка с продолжением, строка таблицы или заголовок с историей — целиком. Код в ``` не трогается."""
    lines = text.split("\n")
    out, i, fence = [], 0, False
    item = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
    while i < len(lines):
        ln = lines[i]
        if ln.lstrip().startswith("```"):
            fence = not fence
            out.append(ln)
            i += 1
            continue
        if fence or not ln.strip():
            out.append(ln)
            i += 1
            continue
        if ln.lstrip().startswith(("|", "#")):
            probe = re.sub(r"^\s*#+\s*[\d.]+\s*", "", ln) if ln.lstrip().startswith("#") else ln
            if not MARK.search(probe):
                out.append(ln)
            i += 1
            continue
        j = i + 1
        if item.match(ln):               # пункт и его продолжение с отступом
            while j < len(lines) and lines[j].strip() and lines[j].startswith(("  ", "\t")) and not item.match(lines[j]):
                j += 1
        else:                            # абзац до пустой строки, таблицы, заголовка или пункта
            while j < len(lines) and lines[j].strip() and not lines[j].lstrip().startswith(("|", "#", "```")) \
                    and not item.match(lines[j]):
                j += 1
        unit = lines[i:j]
        if not MARK.search("\n".join(unit)):
            out += unit
        i = j
    res, keep = [], []
    for k, ln in enumerate(out):
        h = re.match(r"^(#+)\s", ln)
        if h:
            lvl, empty = len(h.group(1)), True
            for nxt in out[k + 1:]:
                h2 = re.match(r"^(#+)\s", nxt)
                if h2 and len(h2.group(1)) <= lvl:
                    break
                if nxt.strip() and not h2:
                    empty = False
                    break
            if empty:
                continue
        res.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(res))


def _drop_line_comments(text: str, opener: str) -> str:
    """Строчные комментарии (#, //) — блоками, как в Python."""
    lines = text.split("\n")
    pos = {}
    rx = re.compile(r"(^|\s)" + re.escape(opener))
    for i, ln in enumerate(lines):
        m = rx.search(ln)
        if m and not (opener == "//" and ":" + "//" in ln[max(0, m.start() - 6):m.start() + 3]):
            pos[i] = (m.start(), not ln[:m.start()].strip())
    blocks, cur = [], []
    for i in sorted(pos):
        if cur and i == cur[-1] + 1 and pos[i][1]:
            cur.append(i)
        else:
            if cur:
                blocks.append(cur)
            cur = [i]
    if cur:
        blocks.append(cur)
    kill, cut = set(), {}
    for b in blocks:
        if any(MARK.search(lines[i][pos[i][0]:].strip()) for i in b):
            for i in b:
                (kill.add(i) if pos[i][1] else cut.__setitem__(i, pos[i][0]))
    return "\n".join(ln[:cut[i]].rstrip() if i in cut else ln for i, ln in enumerate(lines) if i not in kill)


def clean_text(rel: str, text: str) -> str:
    if rel.endswith(".py"):   # в тестах строки — данные: их правят только точечные замены
        text = clean_py(text, prose_strings="/tests/" not in f"/{rel}" and "/eval/" not in f"/{rel}")
    elif rel.endswith((".js", ".css")):
        text = re.sub(r"[ \t]*/\*.*?\*/\n?", lambda m: "" if MARK.search(m.group(0)) else m.group(0), text, flags=re.S)
        text = _drop_line_comments(text, "//")
    elif rel.endswith(".html"):   # комментарий разметки с историей — целиком
        text = re.sub(r"[ \t]*<!--.*?-->\n?", lambda m: "" if MARK.search(m.group(0)) else m.group(0), text, flags=re.S)
    elif rel.endswith(".md"):
        text = clean_md(text)
    elif rel.endswith(".json"):   # поле-пояснение с историей уходит вместе с ключом; значение «pass» — пустое
        text = re.sub(r'(?m)^[ \t]*"(?:_\w+|\w+_(?:source|why|note|comment|about)|source|why)"\s*:\s*"((?:[^"\\\n]|\\.)*)",?[ \t]*\n',
                      lambda m: "" if MARK.search(m.group(1)) else m.group(0), text)
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        text = re.sub(r'("pass"\s*:\s*)"((?:[^"\\\n]|\\.)*)"',
                      lambda m: m.group(1) + '""' if MARK.search(m.group(2)) else m.group(0), text)
    elif rel.endswith((".yaml", ".yml", ".ps1", ".sh", ".txt", ".toml")) or Path(rel).name == "Makefile":
        text = _drop_line_comments(text, "#")
    for rx, b in GENERIC_DATA:
        text = rx.sub(b, text)
    if rel.endswith(".py") and "/tests/" in f"/{rel}":   # номера находок в именах тестов: test_r01_…, test_d2b_…, test_row24_…
        text = re.sub(r"\bdef test_(?:r\d+|d\d+b?|row\d+|k\d+)_", "def test_", text)
    for rx, rep in SPECIFIC.get(rel, []):
        text, n = rx.subn(rep, text)
        if not n:
            raise SystemExit(f"сборка: в {rel} не найден фрагмент: {rx.pattern[:60]}")
    if rel.endswith(".py"):
        ast.parse(text)
    if rel.endswith(".json"):
        json.loads(text)
    return text


# имя файла записи в тестах — «Совещание …», а не название внутреннего продукта
GENERIC_DATA = [(re.compile(r"Планёрка(?= \d)"), "Совещание"), (re.compile(r"192\.168\.100\.59"), "192.0.2.10"),
                (re.compile(r"192\.168\.100\.60"), "192.0.2.11"), (re.compile(r"172\.21\.21\.30"), "192.0.2.12"),
                (re.compile(r"\b10\.0\.0\.5\b"), "198.51.100.5"),
                (re.compile(r"Эльдаб"), "Эльван"), (re.compile(r"Альдаб"), "Альван"),
                (re.compile(r"\?v=\d{8}\w*"), "?v=1.0.0"),
                # реальные организации и проекты из рабочих встреч — вымышленные, с теми же падежами
                (re.compile(r"(?<![А-Яа-яЁё])ТМК\b"), "СТК"), (re.compile(r"(?<![А-Яа-яЁё])Титан(?=[а-яё]{0,2}\b)"), "Орион"),
                (re.compile(r"(?<![А-Яа-яЁё])Курск(?=[а-яё]{0,2}\b)"), "Омск"), (re.compile(r"(?<![А-Яа-яЁё])Газпром(?=[а-яё]{0,2}\b)"), "Нефтегаз"),
                (re.compile(r"(?<![а-яё])тмк(?![а-яё])"), "стк"), (re.compile(r"(?<![а-яё])титан(?=[а-яё]{0,2}(?![а-яё]))"), "орион"),
                (re.compile(r"(?<![а-яё])курск(?=[а-яё]{0,2}(?![а-яё]))"), "омск"), (re.compile(r"(?<![а-яё])газпром(?=[а-яё]{0,2}(?![а-яё]))"), "нефтегаз")]

# точечные правки, найденные сканером
SPECIFIC: dict[str, list[tuple[re.Pattern, str]]] = {
    "meetflow/__main__.py": [
        (re.compile(r"\n        if a\.port in \(8000, 8001\):\n.*?\n            return 2", re.S), ""),
    ],
    "meetflow/core/guard.py": [   # закрытые названия — свои у каждого владельца; публичный список пуст
        (re.compile(r"_CLOSED_SHA256 = frozenset\(\{.*?\}\)", re.S), "# свои закрытые названия: sha256 слова в нижнем регистре, например hashlib.sha256(\"слово\".encode()).hexdigest()\n"
         "_CLOSED_SHA256: frozenset[str] = frozenset()"),
    ],
    "skills/meetflow/engine/meeting_registry/guard.py": [
        (re.compile(r"_CLOSED_SHA256 = frozenset\(\{.*?\}\)", re.S), "# свои закрытые названия: sha256 слова в нижнем регистре, например hashlib.sha256(\"слово\".encode()).hexdigest()\n"
         "_CLOSED_SHA256: frozenset[str] = frozenset()"),
    ],
    "tests/test_guard.py": [
        (re.compile(r"def test_closed_names_stored_only_as_hashes\(\):.*?(?=\n\n\ndef )", re.S),
         "def test_closed_names_list_is_empty_by_default():\n    assert guard.filter_text(\"Сделано для заказчика.\") == "
         "(\"Сделано для заказчика.\", False)"),
        (re.compile(r"C:\\Users\\someone\\proj"), r"D:\\work\\proj"),
        (re.compile(r'"Планёрка перенесена на пятницу\."'), '"Совещание перенесено на пятницу."'),
    ],
    "tests/test_core_text.py": [(re.compile(r'"Совещание 26\.09\.26\.docx", date\(2026, 9, 26\)'),
                                 '"Совещание 26.09.25.docx", date(2025, 9, 26)')],
    "skills/meetflow/engine/tests/test_units.py": [(re.compile(r'"Транскрибация 17\.09\.26\.txt", "2026-09-17"'),
                                                    '"Транскрибация 17.09.25.txt", "2025-09-17"')],
    "pyproject.toml": [
        (re.compile(r'^version = .*$', re.M), 'version = "1.0.0"'),
        (re.compile(r'^description = .*$', re.M),
         'description = "MeetFlow: запись рабочей встречи — протокол и реестр поручений; модель предлагает, код проверяет, '
         'спорное решает человек."'),
    ],
    "meetflow/core/pipeline.py": [(re.compile(r"# и не идут в протокол, единицы и проверку"),
                                   "# строки, похожие на внедрённую инструкцию, не идут в протокол, единицы и проверку")],
    "tests/test_draft_code_checks.py": [(re.compile(r"\n\n\nSUITE = Path\(.*", re.S), "\n")],
    "Makefile": [(re.compile(r" test-scale"), "")],
    "tests/test_settings_monitoring.py": [(re.compile(r'"planerka"'), '"alpha"'), (re.compile(r'"erp"'), '"beta"')],
    "tests/test_skill_header_raw_log.py": [(re.compile(r'ROOT / "skill"\)'), 'ROOT / "skills")')],
    "themes/_default.json": [(re.compile(r"\. Решение владельца 03\.10\.26\","), ".\",")],
    "skills/meetflow/engine/meeting_registry/control.py": [
        (re.compile(r'"max_calls": "[^"]*"'), '"max_calls": "до 14 вызовов модели на прогон"'),
        (re.compile(r'"max_steps": "[^"]*"'), '"max_steps": "шагов разрешающего агента, потолок 12"'),
        (re.compile(r'"max_chars_per_call": "[^"]*"'),
         '"max_chars_per_call": "кусок 12 000 знаков с запасом на справочники в запросе"'),
        (re.compile(r'"max_chunks": "[^"]*"'), '"max_chunks": "10 кусков — встреча около 2 часов"'),
        (re.compile(r'"max_cost_usd": "[^"]*"'),
         '"max_cost_usd": "0,40 $ на прогон (только для облачного режима; локально 0)"'),
        (re.compile(r'"max_seconds": "[^"]*"'), '"max_seconds": "машина не должна думать над протоколом дольше 20 минут"'),
        (re.compile(r'"max_artifacts": "[^"]*"'), '"max_artifacts": "задач и карточек за встречу, потолок 40"'),
    ],
    "docs/DESIGN_SYSTEM.md": [
        (re.compile(r"\| \*Применено\. \|"),
         "| вместо `#71717a` ради контраста ≈5,5:1 на карточке (у `#71717a` было ≈4,0:1, ниже AA) |"),
    ],
    "docs/DEPLOYMENT.md": [
        (re.compile(r"в файл `\.env\.local` в корне репозитория"), "в файл `~/.meetflow/.env.local`"),
        (re.compile(r"из этого файла; Значение"), "из этого файла; значение"),
        (re.compile(r"-Port 8002 -Db data\\project\.db -Llm openrouter"), "-Port 8010 -Llm openrouter"),
        (re.compile(r"--db data/project\.db --port 8002"), "--db ~/.meetflow/project.db --port 8010"),
        (re.compile(r"http://127\.0\.0\.1:8002"), "http://127.0.0.1:8010"),
    ],
    "themes/erp_rollout.json": [
        (re.compile(r'"raw_speech_decision": "[^"]*"'),
         '"raw_speech_decision": "поиск по сырой речи не нужен — сказанное доходит до людей через протокол"'),
    ],
    "tests/test_units_roadmap_search.py": [(re.compile(r'"31\.02\.26"'), '"31.02.25"')],
    "eval/guard/measure_classifier.py": [
        (re.compile(r'Path\.home\(\) / "Documents" / "ITMO_planerka" / "webapp" / "\.env\.local"'),
         'Path.home() / ".meetflow" / ".env.local"'),
    ],
}
# наборы защиты: «курс», «учебные материалы» — слова атак и деловых реплик
_GUARD_FILES = re.compile(r"(?:^|/)tests/(?:test_guard\.py|guard_\w+\.yaml)$")
_GUARD_DATA = re.compile(r"курс|учебн|\bERP\b")   # «выгрузка из ERP» — деловая речь в наборе
SCAN_ALLOW = {
              # шаблоны распознавания атак: «курс», «курсе» — слова атаки, а не история
              "meetflow/core/guard.py": re.compile("курс"),
              "skills/meetflow/engine/meeting_registry/guard.py": re.compile("курс")}

# --------------------------------------------------------------------------- сканер
FORBIDDEN = re.compile(
    r"Мила|Users[\\/]|Планёрк|Планерк|Проект\w*\s+ERP|ERP[ _]project|ERP_Production|meeting-registry|"
    r"[Рр]ешени\w* владельца|[Пп]равил\w* владельца|владелец \d|владельца \d|[Пп]исьм[оау] \d|письм\w* ветк|"
    r"ITMO|ИТМО|HumanCompiler|учебн|\bвех[аиуе]\s+\d|СЛУЧАИ|\bДЗ\b|домашн\w* задани|сесси\w* разработки|"
    r"corporate-style|screen-check|fix-verify|speech-catch|[Мм]анифест|FRAMEWORK_REPORT|OPERATOR_TODO|TEST_LOG|METHODOLOGY_10|"
    r"ERP_DECOMPOSITION|[Вв]ладелец в сесси|\d\d\.26\b|\bкурс(?:а|е|у|ом)\b|\b[Уу]рок\w*\s+\d|"
    # классы, найденные независимой вычиткой 10.10.26: сканер не должен повторять слепые зоны чистки
    r"192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|[Ии]терац|исходн\w*\s+проект|"
    r"проект\w*-пример|\(\d\d/\d+|\bERP\b|Титан|ТМК|Газпром|Курск|planerka|ревью|framework|паспорт|MeetingFlow|"
    r"локальн\w+\s+машин|[Пп]еренесен\w*\s+из|[Вв]зят\w*\s+из")
# ERP — предметная область темы внедрения учётной системы: допустим в темах
_THEME_ERP = re.compile(r"\bERP\b")
SCAN_SKIP: set[str] = set()


def _secrets() -> list[str]:
    vals = []
    for env in (SRC / ".env.local", HOME_DOCS / "ITMO_planerka" / "webapp" / ".env.local"):
        if env.exists():
            for ln in env.read_text(encoding="utf-8-sig").splitlines():
                k, _, v = ln.partition("=")
                v = v.strip().strip('"').strip("'")
                # только секреты: имя модели или адрес сервера из того же файла — не утечка
                if "=" in ln and not ln.strip().startswith("#") and re.search(r"KEY|TOKEN|SECRET|PASS", k, re.I)                         and len(v) >= 12:
                        vals.append(v)
    return vals


_FIRST = set("""Александр Алексей Анатолий Андрей Антон Аркадий Арсений Артём Артем Борис Вадим Валентин Валерий
Василий Виктор Виталий Владимир Владислав Всеволод Вячеслав Георгий Глеб Григорий Даниил Денис Дмитрий Дима Евгений Егор
Иван Игорь Илья Кирилл Константин Лев Леонид Максим Марк Михаил Никита Николай Олег Павел Пётр Петр Роман Руслан Сергей
Семён Святослав Станислав Степан Тимофей Тимур Фёдор Федор Филипп Юрий Ярослав Яков Александра Алёна Алина Алла
Анастасия Ангелина Анна Валентина Валерия Варвара Вера Вероника Виктория Галина Дарья Диана Ева Евгения Екатерина Елена
Вероника Жанна Зоя Инна Ирина Карина Кира Кристина Ксения Лариса Лидия Любовь Людмила Маргарита Марина Мария Милана
Надежда Наталья Нина Оксана Ольга Полина Раиса Светлана София Софья Тамара Татьяна Ульяна Юлия Яна""".split())


def _real_surname_rx() -> list[re.Pattern]:
    """Фамилии людей из рабочих баз (только чтение): основа и до трёх букв окончания, как слово. Наружу не выводятся."""
    stems = set()
    for db in (HOME_DOCS / "ITMO_planerka" / "webapp" / "data" / "app.db",
               HOME_DOCS / "ITMO_case" / "Рабочая папка проекта ERP project" / "webapp" / "data" / "app.db"):
        if not db.exists():
            continue
        con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        for (v,) in con.execute("SELECT full_name FROM users"):
            p = [w for w in re.findall(r"[А-ЯЁ][а-яё]+", str(v or "")) if w not in _FIRST]
            if p and len(p[0]) >= 4:
                w = p[0]
                stems.add(w[:-1] if re.search(r"(?:ов|ев|ёв|ин|ын)а$", w) else w)
        con.close()
    rxs = [re.compile(rf"(?<![А-Яа-яЁё]){re.escape(st)}(?=[а-яё]{{0,3}}(?![А-Яа-яЁё]))", re.I) for st in stems]
    # латиницей — в именах переменных и тестов (третья вычитка 10.10.26 нашла три такие); основы от 5 букв
    for st in stems:
        if len(st) >= 5:
            for v in {_translit(st, k) for k in (0, 1)}:
                rxs.append(re.compile(rf"(?<![a-z]){re.escape(v)}", re.I))
    return rxs


_TR = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y",
       "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
       "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"}


def _translit(word: str, variant: int) -> str:
    out = "".join(_TR.get(ch, ch) for ch in word.lower())
    return out.replace("kh", "h").replace("yu", "iu").replace("ya", "ia") if variant else out


def names_in(text: str, rxs: list[re.Pattern]) -> int:
    return sum(1 for r in rxs if r.search(text))


def repo_names() -> list[str]:
    """Тот же контроль по самому репозиторию и скиллу: реальная фамилия не должна уйти и в приватный GitHub."""
    rxs, bad = _real_surname_rx(), []
    skill = Path.home() / ".claude" / "skills" / "meetflow"
    files = [SRC / r for r in tracked() if "agro" not in r] + [f for f in skill.rglob("*") if "__pycache__" not in f.parts]
    for f in files:
        if f.is_file() and f.suffix in TEXT:
            try:
                n = names_in(f.read_text(encoding="utf-8"), rxs)
            except UnicodeDecodeError:
                continue
            if n:
                bad.append(f"репозиторий/скилл {f.name}: реальных фамилий из рабочих баз — {n} (сами не выводятся)")
    return bad


def tracked() -> list[str]:
    out = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "-z"], cwd=SRC, capture_output=True,
                         check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def place(rel: str) -> str:
    for rx, to in MOVE:
        if rx.search(rel):
            rel = rx.sub(to, rel, count=1)
    return RENAME.get(rel, rel)


def build(out: Path) -> list[str]:
    if out.exists():
        if (out / ".git").exists():
            raise SystemExit(f"сборка: в {out} уже есть git — соберите в новую папку или удалите её вручную")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for rel in tracked():
        if any(rx.search(rel) for rx in EXCLUDE):
            continue
        src, dst_rel = SRC / rel, place(rel)
        dst = out / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in TEXT or src.name.startswith("."):
            dst.write_text(clean_text(dst_rel, src.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
        else:
            shutil.copy2(src, dst)
    pub = SRC / "public"
    for f in pub.rglob("*"):
        if f.is_file():
            d = out / f.relative_to(pub)
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, d)
    return scan(out)


def scan(out: Path) -> list[str]:
    import yaml
    bad, secrets, rxs = repo_names(), _secrets(), _real_surname_rx()
    for sk in (out / "skills").glob("*/SKILL.md"):
        try:
            fm = yaml.safe_load(sk.read_text(encoding="utf-8").split("---")[1])
        except yaml.YAMLError as e:
            bad.append(f"{sk.parent.name}/SKILL.md: заголовок не читается как YAML — {str(e)[:80]}")
            continue
        if fm.get("name") != sk.parent.name or not 0 < len(fm.get("description") or "") <= 1024:
            bad.append(f"{sk.parent.name}/SKILL.md: name не совпадает с папкой или description пустое / длиннее 1024")
    for f in sorted(out.rglob("*")):
        rel = f.relative_to(out).as_posix()
        if not f.is_file() or rel.startswith(".git/"):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(v in text for v in secrets):
            bad.append(f"{rel}: найдено значение ключа из .env.local (значение не выводится)")
        n = names_in(text, rxs)
        if n:
            bad.append(f"{rel}: реальных фамилий из рабочих баз — {n} (сами не выводятся)")
        if rel in SCAN_SKIP:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = FORBIDDEN.search(line)
            allow = SCAN_ALLOW.get(rel) or (_GUARD_DATA if _GUARD_FILES.search(rel) else None) \
                or (_THEME_ERP if rel.startswith("themes/") else None)
            if m and not (allow and allow.search(m.group())):
                bad.append(f"{rel}:{i}: «{m.group()}» — {line.strip()[:110]}")
    return bad


def run_tests(out: Path) -> bool:
    ok = True
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for cwd in (out, out / "skills" / "meetflow" / "engine"):
        r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "-W", "ignore",
                            "-o", "addopts="], cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=env)
        tail = (r.stdout.strip().splitlines() or ["(нет вывода)"])[-1]
        print(f"тесты {cwd.relative_to(out).as_posix() or '.'}: {tail}")
        if r.returncode:
            ok = False
            print("\n".join(r.stdout.splitlines()[-40:]))
    return ok


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    out = Path(sys.argv[1]).resolve()
    if out == SRC or SRC in out.parents:
        raise SystemExit("сборка: папка пакета не может лежать внутри приватного репозитория")
    bad = build(out)
    if bad:
        print(f"Сканер нашёл внутренние следы ({len(bad)}) — пакет НЕ готов:")
        print("\n".join(bad[:400]))
        raise SystemExit(1)
    print(f"Пакет собран: {out}. Сканер чист.")
    if "--test" in sys.argv and not run_tests(out):
        raise SystemExit("тесты внутри пакета не прошли")
    if "--git" in sys.argv:
        git = ["git", "-c", "user.name=MilaTal", "-c", "user.email=noreply@users.noreply.github.com"]
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=out, check=True)
        subprocess.run(git + ["add", "-A"], cwd=out, check=True)
        subprocess.run(git + ["commit", "-q", "-m", "MeetFlow 1.0.0"], cwd=out, check=True)
        print("git: один коммит, удалённого репозитория нет, пуша не было.")


if __name__ == "__main__":
    main()
