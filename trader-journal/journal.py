#!/usr/bin/env python3
"""Trade journal for trader-journal. Standard library only.

Records every closed trade (paper or real) and measures whether the method
makes money after fees, with an honest verdict that accounts for sample size.

  add      records one closed long trade: entry, stop, exit, quantity, fees,
           and whether the plan was followed. --from-plan prefills symbol,
           entry, stop, target, setup and date from trader/plan.json.
  list     prints the trades.
  stats    win rate, average R, expectancy, profit factor, max drawdown,
           worst losing streak, plan discipline, results by setup, and a
           verdict based on a 95% interval around the average R.
  remove   deletes one trade by id (to fix a typo).

    python3 journal.py add --symbol TSLA --entry 364.18 --stop 358.32 --exit 370.04 --qty 8 --followed oui
    python3 journal.py add --from-plan --exit 358.10 --qty 8 --fees 1.50 --followed non --note "entré trop tôt"
    python3 journal.py list --last 10
    python3 journal.py stats
    python3 journal.py stats --setup orb --json
    python3 journal.py remove --id 3

Everything is stored in trader/journal.json.
"""

import argparse
import datetime
import json
import math
import os
import sys

JOURNAL = os.path.join("trader", "journal.json")
PLAN = os.path.join("trader", "plan.json")
MIN_TRADES = 30
YES = ("oui", "o", "yes", "y")
NO = ("non", "n", "no")


class JournalError(Exception):
    pass


# ---------------------------------------------------------------- storage

def load_journal(path):
    if not os.path.exists(path):
        return {"trades": []}
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc.get("trades"), list):
        raise JournalError("%s n'a pas de liste \"trades\"" % path)
    return doc


def save_journal(path, doc):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- one trade

def build_trade(symbol, entry, stop, exit_price, qty, fees=0.0, target=None, setup=None,
                date=None, followed=True, note=None):
    """A closed long trade with its P&L and R multiple, net of fees."""
    if not symbol:
        raise JournalError("il manque le symbole (--symbol)")
    for name, v in (("entry", entry), ("stop", stop), ("exit", exit_price), ("qty", qty)):
        if v is None:
            raise JournalError("il manque --%s" % name)
        if v <= 0:
            raise JournalError("--%s doit être positif" % name)
    if fees < 0:
        raise JournalError("--fees ne peut pas être négatif")
    if stop >= entry:
        raise JournalError("le stop (%s) doit être sous l'entrée (%s) : le pack ne gère que les positions longues"
                           % (stop, entry))
    if target is not None and target <= entry:
        raise JournalError("l'objectif (%s) doit être au-dessus de l'entrée (%s)" % (target, entry))
    if date is None:
        date = datetime.date.today().isoformat()
    else:
        datetime.date.fromisoformat(date)
    risk = (entry - stop) * qty
    gross = (exit_price - entry) * qty
    net = gross - fees
    return {"symbol": symbol.upper(), "date": date, "setup": setup, "entry": entry, "stop": stop,
            "target": target, "exit": exit_price, "qty": qty, "fees": round(fees, 2),
            "risk_usd": round(risk, 2), "pnl_gross": round(gross, 2), "pnl_net": round(net, 2),
            "r": round(net / risk, 3), "followed_plan": bool(followed), "note": note}


def parse_followed(text):
    t = (text or "").strip().lower()
    if t in YES:
        return True
    if t in NO:
        return False
    raise JournalError("--followed attend oui ou non (as-tu respecté ton plan ?)")


# ---------------------------------------------------------------- statistics

def max_drawdown(pnls):
    peak = cum = worst = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
    return worst


def worst_streak(pnls):
    best = run = 0
    for p in pnls:
        run = run + 1 if p <= 0 else 0
        best = max(best, run)
    return best


def summarize(trades):
    """Numbers for a list of trades, in the order they were recorded."""
    n = len(trades)
    out = {"trades": n}
    if not n:
        return out
    pnls = [t["pnl_net"] for t in trades]
    rs = [t["r"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    mean_r = sum(rs) / n
    out.update({
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / n, 3),
        "pnl_net": round(sum(pnls), 2),
        "fees": round(sum(t["fees"] for t in trades), 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "expectancy_usd": round(sum(pnls) / n, 2),
        "avg_r": round(mean_r, 3),
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "max_drawdown": round(max_drawdown(pnls), 2),
        "worst_losing_streak": worst_streak(pnls),
        "followed_rate": round(sum(1 for t in trades if t["followed_plan"]) / n, 3),
    })
    if n >= 2:
        sd = math.sqrt(sum((r - mean_r) ** 2 for r in rs) / (n - 1))
        half = 1.96 * sd / math.sqrt(n)
        out["avg_r_interval"] = [round(mean_r - half, 3), round(mean_r + half, 3)]
    return out


def verdict(s):
    n = s["trades"]
    if n < MIN_TRADES:
        return ("TROP TOT", "%d trade(s) sur %d minimum : le hasard domine encore, aucune conclusion possible."
                % (n, MIN_TRADES))
    lo, hi = s["avg_r_interval"]
    if lo > 0:
        return ("AVANTAGE PROBABLE", "même la borne basse du R moyen est positive (%+.2fR). Continue en simulation "
                "pour confirmer, les marchés changent." % lo)
    if hi < 0:
        return ("PERDANT", "même la borne haute du R moyen est négative (%+.2fR). Cette méthode perd de l'argent "
                "après frais ; ne passe pas en réel avec elle." % hi)
    return ("PAS DE PREUVE D'AVANTAGE", "l'intervalle du R moyen [%+.2fR ; %+.2fR] contient zéro : impossible de "
            "distinguer ce résultat du hasard. Ce n'est pas une raison de passer en réel." % (lo, hi))


def report(trades, label=None):
    s = summarize(trades)
    lines = []
    title = "Journal de trades" + (" (setup %s)" % label if label else "")
    lines.append(title)
    lines.append("=" * len(title))
    if not s["trades"]:
        lines.append("Aucun trade enregistré.")
        return "\n".join(lines), s
    money = lambda v: "n/a" if v is None else "%+.2f USD" % v
    lines.append("Trades              %d (%d gagnants, %d perdants)" % (s["trades"], s["wins"], s["losses"]))
    lines.append("Taux de réussite    %.1f %%" % (100 * s["win_rate"]))
    lines.append("Résultat net        %s (frais inclus : %.2f USD)" % (money(s["pnl_net"]), s["fees"]))
    lines.append("Gain moyen          %s" % money(s["avg_win"]))
    lines.append("Perte moyenne       %s" % money(s["avg_loss"]))
    lines.append("Espérance / trade   %s" % money(s["expectancy_usd"]))
    lines.append("R moyen             %+.2fR" % s["avg_r"])
    if "avg_r_interval" in s:
        lines.append("Intervalle 95 %%     [%+.2fR ; %+.2fR]" % tuple(s["avg_r_interval"]))
    lines.append("Profit factor       %s" % ("n/a" if s["profit_factor"] is None else "%.2f" % s["profit_factor"]))
    lines.append("Drawdown maximal    %.2f USD" % s["max_drawdown"])
    lines.append("Pire série perdante %d trade(s)" % s["worst_losing_streak"])
    lines.append("Plan respecté       %.0f %% des trades" % (100 * s["followed_rate"]))
    followed = [t for t in trades if t["followed_plan"]]
    broken = [t for t in trades if not t["followed_plan"]]
    if followed and broken:
        a, b = summarize(followed), summarize(broken)
        lines.append("  plan respecté     %d trade(s), R moyen %+.2fR" % (a["trades"], a["avg_r"]))
        lines.append("  plan non respecté %d trade(s), R moyen %+.2fR" % (b["trades"], b["avg_r"]))
    if not label:
        setups = sorted(set(t.get("setup") or "?" for t in trades))
        if len(setups) > 1:
            lines.append("Par setup")
            for name in setups:
                sub = summarize([t for t in trades if (t.get("setup") or "?") == name])
                lines.append("  %-17s %d trade(s), réussite %.0f %%, R moyen %+.2fR, net %s"
                             % (name, sub["trades"], 100 * sub["win_rate"], sub["avg_r"], money(sub["pnl_net"])))
    word, why = verdict(s)
    s["verdict"] = word
    lines.append("")
    lines.append("Verdict : %s : %s" % (word, why))
    return "\n".join(lines), s


# ---------------------------------------------------------------- commands

def cmd_add(a):
    plan = {}
    if a.from_plan:
        if not os.path.exists(a.plan):
            raise JournalError("pas de plan dans %s : lance d'abord /trader-exit ou donne les prix" % a.plan)
        with open(a.plan, encoding="utf-8") as fh:
            plan = json.load(fh)
    pick = lambda mine, key: mine if mine is not None else plan.get(key)
    trade = build_trade(pick(a.symbol, "symbol"), pick(a.entry, "entry"), pick(a.stop, "stop"), a.exit,
                        a.qty, a.fees, pick(a.target, "target"), pick(a.setup, "setup"), pick(a.date, "date"),
                        parse_followed(a.followed), a.note)
    doc = load_journal(a.file)
    trade["id"] = max([t.get("id", 0) for t in doc["trades"]] + [0]) + 1
    doc["trades"].append(trade)
    save_journal(a.file, doc)
    print("Trade #%d enregistré : %s %s, %g actions, entrée %.2f, sortie %.2f, net %+.2f USD (%+.2fR)%s"
          % (trade["id"], trade["date"], trade["symbol"], trade["qty"], trade["entry"], trade["exit"],
             trade["pnl_net"], trade["r"], "" if trade["followed_plan"] else ", plan NON respecté"))
    print("%d trade(s) dans le journal." % len(doc["trades"]))


def cmd_list(a):
    trades = load_journal(a.file)["trades"]
    if a.last:
        trades = trades[-a.last:]
    if not trades:
        print("Aucun trade enregistré.")
        return
    print("%4s  %-10s  %-6s  %-8s  %6s  %9s  %9s  %9s  %10s  %7s  %s"
          % ("id", "date", "symb.", "setup", "qty", "entrée", "stop", "sortie", "net USD", "R", "plan"))
    for t in trades:
        print("%4d  %-10s  %-6s  %-8s  %6g  %9.2f  %9.2f  %9.2f  %+10.2f  %+7.2f  %s%s"
              % (t["id"], t["date"], t["symbol"], (t.get("setup") or "")[:8], t["qty"], t["entry"], t["stop"],
                 t["exit"], t["pnl_net"], t["r"], "oui" if t["followed_plan"] else "NON",
                 ("  " + t["note"]) if t.get("note") else ""))


def cmd_stats(a):
    trades = load_journal(a.file)["trades"]
    if a.setup:
        trades = [t for t in trades if (t.get("setup") or "") == a.setup]
    text, s = report(trades, a.setup)
    if a.json:
        print(json.dumps(s, indent=2, ensure_ascii=False))
    else:
        print(text)


def cmd_remove(a):
    doc = load_journal(a.file)
    keep = [t for t in doc["trades"] if t.get("id") != a.id]
    if len(keep) == len(doc["trades"]):
        raise JournalError("aucun trade avec l'id %d" % a.id)
    doc["trades"] = keep
    save_journal(a.file, doc)
    print("Trade #%d supprimé. %d trade(s) restant(s)." % (a.id, len(keep)))


def main(argv=None):
    p = argparse.ArgumentParser(description="Journal de trades et statistiques honnêtes.")
    p.add_argument("--file", default=JOURNAL, help="journal (défaut trader/journal.json)")
    sub = p.add_subparsers(dest="cmd")

    q = sub.add_parser("add", help="enregistrer un trade clôturé")
    q.add_argument("--from-plan", action="store_true", help="reprendre symbole, entrée, stop, objectif de trader/plan.json")
    q.add_argument("--plan", default=PLAN)
    q.add_argument("--symbol")
    q.add_argument("--entry", type=float)
    q.add_argument("--stop", type=float)
    q.add_argument("--target", type=float)
    q.add_argument("--exit", type=float, required=True)
    q.add_argument("--qty", type=float, required=True)
    q.add_argument("--fees", type=float, default=0.0)
    q.add_argument("--setup")
    q.add_argument("--date", help="AAAA-MM-JJ (défaut aujourd'hui)")
    q.add_argument("--followed", required=True, help="oui ou non : as-tu respecté ton plan ?")
    q.add_argument("--note")

    q = sub.add_parser("list", help="afficher les trades")
    q.add_argument("--last", type=int)

    q = sub.add_parser("stats", help="statistiques et verdict")
    q.add_argument("--setup")
    q.add_argument("--json", action="store_true")

    q = sub.add_parser("remove", help="supprimer un trade")
    q.add_argument("--id", type=int, required=True)

    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 1
    try:
        {"add": cmd_add, "list": cmd_list, "stats": cmd_stats, "remove": cmd_remove}[a.cmd](a)
    except (JournalError, ValueError) as e:
        print("Erreur : %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
