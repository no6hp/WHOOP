# WHOOP Coach

Persönliche WHOOP-Datenanalyse: Deine Daten werden stündlich abgeholt, und Claude schickt dir
eine Auswertung aufs Handy (Push über die Claude-App):

| Wann | Was |
|---|---|
| **Jeden Morgen** | Recovery, Schlaf und die Belastung von gestern im Vergleich zu deinem Durchschnitt, dazu eine Trainingsempfehlung für heute |
| **Jeden Abend** | Belastung und Workouts des Tages (Herzfrequenzzonen), Stand bei den WHO-Aktivitätsminuten, empfohlene Schlafenszeit |
| **Sonntags** | Gesundheits-Check: 4-Wochen-Vergleich, alle Werte eingeordnet nach Fachstandards (AHA, WHO, AASM/NSF) und erklärt |

## So funktioniert es

```
WHOOP-Armband → WHOOP-Cloud ──(stündlich, GitHub Actions)──► verschlüsselte Daten im Branch `whoop-data`
                                                                        │
                       Claude-Routine (morgens/abends/sonntags) ◄───────┘
                       → Analyse → Push-Nachricht aufs Handy
```

**Datenschutz:** Dieses Repository ist öffentlich. Deshalb werden Tokens und Gesundheitsdaten
**nur AES-256-verschlüsselt** gespeichert, und die Logs enthalten keine Werte. Den Schlüssel
(`WHOOP_DATA_KEY`) kennen nur deine GitHub-Secrets und deine Claude-Umgebung. Noch sicherer
ist es, das Repo auf **privat** zu stellen (Settings → General → Danger Zone → Change visibility).

## Einrichtung (einmalig, ca. 15 Minuten)

### 1. WHOOP-Entwicklerzugang anlegen
Dein normaler WHOOP-Account reicht aus. Damit meldest du dich beim Entwickler-Portal an:
1. Öffne <https://developer-dashboard.whoop.com> und melde dich mit deinem WHOOP-Account an.
2. Lege ein Team an (beliebiger Name) und danach eine **App**:
   - **Name:** z. B. `Mein Coach`
   - **Scopes:** alle `read:*`-Häkchen setzen (recovery, cycles, workout, sleep, profile, body_measurement) sowie `offline`
   - **Redirect URL:** `https://github.com/no6hp/WHOOP`
3. Notiere dir **Client ID** und **Client Secret**.

### 2. Schlüssel erzeugen
Du brauchst ein langes, zufälliges Passwort als Datenschlüssel, mindestens 32 Zeichen. Nimm dafür einen
Passwort-Generator, z. B. den deines Passwortmanagers. Bewahre es gut auf: Ohne den Schlüssel
lassen sich die gespeicherten Daten nicht mehr lesen.

### 3. GitHub-Secrets eintragen
Gehe im Repo zu **Settings → Secrets and variables → Actions → New repository secret** und lege an:

| Name | Wert |
|---|---|
| `WHOOP_CLIENT_ID` | Client ID aus Schritt 1 |
| `WHOOP_CLIENT_SECRET` | Client Secret aus Schritt 1 |
| `WHOOP_DATA_KEY` | Schlüssel aus Schritt 2 |

### 4. Mit WHOOP verbinden
1. Öffne den Tab **Actions → „WHOOP Setup (Login)“ → Run workflow** und lass das Feld leer.
2. Öffne den fertigen Lauf. In der Zusammenfassung steht ein **WHOOP-Login-Link**. Öffne ihn und erlaube den Zugriff.
3. Danach landest du auf dieser GitHub-Seite. Kopiere die **komplette Adresse** aus der Adresszeile (sie enthält `?code=...`).
4. Starte **Run workflow** noch einmal und füge die Adresse ins Feld ein. Das muss innerhalb weniger Minuten passieren.
5. ✅ Die ersten bis zu 120 Tage werden synchronisiert. Ab dann läuft der Workflow **„WHOOP Sync“** stündlich.

### 5. Claude-Umgebung
Öffne in der Claude-App die Cloud-Umgebung dieses Projekts (Umgebungsmenü in der Titelleiste der Sitzung, dann
**Edit**) und lege diese Umgebungsvariablen an:
- `WHOOP_DATA_KEY`: derselbe Schlüssel wie in Schritt 2
- optional `WHOOP_BIRTH_YEAR` (z. B. `1990`) für altersbezogene Vergleiche wie HRV-Altersnorm und maximale Herzfrequenz

Schalte außerdem in der Claude-App die **Push-Benachrichtigungen** ein.

### 6. Routinen
Die geplanten Routinen für morgens, abends und den Wochen-Check legt Claude für dich an, sobald die Schritte 1–5 erledigt sind.

## Entwicklung
```bash
python3 -m unittest discover -s tests -t .   # Tests (synthetische Daten)
scripts/report.sh morning                    # Digest lokal ansehen (braucht WHOOP_DATA_KEY)
```
Hinweise für Claude und die Coaching-Regeln stehen in [`CLAUDE.md`](CLAUDE.md).

> Die Auswertungen dienen dem Coaching und ersetzen keine ärztliche Diagnose.
