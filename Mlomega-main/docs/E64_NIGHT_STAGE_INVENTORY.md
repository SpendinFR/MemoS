# E64-A - Inventaire des stages LLM/VLM nocturnes (matrice de contrat)

Objectif : recenser chaque appel LLM/VLM de la chaine nocturne (close-day) pour
que l'orchestrateur commun (E64) porte budget/fenetrage/reprise/couverture, et
que chaque stage n'expose que son adaptateur metier (`NightStageAdapter`). Aucun
prompt metier n'est modifie par E64-A/B ; cette page est l'etat des lieux qui
guide le fenetrage E64-C et la migration par vagues E64-F.

Package livre : `src/mlomega_audio_elite/night_orchestrator/`
(`evidence_ref`, `stage_adapter`, `vision_atoms`, `audio_atoms`,
`multimodal_timeline`, `loaders`). Non cable dans le close-day (E64-C/F).

## Ordre reel du close-day

`v18_close_day.py` : `post_stop` -> `longitudinal` -> `coordination` ->
`life_model` -> `live_ready`. `post_stop` (`brainlive_poststop_deep_flow_v15_15`)
declenche Deep Audio, Deep Vision, l'assemblage d'evenements, puis Brain2.

## Matrice des stages

| Stage (module) | Table(s) source verifiees | Unite atomique | Appel LLM/VLM | Comportement sur troncature (constate/attendu) | Vague |
|---|---|---|---|---|---|
| **EpisodeBuilder / Brain2 V13** (`brain2_strict_v13_2`, `v18_brain2_context`, `brain2_flow_v13_3`) | `turns` (audio + `context_vision_raw`), `conversations` | tour de conversation | Qwen JSON (Ollama) | **BLOQUANT** : bundle 1.6M chars, `finish_reason=length`, close-day `blocked` (OBS-13) | **1** |
| **Deep Vision** (`brainlive_offline_deep_vision_v16_1`) | `vision_frames`, `vision_scene_observations`, `brainlive_deep_vision_runs_v161` | frame / observation de scene | VLM (moondream/qwen2.5vl) | risque identique si toutes les frames envoyees brutes | 2 |
| **Deep Audio** (`brainlive_offline_deep_audio_v18_5`) | `brainlive_audio_segments_v154`, `turns` | segment audio / tour | WhisperX + pyannote (pas prompt-bound), sorties = tours | produit les tours audio atomiques (deja OK, OBS-11) | 2 |
| **Assemblage d'evenements** (`brainlive_event_assembler_v15_14`) | `brainlive_raw_timeline_v1514`, `visual_events_v19` | evenement | deterministe + LLM aval | a publier ses EvidenceRef | 2 |
| **Conversation post-stop / Silent Life** (`brainlive_silent_life_v16_0`, `v18_poststop_outputs`) | `turns`, `scene_session_summaries_v19` | tour / resume de scene | Qwen JSON | meme risque de contexte | 2 |
| **Coordination BrainLive<->Brain2** (`brainlive_brain2_coordination_v15_12`, `v18_coordination`) | `brain2_brainlive_coordination_runs`, exports d'evenements | evenement / episode | Qwen JSON | a fenetrer sur gros jours | 3 |
| **Life Model** (`brain2_life_model_updater_v15_13`, `v18_life_model`, `v19_life_model_store`) | `life_model_entries_v19`, `brain2_life_model_strata`, `brain2_life_model_exports` | entree de modele / strate | Qwen JSON | a fenetrer multi-jours | 3 |
| **Longitudinal** (`brain2_longitudinal_cases_v17`, `v18_longitudinal`) | cas longitudinaux, rollups jour/semaine/mois | cas / periode | Qwen JSON | a fenetrer sur longues periodes | 3 |
| **Reconciliation / live-ready / predictions** (`brainlive_readiness_v15_8`, `predictions_v19`, `self_schema_v19`) | `predictions_v19`, `prediction_outcomes_v19`, `self_schema_v19` | prediction / outcome | Qwen JSON | a auditer en E64-A avant migration | 3 |

Note : les colonnes "comportement sur troncature" hors EpisodeBuilder sont
marquees "risque"/"attendu" tant que E64-C ne les a pas instrumentees ; seul
Brain2 est prouve bloquant par le run reel du 2026-07-12.

## Contrat commun (`NightStageAdapter`)

Methodes : `load_evidence`, `estimate_tokens`, `build_window_prompt`,
`validate_window_output`, `merge_outputs`, `persist_outputs`, `verify_coverage`.
Le prompt metier existant reste derriere `build_window_prompt` ; l'executeur
generique (E64-C) porte budget, retry, subdivision sur troncature, checkpoints et
reprise. `EvidenceRef` (`evidence_id` deterministe depuis `(source_table,
source_pk)`, jamais depuis une tentative LLM) est la monnaie commune ;
`compute_coverage` produit le manifeste anti-perte (un `missing` non vide bloque
le stage).

## Reduction deterministe E64-B (prouvee sur le run reel)

`reduce_vision_observations` collapse les observations de scene consecutives de
meme etat (memes (label, track), meme people_count, meme texte, meme scene) en un
`VisionChangeAtom` `[first_seen, last_seen, count, digest, source_refs]`. Un vrai
changement ouvre un atome ; un changement de confiance seule n'en ouvre pas.

Mesure sur `blsess_e28e0d554f2fd667` (vraie video 5 min, DB 17 Mo) :
**472 observations vision -> 120 atomes, 100% lossless** (chaque
`observation_id` couvert exactement une fois), plus **60 segments audio -> 60
tours intacts**, timeline multimodale de 180 entrees. Le bundle passe de ~945
pseudo-tours a 180 unites sans perdre une preuve ; les frames brutes restent en
base pour le replay.
