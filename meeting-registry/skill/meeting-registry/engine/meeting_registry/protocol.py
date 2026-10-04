"""Протокол встречи — документ для людей. Никаких служебных пометок в тексте (правило владельца 10.09.26:
«никогда, ни при каких условиях не включать системные комментарии»). Таблицы собирает код из реестра,
а не модель: модель ни разу из 14 не вернула таблицу целой (Планёрка, 22.09.26).
Нумерация в таблицах с 1; внутренний номер задачи показывается только в реестре.
Протокол не утверждает того, чего система не проверила: если часть записи не разобрана, «не прозвучало»
не пишется (ревью 03.10.26).
"""


def _d(iso):
    if not iso:
        return ""
    y, m, d = iso[:10].split("-")
    return f"{d}.{m}.{y}"


def _cell(text) -> str:
    """Ячейка таблицы markdown: «|» и перевод строки внутри текста ломали таблицу (ревью 03.10.26)."""
    return str(text if text is not None else "—").replace("|", "\\|").replace("\n", " ").strip() or "—"


def _table(rows, people):
    out = ["| № | Задача | Ответственный | Срок |", "|---|---|---|---|"]
    for i, t in enumerate(rows, 1):
        who = people.get(t.get("responsible_id"), t.get("responsible_text") or "—")
        out.append(f"| {i} | {_cell(t['description'])} | {_cell(who)} | {_cell(t.get('due') or '—')} |")
    return out


def render(meeting_date: str, title: str, new_tasks: list, closures: list, held_count: int,
           open_tasks: list, people: dict, degraded: bool = False, notes: dict | None = None) -> str:
    notes = notes or {}
    failed_chunks = notes.get("failed_chunks", 0)
    closing_unfinished = notes.get("closing_unfinished", False)
    duplicates = notes.get("duplicates", 0)

    out = [f"# Протокол совещания {_d(meeting_date)}", ""]
    if title:
        out += [title, ""]
    if degraded:
        # это не служебная пометка, а свойство документа, которое должен знать читатель
        out += ["Протокол собран без языковой модели, по правилам. Возможны пропущенные поручения.", ""]

    out += ["## Поручения этой встречи", ""]
    if new_tasks:
        out += _table(new_tasks, people)
    elif failed_chunks:
        out.append("Поручения с названным исполнителем в разобранной части записи не найдены.")
    else:
        out.append("Новых поручений с названным исполнителем не прозвучало.")
    if duplicates:
        out += ["", f"Повторно прозвучали поручения, которые уже есть в реестре открытых задач: {duplicates}."]
    out.append("")

    out += ["## Выполнено и снято по итогам встречи", ""]
    if closures:
        out += ["| № | Задача | Итог | Основание |", "|---|---|---|---|"]
        for i, c in enumerate(closures, 1):
            out.append(f"| {i} | {_cell(c['description'])} | {'выполнено' if c['status'] == 'done' else 'снято'} | «{_cell(c['quote'])}» |")
    elif closing_unfinished:
        out.append("Сверка выполнения задач по этой встрече не завершена, решение — у ответственного за реестр.")
    else:
        out.append("О выполнении задач из реестра на встрече не сообщалось.")
    out.append("")

    if held_count or failed_chunks or closing_unfinished:
        out += ["## Требует уточнения", ""]
        if held_count:
            out.append(f"Пунктов, которые требуют решения ответственного за реестр: {held_count}. Они не внесены в реестр до уточнения.")
        if failed_chunks:
            out.append(f"Часть записи не разобрана (фрагментов: {failed_chunks}) — список поручений может быть неполным.")
        if closing_unfinished:
            out.append("Сообщения о выполнении задач требуют проверки человеком.")
        out.append("")

    out += [f"## Открытые задачи — срез на {_d(meeting_date)}", ""]
    if open_tasks:
        out += _table(open_tasks, people)
    else:
        out.append("Открытых задач нет.")
    out.append("")
    return "\n".join(out)
