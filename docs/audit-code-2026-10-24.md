# Audit de code — 24 octobre 2026

Révision examinée initialement : `8b38eee`. Audit de qualité, cohérence, code inutilisé,
concurrence et respect des invariants du dépôt. Les constats ci-dessous décrivent cette révision.

## Suivi des corrections

Les sept problèmes confirmés ont été corrigés à la suite de cet audit : couverture
complète des chapitres, contrôle de l'identité du périphérique sélectionné, réservation
des positions et ordonnancement partagés entre lots, drain unique de la barrière,
séparation des versions de livres et de leurs caches, annulation des jobs retenus
par la barrière et normalisation des imports locaux non conformes.

Les anciens exports et les sources de transferts partiels sont préservés. Les MP3
locaux déjà conformes sont copiés directement ; les autres sont convertis sans
modifier les originaux. Les identités des exports existants restent reconnues.

Validation après corrections : **232 tests réussis**, dont **26 nouveaux cas** ;
Ruff, formatage, mypy, vérification du site et construction Linux réussis.
Les tests du binaire incluent le démarrage, Piper et désormais l'import d'un MP3
128 kbps mono normalisé vers la cible imposée. Journal :
`/tmp/shokz-refill-fixes-build.log`. Les vérifications natives Windows restent à effectuer.

Les observations de structure et le nettoyage du code inutilisé restent des travaux
distincts des sept corrections demandées.

## Appréciation générale

La base est saine sur le plan des outils : typage strict, formatage homogène,
services largement indépendants de Qt, intégrations remplaçables, tests sans
périphérique ni compte réels. Les transferts ont de bonnes protections : fichiers
partiels privés, vérification SHA-256, publication sans écrasement et verrou partagé
entre les opérations de l'application.

Les principaux risques se trouvent dans les transitions entre ces composants :
identité du périphérique avant la copie, ordonnancement entre workers, reprise d'un
export et validation du découpage audio. Sept problèmes ont été reproduits : deux
de priorité haute et cinq de priorité moyenne. Les contrôles automatiques actuels
ne couvrent pas ces scénarios.

Périmètre : analyse statique des 48 modules Python applicatifs (8 908 lignes),
revue ciblée des services, workers, contrôleurs et scripts de distribution,
exécution des contrôles et reproductions locales avec fichiers temporaires et fakes.
Cet audit ne valide pas les services distants réels ni un appareil physique.

## Problèmes confirmés

### 1. P1 — Le découpage en chapitres peut perdre une partie du livre

Emplacement : [audiobook_models.py](../src/shokz_refill/audiobook_models.py),
`_chapter_parts`, lignes 210–241.

La fonction rejette certains chevauchements, mais ne vérifie ni que le premier
chapitre commence à zéro, ni la continuité entre chapitres, ni que le dernier
atteigne la fin des sources. Elle accepte donc des chapitres qui ne couvrent pas
le livre, contrairement à son contrat et au guide technique.

Reproduction : une source de 60 secondes et deux chapitres `[10, 20]` et `[30, 40]`
produisent deux fichiers totalisant **20 secondes**. Les 40 autres secondes sont
absentes du plan, sans erreur. L'export peut ensuite être déclaré complet.

Correction proposée : vérifier la couverture complète et contiguë avec une
tolérance explicite ; utiliser le repli par source si cette couverture échoue.
Tester les trous initiaux, intermédiaires et finaux, ainsi que les limites de tolérance.

### 2. P1 — Un téléchargement musical peut écrire sur un périphérique de remplacement

Emplacements : [downloads.py](../src/shokz_refill/downloads.py),
`_download_stage` et `_transfer_stage`, lignes 269–338 ;
[transfer.py](../src/shokz_refill/transfer.py), `_transfer`.

La file musicale conserve le chemin du périphérique, sans conserver son identité
avant le téléchargement. `TransferManager` capture cette identité seulement au
début de la copie. Si le volume est remplacé au même chemin entre ces deux étapes,
la copie considère le nouveau volume comme valide.

Reproduction : le faux downloader déplace le dossier du périphérique vers
`detached`, recrée un autre dossier au chemin initial et y recrée la destination.
Le job termine en **`complete`** et le nouveau dossier reçoit le MP3.
Un polling qui retrouve le même chemin ne garantit pas de détecter ce remplacement.

Correction proposée : capturer l'identité du périphérique dans un worker avant
les opérations longues, puis la vérifier avant chaque mutation et lors des reprises.
Le parcours Audiobookshelf possède déjà un contrôle de ce type : harmoniser les
deux parcours. Ajouter le scénario de remplacement à la suite musicale.

### 3. P2 — Deux envois vers le même dossier réutilisent les positions

Emplacements : [downloads.py](../src/shokz_refill/downloads.py), `enqueue`,
lignes 133–139 ; [ui.py](../src/shokz_refill/ui.py), `_enqueue_tracks` ;
[playback_order.py](../src/shokz_refill/playback_order.py), `next_position`.

La prochaine position vient uniquement des fichiers déjà présents. Les positions
des jobs actifs ne sont pas réservées, et chaque appel à `enqueue` crée sa propre
barrière d'ordonnancement.

Reproduction : lancer A, bloquer sa conversion, puis envoyer B au même endroit.
B termine avant A et les deux jobs ont **`position == 1`**. Le dossier contient
`001 - Unknown Artist - First.mp3` et `001 - Unknown Artist - Second.mp3`.

Correction proposée : réserver atomiquement les positions par destination en
tenant compte des jobs actifs, et partager leur ordonnancement entre les lots.
Tester deux envois successifs alors que le premier est encore en cours.

### 4. P2 — `OrderGate` peut exécuter ses callbacks dans l'ordre inverse

Emplacement : [playback_order.py](../src/shokz_refill/playback_order.py),
`OrderGate._drain`, lignes 81–90.

Le verrou protège la sélection du callback et l'avancement de `_next`, mais le
callback s'exécute après libération du verrou. Un second thread peut donc avancer
et soumettre le transfert suivant avant le premier.

Reproduction déterministe avec deux threads et deux événements : suspendre le
premier callback juste avant son effet, appeler `ready(2, ...)`, puis reprendre le
premier. L'ordre observé est **`[2, 1]`**. Les workers de conversion peuvent appeler
cette barrière simultanément ; un executor de transfert à un thread conserve
l'ordre de soumission ainsi inversé.

Correction proposée : autoriser un seul drain actif tout en évitant d'exécuter
des callbacks arbitraires sous un verrou non réentrant. Ajouter un test concurrent ;
le test actuel de la barrière appelle ses méthodes depuis un seul thread.

### 5. P2 — Réessayer un livre modifié mélange deux versions dans le même dossier

Emplacement : [audiobook_queue.py](../src/shokz_refill/audiobook_queue.py),
`_run`, lignes 196–202, et `retry`, lignes 387–424.

Les détails du livre et les identités sont recalculés à chaque tentative, mais
`destination_prepared` reste vrai. Une nouvelle révision des sources ne provoque
donc pas la sélection d'un autre dossier si le même job est relancé.

Reproduction : exporter le premier chapitre, annuler avant le second, changer
`AudioSource.modified`, puis réessayer. Le job termine en **`complete`**, dans le
même dossier, avec **trois fichiers pour deux chapitres** : `01 - First.mp3`,
`01 - First 2.mp3` et `02 - Second.mp3`.

Correction proposée : conserver l'identité globale de l'export préparé et la
comparer à la nouvelle tentative. En cas de changement, réserver un nouveau dossier
en préservant l'ancien export. Tester une révision après publication partielle.

### 6. P2 — Annuler un job retenu par la barrière ne le termine pas immédiatement

Emplacement : [downloads.py](../src/shokz_refill/downloads.py), `cancel`,
lignes 340–353, et `_submit_transfer`.

Après sa conversion, un job peut attendre dans `OrderGate` sans aucun `Future`
associé. `cancel` positionne son drapeau, mais ne publie `CANCELLED` que si
`future.cancel()` réussit. Ce cas n'a justement plus de future à annuler.

Reproduction : bloquer la conversion du premier morceau, laisser le second atteindre
la barrière, puis annuler le second. État observé : **`cancel_requested=True`**,
**`waiting for transfer`**, **aucun future**. La transition terminale attend que
le morceau précédent libère la barrière ; jusque-là, le job reste actif pour
l'interface et la réservation de destination.

Correction proposée : représenter explicitement l'attente dans la barrière et
permettre son retrait atomique lors de l'annulation. Tester l'annulation à chaque
transition entre deux executors, en plus de l'annulation pendant une opération.

### 7. P2 — L'import local ne respecte pas le format cible imposé

Emplacements : [ui.py](../src/shokz_refill/ui.py), `_add_local`, lignes 1279–1294 ;
[metadata.py](../src/shokz_refill/metadata.py), `validate_source_mp3`, lignes 74–82.

L'import vérifie que le fichier est un MP3 lisible, puis le copie tel quel.
La validation CBR 192 kbps, 44,1 kHz, stéréo est réservée aux conversions.
Cela diverge de l'invariant produit d'`AGENTS.md`, même si le bouton annonce
actuellement une copie sans réencodage.

Reproduction avec le ffmpeg embarqué : un MP3 **128 kbps, 22 050 Hz, mono** passe
`validate_source_mp3` ; le même fichier échoue à `validate_mp3`. Le parcours local
copie directement ses octets sur le périphérique.

Correction proposée : normaliser les MP3 non conformes en arrière-plan et copier
directement ceux qui respectent déjà la cible. Vérifier le format final dans un
test d'import local.

## Code inutilisé et traces d'anciens parcours

Recherche des références dans `src`, `tests` et `scripts`, complétée par une
analyse AST. L'absence d'appel direct ne suffit pas pour les overrides et signaux Qt ;
ils ont été exclus des conclusions de code mort.

| Élément | Constat | Action proposée |
| --- | --- | --- |
| `playback_order.OrderedItem`, ligne 94 | Aucune référence à la classe dans le dépôt. | Supprimer la classe et son import `dataclass` si aucun usage externe n'est prévu. |
| `BrowserPanel.pending_groups`, ligne 253 | Aucune référence à la méthode. | Supprimer ce reste du regroupement par playlist ou le raccorder à un besoin produit explicite. |
| `playback_order.plan_names`, ligne 99 | Utilisé uniquement par un test ; la production appelle `ordered_name`. | Tester directement le chemin de production ou utiliser réellement ce helper. |
| `YouTubeMusicService.oauth_settings` et `connect_oauth` | Appelés uniquement depuis les tests ; le dialogue actuel utilise navigateur et en-têtes. | Décider si la création de sessions OAuth reste une fonctionnalité prise en charge. |
| `transfer_wizard._NEW_ROLE`, lignes 27 et 208 | Valeur écrite dans les items, jamais relue. | Retirer ce marquage inutile. |
| `MainWindow._sort_results`, ligne 741 | Relais appelé uniquement par les tests ; le panneau gère les signaux de tri. | Faire porter ces tests sur `BrowserPanel`, puis retirer le relais. |

Attention au nettoyage OAuth : `_authenticated` sait encore lire les sessions
`shokz_oauth` existantes et `_oauth_client` reste utilisé en production.
`save_private_json` sert aussi à la connexion par navigateur. Supprimer tout le
module `youtube_oauth.py` sans traiter ces dépendances casserait des parcours actifs.

## Structure et cohérence

- **Concentration dans `MainWindow`** : `ui.py` compte 1 391 lignes et cette classe
  possède 84 méthodes. Elle construit les widgets, orchestre YouTube, gère les
  périphériques, l'historique, les mutations et la copie locale. Extraire en priorité
  un contrôleur de périphérique et un service d'import local ; conserver les
  composants Qt existants plutôt qu'introduire une architecture générale.
- **Garanties divergentes entre files** : les contrôles d'identité du périphérique,
  les états terminaux et l'annulation diffèrent entre musique et livres. Centraliser
  les quelques politiques communes et leurs tests, sans fusionner les deux workflows.
- **Documentation vieillissante** : `audiobook_panel.py:436` annonce encore
  « one MP3 per book », alors que l'interface décrit un MP3 par chapitre.
  `docs/development.md:112–125` décrit le livre entier dans un fichier, seulement
  deux voix et un ancien texte par défaut ; le code propose huit voix et deux
  modèles d'annonce. Le même guide affirme encore qu'un double-clic télécharge un
  morceau, alors que `_result_double_clicked` modifie la liste d'envoi.
- **Portabilité de l'aperçu vocal** : `audio_playback.py:42–60` recherche un lecteur
  système Linux (`paplay`, `pw-play`, `aplay`, etc.) et propose d'en installer un
  si aucun n'existe. Les scripts de distribution n'embarquent pas ces lecteurs.
  L'aperçu n'a donc pas la même autonomie que la synthèse ; les smoke tests ne
  valident pas la lecture audio.
- **Prévention des régressions** : le workflow Forgejo déclenche les contrôles
  uniquement sur les tags de release. C'est documenté, mais cela reporte la détection
  des régressions à la publication. Exécuter aussi la qualité sur les propositions
  de changement ou sur la branche de développement.
- **Reproductibilité des builds** : les versions des dépendances, sauf Piper,
  sont décrites par des plages et aucun verrou de dépendances n'est suivi.
  Conserver un jeu de versions validé pour les releases et faire évoluer ce jeu
  explicitement, notamment pour yt-dlp et PyInstaller.

## Vérifications exécutées

Environnement local : Linux, Python **3.14.6** dans `.venv`.

| Vérification | Résultat |
| --- | --- |
| `.venv/bin/python -m pytest` | **206 tests réussis**, 6,77 secondes. |
| `.venv/bin/python -m ruff check .` | Réussi. |
| `.venv/bin/python -m ruff format --check .` | Réussi, 83 fichiers déjà formatés. |
| `.venv/bin/python -m mypy` | Réussi, 51 fichiers analysés. |
| `.venv/bin/python scripts/build_site.py --check` | Réussi, cinq langues et références locales validées. |
| `scripts/build_linux.sh` | Construction PyInstaller réussie et checksum produit. |
| Tests du binaire dans ce script | `--smoke-test` et `--tts-smoke-test` réussis. |
| Reproductions des constats 1 à 6 | Fakes, threads contrôlés par événements et dossiers temporaires ; résultats décrits ci-dessus. |
| Reproduction du constat 7 | Fichier généré localement avec le ffmpeg embarqué, sans réseau. |

Le journal de construction de cette session est dans
`/tmp/shokz-refill-audit-build.log` ; il s'agit d'un fichier temporaire, non versionné.
La construction a régénéré les artefacts Linux ignorés par Git.

Non exécutés : build et vérifications natifs Windows, exécution sous Python 3.11
(minimum déclaré) et 3.12 (version de la CI), tests sur appareil physique et accès
réels à YouTube Music ou Audiobookshelf. Un build Linux réussi ne prouve pas la
compatibilité Windows.

## Ordre de traitement proposé

1. Corriger la couverture des chapitres et l'identité du périphérique musical.
2. Corriger l'ordonnancement concurrent, la réservation des positions et les reprises.
3. Terminer correctement les annulations en attente et normaliser l'import local.
4. Supprimer le code inutilisé confirmé et mettre à jour les textes contradictoires.
5. Réduire les responsabilités de `MainWindow`, puis renforcer les contrôles avant release.
