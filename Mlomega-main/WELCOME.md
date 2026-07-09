# Bienvenue — installer et lancer MLOmega V19

Tu débutes ? **Lance l'assistant, laisse-toi guider** — il fait tout dans l'ordre
(scan matériel, modèles, tokens, installation, lancement, téléphone, entretien) :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\WELCOME_MLOMEGA.ps1
```

- **Voir le déroulé sans rien installer** (recommandé une première fois) :
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\WELCOME_MLOMEGA.ps1 -DryRun
  ```
- **Non interactif** (valeurs sûres par défaut) : ajoute `-Defaults`.

L'assistant n'installe rien lui-même : il **orchestre** les scripts du projet
(`INSTALL_MLOMEGA_V19_WINDOWS.ps1`, `setup_profile.ps1`, `fetch_models_v19.py`,
`START_QDRANT.ps1`, `RUN_MLOMEGA_V19.ps1`, `DOCTOR`) en posant d'abord les bonnes
questions. Chaque étape est idempotente : en cas de souci, il te dit quoi faire et
tu peux relancer.

Pour le détail complet (prérequis, architecture, dépannage) : voir
[`README.md`](README.md) et [`FIRST_TRY_ANDROID.md`](FIRST_TRY_ANDROID.md).
