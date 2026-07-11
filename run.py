#!/usr/bin/env python3
"""
Orchestrateur principal du pipeline PagesJaunes — granularité SECTEUR.

  python3 run.py                    # reprend là où on s'est arrêté
  python3 run.py --retry-failed     # retente uniquement les secteurs en échec

Pour chaque (département, secteur) non-terminé dans state/progress.json :
    1. purge work/                                          (fresh)
    2. scrape UN secteur         -> work/input.csv          (fresh, mode "w")
    3. enrichit SIRET/SIREN      -> work/output_enriched.csv
    4. ajoute les dirigeants     -> work/output_final.csv
    5. nettoie                   -> work/{secteur}.csv
    6. déplace le résultat vers  -> db/{dept}/{secteur}.csv (atomique)
    7. marque (dept, secteur) "done" dans state/progress.json
    8. purge work/ et passe au secteur suivant

Reprise : les (dept, secteur) déjà "done" sont sautés au relancement.
Sur échec d'un secteur : marqué "failed", on continue au suivant — aucune donnée
d'un autre secteur n'est perdue.
"""
import os
import re
import sys
import json
import shutil
import subprocess
from datetime import datetime

import config
import scraper


# ──────────────────────────────────────────────────────────────────────────
#  Utilitaires
# ──────────────────────────────────────────────────────────────────────────
def slugify_secteur(secteur):
    """Convertit 'salle de sport' -> 'salle_de_sport' pour un nom de fichier sûr."""
    s = secteur.strip().lower()
    s = re.sub(r'[^\w]+', '_', s, flags=re.UNICODE)
    s = re.sub(r'_+', '_', s).strip('_')
    return s or "secteur"


def load_departements():
    if not os.path.exists(config.DEPARTEMENTS_FILE):
        print(f"❌ {config.DEPARTEMENTS_FILE} introuvable.")
        sys.exit(1)
    depts = []
    with open(config.DEPARTEMENTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                depts.append(line)
    if not depts:
        print("❌ departements.txt vide.")
        sys.exit(1)
    return depts


# ──────────────────────────────────────────────────────────────────────────
#  État granulaire : { dept: { secteur_slug: {status, rows, updated_at} } }
# ──────────────────────────────────────────────────────────────────────────
def load_progress():
    if os.path.exists(config.PROGRESS_FILE):
        try:
            with open(config.PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Migration ancien format (dept -> {status}) : on ignore, sera écrasé
                for dept, entry in list(data.items()):
                    if isinstance(entry, dict) and "status" in entry and "secteurs" not in entry:
                        # ancien format à plat — repart de zéro pour ce dept
                        data[dept] = {}
                return data
        except Exception:
            return {}
    return {}


def save_progress(progress):
    config.ensure_dirs()
    tmp = config.PROGRESS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config.PROGRESS_FILE)


def mark_sector(progress, dept, secteur_slug, status, rows=None):
    progress.setdefault(dept, {})[secteur_slug] = {
        "status": status,
        "rows": rows,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_progress(progress)


def sector_status(progress, dept, secteur_slug):
    return progress.get(dept, {}).get(secteur_slug, {}).get("status")


# ──────────────────────────────────────────────────────────────────────────
#  Work dir
# ──────────────────────────────────────────────────────────────────────────
def purge_work():
    if os.path.exists(config.WORK_DIR):
        shutil.rmtree(config.WORK_DIR, ignore_errors=True)
    os.makedirs(config.WORK_DIR, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────────
#  Sous-scripts d'enrichissement
# ──────────────────────────────────────────────────────────────────────────
def run_subscript(script_name, stdin_text=None, extra_args=None):
    script_path = os.path.join(config.ENRICH_DIR, script_name)
    python_cmd = "python" if os.name == "nt" else "python3"
    cmd = [python_cmd, script_path]
    if extra_args:
        cmd.extend(extra_args)
    subprocess.run(
        cmd,
        cwd=config.WORK_DIR,
        input=stdin_text if stdin_text is not None else "",
        text=True,
        check=True,
    )


# ──────────────────────────────────────────────────────────────────────────
#  Traitement d'UN secteur
# ──────────────────────────────────────────────────────────────────────────
def process_sector(driver, dept, secteur):
    """Pipeline complet pour (dept, secteur). Retourne (ok, rows)."""
    secteur_slug = slugify_secteur(secteur)
    raw = os.path.join(config.WORK_DIR, config.RAW_CSV)
    enriched = os.path.join(config.WORK_DIR, config.ENRICHED_CSV)
    final = os.path.join(config.WORK_DIR, config.FINAL_CSV)
    cleaned_name = f"{secteur_slug}.csv"
    cleaned = os.path.join(config.WORK_DIR, cleaned_name)

    dept_db_dir = os.path.join(config.DB_DIR, dept)
    os.makedirs(dept_db_dir, exist_ok=True)
    db_target = os.path.join(dept_db_dir, cleaned_name)
    db_target_tmp = db_target + ".tmp"

    purge_work()

    # 1. Scraping
    print(f"\n[1/4] 🌐 Scraping {secteur} / {dept}...")
    try:
        rows = scraper.scrape_sector(driver, dept, secteur, raw)
    except scraper.ScraperBlocked as e:
        print(f"   🛑 Scraper bloqué : {e}")
        return False, 0
    if rows == 0 or not os.path.exists(raw):
        print(f"   ⚠️ 0 ligne scrapée pour {secteur}/{dept}.")
        return False, 0

    # 2. Enrichissement SIRET
    print(f"\n[2/4] 🏢 Enrichissement SIRET/SIREN...")
    run_subscript("scraper.py", "1\n")
    if not os.path.exists(enriched):
        print("   ❌ output_enriched.csv non généré.")
        return False, rows

    # 3. Dirigeants
    print(f"\n[3/4] 👤 Dirigeants (Pappers)...")
    run_subscript("dirigeant.py", "1\no\n")
    if not os.path.exists(final):
        print("   ❌ output_final.csv non généré.")
        return False, rows

    # 4. Nettoyage — non-interactif via argv
    print(f"\n[4/4] 🧹 Nettoyage...")
    try:
        run_subscript("cleaner.py", extra_args=[cleaned_name])
    except subprocess.CalledProcessError as e:
        print(f"   ❌ Cleaner a échoué (exit {e.returncode}) — souvent : 0 ligne valide.")
        return False, rows

    if not os.path.exists(cleaned) or os.path.getsize(cleaned) == 0:
        print(f"   ❌ {cleaned_name} manquant ou vide après cleaner.")
        return False, rows

    # 5. Move atomique vers db/{dept}/{secteur}.csv
    shutil.copy2(cleaned, db_target_tmp)
    os.replace(db_target_tmp, db_target)
    size = os.path.getsize(db_target)
    print(f"   ✅ Résultat final : {db_target} ({size} octets)")

    return True, rows


# ──────────────────────────────────────────────────────────────────────────
#  Boucle principale
# ──────────────────────────────────────────────────────────────────────────
def main():
    config.ensure_dirs()
    retry_failed = "--retry-failed" in sys.argv

    depts = load_departements()
    secteurs = scraper.load_secteurs()
    progress = load_progress()

    print("=" * 64)
    print(f"  PIPELINE — {len(depts)} départements × {len(secteurs)} secteurs = "
          f"{len(depts) * len(secteurs)} unités de travail")
    print("=" * 64)

    driver = None
    try:
        for dept in depts:
            print("\n" + "─" * 64)
            print(f"▶️  DÉPARTEMENT {dept}")
            print("─" * 64)

            for secteur in secteurs:
                secteur_slug = slugify_secteur(secteur)
                status = sector_status(progress, dept, secteur_slug)

                if status == "done":
                    print(f"  ⏭️  {secteur} — déjà fait, skip.")
                    continue
                if status == "failed" and not retry_failed:
                    print(f"  ⏭️  {secteur} — en échec (relancer avec --retry-failed).")
                    continue

                # Lazy start du driver Selenium
                if driver is None:
                    print("\n🚀 Démarrage Selenium...")
                    driver = scraper.setup_driver()

                mark_sector(progress, dept, secteur_slug, "in_progress")

                try:
                    ok, rows = process_sector(driver, dept, secteur)
                    if ok:
                        mark_sector(progress, dept, secteur_slug, "done", rows)
                        print(f"  🎉 {dept}/{secteur} : {rows} lignes brutes → OK")
                    else:
                        mark_sector(progress, dept, secteur_slug, "failed", rows)
                        print(f"  ⚠️ {dept}/{secteur} : échec, on continue.")
                except subprocess.CalledProcessError as e:
                    mark_sector(progress, dept, secteur_slug, "failed")
                    print(f"  ⚠️ {dept}/{secteur} : sous-script en échec ({e}).")
                except Exception as e:
                    mark_sector(progress, dept, secteur_slug, "failed")
                    print(f"  ⚠️ {dept}/{secteur} : erreur inattendue ({e}).")
                finally:
                    purge_work()
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    # Bilan
    print("\n" + "=" * 64)
    print("  BILAN")
    print("=" * 64)
    total_done = 0
    total_failed = 0
    for dept, entries in progress.items():
        done = [s for s, e in entries.items() if e.get("status") == "done"]
        failed = [s for s, e in entries.items() if e.get("status") == "failed"]
        total_done += len(done)
        total_failed += len(failed)
        print(f"  {dept}: ✅ {len(done)} done | ⚠️ {len(failed)} failed")
    print(f"\n  Total : ✅ {total_done} secteurs OK, ⚠️ {total_failed} en échec")
    print(f"  📂 Résultats : {config.DB_DIR}/{{dept}}/{{secteur}}.csv")
    if total_failed:
        print(f"  ↻ Retenter les échecs : python3 run.py --retry-failed")


if __name__ == "__main__":
    main()
