import time
import csv
import os
import re
import random
import base64
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from bs4 import BeautifulSoup
import subprocess
import shutil

def random_sleep(min_s=2, max_s=5):
    time.sleep(random.uniform(min_s, max_s))

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    if os.name != "nt":  # Linux/VPS uniquement
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Options pour passer inaperçu
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument('--log-level=3')  # Supprime les logs d'erreurs de Chrome
    
    # Disable images and stylesheets for speed
    prefs = {
        'profile.managed_default_content_settings.images': 2,
        'profile.managed_default_content_settings.stylesheets': 2,
    }
    chrome_options.add_experimental_option('prefs', prefs)
    
    try:
        # Selenium Manager (Selenium 4.6+) — détecte l'OS automatiquement
        driver = webdriver.Chrome(options=chrome_options)
    except Exception:
        # Fallback : webdriver-manager avec nettoyage du cache
        cache_dir = os.path.join(os.path.expanduser("~"), ".wdm")
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir, ignore_errors=True)
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def handle_cookie_banner(driver):
    """Handles the cookie banner on PagesJaunes"""
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            try:
                title = iframe.get_attribute("title") or ""
                src = iframe.get_attribute("src") or ""
                if "consent" in title.lower() or "consent" in src.lower():
                    driver.switch_to.frame(iframe)
                    accept_btn = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.ID, "appconsent-accept-all"))
                    )
                    driver.execute_script("arguments[0].click();", accept_btn)
                    driver.switch_to.default_content()
                    print("✅ Cookies acceptés.")
                    return True
            except:
                driver.switch_to.default_content()
        
        # Fallback for non-iframe banners
        accept_btn = driver.find_elements(By.ID, "appconsent-accept-all")
        if not accept_btn:
            accept_btn = driver.find_elements(By.ID, "didomi-notice-agree-button")
        if accept_btn:
            driver.execute_script("arguments[0].click();", accept_btn[0])
            print("✅ Cookies acceptés (main).")
            return True
    except:
        pass
    finally:
        driver.switch_to.default_content()
    return False

def parse_address(raw_addr):
    """Extracts (Address, Zip, City) from raw address string"""
    if not raw_addr: return "", "", ""
    # Example: '4 route Lion 14150 Ouistreham'
    zip_match = re.search(r"\b(\d{5})\b", raw_addr)
    if zip_match:
        zip_code = zip_match.group(1)
        parts = raw_addr.split(zip_code)
        addr = parts[0].strip()
        city = parts[1].strip() if len(parts) > 1 else ""
        return addr, zip_code, city
    return raw_addr, "", ""

def scrape_pagesjaunes():
    # Version Universelle - Trouve les dossiers relatifs à l'emplacement du script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = base_dir
    secteur_file = os.path.join(output_dir, "secteur.txt")
    output_file = os.path.join(output_dir, "raw_results_pro.csv")
    
    os.makedirs(output_dir, exist_ok=True)
    
    if not os.path.exists(secteur_file):
        print(f"❌ Le fichier {secteur_file} est introuvable.")
        return
        
    with open(secteur_file, "r", encoding="utf-8") as f:
        secteurs = [line.strip() for line in f if line.strip()]

    if not secteurs:
        print("❌ Le fichier secteur.txt est vide.")
        return

    department = input("Veuillez entrer le département (ex: 67) : ")
    print(f"🚀 Début du scraping pour {len(secteurs)} secteurs dans le département {department}...")

    # Prepare CSV file with headers
    keys = ["Nom de l'entreprise", "Activité", "Téléphone", "Adresse", "Code Postal", "Ville", "Département", "Lien détaillé"]
    if not os.path.exists(output_file):
        with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()

    driver = setup_driver()
    try:
        for secteur in secteurs:
            print(f"\n🔍 Recherche de: {secteur} dans le {department}...")
            driver.get("https://www.pagesjaunes.fr/")
            random_sleep(2, 4)
            handle_cookie_banner(driver)
            
            try:
                wait = WebDriverWait(driver, 10)
                q_input = wait.until(EC.presence_of_element_located((By.ID, "quoiqui")))
                o_input = driver.find_element(By.ID, "ou")
                submit = driver.find_element(By.ID, "findId")
                
                q_input.clear()
                q_input.send_keys(secteur)
                o_input.clear()
                o_input.send_keys(department)
                random_sleep(0.5, 1.5)
                driver.execute_script("arguments[0].click();", submit)
                
                page_num = 1
                while True:
                    print(f"  📄 {secteur} - Page {page_num}...")
                    random_sleep(3, 6)
                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    items = soup.select("li.bi")
                    
                    if not items: 
                        print("  ⚠️ Aucun résultat détecté sur cette page.")
                        break
                    
                    sel_items = driver.find_elements(By.CSS_SELECTOR, "li.bi")
                    def decode_pjlb(element):
                        try:
                            pj_data = json.loads(element['data-pjlb'])
                            url_b64 = pj_data.get("url")
                            if url_b64:
                                return "https://www.pagesjaunes.fr" + base64.b64decode(url_b64).decode("utf-8")
                        except:
                            pass
                        return ""

                    def href_to_url(href):
                        if not href:
                            return ""
                        if href.startswith('/'):
                            return "https://www.pagesjaunes.fr" + href
                        if href.startswith('http'):
                            return href
                        return ""

                    page_data = []
                    for i, item_soup in enumerate(items):
                        try:
                            # Extraction Nom
                            raw_name_tag = item_soup.select_one("h3, .bi-denomination")
                            nom = raw_name_tag.get_text(strip=True) if raw_name_tag else ""

                            # ── LIEN DÉTAILLÉ ──────────────────────────────────────
                            # Stratégie 0 : id du li.bi = "bi-XXXXXXXX" → URL propre /pros/XXXXXXXX
                            lien_detaille = ""
                            li_id = item_soup.get('id', '')
                            if li_id.startswith('bi-'):
                                epj = li_id[3:]
                                if epj.isdigit():
                                    lien_detaille = f"https://www.pagesjaunes.fr/pros/{epj}"

                            # Fallback : a.bi-denomination href ou data-pjlb
                            if not lien_detaille:
                                a_tag = item_soup.select_one("a.bi-denomination")
                                if not a_tag:
                                    a_tag = item_soup.select_one("a[href*='/pros/']")
                                if a_tag:
                                    if 'data-pjlb' in a_tag.attrs:
                                        lien_detaille = decode_pjlb(a_tag)
                                    if not lien_detaille:
                                        lien_detaille = href_to_url(a_tag.get('href', ''))

                            # Extraction Activité
                            activity_tag = item_soup.select_one(".bi-activity-unit")
                            activite = activity_tag.get_text(strip=True) if activity_tag else secteur

                            # Extraction Adresse
                            raw_addr = item_soup.select_one(".bi-address")
                            raw_addr = raw_addr.get_text(strip=True) if raw_addr else ""
                            if "Voir le plan" in raw_addr:
                                raw_addr = raw_addr.replace("Voir le plan", "").strip()
                            addr, cp, ville = parse_address(raw_addr)

                            # ── TÉLÉPHONE ──────────────────────────────────────────
                            # Structure réelle PagesJaunes : div.bi-fantomas > div.number-contact
                            # Numéro arcep : div.bi-fantomas .num-arcep
                            phone = ""

                            # Format arcep (numéro surtaxé)
                            arcep = item_soup.select_one(".bi-fantomas .num-arcep, .bi-fantomas .num.num-arcep")
                            if arcep:
                                phone = arcep.get_text(strip=True)

                            # Format standard : texte direct dans .number-contact
                            if not phone:
                                nc = item_soup.select_one(".bi-fantomas .number-contact, .number-contact")
                                if nc:
                                    raw_phone = nc.get_text(strip=True)
                                    # Extraire uniquement le numéro (regex numéro français)
                                    m = re.search(r'(\d[\d\s\.\-]{6,14}\d)', raw_phone)
                                    if m:
                                        phone = m.group(1).strip()

                            # Fallback : lien tel:
                            if not phone:
                                tel_link = item_soup.select_one("a[href^='tel:']")
                                if tel_link:
                                    phone = tel_link['href'].replace("tel:", "").strip()

                            # Fallback clic bouton si toujours rien
                            if not phone and i < len(sel_items):
                                try:
                                    btn_selectors = [
                                        "button.btn_tel", "button[class*='btn_tel']",
                                        "button[class*='tel']", "button[class*='phone']",
                                    ]
                                    btn = None
                                    for sel in btn_selectors:
                                        found = sel_items[i].find_elements(By.CSS_SELECTOR, sel)
                                        if found:
                                            btn = found[0]
                                            break
                                    if btn:
                                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                                        driver.execute_script("arguments[0].click();", btn)
                                        time.sleep(1.5)
                                        # Après clic : chercher le tel: link ou .number-contact
                                        updated_html = sel_items[i].get_attribute("outerHTML")
                                        updated_soup = BeautifulSoup(updated_html, 'html.parser')
                                        tel_after = updated_soup.select_one("a[href^='tel:']")
                                        if tel_after:
                                            phone = tel_after['href'].replace("tel:", "").strip()
                                        else:
                                            phone_elem = sel_items[i].find_elements(
                                                By.CSS_SELECTOR,
                                                ".number-contact, .numero, [class*='numero'], a[href^='tel:']"
                                            )
                                            if phone_elem:
                                                raw = phone_elem[0].get_attribute("href") or phone_elem[0].text
                                                phone = raw.replace("tel:", "").replace("Tél :", "").strip()
                                except:
                                    pass
                            
                            result = {
                                "Nom de l'entreprise": nom,
                                "Activité": activite,
                                "Téléphone": phone,
                                "Adresse": addr,
                                "Code Postal": cp,
                                "Ville": ville,
                                "Département": cp[:2] if cp else department,
                                "Lien détaillé": lien_detaille
                            }
                            page_data.append(result)
                        except Exception as e: 
                            print(f"    ⚠️ Erreur extraction item: {e}")
                    
                    # Diagnostic : compter les liens et téléphones trouvés
                    links_found = sum(1 for r in page_data if r.get("Lien détaillé"))
                    phones_found = sum(1 for r in page_data if r.get("Téléphone"))
                    total_items = len(page_data)
                    if links_found == 0 and total_items:
                        print(f"    ⚠️ ATTENTION : 0/{total_items} liens — sélecteur HTML peut-être changé")
                    else:
                        print(f"    🔗 {links_found}/{total_items} liens détaillés")
                    if phones_found == 0 and total_items:
                        print(f"    ⚠️ ATTENTION : 0/{total_items} téléphones — sélecteur HTML peut-être changé")
                    else:
                        print(f"    📞 {phones_found}/{total_items} téléphones trouvés")

                    # Save page results immediately to CSV
                    if page_data:
                        is_empty = not os.path.exists(output_file) or os.stat(output_file).st_size == 0
                        with open(output_file, "a", newline="", encoding="utf-8-sig") as f:
                            writer = csv.DictWriter(f, fieldnames=keys)
                            if is_empty:
                                writer.writeheader()
                            writer.writerows(page_data)
                        print(f"    ✅ {len(page_data)} résultats enregistrés.")

                    # Next page
                    try:
                        next_btn_elements = driver.find_elements(By.ID, "pagination-next")
                        if not next_btn_elements:
                            break
                        next_btn = next_btn_elements[0]
                        
                        if "disabled" in next_btn.get_attribute("class") or next_btn.get_attribute("aria-disabled") == "true":
                            break
                        
                        data_pjlb = next_btn.get_attribute("data-pjlb")
                        next_url = None
                        if data_pjlb:
                            try:
                                pj_data = json.loads(data_pjlb)
                                url_b64 = pj_data.get("url")
                                if url_b64:
                                    decoded_path = base64.b64decode(url_b64).decode("utf-8")
                                    next_url = "https://www.pagesjaunes.fr" + decoded_path
                            except Exception as e:
                                print(f"    ⚠️ Erreur décodage pagination: {e}")

                        if next_url:
                            print(f"    ➡️ Navigation vers page suivante...")
                            old_url = driver.current_url
                            driver.get(next_url)
                            try:
                                WebDriverWait(driver, 15).until(lambda d: d.current_url != old_url)
                                try:
                                    WebDriverWait(driver, 15).until(
                                        EC.presence_of_element_located((By.CSS_SELECTOR, "li.bi"))
                                    )
                                except:
                                    print("    ⚠️ Pas de résultats détectés, attente prolongée...")
                                    random_sleep(5, 10)
                                page_num += 1
                            except:
                                break
                        else:
                            driver.execute_script("arguments[0].click();", next_btn)
                            random_sleep(5, 8)
                            page_num += 1
                            
                    except:
                        break
                        
            except Exception as e:
                print(f"⚠️ Erreur lors de la recherche pour {secteur}: {e}")
            
            random_sleep(5, 10)
            
    finally:
        driver.quit()
        print(f"\n🏁 Scraping terminé. Données stockées dans {output_file}")

    # ==========================================
    # PIPELINE D'ENRICHISSEMENT ET DE NETTOYAGE
    # ==========================================
    enrich_dir = os.path.join(base_dir, "enrichement-scrappy")
    input_enrich_csv = os.path.join(enrich_dir, "input.csv")
    
    print("\n" + "="*60)
    print("🚀 LANCEMENT DU PIPELINE D'ENRICHISSEMENT")
    print("="*60)
    
    if not os.path.exists(enrich_dir):
        print(f"❌ Le dossier {enrich_dir} est introuvable. L'enrichissement est annulé.")
        return

    if not os.path.exists(output_file):
        print(f"❌ Le fichier source {output_file} est introuvable. L'enrichissement est annulé.")
        return

    # Copier le fichier raw vers input.csv
    try:
        shutil.copy(output_file, input_enrich_csv)
        print(f"✅ Fichier copié vers: {input_enrich_csv}")
    except Exception as e:
        print(f"❌ Erreur lors de la copie du fichier: {e}")
        return
    
    import sys
    python_cmd = "python3" if os.name != 'nt' else "python"

    # Étape 1: Exécuter scraper.py pour obtenir les SIRET/SIREN
    print("\n[1/3] Récupération des informations légales (SIRET/SIREN)...")
    try:
        subprocess.run([python_cmd, "scraper.py"], cwd=enrich_dir, input="1\n", text=True, check=True)
        
        # Vérification
        if not os.path.exists(os.path.join(enrich_dir, "output_enriched.csv")):
            print("❌ Échec : 'output_enriched.csv' n'a pas été généré.")
            return
    except Exception as e:
        print(f"⚠️ Erreur lors de l'exécution de scraper.py: {e}")
        return
    
    # Étape 2: Exécuter dirigeant.py pour obtenir les noms des dirigeants
    print("\n[2/3] Recherche des noms des dirigeants sur Pappers...")
    try:
        subprocess.run([python_cmd, "dirigeant.py"], cwd=enrich_dir, input="1\no\n", text=True, check=True)
        
        # Vérification
        if not os.path.exists(os.path.join(enrich_dir, "output_final.csv")):
            print("❌ Échec : 'output_final.csv' n'a pas été généré.")
            return
    except Exception as e:
        print(f"⚠️ Erreur lors de l'exécution de dirigeant.py: {e}")
        return
    
    # Étape 3: Exécuter cleaner.py pour nettoyer et nommer le fichier final
    print("\n[3/3] Nettoyage et formatage final...")
    dept_file_name = f"{department}.csv"
    try:
        subprocess.run([python_cmd, "cleaner.py"], cwd=enrich_dir, input=f"1\n{dept_file_name}\n", text=True, check=True)
        
        final_output = os.path.join(enrich_dir, dept_file_name)
        if os.path.exists(final_output):
            print("\n🎉 PROCESSUS COMPLET TERMINÉ !")
            print(f"📂 Le fichier final nettoyé a été créé : {final_output}")
        else:
            print(f"⚠️ Nettoyage terminé mais le fichier {dept_file_name} semble manquant.")
    except Exception as e:
        print(f"⚠️ Erreur lors de l'exécution de cleaner.py: {e}")

if __name__ == "__main__":
    scrape_pagesjaunes()
