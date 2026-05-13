#!/usr/bin/env python3
# run.py - Lance les deux scripts automatiquement

import subprocess
import time
import sys

# Étape 1: scraper.py avec choix "1"
print("=" * 40)
print("ÉTAPE 1: scraper.py")
print("=" * 40)

# Envoyer "1" et Enter à scraper.py
result1 = subprocess.run(
    [sys.executable, "scraper.py"],
    input="1\n",
    text=True,
    capture_output=False
)

# Pause de 10 secondes
print("\n⏱ Pause de 10 secondes...")
time.sleep(10)

# Étape 2: dirigeant.py avec choix "1" puis "o"
print("\n" + "=" * 40)
print("ÉTAPE 2: dirigeant.py")
print("=" * 40)

# Envoyer "1" puis Enter, puis "o" puis Enter
result2 = subprocess.run(
    [sys.executable, "dirigeant.py"],
    input="1\no\n",
    text=True,
    capture_output=False
)

print("\n✅ Terminé!")