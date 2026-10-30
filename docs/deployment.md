# Déploiement et mises à jour

Objectif : **publier depuis le PC, mettre à jour depuis l'interface de Home
Assistant**, sans SSH ni ligne de commande côté Raspberry Pi.

## 1. Dépôt GitHub

Le dépôt doit être **public** pour être utilisé sans jeton GitHub. Il est déjà
configuré pour le compte `SunNathan` :

- `custom_components/thermopt/manifest.json` (`codeowners`, `documentation`, `issue_tracker`)
- `blueprints/thermopt/*.yaml` (`source_url`)

Si le compte change, ces références sont à mettre à jour en même temps que le
`git remote`.

Créer le dépôt distant puis :

```bash
git remote add origin https://github.com/SunNathan/thermopt.git
git push -u origin main
```

### Métadonnées exigées par la validation HACS

Trois éléments ne vivent pas dans le code et se règlent sur GitHub
(*Settings* du dépôt) : sans eux, le job « Validation HACS » reste rouge.

| Élément | Où | Valeur suggérée |
|---|---|---|
| Description | *Settings → General → Description* | « Pilotage optimal du chauffage fil pilote dans Home Assistant » |
| Topics | *Settings → General → Topics* | `home-assistant`, `homeassistant`, `hacs`, `custom-integration`, `heating`, `climate`, `energy` |
| Licence | fichier `LICENSE` | déjà présent (MIT) |

En ligne de commande, avec un jeton personnel (`repo` scope) :

```bash
curl -X PATCH https://api.github.com/repos/SunNathan/thermopt \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -d '{"description":"Pilotage optimal du chauffage fil pilote dans Home Assistant","topics":["home-assistant","homeassistant","hacs","custom-integration","heating","climate","energy"]}'
```

## 2. Flux de publication

```
main ──► CI (ruff + mypy + pytest + hassfest + validation HACS)
   │
   └──► tag v0.2.0 ──► GitHub Release ──► HACS détecte la mise à jour
```

### Publier une version

1. Mettre à jour `"version"` dans `custom_components/thermopt/manifest.json`.
2. Mettre à jour `CHANGELOG.md` (facultatif, `generate_release_notes` le fait).
3. Committer, puis :

```bash
git tag v0.2.0
git push origin main --tags
```

Le workflow `release.yml` vérifie que le tag correspond à `manifest.version`
et crée la release. Si les deux divergent, il échoue : c'est volontaire, HACS
se base sur cette version pour proposer la mise à jour.

### Mettre à jour depuis Home Assistant

*Paramètres → Mises à jour* affiche **ThermOpt** dès qu'une release plus
récente existe → **Installer** → Home Assistant redémarre (ou affiche
« Redémarrage requis »). Pour revenir en arrière, HACS permet de retélécharger
une version antérieure.

Contraintes assumées :
- un redémarrage de Home Assistant est nécessaire (le code du composant est
  chargé au démarrage) ;
- une version = un tag = une release. Pas de « pull » instantané.

## 3. Boucle de développement

### Côté PC (privilégié)

`core/` et `perception/` sont du Python pur : on itère avec `pytest`, sans
Home Assistant. C'est là que se fait l'essentiel du travail (modèle, MPC,
garde-fous) et c'est ce qui garantit le critère « cycle < 100 ms ».

```bash
pytest -q
```

Les tests `tests/test_init.py` chargent une vraie instance Home Assistant en
mémoire (via `pytest-homeassistant-custom-component`) : ils valident le config
flow, la création des entités et les garde-fous.

### Côté Pi (ponctuel)

Pour itérer sur le câblage Home Assistant sans publier de release, monter le
partage Samba du Pi sur le PC et cloner le dépôt **dans un dossier séparé**,
puis copier `custom_components/thermopt` à la main et redémarrer.

**Ne jamais** cumuler un clone git et une installation HACS dans le même
dossier `custom_components/thermopt` : HACS perdrait la main sur les mises à
jour.

## 4. Intégration continue

`.github/workflows/ci.yml` exécute à chaque push et chaque pull request :

| Job | Contenu |
|---|---|
| `quality` | `ruff check`, `ruff format --check`, `mypy`, `pytest` |
| `hassfest` | validation du manifest et des traductions par Home Assistant |
| `hacs` | validation de la structure du dépôt pour HACS |

Pour ne pas découvrir un run rouge après coup, `scripts/check.ps1` exécute les
quatre mêmes commandes que le job `quality` en local.

`.github/workflows/release.yml` s'exécute sur un tag `v*` :
cohérence tag ↔ `manifest.version`, puis création de la GitHub Release.

## 5. Bonnes pratiques

- Ne jamais committer `secrets.yaml`, `.storage/`, les bases `*.db` (déjà dans
  `.gitignore`).
- Prix de l'énergie, plages HC et profil de confort vivent dans les **options
  de l'intégration**, pas dans le code : une révision tarifaire ne demande
  aucune release.
- Après chaque mise à jour, vérifier `sensor.thermopt_statut` et
  `binary_sensor.thermopt_mode_degrade` pendant quelques minutes.
