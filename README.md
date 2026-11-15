# Akisames xStream Mod
Made with ❤️

---

## Über dieses Projekt

Aki-xStream ist ein **unabhängiger Fork**. Dieses Projekt wird eigenständig
gepflegt und steht in keinem Zusammenhang mit dem ursprünglichen
xStream Dev-Team.

---

## Lizenz

Dieses Addon steht unter der **GNU General Public License v3**.
Der vollständige Lizenztext liegt in der Datei `LICENSE`.

---

## Disclaimer

Aki-xStream ist ein Kodi-Addon, das Links zu Streams auf Drittanbieter-Seiten
findet und bündelt. Das Addon speichert, hostet und verteilt selbst keine
Inhalte — es zeigt nur, was auf externen Seiten ohnehin schon liegt.

Worauf du zugreifst und ob das in deinem Land erlaubt ist, liegt allein in
deiner Verantwortung.

**Nutzung auf eigene Verantwortung.**

---

## Credits & Danksagung

Ohne die Vorarbeit anderer gäbe es diesen Fork nicht.
Riesigen Respekt und Dank an:

**xStream Dev-Team Heptamer**
Für die ursprüngliche Codebase. Das gesamte Plugin-Gerüst, der
Site-Plugin-Mechanismus, die GUI-Architektur, die Hoster-Resolver-Integration
— alles steht auf dem Fundament das ihr über Jahre gebaut habt.

**xShip Dev-Team Kasi**
Für viele Patterns, Architektur-Ideen und konkrete Lösungen die in diesen
Fork eingeflossen sind.

**michaz**
Für Pflege über die Zeit.

**CarstenG2**
Danke für das Trailer-File und diverse Fixes.

**ParanoidTeam**
Für moralische und tatkräftige Unterstützung.

**Alle weiteren Contributors** der xStream/xShip-Linie über die Jahre, und alle
die sich bis heute tatkräftig beteiligen.

### Externe Dienste & Bibliotheken

**[Gujal00 / ResolveURL](https://github.com/Gujal00)**
Hoster-Resolver-Backbone von Kodi. Ohne ResolveURL gäbe es kein
zuverlässiges Stream-Resolving für die aggregierten Hoster.

**meinecloud**
Player-Dienst, hinter dem mehrere Seiten ihre Hoster bündeln. xStream fragt ihn
für Staffeln, Folgen und Hoster direkt ab.

**[Vavoo](https://vavoo.to/)**
Grundlage für den Live-TV-Bereich — Senderliste und Streams.

**[Internet Archive](https://archive.org/)**
Öffentliche Sammlungen als Quelle, angebunden über die Such-API der Seite.

**[TMDB](https://www.themoviedb.org/)**
Metadaten-Quelle für Filme und Serien, Cover, Posters, Bewertungen,
Trailer-IDs. Das Plugin nutzt die offizielle TMDB-API. Dieses Projekt
wird nicht von TMDB gesponsert oder anderweitig unterstützt.

**[UI Avatars](https://ui-avatars.com/)**
Platzhalterbilder für Personen ohne Foto im TMDB-Info-Dialog.

**[IMDB](https://www.imdb.com/)**
Trailer-Quelle: Direkt-Streams (MP4/HLS) über die IMDb-Schnittstelle, auch für
deutsche Fassungen — abspielbar ganz ohne YouTube-Addon.

**[KinoCheck](https://kinocheck.de/)**
Deutschsprachige Trailer-API. Erste Anlaufstelle für DE-Trailer in der
Trailer-Pipeline.

**[YouTube](https://www.youtube.com/)**
Unter anderem für die Trailer. Die Suche nach passenden Trailer-Videos läuft
über die offizielle YouTube Data API, die Wiedergabe über das Kodi-YouTube-Addon,
das xStream bei Bedarf installiert oder aktiviert.

**[2Captcha](https://2captcha.com/)**
Optionaler Captcha-Dienst für Seiten und Hoster, die ein Captcha verlangen. Er ist
kostenpflichtig und braucht einen eigenen API-Schlüssel, der in den
Einstellungen hinterlegt wird — ohne Schlüssel bleibt die Funktion schlicht aus.

**[Cloudflare DNS](https://www.cloudflare.com/dns/)**
Namensauflösung per DNS-over-HTTPS, wenn der normale Weg blockiert ist.

**[DDoS-Guard](https://ddos-guard.net/)**
Schutzsystem einiger Seiten. Die Freischaltung per Cookie holt sich xStream
automatisch, wenn eine Seite dahinter liegt.

**[GitHub](https://github.com/)**
Über die GitHub-API hält das Addon ResolveURL aktuell — es prüft den
master-Branch auf neue Commits und installiert die aktuelle Fassung direkt.