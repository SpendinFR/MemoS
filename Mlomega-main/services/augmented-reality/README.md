# MLOmega Augmented Reality

Ce service isolé recevra les capacités FreeGuy optionnelles. Il ne lit ni
n'écrit la base mémoire et n'est jamais lancé par défaut.

État des lots 1–4 :

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
- `consented_people` : carte locale pour acteur enrôlé et consenti; pour un acteur
  inconnu avec release studio, recherche Google Web Detection puis expansion
  optionnelle du pseudo par Sherlock, toujours `probable` jusqu'à confirmation;
- `pulse_aura` : seule la ROI consentie est envoyée au téléphone; le signal rPPG
  reste local, volatile et abstentionniste.
- `indoor_navigation` : graphe appris par la pose XREAL; Wi-Fi/BLE/magnétique
  servent uniquement à relocaliser et n'inventent jamais une coordonnée ;
- `planetarium` : calcul local JPL/catalogue borné, rendu après preuve de nord ;
- `weather_context` : Open-Meteo opt-in, cache daté de 15 minutes ;
- `legal_context` : recherche globale LEGI France en vigueur, session explicite
  et bornée, aucune écriture mémoire.

Probe sans démarrer le serveur :

```powershell
.\.venv-live\Scripts\python.exe services\augmented-reality\service.py --probe
```

Démarrage produit opt-in :

```powershell
.\scripts\RUN_MLOMEGA_V19.ps1 -LivePhone -AugmentedReality `
  -StudioReleaseId release-film-2026-001
```

Configuration opérateur locale :

```powershell
# Wikipédia FR hors ligne (~149 Mo outils inclus), SHA-256 vérifié
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\INSTALL_KIWIX_FR.ps1

# Un objet Home Assistant; le jeton est demandé sans écho
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\CONFIGURE_AUGMENTED_REALITY.ps1 `
  -Mode device -Label "lampe salon" -EntityId "light.salon"

# Un code unique pour toute la session de tournage
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\CONFIGURE_AUGMENTED_REALITY.ps1 `
  -Mode studio -ReleaseId "release-film-2026-001"
```

Le service reste sur `127.0.0.1:8791`. Les futurs workers consommeront les
frames/audio/poses par un contrat distinct; aucune boucle média ne doit passer
par l'endpoint HTTP de préférences.

Routes du Lot 1 :

- `POST /v1/preferences` : état session et preuve des providers device ;
- `POST /v1/object-card` : projection d'un snapshot VisionRT visible ;
- `POST /v1/object-action` : action allowlistée et receipt terminal ;
- `POST /v1/contextual-knowledge` : fiche Kiwix courte et sourcée ;
- `POST /v1/consented-person` : carte d'une identité locale consentie, candidat Web
  autorisé ou ROI physiologique locale.
- `POST /v1/weather` : widget actuel/caché et daté ;
- `POST /v1/planetarium` : contrat `sky_dome` en espace `tracking_local` ;
- `POST /v1/context-assist` : repère LEGI/Kiwix sourcé, seulement pendant une
  session explicitement active.

Le service ne reçoit pas le flux vidéo ou PCM. ML Kit et YAMNet tournent sur le
S24; le bridge PC ne transmet que les événements bornés. Le VLM n'est invoqué
qu'après l'action explicite « Manuel court ».

Variables optionnelles :

- `MLOMEGA_AR_DEVICE_REGISTRY` : chemin du registre objet/domotique ;
- `MLOMEGA_AR_CONSENTED_PEOPLE` : registre local optionnel pour les profils déjà
  enrôlés et la physiologie; il n'est plus requis pour la recherche Web studio ;
- `MLOMEGA_GOOGLE_VISION_API_KEY` : clé Web Detection conservée dans `.env` ;
- `MLOMEGA_SHERLOCK_COMMAND` : chemin optionnel vers la commande `sherlock` ;
- le `token_env` de chaque entrée désigne la variable du token Home Assistant ;
- `MLOMEGA_KIWIX_URL` : endpoint Kiwix local (`127.0.0.1`/`localhost`) ;
- `MLOMEGA_KIWIX_EXE` + `MLOMEGA_KIWIX_ZIM` : permettent à RUN de démarrer et
  arrêter automatiquement le serveur ;
- `MLOMEGA_LEGAL_JURISDICTION` : `FR` par défaut dans le lanceur ;
- `MLOMEGA_LEGAL_KIWIX_URL` : fallback local optionnel pour le profil juridique ;
- `MLOMEGA_AR_STUDIO_CONFIG` : hash local du code de release, jamais le code en
  clair.

La recherche publique exige aussi `-StudioReleaseId` et le code de cette release.
Sans release, code valide ou clé, elle est indisponible et aucun crop ne quitte le
PC. Sherlock cherche un **pseudo** sur plusieurs sites; il ne reconnaît pas le
visage et ses résultats ne sont jamais promus automatiquement dans la mémoire.

La mémoire n'est accessible que par les frontières produit déclarées dans le
manifeste : lecture WorldBrain/MemoryQuery/HotContext lorsqu'elle est utile, ou
writer d'événement déjà validé pour une nouvelle observation. Le processus ne
doit jamais ouvrir `memory.db` directement.
