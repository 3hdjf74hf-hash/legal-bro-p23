#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
markup.py — детерминированная разметка (ФАЗА 0) конвейера п.23.


Обрабатывает СТРОГО три суда:
  - 7кас  (4 части: 7кас_ч.1.txt … 7кас_ч.4.txt)         — кассация
  - 8кас  (4 части: 8кас_ч.1.txt … 8кас_ч.4.txt)         — кассация
  - СОЮ Москвы и области (3 части: СОЮ_Москвы_1..3.txt)  — АПЕЛЛЯЦИЯ Мосгорсуда

Что делает:
  1. Находит границы определений в каждой части (два паттерна заголовка).
  2. Сквозная нумерация дел через все части суда.
  3. Проверяет стыки частей на дубль последнего дела (по номеру определения).
  4. Режет на группы по 10 (в пределах одной части; последняя группа части — остаток).
  5. Пишет п.23/<суд>/разметка.md.
  6. Создаёт заготовки: дела_XX-YY.md, сводная_таблица.csv (BOM+';'), сводная_таблица.md.

Запуск (из корня репозитория):
  python markup.py            # обработать все три суда
  python markup.py 7кас       # только один суд
"""

import os
import re
import sys
import glob

# ЖЁСТКО зашитый scope — только эти три судьи.
TARGETS = ["7кас", "8кас", "СОЮ Москвы и области"]

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "п.23")

# Паттерны заголовков (после очистки \xa0 и strip).
KASS_RE = re.compile(r"КАССАЦИОННЫЙ СУД ОБЩЕЙ ЮРИСДИКЦИИ\s*$")
SOY_RE = re.compile(r"^МОСКОВСКИЙ ГОРОДСКОЙ СУД\s*$")
# Номер определения/дела: "N 88-7492/2026" или "по делу N 33-19277/2026".
NUM_RE = re.compile(r"N\s*(\d+-\d+/\d+)")


def clean(s: str) -> str:
    """Убираем неразрывные пробелы и обрамляющие пробелы."""
    return s.replace("\xa0", " ").strip()


def find_parts(court: str):
    """Список файлов-частей суда в правильном порядке."""
    cdir = os.path.join(BASE, court)
    if court.startswith("СОЮ"):
        parts = sorted(glob.glob(os.path.join(cdir, "СОЮ_Москвы_*.txt")))
    else:
        parts = sorted(glob.glob(os.path.join(cdir, f"{court}_ч.*.txt")))
        if not parts:  # одночастный файл
            parts = sorted(glob.glob(os.path.join(cdir, f"{court}.txt")))
    return parts


def detect_kind(first_lines):
    """Определяем тип суда по первым непустым строкам."""
    head = " ".join(clean(l) for l in first_lines[:8])
    if "МОСКОВСКИЙ ГОРОДСКОЙ СУД" in head:
        return "сою"
    return "кассация"


def find_definitions(path, kind):
    """
    Возвращает (starts, lines, numbers):
      starts  — 0-based индексы строк начала определений,
      lines   — все строки файла,
      numbers — номера определений (или None, если не найден/обезличен).
    Заголовок подтверждаем наличием слова ОПРЕДЕЛЕНИЕ в ближайших строках —
    это ловит и нестандартные заголовки (СОЮ ч.3, где 2 дела без 'АПЕЛЛЯЦИОННОЕ').
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    starts, numbers = [], []
    for i, line in enumerate(lines):
        s = clean(line)
        if kind == "кассация":
            if not (KASS_RE.search(s) and s.isupper()):
                continue
        else:  # сою
            if not SOY_RE.match(s):
                continue
        # Подтверждение: в следующих ~5 строках есть ОПРЕДЕЛЕНИЕ.
        window_lines = [clean(l) for l in lines[i + 1: i + 6]]
        window = " ".join(window_lines)
        if "ОПРЕДЕЛЕНИЕ" not in window.upper():
            continue
        starts.append(i)
        m = NUM_RE.search(window)
        numbers.append(m.group(1) if m else None)
    return starts, lines, numbers


def make_groups(starts, lines, part_name, start_num):
    """Режем определения одной части на группы по 10. Нумерация — со start_num."""
    groups = []
    n = len(starts)
    i = 0
    num = start_num
    while i < n:
        j = min(i + 10, n)
        first_def, last_def = i, j - 1
        start_line = starts[first_def] + 1  # 1-based
        end_line = starts[last_def + 1] if last_def + 1 < n else len(lines)
        groups.append({
            "from": num,
            "to": num + (j - i) - 1,
            "part": part_name,
            "start_line": start_line,
            "end_line": end_line,
            "count": j - i,
        })
        num += (j - i)
        i = j
    return groups, num


def process_court(court: str):
    parts = find_parts(court)
    if not parts:
        print(f"!! {court}: файлы не найдены, пропуск.")
        return None

    all_groups = []
    total_defs = 0
    num = 1
    stitches = []  # (стык, prev_num, next_num, is_dup, prev_delo, next_delo)
    prev_last_number = None
    prev_last_delo = None
    prev_part = None

    for part_path in parts:
        part_name = os.path.basename(part_path)
        with open(part_path, encoding="utf-8", errors="replace") as f:
            first_lines = [f.readline() for _ in range(8)]
        kind = detect_kind(first_lines)
        starts, lines, numbers = find_definitions(part_path, kind)

        first_delo_global = num  # глобальный номер первого дела этой части

        # Проверка стыка на дубль (по номеру определения).
        if prev_last_number is not None and numbers and numbers[0] is not None:
            is_dup = (numbers[0] == prev_last_number)
            stitches.append((f"{prev_part} → {part_name}",
                             prev_last_number, numbers[0], is_dup,
                             prev_last_delo, first_delo_global))

        groups, num = make_groups(starts, lines, part_name, num)
        all_groups.extend(groups)
        total_defs += len(starts)
        if numbers:
            prev_last_number = numbers[-1]
            prev_last_delo = first_delo_global + len(starts) - 1
        prev_part = part_name


    return {
        "court": court,
        "parts": [os.path.basename(p) for p in parts],
        "groups": all_groups,
        "total_defs": total_defs,
        "stitches": stitches,
    }


def write_razmetka(res):
    court = res["court"]
    out = os.path.join(BASE, court, "разметка.md")
    lines = []
    lines.append(f"# Разметка — {court}")
    lines.append("")
    lines.append(f"**Частей:** {len(res['parts'])} ({', '.join(res['parts'])})")
    lines.append(f"**Всего определений:** {res['total_defs']}")
    lines.append(f"**Групп:** {len(res['groups'])}")
    lines.append("")
    lines.append("## Стыки частей (проверка на дубль)")
    lines.append("")
    if res["stitches"]:
        for stk, prev, nxt, is_dup, prev_delo, next_delo in res["stitches"]:
            if is_dup:
                lines.append(f"- {stk}: определение {prev} — ⚠️ **ДУБЛЬ**: "
                             f"дело {next_delo} повторяет дело {prev_delo} "
                             f"(нумерацию НЕ сдвигать, дело {next_delo} пометить дублём).")
            else:
                lines.append(f"- {stk}: последний={prev} (дело {prev_delo}) / "
                             f"первый={nxt} (дело {next_delo}) — ✅ чисто")
    else:
        lines.append("- (одна часть, стыков нет)")

    lines.append("")
    lines.append("## Группы")
    lines.append("")
    lines.append("| Группа | Часть | Строки (1-based) | Дел |")
    lines.append("|---|---|---|---|")
    for g in res["groups"]:
        rng = f"{g['from']:02d}-{g['to']:02d}"
        lines.append(f"| дела_{rng} | {g['part']} | {g['start_line']}–{g['end_line']} | {g['count']} |")
    lines.append("")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return out


def create_stubs(res):
    court = res["court"]
    cdir = os.path.join(BASE, court)
    # Заготовки дела_XX-YY.md
    for g in res["groups"]:
        rng = f"{g['from']:02d}-{g['to']:02d}"
        path = os.path.join(cdir, f"дела_{rng}.md")
        if os.path.exists(path):
            continue
        title = ("Московский городской суд (апелляция)" if court.startswith("СОЮ")
                 else f"{court} — кассационный суд общей юрисдикции")
        body = (
            f"# {title} — анализ определений, дела {rng}\n\n"
            f"**Источник:** {g['part']}, строки {g['start_line']}–{g['end_line']}\n\n"
            f"<!-- ЧЕРНОВИК (Luna 5.6): для каждого определения блок \"### Дело N ...\" "
            f"по структуре из AGENT_copilot.md. В конце — \"## Общие наблюдения по группе\". -->\n"

        )
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    # Заготовка сводная_таблица.csv (BOM + заголовок, разделитель ';', поля в кавычках)
    csv_path = os.path.join(cdir, "сводная_таблица.csv")
    if not os.path.exists(csv_path):
        header = ("№;Определение;Дата;Дело N;Истец (должность);Ответчик;"
                  "Способ определения размера ЗП;Размер / база расчёта;Итог;Ключевой вывод по п. 23")
        quoted = ";".join(f'"{c}"' for c in header.split(";"))
        with open(csv_path, "w", encoding="utf-8-sig", newline="\n") as f:
            f.write(quoted + "\n")
    # Заготовка сводная_таблица.md (6 колонок)
    md_path = os.path.join(cdir, "сводная_таблица.md")
    if not os.path.exists(md_path):
        with open(md_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# Сводная таблица — {court}\n\n")
            f.write("| № | Определение, дата | Стороны | Способ | Итог | Ключевой вывод |\n")
            f.write("|---|---|---|---|---|---|\n")


def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else TARGETS
    for court in targets:
        if court not in TARGETS:
            print(f"!! {court}: вне scope (разрешены только {TARGETS}), пропуск.")
            continue
        res = process_court(court)
        if not res:
            continue
        out = write_razmetka(res)
        create_stubs(res)
        dups = [s for s in res["stitches"] if s[3]]
        print(f"OK {court}: определений={res['total_defs']}, групп={len(res['groups'])}, "
              f"стыков={len(res['stitches'])}, дублей={len(dups)} → {out}")
    print("\nМУЖИК, ВКЛЮЧАЙ LUNA 5.6 — разметка готова. Запускай черновой разбор: «черновик 7кас» (или 8кас / СОЮ).")



if __name__ == "__main__":
    main()
