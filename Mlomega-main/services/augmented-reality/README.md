# MLOmega Augmented Reality

Ce service isolé recevra les capacités FreeGuy optionnelles. Il ne lit ni
n'écrit la base mémoire et n'est jamais lancé par défaut.

État du lot 4.0-A :

- protocole de préférences borné sur loopback ;
- toutes les capacités déclarées `false` tant que leurs vrais workers n'existent
  pas ;
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

La mémoire n'est accessible que par les frontières produit déclarées dans le
manifeste : lecture WorldBrain/MemoryQuery/HotContext lorsqu'elle est utile, ou
writer d'événement déjà validé pour une nouvelle observation. Le processus ne
doit jamais ouvrir `memory.db` directement.
