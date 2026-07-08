# Memory Dashboard — MLOmega V19 (lecture seule)

Dashboard Streamlit **une page** pour lire la base `memory.db` du projet : ce que la
mémoire produit (hypothèses, modèle de vie, prédictions vérifiées, preuves
visuelles, zones/routines, sessions et close-days) — idéal pour le debug et pour
lire le résultat d'une session réelle après le close-day.

Adapté de MemoryLight Dashboard 2.0 (E50, 2026-07-08) : mêmes principes —
**lecture seule stricte** (SQLite ouvert en `mode=ro`, aucune requête
INSERT/UPDATE/DELETE), les rares interactions passent par la CLI officielle du
cœur et sont verrouillées derrière la saisie du mot `ECRIRE`.

## Lancement (le plus simple)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\RUN_DASHBOARD.ps1
```

Le script installe streamlit/pandas dans `.venv-live` s'ils manquent, lit
`MLOMEGA_DB` depuis le `.env` du projet, et sert sur **http://localhost:8720**.

> Port **8720** — choisi pour ne pas entrer en collision avec le projet :
> 8710 (SessionHub), 6333/6334 (Qdrant), 11434 (Ollama), 8766 (Phone Bridge,
> interdit), 8704/8706 (profils sim), 8776, 8601.

## Lancement manuel

```powershell
$env:MLOMEGA_DB="C:\chemin\vers\memory.db"   # sinon lu depuis le .env du projet
.venv-live\Scripts\python -m streamlit run apps\memory-dashboard\app.py
# options : -- --db <chemin> --person-id me --limit 14
```

## Ce que la page affiche

1. Métriques globales, self-model, bloc « Aujourd'hui », panneau
   sûr/hypothèse/prédiction, score de fiabilité, timeline — hérités de MemoryLight.
2. **🛰️ Bloc V19** (nouveau, E50) :
   - compteurs live (événements visuels, interventions, receipts, prédictions…) ;
   - hypothèses E38 — en attente / auto-confirmées / réfutées, avec preuves ;
   - Life Model V19 — entrées typées, self-schema, prédictions +
     `verification_spec` + outcomes (vérifiées/réfutées) + calibration ;
   - événements visuels + chaîne de preuve (asset, sha256) ;
   - entités/lieux/routines WorldBrain (`brain2_spatial_routine_models`,
     `scene_session_summaries_v19`) ;
   - sessions live + close-day runs (statut `reopened` des multi-sessions inclus).
3. Chat mémoire (`v14-ask` — toujours valide dans la CLI actuelle du cœur, routé
   sur `ask_brain2`), recherche globale, vue preuves, toutes les tables en
   sections pliables, debug brut.

Toute table absente de la base s'affiche « absent » — jamais une erreur.

## Sécurité

- Base ouverte `file:...?mode=ro` ; le dashboard n'écrit jamais directement.
- Les seules actions modificatrices possibles sont `v14-answer` (répondre à une
  clarification) et `v14-intervention-feedback`, via la CLI du cœur
  (`python -m mlomega_audio_elite.cli`), désactivées tant que le verrou `ECRIRE`
  n'est pas saisi dans la barre latérale.
