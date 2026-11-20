# Scout

Dossier de scouting League of Legends : on rentre les 5 joueurs d'une équipe
(un par rôle), le programme lit leurs ranked via l'API Riot et sort un rapport
complet, consultable dans le navigateur et imprimable en PDF.

## Lancer

```bash
pip install -r requirements.txt
python app.py
```

Ça ouvre http://127.0.0.1:5057. Rentre les Riot ID (`Pseudo#TAG`), le nom de
l'équipe, puis « Lancer l'analyse ».

## La clé API

La clé Riot se met dans `key.txt` à la racine (ou dans la variable
d'environnement `RIOT_API_KEY`). `key.txt` est dans le `.gitignore`, comme le
cache et les rapports générés : rien de tout ça ne part sur GitHub.

Une clé de développement expire toutes les 24 h et est limitée à 100 requêtes
par 2 minutes. Le programme lit les limites renvoyées par Riot et s'y adapte
tout seul, donc une clé de production marche sans rien changer — juste plus vite.

Ordre de grandeur avec une clé de dev : une game = 2 requêtes (match +
timeline). 5 joueurs × 100 games ≈ 15-20 min la première fois. Les games sont
gardées en cache (`cache/`, compressé) pour toujours : relancer, ou scouter une
équipe qui a joué contre celle-ci, est quasi instantané.

## Ce que contient le rapport

**Vue d'ensemble** : rang, games, WR, KDA, GD@15, morts < 14 min, champions
principaux, bans conseillés pour l'équipe, signaux clés par joueur. Les smurfs
probables (score ≥ 80) apparaissent sous leur joueur.

**Par joueur**
- Rangs (SoloQ, Flex, Ranked 5 stack…), sorts d'invocateur.
- Signaux : tableau des indicateurs qui ressortent (indicateur · valeur ·
  contexte) ; bordure verte = point fort, rouge = faiblesse, grise = info.
- Bilan, early à 15 min, style de jeu, durée et côté bleu/rouge.
- Détail de l'early à 10 et 15 min : écarts d'or/CS/XP, morts en 1v1, morts sur
  gank, first blood donné, WR en avance / en retard, timing niveau 6, premier retour.
- Champions : G, WR, games sur 30 j, KDA, CS/min, dégâts/min, KP, GD/CSD@15,
  rune et premier item les plus fréquents, date.
- Contre quel vis-à-vis, contre quelle classe de champion.
- Cartes kills/assists/morts avant 14 min, heatmaps, temps par zone ; pathing
  jungle, roams du mid, déplacements du support.
- Objectifs (participation drakes, grubs, héraut, nashor), gestion de partie
  (avances perdues, remontées, FF), maîtrises et picks cachés (grosse maîtrise,
  0 ranked sur la période).

**Smurf probable (score ≥ 80)** : analysé exactement comme un titulaire, page
juste après son joueur, avec le pool combiné main + smurf. Ses champions
comptent dans les bans conseillés.

**Botlane**, **Premades**, **Compos en équipe**, **Détection de smurfs** (tableau
des candidats avec chaque critère).

## Face à face

Menu « Face à face » : choisir deux rapports existants (par exemple ta propre
équipe et l'adversaire). Comparaison :
- rôle par rôle sur ~20 indicateurs, le meilleur des deux en gras ;
- matchups de lane : résultats de chaque joueur contre les champions que son
  vis-à-vis joue le plus, et contre sa classe principale ;
- bans conseillés dans les deux sens ;
- stats en stack (WR, objectifs pris en premier, profil de dégâts) ;
- les games où les deux équipes se sont déjà croisées, avec le score.

## Draft

Menu « Draft » (ou bouton « Draft contre eux » dans un rapport) : choisir
l'équipe adverse, puis pour chaque rôle ton pick et jusqu'à 5 bans. Pour chaque
pick :
- les champions **du pool de ton vis-à-vis** (main + smurfs détectés) qui
  gagnent contre ton pick en lane, avec le WR du counter, l'écart d'or à 15 min
  et ses stats à lui dessus (games au rôle, WR, KDA, games sur 30 jours) ;
- son historique personnel contre ton champion ;
- les autres counters fréquents hors de son pool.
Les champions bannis ou déjà pris par toi sont grisés. Picks et bans sont
gardés dans le navigateur, par rapport.

Données de counter : fichiers de matchups publics de u.gg (ranked solo, monde,
deux derniers patchs fusionnés, elo au choix), mis en cache dans `cache/ugg`.
Aucune requête à l'API Riot.

## Détection de smurfs

Quand quelqu'un a un deuxième compte, ses potes jouent aussi avec. Pour chaque
joueur P :

1. On prend ses partenaires : les autres joueurs de la liste + les comptes
   avec qui il a joué au moins 3 games.
2. On lit les games de ces partenaires **sans** P, et on note avec qui ils
   jouent.
3. Un compte qui revient souvent avec eux, qui n'a jamais été dans une game de
   P (ni avec, ni contre) et qui n'a jamais joué pendant une game de P est un
   candidat.
4. Indice principal : les **enchaînements**. La game de P finit à 20:10 et
   celle du candidat commence à 20:20 (ou l'inverse) : c'est ce que fait
   quelqu'un qui change de compte. Plusieurs enchaînements sans aucun
   chevauchement = très probablement la même personne (≤ 15 min compte plein,
   jusqu'à 30 min compte un peu moins).
5. Le reste du score : games et partenaires en commun, mêmes horaires, games
   les jours où P ne joue pas, niveau du compte. Même rôle et mêmes champions
   ne font qu'**ajouter** des points : un smurf sert souvent à entraîner
   d'autres champions en secret, ne pas les jouer n'est donc pas un contre-indice.
   Sans aucun enchaînement, un compte plafonne vers 70 et n'atteint pas le seuil
   d'analyse complète (80).
6. Les meilleurs candidats sont vérifiés : on récupère leur liste de games, on
   estime l'heure de chacune à partir de son identifiant (les IDs de match
   augmentent avec le temps), et on télécharge celles qui tombent près d'une
   game de P : pour écarter un chevauchement et trouver d'autres enchaînements.

Trois niveaux de recherche (rapide / normale / poussée) selon le temps qu'on
veut y mettre. Un score élevé reste un indice, pas une preuve.

## Organisation du code

```
app.py              serveur Flask local + API JSON
scoutlib/riot.py    client Riot : limites lues dans les en-têtes, cache gzip
scoutlib/static.py  Data Dragon en français (champions, items, runes, sorts)
scoutlib/geo.py     zones de la carte (lanes, rivières, jungles alliée/ennemie)
scoutlib/extract.py une game -> stats d'un joueur (match + timeline)
scoutlib/player.py  agrégats par joueur
scoutlib/team.py    botlane, premades, games en stack
scoutlib/smurf.py   comptes secondaires
scoutlib/counters.py matchups de lane (u.gg) pour la draft
scoutlib/insights.py signaux (indicateurs qui ressortent)
scoutlib/report.py  orchestration, sauvegarde du rapport
web/                interface (HTML/CSS/JS sans build)
```
