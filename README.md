<h1 align="center">Camillou</h1>

<p align="center"><img src="assets/avatar.png" alt="Logo Camillou" width="160"></p>

<h3 align="center">L'agent qui fait ce qu'il peut</h3>

Camillou se branche sur le widget de chat d'assistance du site
[zou.maregionsud.fr](https://zou.maregionsud.fr/) (le bot « Camille ») et l'expose comme un backend de modèle
compatible OpenAI : n'importe quel assistant de code, tel que **opencode**, peut s'y connecter exactement
comme à une API d'IA classique, alors que l'inférence est en réalité assurée par le chatbot du site.

Inspiré de [cyberpapiii/chipotlai-max](https://github.com/cyberpapiii/chipotlai-max).

---

## Ce que ça fait

- **Démarre une session de chat anonyme** (sans authentification, sans cookie, sans navigateur) auprès du hub Omnichannel.
- **Expose une API compatible OpenAI** : `GET /v1/models`, `POST /v1/chat/completions` (streaming et non-streaming).
- **Adaptateur d'appel d'outils** : traduit les réponses « action » JSON du bot en vrais `tool_calls` OpenAI, pour que
  les clients d'agent (opencode, SDK, tout ce qui parle OpenAI) puissent piloter de vrais outils.
- **Garde-fous de fiabilité et de sécurité** (voir plus bas) qui maintiennent un modèle de base limité sur les rails.
- **Banc de régression** : 24 scénarios notés + invariants.

## Prérequis

- Python 3 (bibliothèque standard uniquement, aucun `pip install`).
- Optionnel : [`opencode`](https://opencode.ai) pour la démo agent.

## Arborescence

```
camillou/
├── camillou.py            # l'outil : client + proxy + adaptateur + garde-fous + sous-commandes
├── agent_bench.py         # banc de régression (24 scénarios + invariants)
├── examples/
│   └── opencode.json      # config de provider opencode prête à l'emploi
├── docs/
│   └── ENDPOINT-SPEC.md   # référence d'endpoints nettoyée (secrets masqués)
└── README.md
```

## Démarrage rapide

```bash
# complétion ponctuelle
python3 camillou.py ask "Explique les trous noirs en une phrase"

# serveur compatible OpenAI
python3 camillou.py serve --port 3000
curl -s http://127.0.0.1:3000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"camillou-1","messages":[{"role":"user","content":"Bonjour"}]}'

# banc de régression
python3 agent_bench.py                       # les 24 scénarios
python3 agent_bench.py two-file-refactor     # un sous-ensemble par nom
```

L'usage avec opencode est détaillé dans la section suivante.

## Utilisation avec opencode

Prérequis : [`opencode`](https://opencode.ai) installé.

**1. Lancer le proxy** (ou passer par le tout-en-un, plus bas) :

```bash
python3 camillou.py serve --port 3000
```

**2. Déclarer le provider** dans un dossier de travail :

```bash
python3 camillou.py opencode-config --dir ~/camillou-agent
```

Ça écrit `~/camillou-agent/opencode.json` :

```json
{
  "provider": {
    "camillou": {
      "npm": "@ai-sdk/openai-compatible",
      "options": { "baseURL": "http://127.0.0.1:3000/v1", "apiKey": "camillou-local" },
      "models": { "camillou-1": {} }
    }
  },
  "model": "camillou/camillou-1"
}
```

**À propos de la clé API** : opencode exige un `apiKey` non vide pour charger le provider, mais le proxy
l'ignore totalement. N'importe quelle valeur convient (`camillou-local` par défaut, modifiable avec `--key`).
Donc : aucun compte, aucun login, aucun `/register`. Le provider est « enregistré » en l'écrivant dans
`opencode.json`.

**3. Ouvrir une session :**

```bash
cd ~/camillou-agent
XDG_CONFIG_HOME=/tmp/oc-clean opencode            # session interactive
XDG_CONFIG_HOME=/tmp/oc-clean opencode run --model camillou/camillou-1 --auto "…"
```

Dans le TUI :

- `/models` puis sélectionne **Camillou** → `camillou-1`
- `/new` pour une nouvelle session
- `/provider` pour gérer les providers et identifiants

**Tout-en-un** (proxy + config + session en une commande) :

```bash
python3 camillou.py opencode --dir ~/camillou-agent
python3 camillou.py opencode --dir ~/camillou-agent -- run --auto "…"
```

Notes :

- `--pure` (optionnel) évite de charger tes plugins opencode.
- Isole `XDG_CONFIG_HOME` pour ne pas toucher à ta config habituelle.
- `--auto` approuve automatiquement les actions : à réserver à un dossier isolé.
- Vérification : `opencode models camillou` → `camillou/camillou-1`.

## Sous-commandes

| Commande | Rôle |
|---|---|
| `ask PROMPT` | complétion ponctuelle |
| `bootstrap` | crée une session anonyme ; affiche ChatId / endpoint ACS / VisitorId |
| `recon` | récupère la config du widget (lisible anonymement) |
| `serve [--host --port]` | API compatible OpenAI + adaptateur d'appel d'outils |
| `opencode` | tout-en-un : démarre le proxy puis lance opencode sur Camillou |
| `opencode-config --dir` | écrit une config de provider opencode pointant vers le proxy |
| `agent --task --test` | agent de code autonome (générer → exécuter → corriger) |
| `bench [-n]` | test de concurrence / débit |
| `selftest` | test de fumée de bout en bout |

## Variables d'environnement

| Variable | Défaut | Signification |
|---|---|---|
| `CAMILLOU_OMS` | URL du hub ZOU! | URL de base du hub Omnichannel |
| `CAMILLOU_ORG` / `CAMILLOU_WID` | org/widget ZOU! | identifiants publics du widget |
| `CAMILLOU_ORIGIN` | `https://zou.maregionsud.fr` | valeur de l'en-tête `Origin` |
| `CAMILLOU_TOOLS` | outils fichier/shell de base | **liste blanche** des outils proposés au modèle |
| `CAMILLOU_DENY` | `question` | liste noire supplémentaire par-dessus la liste blanche |
| `CAMILLOU_MAX_ACTIONS` | `12` | plafond d'actions d'outil par tour |
| `CAMILLOU_DEBUG` | désactivé | journalise chaque prompt construit + la réponse dans `/tmp/camillou_dbg.txt` |

## Comment fonctionne l'adaptateur

Pour les clients d'agent (requêtes contenant `tools`) :

1. On construit un prompt compact : outils autorisés + conversation récente + tour utilisateur courant.
2. On demande au bot de répondre par **une seule action JSON** : `{"tool":"bash","args":{"command":"ls"}}` ou `{"final":"…"}`.
3. On l'analyse et on la traduit en réponse OpenAI correcte (`finish_reason:"tool_calls"` avec `message.tool_calls`,
   ou `finish_reason:"stop"` avec `message.content`).
4. Les résultats d'outil reviennent en messages `role:"tool"` ; on répète jusqu'à ce que le bot émette `final`.

### Garde-fous de fiabilité et de sécurité

- **Liste blanche** : seuls les outils de base sont proposés ; les outils MCP / à effet de bord sont exclus par défaut.
- **Réessai sur action invalide** : outils inconnus, noms préfixés `functions.`, JSON malformé et arguments
  requis manquants sont rejetés puis redemandés.
- **Anti-boucle** : détection d'appel identique, limites de répétition par outil, et blocage de l'outil `question`.
- **Plafond d'actions par tour** : au plus `CAMILLOU_MAX_ACTIONS` actions par message, puis il s'arrête et le signale.
- **Gestion du contexte** : abandonne sa propre prose précédente et met en avant la demande courante (survit aux changements de sujet).
- **Réutilisation de fichier** : injecte le dernier chemin écrit pour qu'il modifie le même fichier au lieu d'en créer des copies.
- **Garde-fou d'honnêteté** : s'il *prétend* avoir modifié quelque chose sans action réelle, la prétention est remplacée par une note honnête.
- **Application des impératifs** : une commande directe sur un fichier existant est relancée jusqu'à un vrai `edit`/`write`.
- **Nettoyage des refus** : supprime le « je ne peux pas fournir de code » contradictoire après avoir fait le travail.
- **Protection broken-pipe** : plus de plantage quand le client se déconnecte en plein flux.

## Banc de régression

`agent_bench.py` démarre son propre proxy, pilote le protocole d'outils, simule les outils et note chaque scénario :

**Inspecter** liste · lecture · réponse-d'après-lecture · grep · glob+compte ·
**Créer/Modifier** write · edit-args · réutilisation · correction de bug · refactor 2 fichiers · anglais ·
**Exécuter** commande simple · write→run ·
**Q&R** question pure · explication ·
**Contexte** changement de sujet · long transcript · ambigu ·
**Sécurité** anti-boucle · erreur-gracieuse · résultat-malformé · sortie-volumineuse · garde-fou-honnêteté · MCP-refusé

Plus des **invariants** sur toute la campagne : aucun outil inventé, aucune fuite de JSON brut.

## Limites

L'adaptateur améliore l'**orchestration**, pas le modèle. Derrière, c'est un chatbot de support Microsoft
Copilot Studio (famille GPT-4o), pas un modèle conçu pour piloter un agent. Voici ce que ça implique,
observé en pratique :

**Raisonnement**
- Pas de vraie planification : les tâches longues ou en plusieurs étapes dérivent.
- Connaissance métier faible : il ignore par exemple qu'un fournisseur de cartes est passé derrière une clé
  API, ou qu'un endpoint de tuiles est déprécié.
- Sécurité par sujet, incohérente : il refuse, esquive ou négocie selon le thème, parfois à contretemps.
- Il lui arrive de **prétendre avoir fait** une modification sans rien faire. Le *garde-fou d'honnêteté*
  remplace le mensonge par une note franche, mais ne peut pas l'obliger à agir.

**Comportement**
- Ne converge pas toujours : il peut alterner entre plusieurs solutions sans garder en mémoire les échecs.
- Tendance à trop demander (« Souhaitez-vous… ? ») et à clore poliment, d'où le blocage de l'outil `question`.
- Peut ignorer un ordre direct (« fait le ! »). Mitigé par l'adaptateur, pas éliminé.

**Performance / contexte**
- Lent : ~8–40 s par étape, et chaque sous-agent ou appel d'outil en ajoute.
- Transcript limité aux ~8 derniers messages ; sorties d'outils tronquées (~2500 caractères). Un contenu
  volumineux (ex. un fichier de 4000 lignes) n'est donc pas réellement traité.
- Erreurs transitoires (« souci technique ») masquées par les réessais.

**En résumé** : attendez-vous à « utile mais supervisé », pas à de l'autonome. Laissez `--auto` désactivé pour
tout ce qui compte, travaillez dans un dossier isolé, et gardez à l'esprit que chaque exécution consomme le
quota de la cible (voir la section Légal / éthique).

## Légal / éthique

Camillou est une **preuve de concept**, à des fins de **recherche et d'éducation**. Il démontre qu'une chose
est possible, pas qu'elle est permise partout.

En clair :

- **Seulement chez vous (ou avec autorisation).** N'utilisez Camillou que sur des systèmes que vous
  **possédez** ou pour lesquels vous avez une **autorisation écrite**. Tester sans autorisation est illégal
  (en France, art. 323-1 et suivants du Code pénal).
- **Pas de tiers.** Ce qui fonctionne sur une cible fonctionne sur toutes : ne visez jamais l'infrastructure
  d'autrui.
- **Ça coûte, et ça vous engage.** Chaque requête tire sur le quota Copilot Studio / Azure de la cible et va
  à l'encontre des conditions d'utilisation de Microsoft. C'est votre responsabilité, pas celle du bot.
- **L'agent ne fait pas semblant.** Via `bash` / `write` / `edit`, il exécute réellement des commandes sur
  votre machine : travaillez dans un dossier isolé et laissez `--auto` de côté quand ça compte.
- **Sans garantie.** Fourni tel quel. Vous restez seul responsable de ce que vous en faites.

Pour résumer : une preuve de concept, qui fait ce qu'il peut, entre de bonnes mains.
