# PnL Cards

Journal de trading memecoins **local et open source**. Glisse tes PNL cards (Terminal, Axiom, GMGN), ou connecte ton wallet Solana : tout est lu, classé et analysé sur ton ordinateur.

**Démo : [pnl.tradeblanks.com](https://pnl.tradeblanks.com)** (données fictives) · Interface en français et en anglais (bouton FR / EN).

> **English:** local, open-source memecoin trading journal. Drop Terminal / Axiom / GMGN PnL cards (OCR) or connect your public Solana wallet address; get a dashboard, journal with entry/exit market cap, holding time and stats. Everything stays on your machine. Run `start.bat` (Windows) or `./start.sh`, and switch the UI to English with the EN button.

## Ce que ça fait

- **Lecture des cartes** : l'OCR lit les images PNL de Terminal, Axiom et GMGN (token, PnL, investi, %), avec des contrôles de cohérence.
- **Wallet** : colle l'adresse publique de ton wallet, l'app reconstruit chaque trade (achats, ventes, heure, durée de détention). Clé Helius facultative.
- **Dashboard** : courbe de capital, calendrier, objectif du jour, résultat par jour / semaine / mois / plateforme, durée de détention.
- **Journal** : tous les trades d'un jour ou d'une période, avec tags, notes, market cap d'entrée et de sortie, montant investi et reçu, heure, multiple et bénéfice calculés automatiquement.
- **Import / export** : CSV et Google Sheets.
- **Tes données restent chez toi** : images et trades sont stockés dans le dossier `data/`.

## Installation (Windows)

1. Installe [Python 3.10+](https://www.python.org/downloads/) et [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) (`winget install UB-Mannheim.TesseractOCR`).
2. Télécharge ce dépôt (Code, puis Download ZIP) et décompresse-le.
3. Double-clique sur `start.bat`. L'app s'ouvre sur http://127.0.0.1:5173.

Mac / Linux : installe Tesseract (`brew install tesseract` ou `apt install tesseract-ocr`), puis lance `./start.sh`.

## Connecter son wallet

Terminal, Axiom et GMGN trade tous on-chain : l'adresse publique de ton wallet suffit.

- Onglet **Wallet**, colle l'adresse (Terminal : Wallet, copie l'adresse).
- **Sans clé** : lecture des 300 dernières transactions par les serveurs publics de Solana (plus lent).
- **Avec une clé [Helius](https://helius.dev) gratuite** : tout l'historique, bien plus vite.

Lecture seule : l'application refuse les phrases secrètes et les clés privées. L'adresse et la clé ne servent qu'à interroger Solana / Helius depuis ton ordinateur.

## Limites connues

- Les frais réseau et les frais du terminal sont inclus dans le PnL calculé depuis le wallet.
- Un trade est considéré comme fermé quand il reste moins de 2 % de la position.
- Le résultat de la lecture par le wallet dépend des réponses de Helius ou du serveur RPC public (rate limit possible).

## Licence

MIT, voir [LICENSE](LICENSE).
