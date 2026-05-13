# 🚀 Déploiement du Scraper sur VPS Debian/Ubuntu

Ce guide détaille toutes les étapes pour configurer un VPS (Debian 11/12 ou Ubuntu), installer les dépendances nécessaires pour Selenium, et lancer le scraper pour qu'il tourne en arrière-plan sans interruption.

---

## 🛠️ 1. Connexion initiale au VPS

Ouvrez un terminal sur votre ordinateur local (ou PuTTY sur Windows) et connectez-vous au serveur :

```bash
ssh root@<IP_DE_VOTRE_VPS>
```

Une fois connecté, mettez à jour la machine :
```bash
apt update && apt upgrade -y
```

---

## 📦 2. Installation des dépendances systèmes

Le scraper a besoin de Python, de Google Chrome et de quelques autres outils pour tourner en mode "Headless".

**A. Installez les outils de base et Python :**
```bash
apt install wget curl unzip python3 python3-pip tmux -y
```

**B. Installez Google Chrome officiel :**
```bash
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt install -y ./google-chrome-stable_current_amd64.deb
rm google-chrome-stable_current_amd64.deb
```

---

## 📂 3. Récupération du code sur le VPS

Vous n'avez plus besoin de transférer les fichiers manuellement via FileZilla.
Clonons directement le dépôt GitHub :

```bash
cd ~
git clone https://github.com/Yassineaz1/yellow-loop.git
cd yellow-loop
```

L'architecture est maintenant unifiée et autonome :
```text
~/yellow-loop/
├── scraper.py
├── secteur.txt
├── requirements.txt
└── enrichement-scrappy/
    ├── scraper.py
    ├── dirigeant.py
    └── cleaner.py
```

---

## 🐍 4. Installation des dépendances Python

Installez toutes les dépendances requises d'un seul coup :

```bash
pip3 install -r requirements.txt
```

---

## 🚀 5. Lancement du script en continu (avec Tmux)

Pour que le script continue de tourner même si vous éteignez votre ordinateur, nous allons utiliser `tmux` (un terminal virtuel).

**1. Créez une nouvelle session virtuelle nommée "scraper" :**
```bash
tmux new -s scraper
```

**2. Lancez le script :**
```bash
python3 scraper.py
```
*Le script va vous demander d'entrer le numéro du département (ex: 67). Entrez-le et validez.*

**3. Détachez-vous de la session pour laisser tourner :**
Faites la combinaison clavier suivante :
- Appuyez sur **`Ctrl` + `B`**
- Relâchez les touches
- Appuyez sur **`D`** (comme Detach)

Vous revenez sur votre terminal principal. **Vous pouvez maintenant fermer votre fenêtre SSH (ou éteindre votre PC)**, le scraper tourne toujours sur le serveur !

---

## 👀 6. Revenir voir l'avancement

Si vous vous reconnectez plus tard à votre VPS et voulez voir où en est l'extraction, tapez simplement :

```bash
tmux attach -t scraper
```

*Pour ressortir sans couper le script, refaites `Ctrl + B` puis `D`.*

---

## 📥 7. Récupérer les fichiers finaux

Une fois le processus totalement terminé (Scraping initial + SIRET + Pappers + Nettoyage), le fichier nettoyé sera créé dans le dossier `enrichement-scrappy` sous le nom de votre département (ex: `67.csv`).

Ouvrez **FileZilla / WinSCP**, connectez-vous au VPS, allez dans `/root/scraper/enrichement-scrappy/` et téléchargez le fichier CSV sur votre ordinateur !
