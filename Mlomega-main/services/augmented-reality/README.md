# MLOmega Augmented Reality

Ce service isolé recevra les capacités FreeGuy optionnelles. Il ne lit ni
n'écrit la base mémoire et n'est jamais lancé par défaut.

État du lot 4.0-A / Lot 1 :

- protocole de préférences borné sur loopback ;
- `object_menus` : carte suivie VisionRT, labels ML Kit device et registre
  d'actions explicites ;
- `semantic_sound` : provider YAMNet device confirmé par le probe du modèle ;
- `contextual_knowledge` : Kiwix loopback seulement, novelty/cooldown ;
- `action_recognition`, super-résolution et mesure restent indisponibles tant que
  leurs vrais providers n'existent pas ;
- aucun modèle, caméra ou thread quand
  `MLOMEGA_AUGMENTED_REALITY=0` ;
- aucune dépendance ARCore ajoutée à l'APK XREAL.

Probe sans démarrer le serveur :

```powershell
.\.venv-live\Scripts\python.exe services\augmented-reality\service.py --probe
```

Démarrage produit opt-in :

```powershell
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -AugmentedReality
```

Le service reste sur `127.0.0.1:8791`. Les futurs workers consommeront les
frames/audio/poses par un contrat distinct; aucune boucle média ne doit passer
par l'endpoint HTTP de préférences.

Routes du Lot 1 :

- `POST /v1/preferences` : état session et preuve des providers device ;
- `POST /v1/object-card` : projection d'un snapshot VisionRT visible ;
- `POST /v1/object-action` : action allowlistée et receipt terminal ;
- `POST /v1/contextual-knowledge` : fiche Kiwix courte et sourcée.

Le service ne reçoit pas le flux vidéo ou PCM. ML Kit et YAMNet tournent sur le
S24; le bridge PC ne transmet que les événements bornés. Le VLM n'est invoqué
qu'après l'action explicite « Manuel court ».

Variables optionnelles :

- `MLOMEGA_AR_DEVICE_REGISTRY` : chemin du registre objet/domotique ;
- le `token_env` de chaque entrée désigne la variable du token Home Assistant ;
- `MLOMEGA_KIWIX_URL` : endpoint Kiwix local (`127.0.0.1`/`localhost`).

La mémoire n'est accessible que par les frontières produit déclarées dans le
manifeste : lecture WorldBrain/MemoryQuery/HotContext lorsqu'elle est utile, ou
writer d'événement déjà validé pour une nouvelle observation. Le processus ne
doit jamais ouvrir `memory.db` directement.
