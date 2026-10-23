---
name: trader-journal
description: >-
  Journal de trades et statistiques honnêtes. Enregistre chaque trade clôturé,
  en simulation ou en réel : entrée, stop, sortie, quantité, frais et respect
  du plan. Calcule taux de réussite, R moyen, espérance par trade, profit
  factor, drawdown maximal, pire série perdante, résultats par setup, et rend
  un verdict qui tient compte de la taille de l'échantillon. À utiliser pour
  « note ce trade », « ajoute au journal », « mes stats », « est-ce que ma
  méthode marche ? », « je peux passer en réel ? » ou après la sortie d'une
  position. Répond en français, sans passer d'ordre.
argument-hint: "[add | list | stats]"
---

# trader-journal

## Langue et format de restitution

Répondre en français naturel, avec le tutoiement. Expliquer brièvement les termes techniques utiles ; garder les noms de commandes, chemins, clés JSON, symboles et paramètres tels quels. Les prix restent en USD. Ne jamais arrondir un résultat à l'avantage de l'utilisateur ni masquer un verdict défavorable.

Le journal mesure ce que la méthode a réellement produit. Il ne prédit rien. Un bon historique en simulation n'est pas une garantie en réel : l'exécution, les frais réels et la psychologie changent avec de l'argent réel.

`${CLAUDE_SKILL_DIR}` désigne le dossier de ce skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/journal.py" add --symbol TSLA --entry 364.18 --stop 358.32 --target 370.04 --exit 370.04 --qty 8 --fees 0 --setup orb --followed oui
python3 "${CLAUDE_SKILL_DIR}/journal.py" add --from-plan --exit 358.10 --qty 8 --followed non --note "entré avant la clôture de la bougie"
python3 "${CLAUDE_SKILL_DIR}/journal.py" list --last 10
python3 "${CLAUDE_SKILL_DIR}/journal.py" stats
python3 "${CLAUDE_SKILL_DIR}/journal.py" stats --setup orb --json
python3 "${CLAUDE_SKILL_DIR}/journal.py" remove --id 3
```

## Fichiers

| Fichier | Usage |
| --- | --- |
| `trader/journal.json` | Écrit par `add` et `remove` : liste `trades[]` avec `id`, `date`, `symbol`, `setup`, `entry`, `stop`, `target`, `exit`, `qty`, `fees`, `risk_usd`, `pnl_gross`, `pnl_net`, `r`, `followed_plan`, `note`. |
| `trader/plan.json` | Lu par `add --from-plan` : symbole, entrée, stop, objectif, setup et date écrits par trader-exit. |

## Définitions

- **R** : résultat net divisé par le risque initial au stop. +1R = gagné autant que le risque prévu ; -1R = perte égale au risque prévu ; moins de -1R = stop dépassé ou plan non respecté.
- **Espérance** : gain ou perte moyen par trade, frais inclus. C'est le chiffre qui compte.
- **Profit factor** : somme des gains divisée par la somme des pertes. Sous 1, la méthode perd.
- **Drawdown maximal** : pire baisse du résultat cumulé depuis un sommet.
- **Intervalle 95 %** : plage plausible du R moyen réel. Tant qu'elle contient zéro, le résultat ne se distingue pas du hasard.

## Verdict

| Verdict | Condition |
| --- | --- |
| `TROP TOT` | Moins de 30 trades. |
| `PERDANT` | Borne haute de l'intervalle sous zéro. |
| `PAS DE PREUVE D'AVANTAGE` | L'intervalle contient zéro. |
| `AVANTAGE PROBABLE` | Borne basse au-dessus de zéro ; à confirmer sur la durée. |

## Déroulement

1. Après chaque sortie, demander : prix de sortie réel, quantité, frais, et **si le plan a été respecté** (`--followed oui` ou `non`). Ne jamais répondre à la place de l'utilisateur.
2. Si `trader/plan.json` correspond au trade, utiliser `--from-plan` ; sinon demander entrée et stop.
3. Enregistrer **tous** les trades, y compris les pertes et les erreurs. Un journal qui oublie les mauvais trades est faux.
4. Pour `stats`, commenter d'abord le verdict, puis l'espérance, puis l'écart entre trades avec et sans respect du plan.
5. Si l'utilisateur demande s'il peut passer en réel : rappeler le verdict tel quel. Avant 30 trades ou sans `AVANTAGE PROBABLE`, dire clairement que les chiffres ne le justifient pas.

## Limites

- Positions longues uniquement, comme le reste du pack.
- L'intervalle suppose des trades indépendants ; avec peu de trades ou une seule action, il reste optimiste.
- Le journal ne vérifie pas les prix auprès du courtier : il enregistre ce que l'utilisateur déclare.
- 30 trades est un minimum pour parler, pas un seuil de preuve.

## Sécurité

- Outil éducatif, pas un conseil financier personnalisé.
- Aucun ordre placé, aucune connexion au courtier.
- Ne jamais modifier ni supprimer un trade sans demande explicite de l'utilisateur.
