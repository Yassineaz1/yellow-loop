#!/usr/bin/env python3
"""
Orchestrateur du pipeline PagesJaunes.

Mode standard — parcourt departements.txt × secteur.txt et sauvegarde
db/{dept}/{secteur}.csv :

  python3 run.py                    # reprend là où on s'est arrêté
  python3 run.py --retry-failed     # retente uniquement les secteurs en échec

Mode single-secteur / all-France — scrape UN SEUL secteur sur tous les
départements français et concatène dans UN CSV unique :

  python3 run.py --single-secteur camping --output db/camping_france.csv --all-france
  python3 run.py --single-secteur camping --output db/camping_france.csv --depts 40,44,47
  python3 run.py --single-secteur camping --output db/camping_france.csv --all-france --retry-failed

Le state est stocké dans state/single_<slug>.json pour ne pas polluer le state
du mode standard.
"""
import os
import re
import sys
import csv
import json
import shutil
import subprocess
from datetime import datetime

import config
import scraper


# Départements FR métropolitains (01→95 sauf 20, plus 2A/2B pour la Corse).
ALL_FR_DEPTS = [f"{n:02d}" for n in range(1, 96) if n != 20] + ["2A", "2B"]


def parse_args():
    """Extrait --single-secteur, --output, --all-france, --depts, --retry-failed."""
    args = {
        "single_secteur": None,
        "output": None,
        "all_france": "--all-france" in sys.argv,
        "depts_override": None,
        "retry_failed": "--retry-failed" in sys.argv,
    }
    for i, a in enumerate(sys.argv):
        if a == "--single-secteur" and i + 1 < len(sys.argv):
            args["single_secteur"] = sys.argv[i + 1]
        elif a == "--output" and i + 1 < len(sys.argv):
            args["output"] = sys.argv[i + 1]
        elif a == "--depts" and i + 1 < len(sys.argv):
            args["depts_override"] = [d.strip() for d in sys.argv[i + 1].split(",") if d.strip()]
    return args


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
#  Résilience Selenium — driver vivant / recyclage
# ──────────────────────────────────────────────────────────────────────────

# Restart préventif toutes les N sectors pour éviter les fuites mémoire Chrome
# et les sessions webdriver qui se dégradent après des heures d'utilisation.
RESTART_DRIVER_EVERY_N_SECTORS = 30

# Marqueurs d'erreur qui signifient "le driver est mort, faut le recréer"
DEAD_DRIVER_MARKERS = (
    "Connection refused",
    "Max retries exceeded",
    "NewConnectionError",
    "invalid session id",
    "chrome not reachable",
    "session deleted",
    "no such session",
    "disconnected",
)


def is_dead_driver_error(exc):
    """Détecte si une exception vient d'un driver Selenium mort/injoignable."""
    msg = str(exc)
    return any(marker in msg for marker in DEAD_DRIVER_MARKERS)


def is_driver_alive(driver):
    """Ping léger : accède à driver.current_url pour vérifier le lien webdriver."""
    if driver is None:
        return False
    try:
        _ = driver.current_url  # accès trivial qui échoue si le webdriver est mort
        return True
    except Exception:
        return False


def restart_driver(driver):
    """Ferme proprement (best-effort) puis relance un driver neuf. Retourne le nouveau."""
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass
    print("\n♻️  Redémarrage Selenium (driver neuf)...")
    return scraper.setup_driver()


# ──────────────────────────────────────────────────────────────────────────
#  Traitement d'UN secteur
# ──────────────────────────────────────────────────────────────────────────
def append_csv_to(src, dst):
    """Append les lignes de src (avec header) à dst.

    Écrit le header dans dst s'il n'existe pas ou est vide. Ignore le header
    des appends suivants. Ajoute une colonne 'Département' automatiquement
    si absente pour tracer d'où vient chaque ligne (utile en mode all-France).
    """
    with open(src, "r", encoding="utf-8", newline="") as fsrc:
        reader = csv.reader(fsrc)
        try:
            header = next(reader)
        except StopIteration:
            return 0
        rows = list(reader)

    dst_exists = os.path.exists(dst) and os.path.getsize(dst) > 0
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    mode = "a" if dst_exists else "w"
    with open(dst, mode, encoding="utf-8", newline="") as fdst:
        writer = csv.writer(fdst)
        if not dst_exists:
            writer.writerow(header)
        writer.writerows(rows)
    return len(rows)


def process_sector(driver, dept, secteur, append_to=None):
    """Pipeline complet pour (dept, secteur). Retourne (ok, rows).

    Si `append_to` est fourni, les lignes nettoyées sont APPENDÉES à ce fichier
    au lieu d'être copiées vers db/{dept}/{secteur}.csv. Utilisé par le mode
    --single-secteur / --all-france pour agréger un CSV unique.
    """
    secteur_slug = slugify_secteur(secteur)
    raw = os.path.join(config.WORK_DIR, config.RAW_CSV)
    enriched = os.path.join(config.WORK_DIR, config.ENRICHED_CSV)
    final = os.path.join(config.WORK_DIR, config.FINAL_CSV)
    cleaned_name = f"{secteur_slug}.csv"
    cleaned = os.path.join(config.WORK_DIR, cleaned_name)

    # Dossier db/{dept}/ créé UNIQUEMENT en cas de succès (étape 5), pour éviter
    # de laisser des dossiers vides trompeurs quand tous les secteurs échouent.
    dept_db_dir = os.path.join(config.DB_DIR, dept)
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

    # 5a. Mode single-secteur / all-France : append au CSV agrégé
    if append_to:
        n_appended = append_csv_to(cleaned, append_to)
        total_size = os.path.getsize(append_to)
        print(f"   ✅ Appendé {n_appended} lignes à {append_to} (total {total_size} octets)")
        return True, rows

    # 5b. Mode standard : move atomique vers db/{dept}/{secteur}.csv
    os.makedirs(dept_db_dir, exist_ok=True)
    shutil.copy2(cleaned, db_target_tmp)
    os.replace(db_target_tmp, db_target)
    size = os.path.getsize(db_target)
    print(f"   ✅ Résultat final : {db_target} ({size} octets)")

    return True, rows


# ──────────────────────────────────────────────────────────────────────────
#  Mode SINGLE-SECTEUR / ALL-FRANCE — un secteur × tous les dépts → 1 CSV
# ──────────────────────────────────────────────────────────────────────────
def load_single_progress(state_file):
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_single_progress(state_file, progress):
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    tmp = state_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)
    os.replace(tmp, state_file)


def main_single_secteur(secteur, output_file, depts, retry_failed):
    """Scrape UN SEUL secteur sur une LISTE de départements et concatène dans
    un unique CSV agrégé. State dans state/single_<slug>_<output>.json.
    """
    config.ensure_dirs()
    output_file = os.path.abspath(output_file)
    slug = slugify_secteur(secteur)
    out_basename = os.path.splitext(os.path.basename(output_file))[0]
    state_file = os.path.join(config.STATE_DIR, f"single_{slug}_{out_basename}.json")

    progress = load_single_progress(state_file)

    print("=" * 64)
    print(f"  PIPELINE SINGLE — secteur '{secteur}' × {len(depts)} dépts")
    print(f"  Sortie agrégée : {output_file}")
    print(f"  État           : {state_file}")
    print("=" * 64)

    driver = None
    sectors_since_restart = 0
    try:
        for dept in depts:
            print("\n" + "─" * 64)
            print(f"▶️  {dept} / {secteur}")
            print("─" * 64)

            status = progress.get(dept, {}).get("status")
            if status == "done":
                print(f"  ⏭️  déjà fait, skip.")
                continue
            if status == "failed" and not retry_failed:
                print(f"  ⏭️  en échec (relancer avec --retry-failed).")
                continue

            # Résilience driver
            if driver is not None and sectors_since_restart >= RESTART_DRIVER_EVERY_N_SECTORS:
                print(f"♻️  Recyclage préventif ({sectors_since_restart} sectors).")
                driver = restart_driver(driver)
                sectors_since_restart = 0
            if driver is not None and not is_driver_alive(driver):
                print("💀 Driver mort — recréation.")
                driver = restart_driver(driver)
                sectors_since_restart = 0
            if driver is None:
                print("🚀 Démarrage Selenium...")
                driver = scraper.setup_driver()
                sectors_since_restart = 0

            progress[dept] = {"status": "in_progress", "updated_at": datetime.now().isoformat(timespec="seconds")}
            save_single_progress(state_file, progress)

            try:
                ok, rows = process_sector(driver, dept, secteur, append_to=output_file)
                progress[dept] = {
                    "status": "done" if ok else "failed",
                    "rows": rows,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
                save_single_progress(state_file, progress)
                print(f"  {'🎉' if ok else '⚠️'} {dept}/{secteur} : {rows} lignes")
                sectors_since_restart += 1
            except subprocess.CalledProcessError as e:
                progress[dept] = {"status": "failed", "updated_at": datetime.now().isoformat(timespec="seconds")}
                save_single_progress(state_file, progress)
                print(f"  ⚠️ {dept}/{secteur} : sous-script en échec ({e}).")
                sectors_since_restart += 1
            except Exception as e:
                progress[dept] = {"status": "failed", "updated_at": datetime.now().isoformat(timespec="seconds")}
                save_single_progress(state_file, progress)
                print(f"  ⚠️ {dept}/{secteur} : erreur inattendue ({e}).")
                if is_dead_driver_error(e) or not is_driver_alive(driver):
                    print("  💀 Driver mort — recréation.")
                    driver = restart_driver(driver)
                    sectors_since_restart = 0
                else:
                    sectors_since_restart += 1
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
    print("  BILAN SINGLE-SECTEUR")
    print("=" * 64)
    done = [d for d, e in progress.items() if e.get("status") == "done"]
    failed = [d for d, e in progress.items() if e.get("status") == "failed"]
    total_lines_out = 0
    if os.path.exists(output_file):
        with open(output_file, "r", encoding="utf-8") as f:
            total_lines_out = sum(1 for _ in f) - 1  # -1 pour le header
    print(f"  ✅ {len(done)} départements OK, ⚠️ {len(failed)} en échec")
    print(f"  📊 {total_lines_out} lignes dans {output_file}")
    if failed:
        print(f"  ↻ Retenter les échecs : ajouter --retry-failed à la commande")


# ──────────────────────────────────────────────────────────────────────────
#  Boucle principale — dispatch entre les 2 modes
# ──────────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()

    # Mode single-secteur / all-France
    if args["single_secteur"]:
        if not args["output"]:
            print("❌ --single-secteur requiert --output <chemin/fichier.csv>")
            sys.exit(1)
        if args["all_france"]:
            depts = list(ALL_FR_DEPTS)
        elif args["depts_override"]:
            depts = args["depts_override"]
        else:
            print("❌ --single-secteur requiert --all-france ou --depts <liste>")
            sys.exit(1)
        return main_single_secteur(
            args["single_secteur"], args["output"], depts, args["retry_failed"]
        )

    # Mode standard : departements.txt × secteur.txt → db/{dept}/{secteur}.csv
    return main_standard(retry_failed=args["retry_failed"])


def main_standard(retry_failed):
    config.ensure_dirs()

    depts = load_departements()
    secteurs = scraper.load_secteurs()
    progress = load_progress()

    print("=" * 64)
    print(f"  PIPELINE — {len(depts)} départements × {len(secteurs)} secteurs = "
          f"{len(depts) * len(secteurs)} unités de travail")
    print("=" * 64)

    driver = None
    sectors_since_restart = 0
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

                # A. Restart préventif toutes les N sectors — évite les fuites Chrome
                if driver is not None and sectors_since_restart >= RESTART_DRIVER_EVERY_N_SECTORS:
                    print(f"\n♻️  {sectors_since_restart} sectors depuis le dernier restart — recyclage.")
                    driver = restart_driver(driver)
                    sectors_since_restart = 0

                # B. Vérif liveness — si le webdriver est mort, on le recrée
                if driver is not None and not is_driver_alive(driver):
                    print("\n💀 Driver Selenium mort détecté — recréation.")
                    driver = restart_driver(driver)
                    sectors_since_restart = 0

                # C. Lazy start
                if driver is None:
                    print("\n🚀 Démarrage Selenium...")
                    driver = scraper.setup_driver()
                    sectors_since_restart = 0

                mark_sector(progress, dept, secteur_slug, "in_progress")

                try:
                    ok, rows = process_sector(driver, dept, secteur)
                    if ok:
                        mark_sector(progress, dept, secteur_slug, "done", rows)
                        print(f"  🎉 {dept}/{secteur} : {rows} lignes brutes → OK")
                    else:
                        mark_sector(progress, dept, secteur_slug, "failed", rows)
                        print(f"  ⚠️ {dept}/{secteur} : échec, on continue.")
                    sectors_since_restart += 1
                except subprocess.CalledProcessError as e:
                    mark_sector(progress, dept, secteur_slug, "failed")
                    print(f"  ⚠️ {dept}/{secteur} : sous-script en échec ({e}).")
                    sectors_since_restart += 1
                except Exception as e:
                    mark_sector(progress, dept, secteur_slug, "failed")
                    print(f"  ⚠️ {dept}/{secteur} : erreur inattendue ({e}).")
                    # Driver mort ? recréer avant le prochain sector au lieu
                    # d'enchaîner 100 échecs identiques.
                    if is_dead_driver_error(e) or not is_driver_alive(driver):
                        print("  💀 Le driver semble mort — recréation avant le prochain sector.")
                        driver = restart_driver(driver)
                        sectors_since_restart = 0
                    else:
                        sectors_since_restart += 1
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
