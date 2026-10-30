"""
Filtre "hébergements indépendants hors centre-ville" (prospection solaire).

Appliqué sur work/input.csv juste après le scraping PagesJaunes, AVANT
l'enrichissement SIRET/Pappers (l'étape lente) :
  1. exclut les chaînes et franchises (Accor, Brit Hotel, Best Western...)
  2. exclut les doublons déjà présents dans le CSV de sortie
  3. géolocalise l'adresse (Géoplateforme IGN, repli sur api-adresse)
  4. calcule la distance à la mairie de la commune (geo.api.gouv.fr)
  5. garde seulement les établissements hors centre-ville

Les lignes gardées reçoivent 4 colonnes qui suivent jusqu'au CSV final :
Latitude, Longitude, Distance_centre_km, Population_commune.
"""
import csv
import json
import math
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request

# ──────────────────────────────────────────────────────────────────────────
#  Chaînes / franchises exclues (comparaison sans accents, minuscules)
# ──────────────────────────────────────────────────────────────────────────
CHAIN_PATTERNS = [
    # Accor
    r"\bibis\b", r"\bnovotel\b", r"\bsuite ?novotel\b", r"\bmercure\b", r"\bpullman\b",
    r"\bsofitel\b", r"\bmgallery\b", r"\badagio\b", r"\bhotel ?f1\b", r"\bformule ?1\b",
    r"\bmama shelter\b", r"\bjo ?& ?joe\b", r"\bgreet\b", r"\btribe\b", r"\bswissotel\b",
    r"\bfairmont\b", r"\bmovenpick\b", r"\bmantis\b", r"\b25 ?hours\b", r"\baccor\b",
    # Brit Hotel
    r"\bbrit ?hotel\b",
    # Louvre Hotels
    r"\bcampanile\b", r"\bkyriad\b", r"\bpremiere classe\b", r"\bgolden tulip\b",
    r"\btulip inn\b", r"\broyal tulip\b",
    # Autres réseaux / franchises
    # (pas de "b&b" ni "logis" seuls : trop de chambres d'hôtes indépendantes
    #  s'appellent "B&B ..." ou "Le Logis de ...")
    r"\bbest ?western\b", r"\bb ?& ?b hotels?\b", r"\blogis hotels?\b", r"\bfasthotel\b",
    r"\bfast hotel\b", r"\bthe originals\b", r"\binter[- ]?hotel\b", r"\bcitotel\b",
    r"\bhotel ?premiere\b", r"\bquality (hotel|suites|inn)\b", r"\bcomfort (hotel|suites|inn)\b",
    r"\bclarion\b", r"\bholiday inn\b", r"\bcrowne plaza\b", r"\bintercontinental\b",
    r"\bhilton\b", r"\bdoubletree\b", r"\bhampton by hilton\b", r"\bmarriott\b",
    r"\bresidence inn\b", r"\bsheraton\b", r"\bradisson\b", r"\bpark inn\b",
    r"\bnemea\b", r"\bodalys\b", r"\bpierre ?& ?vacances\b", r"\bappart'?city\b",
    r"\bstudeo\b", r"\bsejours ?& ?affaires\b", r"\bmister bed\b", r"\bballadins\b",
    r"\bonestay\b", r"\bzenitude\b", r"\bkopster\b", r"\bokko\b", r"\bhappyculture\b",
    r"\bp'?tit dej'? hotel\b", r"\bastotel\b", r"\bvacanceole\b",
]
_CHAIN_RE = re.compile("|".join(CHAIN_PATTERNS))

# Rayon du "centre-ville" selon la population de la commune (km)
CENTRE_RADIUS_BY_POP = [
    (2_000, 0.5),
    (10_000, 1.0),
    (50_000, 2.0),
    (200_000, 3.0),
    (float("inf"), 5.0),
]

# Arrondissements de Paris / Lyon / Marseille : toujours considérés urbains
_URBAN_CITYCODE_RE = re.compile(r"^(751\d\d|6938\d|132\d\d)$")

USER_AGENT = "yellow-loop/1.0 (prospection)"
GEOCODERS = [
    "https://data.geopf.fr/geocodage/search",
    "https://api-adresse.data.gouv.fr/search/",
]

_commune_cache = {}


def _norm(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def is_chain(name):
    return bool(_CHAIN_RE.search(_norm(name)))


def row_key(row):
    link = (row.get("Lien détaillé") or "").strip()
    if link:
        return link
    name = _norm(row.get("Nom de l'entreprise", ""))
    cp = (row.get("Code Postal") or "").strip()
    return f"{name}|{cp}"


def _get_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def geocode(address, postcode):
    """Retourne (lat, lon, citycode, type) ou None."""
    params = {"q": address, "limit": 1}
    if postcode:
        params["postcode"] = postcode
    qs = urllib.parse.urlencode(params)
    for base in GEOCODERS:
        try:
            data = _get_json(f"{base}?{qs}")
            feats = data.get("features") or []
            if not feats:
                return None
            f = feats[0]
            if (f.get("properties", {}).get("score") or 0) < 0.4:
                return None
            lon, lat = f["geometry"]["coordinates"]
            props = f["properties"]
            return lat, lon, props.get("citycode"), props.get("type")
        except Exception:
            continue
    return None


def commune_info(citycode):
    """Retourne (lat_centre, lon_centre, population) via geo.api.gouv.fr (cache)."""
    if citycode in _commune_cache:
        return _commune_cache[citycode]
    info = None
    for fields in ("nom,centre,population,mairie", "nom,centre,population"):
        try:
            data = _get_json(f"https://geo.api.gouv.fr/communes/{citycode}?fields={fields}")
            point = data.get("mairie") or data.get("centre")
            if point and point.get("coordinates"):
                lon, lat = point["coordinates"]
                info = (lat, lon, data.get("population") or 0)
            break
        except Exception:
            continue
    _commune_cache[citycode] = info
    return info


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def centre_radius_km(population):
    for max_pop, radius in CENTRE_RADIUS_BY_POP:
        if population < max_pop:
            return radius
    return 5.0


def load_seen_keys(output_file):
    seen = set()
    if output_file and os.path.exists(output_file):
        with open(output_file, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                seen.add(row_key({(k or "").lstrip("﻿"): v for k, v in row.items()}))
    return seen


def filter_independent_outskirts(raw_csv, seen_keys):
    """Filtre raw_csv en place. Retourne le nombre de lignes gardées."""
    with open(raw_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    stats = {"total": len(rows), "chaine": 0, "doublon": 0, "centre": 0,
             "non_localise": 0, "garde": 0}
    extra = ["Latitude", "Longitude", "Distance_centre_km", "Population_commune"]
    kept = []
    batch_keys = set()

    for row in rows:
        if is_chain(row.get("Nom de l'entreprise", "")):
            stats["chaine"] += 1
            continue
        key = row_key(row)
        if key in seen_keys or key in batch_keys:
            stats["doublon"] += 1
            continue

        address = " ".join(x for x in (row.get("Adresse"), row.get("Code Postal"), row.get("Ville")) if x)
        geo = geocode(address, (row.get("Code Postal") or "").strip()) if address else None
        time.sleep(0.05)
        # Résultat au niveau "commune" = coordonnées du centre de la commune :
        # inexploitable pour juger centre/périphérie → traité comme non localisé.
        if geo and geo[3] == "municipality":
            geo = None

        if not geo:
            # Non localisé : gardé par défaut (mieux vaut un faux positif qu'un prospect perdu)
            stats["non_localise"] += 1
            row.update({k: "" for k in extra})
            kept.append(row)
            batch_keys.add(key)
            continue

        lat, lon, citycode, rtype = geo
        if citycode and _URBAN_CITYCODE_RE.match(citycode):
            stats["centre"] += 1
            continue

        info = commune_info(citycode) if citycode else None
        if info:
            dist = haversine_km(lat, lon, info[0], info[1])
            pop = info[2]
            # lieu-dit = hors bourg par définition
            if rtype != "locality" and dist < centre_radius_km(pop):
                stats["centre"] += 1
                continue
            row.update({"Latitude": f"{lat:.6f}", "Longitude": f"{lon:.6f}",
                        "Distance_centre_km": f"{dist:.2f}", "Population_commune": str(pop)})
        else:
            row.update({"Latitude": f"{lat:.6f}", "Longitude": f"{lon:.6f}",
                        "Distance_centre_km": "", "Population_commune": ""})
        kept.append(row)
        batch_keys.add(key)

    stats["garde"] = len(kept)
    with open(raw_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames + extra, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)

    print(f"   🧭 Filtre hors centre : {stats['total']} fiches → {stats['garde']} gardées "
          f"(chaînes {stats['chaine']}, doublons {stats['doublon']}, centre-ville {stats['centre']}, "
          f"non localisées gardées {stats['non_localise']})")
    return len(kept)
