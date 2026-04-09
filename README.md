# 🏀 Roma Basket Casa

Web App PWA per monitorare le partite in casa di Virtus Roma e LUISS Roma (Serie B Nazionale).

## 🌐 Link all'App
Apri l'app qui: **[https://bad-think.github.io/basket-roma/](https://bad-think.github.io/basket-roma/)**

## 📱 Installazione su Android
1. Apri il link sopra in Chrome.
2. Tocca i tre puntini (⋮) e seleziona **"Aggiungi a schermata Home"**.
3. L'app apparirà tra le tue applicazioni e funzionerà anche offline.

## 🛠️ Note Tecniche
- **Sincronizzazione**: Lo script in `scripts/update_data.py` gira ogni sera per aggiornare i risultati.
- **Cache**: Utilizza un Service Worker per caricare i dati istantaneamente.
- **Validazione**: Se lo scraping fallisce, il sistema protegge i dati esistenti e invia un'email di alert tramite GitHub Actions.
