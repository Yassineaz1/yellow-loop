#!/usr/bin/env python3
"""
Outil de consultation de la base de résultats (db/).

Usage :
    python3 db_tool.py list           # liste les départements finis (nb de lignes)
    python3 db_tool.py status         # état complet (done / failed / restants)
    python3 db_tool.py get <dept>     # affiche la commande scp pour télécharger db/<dept>.csv
"""
import os
import sys
import csv
import json

import config


def count_rows(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            return max(sum(1 for _ in csv.reader(f)) - 1, 0)  # -1 pour l'en-tête
    except Exception:
        return "?"


def cmd_list():
    if not os.path.isdir(config.DB_DIR):
        print("Aucun résultat : db/ n'existe pas encore.")
        return
    files = sorted(f for f in os.listdir(config.DB_DIR) if f.endswith(".csv"))
    if not files:
        print("db/ est vide.")
        return
    print(f"{'Fichier':40} {'Lignes':>8}")
    print("-" * 50)
    total = 0
    for f in files:
        path = os.path.join(config.DB_DIR, f)
        n = count_rows(path)
        if isinstance(n, int):
            total += n
        print(f"{f:40} {n:>8}")
    print("-" * 50)
    print(f"{'TOTAL':40} {total:>8}")


def cmd_status():
    depts = []
    if os.path.exists(config.DEPARTEMENTS_FILE):
        with open(config.DEPARTEMENTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    depts.append(line)

    progress = {}
    if os.path.exists(config.PROGRESS_FILE):
        with open(config.PROGRESS_FILE, "r", encoding="utf-8") as f:
            progress = json.load(f)

    print(f"{'Dept':8} {'Statut':14} {'Lignes':>8} {'Mis à jour'}")
    print("-" * 60)
    for d in depts:
        e = progress.get(d, {})
        status = e.get("status", "à faire")
        rows = e.get("rows", "")
        updated = e.get("updated_at", "")
        print(f"{d:8} {status:14} {str(rows or ''):>8} {updated}")


def cmd_get(dept):
    fname = f"{dept}.csv"
    path = os.path.join(config.DB_DIR, fname)
    if not os.path.exists(path):
        print(f"❌ {fname} introuvable dans db/. Départements disponibles :")
        cmd_list()
        return
    print(f"📂 Fichier local : {path}")
    print(f"   {count_rows(path)} lignes.")
    print("\nPour le télécharger depuis le VPS vers ta machine, lance EN LOCAL :")
    print(f"   scp <user>@<ip-vps>:'{path}' .")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1].lower()
    if cmd == "list":
        cmd_list()
    elif cmd == "status":
        cmd_status()
    elif cmd == "get" and len(sys.argv) >= 3:
        cmd_get(sys.argv[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
