"""Живой замер досмотра моделью роли guard (владелец 10.10.26: «расширяй и замеряй досмотр»).

Путь тот же, что в конвейере: правило guard.line_verdict помечает уверенные строки; строки «unsure» уходят модели
(guard.classify: ответ ДА/НЕТ, иначе None); итог — помечено правилом ИЛИ модель сказала ДА.

  python eval/guard/measure_classifier.py [--model qwen/qwen-plus] [--real]

Наборы: настроечный, отложенные 1–3 (третий — итоговый: правила зафиксированы до его первого прогона). --real —
строки «unsure» реальных встреч (MEETFLOW_REAL_DBS) уходят модели, печатаются только числа. Ключ — переменная
OPENROUTER_API_KEY или строка из .env.local Планёрки (так же берёт run_dev.ps1); значение не печатается.
Потолок расхода — 0,50 $ на прогон: дальше вызовы не идут."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval" / "guard"))

from meetflow.connectors.llm_openrouter import OpenRouterLLM  # noqa: E402
from meetflow.core import guard  # noqa: E402

CAP_USD = 0.50


def load_key() -> None:
    if os.environ.get("OPENROUTER_API_KEY"):
        return
    for f in (ROOT / ".env.local", Path.home() / "Documents" / "ITMO_planerka" / "webapp" / ".env.local"):
        if f.exists():
            for ln in f.read_text(encoding="utf-8-sig").splitlines():
                if ln.strip().startswith("OPENROUTER_API_KEY="):
                    os.environ["OPENROUTER_API_KEY"] = ln.split("=", 1)[1].strip().strip('"').strip("'")
                    return
    sys.exit("нет ключа OPENROUTER_API_KEY")


class Counted:
    def __init__(self, llm):
        self.llm, self.cost, self.calls = llm, 0.0, 0

    def complete(self, system, user, **kw):
        if self.cost >= CAP_USD:
            raise RuntimeError("потолок расхода")
        res = self.llm.complete(system, user, **kw)
        self.calls += 1
        self.cost += res.cost_usd or 0.0
        return res


def judge(lines, llm):
    """(помечено итогом, None от модели, вызовов) по списку строк."""
    flagged = none = calls = 0
    for ln in lines:
        v = guard.line_verdict(ln)
        if v["suspicious"]:
            flagged += 1
            continue
        if v["unsure"]:
            calls += 1
            said = guard.classify(llm, ln)
            flagged += said is True
            none += said is None
    return flagged, none, calls


def main() -> None:
    model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "qwen/qwen-plus"
    load_key()
    llm = Counted(OpenRouterLLM(model=model, max_answer_tokens=5, attempts=2, backoff=3.0))
    t = ROOT / "tests"
    c = yaml.safe_load((t / "guard_corpus.yaml").read_text(encoding="utf-8"))
    sets = [("настроечный", [x for v in c["attacks"].values() for x in v], c["benign"])]
    for n, f, a, b in ((1, "guard_holdout.yaml", "holdout_attacks", "holdout_benign"),
                       (2, "guard_holdout2.yaml", "holdout2_attacks", "holdout2_benign"),
                       (3, "guard_holdout3.yaml", "holdout3_attacks", "holdout3_benign")):
        h = yaml.safe_load((t / f).read_text(encoding="utf-8"))
        sets.append((f"отложенный {n}", h[a], h[b]))
    print(f"модель досмотра: {model}")
    for name, att, ben in sets:
        rule_a = sum(guard.line_verdict(x)["suspicious"] for x in att)
        fa, na, ca = judge(att, llm)
        fb, nb, cb = judge(ben, llm)
        print(f"{name}: атак {fa}/{len(att)} (правилом {rule_a}, модель без ответа {na}); "
              f"ложных {fb}/{len(ben)} (без ответа {nb}); вызовов {ca + cb}")
    if "--real" in sys.argv:
        from measure_real import lines_of   # noqa: E402
        import sqlite3
        lines = []
        for db in [p for p in os.environ.get("MEETFLOW_REAL_DBS", "").split(";") if p.strip()]:
            base = Path(db).resolve().parents[1]
            con = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)
            for (fp,) in con.execute("SELECT file_path FROM meeting_sources WHERE is_current=1"):
                p = Path(fp) if os.path.isabs(fp) else base / fp
                if p.exists():
                    lines += [ln for ln in lines_of(p) if ln.strip() and guard.line_verdict(ln)["unsure"]]
        f, n, cl = judge(lines, llm)
        print(f"реальные встречи: строк на досмотр {len(lines)}, модель сказала ДА {f}, без ответа {n}")
    print(f"вызовов модели {llm.calls}, расход {llm.cost:.4f} $")


if __name__ == "__main__":
    main()
