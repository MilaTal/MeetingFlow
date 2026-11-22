"""Конвертирует markdown-файл (протокол/план/сводка/карта) в .docx по корпоративному оформлению.

Оформление не «на глаз»: оно собрано из двух источников, которые у проекта уже есть.

1. **Стандарт компании** — «Описание проекта» (раздел про .docx: «стиль — Calibri 11pt тело, заголовки —
   настоящие стили Word») и `system/skills/corporate-style/STYLE.md` («заголовок раздела — жирным, без
   нумерации markdown, просто «N Название»»). Уточнение владельца 09.10.26: стандартный шрифт всех
   выгружаемых документов — **Calibri 11**, и он же в таблицах. Тогда же выяснилось, что в STYLE.md
   оставалась строка «Times New Roman, 12pt» — прямое противоречие «Описанию проекта»; приведена к
   Calibri 11, чтобы стандарт не спорил сам с собой.

2. **ГОСТ Р 7.0.97-2016** «Требования к оформлению документов» (действует с 01.07.2018): лист A4;
   поля не менее 20 мм слева и сверху/снизу и 10 мм справа; абзацный отступ 1,25 см; текст
   выравнивается по ширине; межстрочный интервал 1–1,5; в таблицах допускается кегль меньше
   основного; нумерация страниц — со второй, посередине верхнего поля.

Что чем закрыто:

* **Лист и поля** — A4 (21 × 29,7 см; раньше файл получался в Letter — на печати в России это
  обрезанные поля), поля 25 / 15 / 20 / 20 мм: левое по ГОСТ не менее 20 мм с запасом на подшивку;
* **Шрифт** — Calibri 11 pt и в тексте, и в таблицах (уточнение владельца 09.10.26: «стандартный шрифт
  ко всем документам»; прежде здесь был Times New Roman 12 — прямое противоречие «Описанию проекта»);
* **Абзац** — по ширине, первая строка 1,25 см, интервал 1,15, отбивка 6 pt после абзаца,
  запрет «висячих» строк. Раньше текст шёл «в стену»: без отступов, одиночным интервалом и с
  двойным пропуском перед каждым заголовком;
* **Заголовки** — настоящие стили Word Heading 1/2/3 (панель навигации и автособираемое
  оглавление работают), шрифт заголовков — Calibri тем же кеглем по уровням: раньше заголовки
  оставались Calibri Light из темы Word, и в одном документе жили два шрифта. Цвет чёрный (не синий
  акцент темы), заголовок не отрывается от следующего текста (`keep_with_next`);
* **Название документа** — Heading 1 по центру; разделы «N Название» — Heading 2, как на экране;
* **Таблицы** — сетка, шапка жирная с лёгкой заливкой, шапка **повторяется** на новых страницах
  (раньше длинная таблица обрывалась, и на второй странице колонки шли без заголовков), строки не
  разрываются между страницами, подпись под формулировкой («¦поставлена ДД.ММ.ГГ») — тонкой
  строкой под текстом, как на экране (раньше она склеивалась с текстом через « · »);
* **Нумерация страниц** — со второй, посередине верхнего поля (ГОСТ); на первой странице номера
  нет, как и требует стандарт;
* **Свойства файла** — в свойствах записано название документа: в списке последних файлов и в
  проводнике видно, что это за документ.

Понимает ту же разметку, что и экран (`services/docx_export.py` готовит её из текста в базе):
название документа первой строкой, `## раздел` / `### подраздел`, `- пункт`, `| таблица |`,
`**жирный**`, `*курсив*`, `` `код` ``. Порядок блоков и их состав не меняются — оформление
касается только внешнего вида (владелец 09.10.26: «структуру сохранить как выдаёт на мониторинге,
а оформление структуры — как в лучших практиках»).

Использование: python scripts/md_to_docx.py "путь/к/файлу.md"
Сохраняет рядом файл с тем же именем и расширением .docx.
"""

import os
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# --- оформление: стандарт компании + ГОСТ Р 7.0.97-2016 ---
FONT_NAME = "Calibri"                  # стандарт компании: «Calibri 11pt тело» («Описание проекта», STYLE.md)
FONT_SIZE = Pt(11)
TABLE_FONT_SIZE = Pt(11)               # в таблицах тот же шрифт: владелец 09.10.26 — «стандартный шрифт ко всем документам»
CODE_FONT = "Consolas"
LINE_SPACING = 1.15                    # ГОСТ: интервал 1–1,5
SPACE_AFTER = Pt(6)
FIRST_LINE_INDENT = Cm(1.25)           # ГОСТ: абзацный отступ текста документа — 1,25 см
HEADING_SIZES = {1: Pt(16), 2: Pt(14), 3: Pt(13)}
HEADING_SPACE_BEFORE = {1: Pt(0), 2: Pt(16), 3: Pt(12)}
HEADING_SPACE_AFTER = Pt(6)
HEADING_COLOR = RGBColor(0, 0, 0)      # чёрный, не синий акцент темы Word по умолчанию

PAGE_WIDTH, PAGE_HEIGHT = Cm(21), Cm(29.7)          # A4, а не Letter
MARGIN_LEFT, MARGIN_RIGHT = Cm(2.5), Cm(1.5)        # ГОСТ: не менее 20 мм слева, 10 справа
MARGIN_TOP, MARGIN_BOTTOM = Cm(2), Cm(2)
HEADER_DISTANCE = Cm(1.2)                            # номер страницы не липнет к тексту

TABLE_HEADER_FILL = "F2F2F2"           # лёгкая заливка шапки — стандарт деловых таблиц, не декор
# Системные пометки — это наш текст, а не слова участников: подпись под формулировкой задачи
# («поставлена 01.09.2026 · выполнена 02.09.2026»), дата постановки хвостом к описанию (так её пишет
# Планёрка) и предложение ассистента в Сводке и Дорожной карте ERP. Печатаются мелким курсивом серым —
# владелец 09.10.26: «дату постановки задачи — шрифтом 9 и курсивом, как и все системные сообщения;
# включая примечание Ассистента для ERP». Стиль один: правило живёт в общем конвертере, поэтому
# действует на все документы обоих продуктов сразу, а не на тот, о котором написали.
SYSTEM_NOTE_SIZE = Pt(9)
SYSTEM_NOTE_COLOR = RGBColor(0x59, 0x59, 0x59)
SUBCAPTION_SIZE = SYSTEM_NOTE_SIZE     # прежнее имя: подпись под формулировкой — та же системная пометка
SUBCAPTION_COLOR = SYSTEM_NOTE_COLOR
NEW_TASK_MARK = "[new] "                # пометка задачи этой встречи в едином списке протокола (18.10.2026)
MARKER_PARAGRAPH_SIZE = Pt(2)          # разделительный абзац между двумя таблицами — почти невидим
EMU_PER_TWIP = 635                     # 1 twip = 1/20 pt = 635 EMU; в twips пишется w:tblW

LIST_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
LIST_NUMBER_RE = re.compile(r"^\d+[.)]\s+(.*)$")

# Дата постановки и выполнения прямо в тексте задачи: Планёрка пишет её хвостом к описанию —
# «Завести несоответствия … поставлена 01.09.2026». Слева — не буква и не точка: «подставлена» и
# «10.10.2026.поставлена» пометками не считаются; справа — не продолжение числа.
SYSTEM_NOTE_RE = re.compile(r"(?<![\w.])(?:поставлена|выполнена)\s+\d{2}\.\d{2}\.\d{2,4}(?![\d.])")
# Предложение ассистента (Сводка и Карта ERP) — не решение встречи: системной пометкой идёт строка целиком,
# иначе рекомендация ассистента читалась бы как договорённость участников.
ASSISTANT_NOTE_MARK = "Предложение ассистента (не решение встречи)"

# *курсив* — тоже разметка, не текст (тест двух циклов 01.10.26: пометки вида «*(не заведена …)*» в
# ячейках таблиц уходили в .docx со звёздочками). Одиночная звёздочка без пары остаётся как есть.
INLINE_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|(?<!\*)\*(?!\*)[^*\n]+?(?<!\*)\*(?!\*))")


# --------------------------------------------------------------------------
# Шрифты и стили
# --------------------------------------------------------------------------

def set_run_font(run, size=None, *, color=None, italic=False):
    """Шрифт одного фрагмента. Имя ставится и в обычные атрибуты, и в восточно-азиатские/сложные:
    без этого Word подставляет для кириллицы шрифт темы, и «Times New Roman» в настройках не
    действует (классическая ловушка python-docx)."""
    run.font.name = FONT_NAME
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), FONT_NAME)
    if size is not None:
        run.font.size = size
    if color is not None:
        run.font.color.rgb = color
    if italic:
        run.italic = True


def _style_font(style, *, size=None, bold=None, color=None):
    """Шрифт стиля: те же четыре атрибута имени, иначе кириллица остаётся темой Word."""
    style.font.name = FONT_NAME
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), FONT_NAME)
    if size is not None:
        style.font.size = size
    if bold is not None:
        style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color


def _style_russian_language(style) -> None:
    """Язык стиля — русский: иначе Word подчёркивает русский текст как иностранный."""
    rpr = style.element.get_or_add_rPr()
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:val"), "ru-RU")
    lang.set(qn("w:eastAsia"), "ru-RU")
    lang.set(qn("w:bidi"), "ar-SA")


def setup_styles(doc) -> None:
    """Единые стили документа: их видно в Word, по ним собирается оглавление, и они переносят
    оформление на любой дописанный человеком абзац — в отличие от прямого форматирования."""
    normal = doc.styles["Normal"]
    _style_font(normal, size=FONT_SIZE, color=HEADING_COLOR)
    _style_russian_language(normal)
    pf = normal.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.first_line_indent = FIRST_LINE_INDENT
    pf.line_spacing = LINE_SPACING
    pf.space_after = SPACE_AFTER
    pf.widow_control = True            # не оставлять одну строку абзаца на странице

    for level in (1, 2, 3):
        style = doc.styles[f"Heading {level}"]
        _style_font(style, size=HEADING_SIZES[level], bold=True, color=HEADING_COLOR)
        _style_russian_language(style)
        hpf = style.paragraph_format
        hpf.alignment = WD_ALIGN_PARAGRAPH.CENTER if level == 1 else WD_ALIGN_PARAGRAPH.LEFT
        hpf.first_line_indent = Cm(0)
        hpf.space_before = HEADING_SPACE_BEFORE[level]
        hpf.space_after = HEADING_SPACE_AFTER
        hpf.keep_with_next = True      # заголовок не остаётся один в конце страницы
        hpf.line_spacing = 1.0

    for имя in ("List Bullet", "List Number"):
        try:
            style = doc.styles[имя]
        except KeyError:               # шаблон без этого стиля — список оформим абзацем
            continue
        _style_font(style, size=FONT_SIZE)
        _style_russian_language(style)
        style.paragraph_format.first_line_indent = Cm(0)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.line_spacing = LINE_SPACING


def add_page_numbers(doc) -> None:
    """Номер страницы — со второй, посередине верхнего поля (ГОСТ Р 7.0.97-2016). На первой
    странице номера нет: у документа и так есть название, а номер с единицы там не нужен."""
    section = doc.sections[0]
    section.different_first_page_header_footer = True
    header = section.header
    p = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    p.text = ""
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run()
    set_run_font(run, size=Pt(11), color=RGBColor(0x40, 0x40, 0x40))
    начало = OxmlElement("w:fldChar")
    начало.set(qn("w:fldCharType"), "begin")
    инструкция = OxmlElement("w:instrText")
    инструкция.set(qn("xml:space"), "preserve")
    инструкция.text = "PAGE"
    конец = OxmlElement("w:fldChar")
    конец.set(qn("w:fldCharType"), "end")
    run._element.append(начало)
    run._element.append(инструкция)
    run._element.append(конец)


def setup_page(doc) -> None:
    section = doc.sections[0]
    section.page_width, section.page_height = PAGE_WIDTH, PAGE_HEIGHT
    section.left_margin, section.right_margin = MARGIN_LEFT, MARGIN_RIGHT
    section.top_margin, section.bottom_margin = MARGIN_TOP, MARGIN_BOTTOM
    section.header_distance = HEADER_DISTANCE


# --------------------------------------------------------------------------
# Разметка внутри строки и блоки документа
# --------------------------------------------------------------------------

def _с_системными_заметками(text):
    """Режет строку на куски «обычный текст» и «системная пометка» (см. SYSTEM_NOTE_RE).

    Отдельной функцией — потому что правило одно для всех документов обоих продуктов, и проверяется оно
    тестом без Word: конвертер один, документы разные. Строка целиком считается системной, если это
    предложение ассистента ERP (ASSISTANT_NOTE_MARK): в Сводке и Карте оно идёт отдельным абзацем и
    решением встречи не является — значит, и печататься должно как служебная пометка, а не как текст
    участников."""
    полоса = text or ""
    if полоса.strip().startswith(ASSISTANT_NOTE_MARK):
        return [(полоса, True)]
    # Предложение посреди абзаца (находка локальной машины 19.10.2026: в Сводке все 9 строк стояли после текста абзаца
    # — «…. Предложение ассистента (не решение встречи) — …» — и печатались обычным текстом): от пометки до конца абзаца —
    # служебным видом, текст до неё — обычным.
    где = полоса.find(ASSISTANT_NOTE_MARK)
    if где > 0:
        return _с_системными_заметками(полоса[:где]) + [(полоса[где:], True)]
    куски, конец = [], 0
    for найденное in SYSTEM_NOTE_RE.finditer(полоса):
        if найденное.start() > конец:
            куски.append((полоса[конец:найденное.start()], False))
        куски.append((найденное.group(0), True))
        конец = найденное.end()
    if конец < len(полоса):
        куски.append((полоса[конец:], False))
    return куски


def _add_markup_runs(p, text, bold=False, size=None):
    """Разметка внутри строки: **жирный** -> жирный run, `код` -> моноширинный run, *курсив* ->
    курсив; сами маркеры в текст не попадают. Раньше в .docx оставались литеральные звёздочки и
    обратные кавычки (найдено аудитом 28.09.26; в Планёрке жирный починен 24.09.26)."""
    for part in INLINE_RE.split(text):
        if not part:
            continue
        is_bold = part.startswith("**") and part.endswith("**") and len(part) > 4
        is_code = part.startswith("`") and part.endswith("`") and len(part) > 2
        is_italic = (not is_bold and part.startswith("*") and part.endswith("*") and len(part) > 2)
        if is_bold:
            part = part[2:-2]
        elif is_code:
            part = part[1:-1]
        elif is_italic:
            part = part[1:-1]
        run = p.add_run(part)
        set_run_font(run, size=size)
        if is_code:
            run.font.name = CODE_FONT
        if bold or is_bold:
            run.bold = True
        if is_italic:
            run.italic = True


def add_inline_runs(p, text, bold=False, size=None):
    """Текст абзаца или ячейки: сначала системные пометки (мелкий курсив серым), остальное — с
    разметкой. Так «поставлена 01.09.2026» внутри формулировки задачи и предложение ассистента ERP
    печатаются одинаково во всех документах — и в протоколе Планёрки, и в Сводке ERP."""
    for кусок, системный in _с_системными_заметками(text):
        if not кусок:
            continue
        if системный:
            run = p.add_run(кусок)
            # Предложение ассистента ERP — кеглем текста, курсивом, серым, как служебное слово «решили:» (решение владелицы
            # 19.10.2026); прочие системные пометки — мелким курсивом, как прежде.
            помета = кусок.strip().startswith(ASSISTANT_NOTE_MARK)
            set_run_font(run, size=(size if помета else SYSTEM_NOTE_SIZE), color=SYSTEM_NOTE_COLOR, italic=True)
            if bold:
                run.bold = True
            continue
        _add_markup_runs(p, кусок, bold=bold, size=size)


def strip_inline_markup(text):
    """Для заголовков: убрать маркеры **...**, *...* и `...`, оставив текст."""
    return INLINE_RE.sub(lambda m: m.group(0).strip("*`"), text)


# Номер раздела в заголовке печатается с точкой: «1. Состояние по блокам» (просьба владельца 09.10.26).
# Правило узкое: только номер В НАЧАЛЕ заголовка и только когда после него идёт слово. «1.2 Название»
# и «10.10.26 …» не трогаются — там номер не раздел. Нумерованные списки в тексте не затрагиваются:
# их нумерует сам Word (стиль List Number), точка ставится его нумерацией.
_НОМЕР_В_НАЧАЛЕ = re.compile(r"^\s*(\d{1,3})[.)]?\s+(?=\S)")


def _с_точкой_после_номера(text: str) -> str:
    return _НОМЕР_В_НАЧАЛЕ.sub(r"\1. ", text or "", count=1)


# Служебное слово договорённости в протоколе (решение владелицы 19.10.2026, по протоколу 19.10): строка «Решили: …» /
# «Открытый вопрос: …» печатается словом «решили:» / «открытый вопрос:» — со строчной, курсивом, серым системных пометок
# (SYSTEM_NOTE_COLOR, 7:1 к белому), не полужирным, кеглем текста; сама формулировка — обычным текстом. Так же на экране
# (renderDocHtml, класс doc-agree-label) обеих систем. Текст документа в базе не меняется — это вид при выгрузке.
# 26.10.2026 (решение владелицы): слова «Решили» в протоколе нет вообще — строка «Решили: …» сохранённого протокола
# печатается обычным предложением без метки, с заглавной буквы; «Открытый вопрос:» — как прежде.
AGREEMENT_LABEL_RE = re.compile(r"^(Решили|Открытый вопрос):\s+")


def _служебное_слово_договорённости(p, text):
    """Ставит в абзац служебное слово договорённости и возвращает остаток строки; не договорённость — строку как есть.
    «Решили: …» (26.10.2026) — остаток строки с заглавной буквы, без метки."""
    найдено = AGREEMENT_LABEL_RE.match(text or "")
    if not найдено:
        return text
    if найдено.group(1) in ("Решили", "Открытый вопрос"):    # «Открытый вопрос:» — тоже без метки (26.10.2026)
        остаток = text[найдено.end():]
        return остаток[:1].upper() + остаток[1:]
    run = p.add_run(найдено.group(1).lower() + ": ")
    set_run_font(run, color=SYSTEM_NOTE_COLOR, italic=True)
    return text[найдено.end():]


def add_paragraph(doc, text):
    """Обычный абзац: непрерывная проза. Тема/метка жирным внутри фразы не выделяется и на новую
    строку не переносится — по прямой просьбе пользователя: это дробило текст на визуальные блоки."""
    p = doc.add_paragraph()
    add_inline_runs(p, _служебное_слово_договорённости(p, text))
    return p


def add_heading(doc, text, level=2):
    """Настоящий стиль Word «Heading N» — не имитация жирным текстом: так заголовки попадают в
    оглавление и панель навигации, а оформление (шрифт, кегль, отбивки) берётся из стиля.

    Номер раздела печатается с точкой: «1. Состояние по блокам» (просьба владельца 09.10.26). Так —
    в выгрузке; на экране номер остаётся без точки, как в мониторе."""
    level = max(1, min(level, 3))
    p = doc.add_heading(_с_точкой_после_номера(strip_inline_markup(text)), level=level)
    for run in p.runs:
        set_run_font(run, size=HEADING_SIZES[level], color=HEADING_COLOR)
        run.bold = True
    return p


def add_list_item(doc, text, ordered):
    style = "List Number" if ordered else "List Bullet"
    try:
        p = doc.add_paragraph(style=style)
    except KeyError:
        p = doc.add_paragraph()
    add_inline_runs(p, _служебное_слово_договорённости(p, text))
    return p


def add_marker_paragraph(doc):
    """Пустой абзац-разделитель. Нужен только там, где без него два блока склеятся: между двумя
    таблицами (Word слил бы их в одну) и в конце документа, если он кончается таблицей."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.space_before = Pt(0)
    run = p.add_run("")
    set_run_font(run, size=MARKER_PARAGRAPH_SIZE)
    return p


# --------------------------------------------------------------------------
# Таблицы
# --------------------------------------------------------------------------

def is_table_line(line):
    s = line.strip()
    return s.startswith("|") and s.endswith("|")


def is_separator_line(line):
    s = line.strip().strip("|")
    cells = [c.strip() for c in s.split("|")]
    return all(re.fullmatch(r"-{2,}", c) for c in cells if c != "")


def parse_table_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


MIN_COL_WIDTH = Cm(1.6)     # минимальная ширина колонки, чтобы не схлопывалась
# «Фон» длины: «№», «—», «да» — это не содержание. Две буквы есть в любой колонке, и без вычитания
# короткая номерная колонка получала заметно больше, чем ей нужно (в таблице «№ | Задача» — до 2,5 см).
BASELINE_LENGTH = 4
# Запас к замеру ширины слова (см. `_нижние_ширины`): замер PIL чуть уже вёрстки Word.
WORD_WIDTH_SLACK_FACTOR = 1.02
WORD_WIDTH_SLACK_CM = 0.08
_ШРИФТЫ_КЕШ: dict = {}


def _ширина_текста_см(текст: str, кегль: float, жирный: bool = False):
    """Ширина строки в сантиметрах — замером настоящего шрифта (Calibri из системы), а не «на глаз».

    Замер нужен, чтобы колонка не была уже самого длинного слова: иначе Word рвёт слово посередине —
    на живой выгрузке ERP так рвались «Ответственн/ый» в шапке и «выполнен/а 07.10.2026» в пометке.
    Нет PIL или шрифта — возвращаем None, и вызывающий считает по числу знаков (оценка чуть грубее,
    но конвертер обязан работать и без замера)."""
    try:
        from PIL import ImageFont
        ключ = (кегль, жирный)
        шрифт = _ШРИФТЫ_КЕШ.get(ключ)
        if шрифт is None:
            папка = os.environ.get("WINDIR", r"C:\Windows")
            файл = os.path.join(папка, "Fonts", "calibrib.ttf" if жирный else "calibri.ttf")
            шрифт = ImageFont.truetype(файл, 1000)      # 1000 знаков — потом масштабируем в сантиметры
            _ШРИФТЫ_КЕШ[ключ] = шрифт
        return шрифт.getlength(текст) / 1000 * кегль / 72 * 2.54
    except Exception:
        return None


def _неразрывные_куски(текст: str):
    """Куски, которые Word не переносит по частям: он рвёт строку по пробелу, «/» и дефису — значит,
    всё остальное обязано поместиться в колонку целиком."""
    return [кусок for кусок in re.split(r"[\s/–—-]+", текст or "") if кусок]


def _нужно_для_слова(текст: str, кегль: float, жирный: bool) -> float:
    """Сколько сантиметров нужно, чтобы самое длинное неразрывное слово строки не разорвалось."""
    нужно = 0.0
    for кусок in _неразрывные_куски(текст):
        ширина = _ширина_текста_см(кусок, кегль, жирный)
        if ширина is None:
            ширина = 0.2 * len(кусок) * (кегль / 11.0)      # оценка: ~2 мм на знак при 11 pt
        нужно = max(нужно, ширина)
    return нужно


def _нижние_ширины(rows, ncols):
    """Нижняя граница каждой колонки: в неё обязано поместиться её самое длинное неразрывное слово
    (шапка — жирным 11 pt, подпись после «¦» — системная пометка 9 pt) плюс внутренние отступы ячейки.
    Общая нижняя граница MIN_COL_WIDTH остаётся для колонок из одних цифр.

    Запас к замеру (WORD_WIDTH_SLACK_*) — не «на глаз»: замер шрифта через PIL систематически чуть уже
    того, что делает сам Word (кернинг и округление при вёрстке). Калибровка живыми прогонами через
    Word: шапка «Ответственный» (жирный 11 pt) рвётся при 2,90 см и влезает с 3,00; «01.10.2026» — рвётся
    при 2,15 и влезает с 2,20. Замер даёт 2,569 и 1,77 см; с отступами 0,38 см и запасом выходит
    3,05 и 2,23 см — то есть слово не рвётся с небольшим запасом на печать."""
    отступы = 2 * 108 / 567            # 2 × 108 twips (внутренние поля ячейки) в сантиметрах
    нижние = []
    for j in range(ncols):
        нужно = 0.0
        for i, row in enumerate(rows):
            if j >= len(row):
                continue
            главное, знак, подпись = row[j].partition("¦")
            нужно = max(нужно, _нужно_для_слова(главное, TABLE_FONT_SIZE.pt, i == 0))
            if знак:
                нужно = max(нужно, _нужно_для_слова(подпись, SYSTEM_NOTE_SIZE.pt, False))
        нужно = нужно * WORD_WIDTH_SLACK_FACTOR + WORD_WIDTH_SLACK_CM
        нижние.append(int(max(Cm(нужно + отступы), MIN_COL_WIDTH)))
    return нижние


def _column_scores(rows, ncols):
    """Вес колонки — корень из средней ПОЛЕЗНОЙ длины её содержимого (по всем строкам, включая шапку).

    Средняя длина, а не самая длинная строка: одна нетипично длинная ячейка не должна раздувать
    столбец. Корень сохраняет порядок (кто длиннее — шире), но не даёт разрыву между колонками быть
    многократным: без этого сглаживания колонка с многопунктовым описанием забирала почти всю ширину
    листа, а соседняя с тоже длинным, но не самым длинным текстом визуально схлопывалась."""
    scores = []
    for j in range(ncols):
        lengths = [len(row[j]) for row in rows if j < len(row)]
        mean_len = (sum(lengths) / len(lengths)) if lengths else 1
        scores.append(max(mean_len - BASELINE_LENGTH, 0.5) ** 0.5)
    return scores


def _уравнять_сумму(widths, usable_width):
    """Догнать сумму ширин ровно до ширины полосы набора: остаток округления отдаём самой широкой
    колонке. Это и есть обещанная проверка «таблица помещается в A4»: сумма ширин колонок, ширина
    таблицы (`w:tblW`) и ширина полосы набора совпадают до twips, поэтому ни Word, ни LibreOffice
    не досчитывают таблицу сами — а именно этот дорасчёт и выносил колонки за край листа."""
    всего = sum(widths)
    разница = int(usable_width) - всего
    if not разница or not widths:
        return widths
    j = max(range(len(widths)), key=lambda k: widths[k])
    widths[j] += разница
    if widths[j] < MIN_COL_WIDTH:                     # много колонок: размазываем по всем, но не в ноль
        widths = [max(MIN_COL_WIDTH, w) for w in widths]
    return widths


def compute_column_widths(rows, usable_width):
    """Ширина колонки — от объёма реального содержимого, а не от имени колонки и не поровну.

    Правило владельца 09.10.26: «ширину колонки формировать сбалансированно по количеству контекста»
    и «применять к каждой таблице проверку, чтобы помещалась визуально в формат A4».

    Порядок: вес колонки (см. `_column_scores`) → доли ширины полосы набора → нижние границы
    (у каждой колонки своя: не уже самого длинного слова, см. `_нижние_ширины`) → верхняя граница
    «сколько остаётся после минимальных долей остальных»: самая широкая колонка забирает тот объём,
    который иначе пропал бы впустую, и таблица заполняет лист целиком, а не на две трети. Прежняя
    верхняя граница («не больше, чем в 5 раз шире минимальной») отдавала освободившуюся ширину
    короткой колонке: в таблице «№ | Задача» столбец «№» вырастал до половины листа."""
    ncols = len(rows[0])
    scores = _column_scores(rows, ncols)

    total = sum(scores)
    widths = [usable_width * s / total for s in scores]

    нижние = _нижние_ширины(rows, ncols)
    сумма_нижних = sum(нижние)
    if сумма_нижних > usable_width * 0.9:        # много колонок: нижние в полосу не влезают — ужимаем
        k = usable_width * 0.9 / сумма_нижних
        нижние = [max(int(MIN_COL_WIDTH * 0.6), int(н * k)) for н in нижние]
    widths = _redistribute(widths, scores, ncols, нижние, "min")
    верх = max(MIN_COL_WIDTH, usable_width - MIN_COL_WIDTH * (ncols - 1))
    widths = _redistribute(widths, scores, ncols, верх, "max")

    return _уравнять_сумму([int(w) for w in widths], usable_width)


def _redistribute(widths, scores, ncols, bound, mode):
    """Проводит значения widths к границе bound (снизу — mode='min', сверху
    — mode='max'), а высвободившуюся/недостающую разницу перераспределяет
    между оставшимися («гибкими») колонками пропорционально их весу —
    несколько проходов, пока не останется нарушений границы.

    Граница бывает и разной для колонок (список длиной ncols): нижняя граница у каждой своя — по
    самому длинному слову колонки (см. `_нижние_ширины`)."""
    границы = list(bound) if isinstance(bound, (list, tuple)) else [bound] * ncols
    fixed = [False] * ncols
    for _ in range(ncols):
        if mode == "min":
            violating = [j for j in range(ncols) if not fixed[j] and widths[j] < границы[j]]
        else:
            violating = [j for j in range(ncols) if not fixed[j] and widths[j] > границы[j]]
        if not violating:
            break
        delta = sum((границы[j] - widths[j]) if mode == "min" else (widths[j] - границы[j])
                    for j in violating)
        for j in violating:
            widths[j] = границы[j]
            fixed[j] = True
        flexible = [j for j in range(ncols) if not fixed[j]]
        flexible_score = sum(scores[j] for j in flexible)
        if not flexible or flexible_score <= 0:
            break
        sign = -1 if mode == "min" else 1
        for j in flexible:
            widths[j] += sign * delta * (scores[j] / flexible_score)
    return widths


def _set_cell_shading(cell, fill: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _repeat_header_row(row) -> None:
    """Шапка повторяется на каждой новой странице: иначе длинная таблица задач обрывается, и на
    второй странице колонки идут без заголовков (видно на живом протоколе)."""
    trpr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    trpr.append(tbl_header)


def _keep_row_together(row) -> None:
    """Строка таблицы не разрывается между страницами — иначе формулировка задачи рвётся пополам."""
    trpr = row._tr.get_or_add_trPr()
    trpr.append(OxmlElement("w:cantSplit"))


def _set_cell_margins(table, left: int = 108, right: int = 108, top: int = 40, bottom: int = 40) -> None:
    """Внутренние отступы ячеек (в twips; 108 ≈ 1,9 мм): текст не липнет к линиям сетки."""
    tblpr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for имя, значение in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        элемент = OxmlElement(f"w:{имя}")
        элемент.set(qn("w:w"), str(значение))
        элемент.set(qn("w:type"), "dxa")
        mar.append(элемент)
    tblpr.append(mar)


def _fix_table_width(table, widths) -> None:
    """Жёстко закрепить ширины колонок и ширину таблицы целиком.

    Здесь было ДВЕ ошибки, из-за которых Word печатал таблицу шире листа A4 (нашёл владелец 09.10.26
    по выгрузке Планёрки: колонки «Ответственный» и «Срок» уехали за край листа, текст обрывался на
    середине слова):

      1. В свойствах таблицы оставались ДВА элемента `w:tblW` — первый `auto/0` от python-docx,
         второй наш. Word, в отличие от LibreOffice, читает первый и включает автоподбор по
         содержимому: картинка сходилась (в LibreOffice тот же файл печатался по полям), а в Word
         таблица выходила за лист. Теперь элемент один: существующий переписываем, а если его нет —
         вставляем в правильное место схемы (перед `w:tblLayout`/`w:tblCellMar`/`w:tblLook`).
      2. Значение писалось в EMU, а `w:type="dxa"` требует twips: выходило 6 120 763 вместо 9 639.

    Одних `cell.width` не хватает и теперь: пока в свойствах не сказано `tblLayout=fixed`, Word и
    LibreOffice сами уравнивают колонки — на живом протоколе «Описание задачи» (8 см по расчёту)
    печаталось как «№» (1,8 см), и формулировки задач рвались на шесть строк.
    """
    tblpr = table._tbl.tblPr
    ширина = tblpr.find(qn("w:tblW"))
    if ширина is None:
        ширина = OxmlElement("w:tblW")
        вставили = False
        for после in ("w:tblLayout", "w:tblCellMar", "w:tblLook"):
            якорь = tblpr.find(qn(после))
            if якорь is not None:
                якорь.addprevious(ширина)
                вставили = True
                break
        if not вставили:
            tblpr.append(ширина)
    ширина.set(qn("w:w"), "0")                 # значение проставим ниже, когда узнаем сетку колонок
    ширина.set(qn("w:type"), "dxa")            # twips: в других единицах Word считает ширину неверно
    layout = tblpr.get_or_add_tblLayout()      # ровно один элемент: второй Word понимает как «auto»
    layout.set(qn("w:type"), "fixed")
    for j, w in enumerate(widths):
        if j < len(table.columns):
            table.columns[j].width = w

    # Ширина таблицы целиком = сумма колонок В TWIPS, как она записана в `w:tblGrid`. python-docx
    # переводит каждую колонку в twips отдельно и округляет, поэтому сумма может разойтись с переводом
    # общей длины на twip (9640 против 9639 — ровно этот случай и поймала проверка выгрузок). Остаток
    # отдаём самой широкой колонке: тогда сетка, ширина таблицы и полоса набора совпадают до twip, и
    # таблица не «досчитывается» ни Word, ни LibreOffice.
    grid = table._tbl.find(qn("w:tblGrid"))
    колонки = list(grid) if grid is not None else []
    if колонки:
        значения = [int(g.get(qn("w:w"))) for g in колонки]
        разница = int(sum(int(w) for w in widths) // EMU_PER_TWIP) - sum(значения)
        if разница:
            j = max(range(len(значения)), key=lambda k: значения[k])
            значения[j] += разница
            колонки[j].set(qn("w:w"), str(значения[j]))
        всего_twips = sum(значения)
    else:
        всего_twips = int(sum(int(w) for w in widths) // EMU_PER_TWIP)
    ширина.set(qn("w:w"), str(всего_twips))


def _add_cell_text(cell, text: str, *, bold: bool, size):
    """Содержимое ячейки. «формулировка¦подпись» печатается так же, как на экране: подпись —
    отдельной тонкой строкой под формулировкой (раньше она склеивалась с текстом через « · »).
    Подпись — системная пометка: 9 pt курсивом серым, как дата постановки в тексте задачи."""
    p = cell.paragraphs[0]
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    # Задача этой встречи в едином списке протокола (решение владелицы 18.10.2026): пометку «[new] » в начале формулировки
    # ставит код при выгрузке. Значок в ячейку Word не вставляем — печатаем короткое «new» мелким полужирным серым,
    # как системную пометку (на экране на этом месте маленький значок того же текста).
    if text.startswith(NEW_TASK_MARK):
        text = text[len(NEW_TASK_MARK):]
        run = p.add_run("new")
        set_run_font(run, size=SYSTEM_NOTE_SIZE, color=SYSTEM_NOTE_COLOR)
        run.bold = True
        p.add_run(" ")
    if "¦" in text:
        главное, подпись = text.split("¦", 1)
        add_inline_runs(p, главное.strip(), bold=bold, size=size)
        line_break = p.add_run()
        line_break.add_break()
        run = p.add_run(подпись.strip())
        set_run_font(run, size=SUBCAPTION_SIZE, color=SUBCAPTION_COLOR, italic=True)
    else:
        add_inline_runs(p, text, bold=bold, size=size)


def add_table(doc, rows, section):
    ncols = len(rows[0])
    table = doc.add_table(rows=0, cols=ncols)
    table.style = "Table Grid"
    table.autofit = False
    _set_cell_margins(table)

    usable_width = section.page_width - section.left_margin - section.right_margin
    widths = compute_column_widths(rows, usable_width)

    for i, row_cells in enumerate(rows):
        row = table.add_row()
        _keep_row_together(row)
        for j, cell_text in enumerate(row_cells):
            if j >= len(row.cells):
                continue
            cell = row.cells[j]
            cell.width = widths[j]
            cell.text = ""
            _add_cell_text(cell, cell_text, bold=(i == 0), size=TABLE_FONT_SIZE)
            if i == 0:
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                _set_cell_shading(cell, TABLE_HEADER_FILL)
            else:
                cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
    for row in table.rows:
        for j, w in enumerate(widths):
            if j < len(row.cells):
                row.cells[j].width = w
    _fix_table_width(table, widths)
    if table.rows:
        _repeat_header_row(table.rows[0])


# --------------------------------------------------------------------------
# Сборка документа
# --------------------------------------------------------------------------

def convert(md_path: Path):
    lines = md_path.read_text(encoding="utf-8").splitlines()
    doc = Document()
    setup_page(doc)
    setup_styles(doc)
    add_page_numbers(doc)

    section = doc.sections[0]
    i = 0
    n = len(lines)
    para_buf = []
    last_was_table = False

    def add_block_spacer():
        """Разделитель нужен только между двумя таблицами: без него Word слил бы их в одну."""
        nonlocal last_was_table
        if last_was_table:
            add_marker_paragraph(doc)

    def flush_para():
        nonlocal last_was_table
        if not para_buf:
            return
        text = " ".join(s.strip() for s in para_buf if s.strip())
        para_buf.clear()
        if text:
            add_block_spacer()
            add_paragraph(doc, text)
            last_was_table = False

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("### "):
            flush_para()
            add_block_spacer()
            add_heading(doc, stripped[4:].strip(), level=3)
            last_was_table = False
            i += 1
            continue
        if stripped.startswith("## "):
            flush_para()
            add_block_spacer()
            add_heading(doc, stripped[3:].strip(), level=2)
            last_was_table = False
            i += 1
            continue
        if stripped.startswith("# "):
            flush_para()
            add_block_spacer()
            add_heading(doc, stripped[2:].strip(), level=1)
            last_was_table = False
            i += 1
            continue

        if is_table_line(line):
            flush_para()
            add_block_spacer()
            table_rows = [parse_table_row(line)]
            i += 1
            if i < n and is_table_line(lines[i]) and is_separator_line(lines[i]):
                i += 1
            while i < n and is_table_line(lines[i]):
                table_rows.append(parse_table_row(lines[i]))
                i += 1
            add_table(doc, table_rows, section)
            last_was_table = True
            continue

        bullet_match = LIST_BULLET_RE.match(stripped)
        number_match = LIST_NUMBER_RE.match(stripped)
        if bullet_match or number_match:
            flush_para()
            add_block_spacer()
            text = (bullet_match or number_match).group(1).strip()
            add_list_item(doc, text, ordered=bool(number_match))
            last_was_table = False
            i += 1
            continue

        if stripped == "":
            flush_para()
            i += 1
            continue

        para_buf.append(line)
        i += 1

    flush_para()
    if last_was_table:
        add_marker_paragraph(doc)      # документ не должен заканчиваться таблицей

    # Название документа — в свойства файла: в проводнике и списке последних файлов видно, что это.
    заголовок = next((l.strip().lstrip("# ").strip() for l in lines if l.strip()), "")
    if заголовок:
        doc.core_properties.title = заголовок[:250]

    out_path = md_path.with_suffix(".docx")
    doc.save(str(out_path))
    return out_path


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        out = convert(p)
        print(f"OK: {out}")
