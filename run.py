#!/usr/bin/env python3
"""
Orchestrateur principal du pipeline de scraping PagesJaunes.

C'est le SEUL script à lancer :  python3 run.py

Pour chaque département listé dans departements.txt :
    1. purge le dossier work/ (aucun reste du département précédent)
    2. scrape PagesJaunes        -> work/input.csv          (frais, mode "w")
    3. enrichit SIRET/SIREN      -> work/output_enriched.csv
    4. ajoute les dirigeants     -> work/output_final.csv
    5. nettoie                   -> work/{dept}.csv
    6. déplace le résultat       -> db/{dept}.csv
    7. marque le département "done" dans state/progress.json
    8. purge work/ et passe au département suivant

Reprise : les départements déjà "done" sont sautés au relancement.
Sur échec d'une étape : le département est marqué "failed", on continue au suivant.
"""
import os
import sys
import json
import shutil
import subprocess
from datetime import datetime

import config
import scraper


# ──────────────────────────────────────────────────────────────────────────
#  Lecture des fichiers d'entrée
# ──────────────────────────────────────────────────────────────────────────
def load_departements():
    """Lit departements.txt : 1 département par ligne, '#' = commentaire."""
    if not os.path.exists(config.DEPARTEMENTS_FILE):
        print(f"❌ {config.DEPARTEMENTS_FILE} introuvable.")
        sys.exit(1)
    depts = []
    with open(config.DEPARTEMENTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            # Retirer le commentaire éventuel
            line = line.split("#", 1)[0].strip()
            if line:
                depts.append(line)
    if not depts:
        print("❌ departements.txt ne contient aucun département.")
        sys.exit(1)
    return depts


# ──────────────────────────────────────────────────────────────────────────
#  État / progression (reprise après crash)
# ──────────────────────────────────────────────────────────────────────────
def load_progress():
    if os.path.exists(config.PROGRESS_FILE):
        try:
            with open(config.PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_progress(progress):
    config.ensure_dirs()
    with open(config.PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def mark(progress, dept, status, rows=None):
    progress[dept] = {
        "status": status,
        "rows": rows,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_progress(progress)


# ──────────────────────────────────────────────────────────────────────────
#  Dossier de travail éphémère
# ──────────────────────────────────────────────────────────────────────────
def purge_work():
    """Vide entièrement work/ pour éliminer tout reste du département précédent."""
    if os.path.exists(config.WORK_DIR):
        shutil.rmtree(config.WORK_DIR, ignore_errors=True)
    os.makedirs(config.WORK_DIR, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────────
#  Étapes d'enrichissement (sous-scripts pilotés dans work/)
# ──────────────────────────────────────────────────────────────────────────
def run_subscript(script_name, stdin_text):
    """
    Lance un sous-script d'enrichissement avec cwd=work/.
    Le script (physiquement dans enrichement-scrappy/) lit/écrit ses fichiers
    fixes (input.csv, output_enriched.csv, ...) dans work/ grâce au cwd.
    Lève CalledProcessError si le script renvoie un code != 0.
    """
    script_path = os.path.join(config.ENRICH_DIR, script_name)
    python_cmd = "python" if os.name == "nt" else "python3"
    subprocess.run(
        [python_cmd, script_path],
        cwd=config.WORK_DIR,
        input=stdin_text,
        text=True,
        check=True,
    )


def process_department(dept, secteurs):
    """
    Traite un département de bout en bout. Retourne (ok: bool, rows: int|None).
    """
    raw = os.path.join(config.WORK_DIR, config.RAW_CSV)            # input.csv
    enriched = os.path.join(config.WORK_DIR, config.ENRICHED_CSV)  # output_enriched.csv
    final = os.path.join(config.WORK_DIR, config.FINAL_CSV)        # output_final.csv
    cleaned_name = f"{dept}.csv"
    cleaned = os.path.join(config.WORK_DIR, cleaned_name)
    db_target = os.path.join(config.DB_DIR, cleaned_name)

    # 1. Repartir d'un work/ propre
    purge_work()

    # 2. Scraping PagesJaunes -> work/input.csv
    print(f"\n[1/4] 🌐 Scraping PagesJaunes pour le {dept}...")
    rows = scraper.scrape_department(dept, raw, secteurs)
    if rows == 0 or not os.path.exists(raw):
        print(f"   ⚠️ Aucune donnée scrapée pour le {dept}.")
        return False, 0

    # 3. Enrichissement SIRET/SIREN -> work/output_enriched.csv
    print(f"\n[2/4] 🏢 Enrichissement SIRET/SIREN...")
    run_subscript("scraper.py", "1\n")
    if not os.path.exists(enriched):
        print("   ❌ output_enriched.csv non généré.")
        return False, rows

    # 4. Dirigeants (Pappers) -> work/output_final.csv
    print(f"\n[3/4] 👤 Recherche des dirigeants (Pappers)...")
    run_subscript("dirigeant.py", "1\no\n")
    if not os.path.exists(final):
        print("   ❌ output_final.csv non généré.")
        return False, rows

    # 5. Nettoyage -> work/{dept}.csv
    print(f"\n[4/4] 🧹 Nettoyage final...")
    run_subscript("cleaner.py", f"1\n{cleaned_name}\n")
    if not os.path.exists(cleaned):
        print(f"   ❌ {cleaned_name} non généré par le cleaner.")
        return False, rows

    # 6. Déplacement vers db/ (seul fichier qui survit)
    config.ensure_dirs()
    shutil.move(cleaned, db_target)
    print(f"   ✅ Résultat final : {db_target}")

    return True, rows


# ──────────────────────────────────────────────────────────────────────────
#  Boucle principale
# ──────────────────────────────────────────────────────────────────────────
def main():
    config.ensure_dirs()

    # Option : --retry-failed pour ne retraiter QUE les départements en échec
    retry_failed = "--retry-failed" in sys.argv

    depts = load_departements()
    secteurs = scraper.load_secteurs()
    progress = load_progress()

    print("=" * 64)
    print(f"  PIPELINE SCRAPPY — {len(depts)} départements, {len(secteurs)} secteurs")
    print("=" * 64)

    for dept in depts:
        entry = progress.get(dept, {})
        status = entry.get("status")

        if status == "done":
            print(f"\n⏭️  {dept} déjà traité (done) — on saute.")
            continue
        if status == "failed" and not retry_failed:
            print(f"\n⏭️  {dept} en échec précédemment — relancer avec --retry-failed.")
            continue

        print("\n" + "─" * 64)
        print(f"▶️  DÉPARTEMENT {dept}")
        print("─" * 64)
        mark(progress, dept, "in_progress")

        try:
            ok, rows = process_department(dept, secteurs)
            if ok:
                mark(progress, dept, "done", rows)
                print(f"\n🎉 {dept} terminé — {rows} lignes brutes → db/{dept}.csv")
            else:
                mark(progress, dept, "failed", rows)
                print(f"\n⚠️ {dept} en échec — on continue au suivant.")
        except subprocess.CalledProcessError as e:
            mark(progress, dept, "failed")
            print(f"\n⚠️ {dept} : une étape d'enrichissement a échoué ({e}). On continue.")
        except Exception as e:
            mark(progress, dept, "failed")
            print(f"\n⚠️ {dept} : erreur inattendue ({e}). On continue.")
        finally:
            # Purge systématique pour ne rien laisser traîner entre deux départements
            purge_work()

    # Bilan
    print("\n" + "=" * 64)
    print("  BILAN")
    print("=" * 64)
    done = [d for d, e in progress.items() if e.get("status") == "done"]
    failed = [d for d, e in progress.items() if e.get("status") == "failed"]
    print(f"  ✅ Terminés : {', '.join(done) if done else '—'}")
    print(f"  ⚠️ En échec : {', '.join(failed) if failed else '—'}")
    print(f"  📂 Résultats dans : {config.DB_DIR}")
    if failed:
        print(f"  ↻ Relancer les échecs : python3 run.py --retry-failed")


if __name__ == "__main__":
    main()
