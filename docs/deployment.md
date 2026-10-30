# Déploiement et mises à jour

Objectif : **publier depuis le PC, mettre à jour depuis l'interface de Home
Assistant**, sans SSH ni ligne de commande côté Raspberry Pi.

## 1. Le dépôt

Le dépôt est un **dépôt d'apps** : `repository.yaml` à la racine, une app dans
`thermopt_app/`. Il doit être **public** pour que le Supervisor puisse cloner et
que l'image soit tirable.

Créer le dépôt distant puis :

```bash
git remote add origin https://github.com/SunNathan/thermopt.git
git push -u origin main
```

### Métadonnées du dépôt (recommandées)

| Élément | Où | Valeur suggérée |
|---|---|---|
| Description | *Settings → General → Description* | « Pilotage optimal du chauffage fil pilote dans Home Assistant » |
| Topics | *Settings → General → Topics* | `home-assistant`, `addon`, `heating`, `climate`, `energy` |
| Licence | fichier `LICENSE` | MIT |

### L'image ghcr doit être publique

Le Supervisor tire `ghcr.io/sunnathan/thermopt:<version>` sans identifiants. Un
package GitHub est **privé par défaut** : après le premier build, passer le
package en *Public* depuis ses réglages. Sinon l'installation échoue avec une
erreur de tirage.

## 2. Flux de publication

```
main ──► CI (ruff + mypy + pytest)
   │
   └──► tag v0.6.0 ──► GitHub Release + image multi-arch
```

### Publier une version

1. Mettre à jour `version` dans `thermopt_app/config.yaml`.
2. Committer.
3. `git tag v0.6.0 && git push origin main --tags`.

Le workflow `build-app.yaml` vérifie que le tag correspond à `config.yaml` puis
construit et publie `ghcr.io/sunnathan/thermopt:0.6.0` pour **amd64 et arm64**.
`release.yml` crée la release GitHub.

### Mettre à jour depuis Home Assistant

*Paramètres → Apps → ThermOpt → Mettre à jour*, puis redémarrer l'app. Pas de
redémarrage de Home Assistant. Pour revenir en arrière, réinstaller une version
antérieure depuis l'App store.

## 3. Boucle de développement

### Côté PC (privilégié)

`lib/thermopt_lib` et `thermopt_app/app` ne dépendent pas de Home Assistant :
on itère avec pytest, sans conteneur ni broker.

```bash
.\scripts\check.ps1     # ruff + format + mypy + pytest, comme la CI
```

Les tests web ouvrent un vrai serveur aiohttp local : ils vérifient les
redirections relatives, la sauvegarde de configuration et le rendu des pages.

### Côté Pi (ponctuel)

Pour tester une modification sans publier de release, on peut reconstruire
l'image localement et la pousser avec un tag de préversion, puis choisir cette
version dans l'App store. Plus simple encore : passer par un tag `vX.Y.Z-dev`
et revenir ensuite à la version stable.

## 4. Intégration continue

`.github/workflows/ci.yml` exécute à chaque push et chaque pull request :

| Étape | Contenu |
|---|---|
| `ruff check` | lint sur `lib`, `thermopt_app`, `tests` |
| `ruff format --check` | formatage |
| `mypy` | typage de `lib/thermopt_lib` et `thermopt_app/app` |
| `pytest` | 191 tests |

`.github/workflows/build-app.yaml` construit l'image à chaque tag et publie
`ghcr.io/sunnathan/thermopt`.

## 5. Bonnes pratiques

- Ne jamais committer de secret : la configuration vit dans `/data/config.json`
  du conteneur, sauvegardé avec les backups de l'app.
- Prix de l'énergie, plages HC et profil de confort se règlent dans l'interface,
  pas dans le code : une révision tarifaire ne demande aucune release.
- Après chaque mise à jour, vérifier le mode affiché, la carte Météo et le
  dernier cycle.
