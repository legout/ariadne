# nao Context Builder im Detail – Vergleich mit Ariadne

**Datum:** 2026-10-13. **Klassifikation:** Recherche und Übernahmekandidaten, keine freigegebene Spezifikation, Ausführungsplanung oder Implementierung (planning-contract v1; installierte Skill-Provenienz unbekannt).

**Quellstände:** nao `94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0` (main, Commit 2026-10-13; `nao-core` nennt im Quellstand Version 0.1.9). Ariadne Runtime `a8d24b18d16854058e6b2b97bd1801cb0687ffbd`, unverändert während dieser Untersuchung. Die lokalen freigegebenen Specs 0021/0022/0023 und Tickets #66–#68 sind **nicht implementiert**. Spec 0023 liegt inzwischen in freigegebener Revision 2 vor (SHA-256 `d3d838b6424a2fa9e7a3e5fcdca10ea589547b8384bdf59d1534428fbb050258`); ihr SQL-/Feedback-Scope und Hash wurden mit dem aktuellen OPEN-Ticket #68 abgeglichen. Der untersuchte Ariadne-Git-Stand ist nicht gleichbedeutend mit dem bereits veröffentlichten PyPI-Release 0.2.0. Die ursprüngliche [Vergleichsnotiz vom September](2026-09-23-ariadne-ktx-nao-omnigraph-comparison.md) bleibt ein historischer Snapshot; insbesondere ihre Empfehlung eines Recorded-Trace-Tests wurde inzwischen durch die Owner-Entscheidung zur Abschaffung dieses Testtiers überholt.

**Later main integration and planning update (2026-10-13):** local and GitHub `main` were verified at `b20a61e1d2d5e234c88435338f0055fa539c7550`. #66–#68 are CLOSED and their implementation/fix commits are integrated, including native-reference quoting and active Example feedback. Statements below about their unimplemented status describe the original research snapshot, not this later main. No new feature acceptance or independent re-review of those completed changes was performed here. The remaining approved spec 0024 is now decomposed into canonical [C1 #69](https://github.com/legout/ariadne/issues/69) → [C2 #70](https://github.com/legout/ariadne/issues/70); C2 consumes C1's accepted committed result. Spec 0024/glossary source handoff and execution authority remain pending; no duplicate implementation-plan file is added.

**Methode und Grenze:** direkte Untersuchung der CLI-/Sync-/Template-/Provider-Implementierung, zugehöriger Tests und Skills sowie der relevanten Backend-Lese-, Query-, Feedback-, Memory-, Recommendation- und Review-Pfade. Ergänzend offizielle Docs und ein erster Partei-Blog. Zuerst Vault-Suche; sie ergab keinen einschlägigen nao-Context-Builder-Beitrag. Keine nao-Installation, kein Start fremden Codes, keine Verbindung zu Warehouses, keine LLM-Aufrufe und kein vergleichender Qualitäts-, Kosten- oder Performance-Benchmark. Tests wurden gelesen, nicht ausgeführt. Die Ergebnisse belegen implementierte Mechanismen und statisch nachvollziehbare Grenzen, nicht Deployment-Reife oder generelle Antwortüberlegenheit.

## 1. Kernaussage

nao ist stärker als **Context-Onboarding- und Analytics-Agent-Produkt**: vorhandene Quellen anschließen, strukturierte Evidenzdateien erzeugen, Menschen gezielt nach fehlendem Geschäftswissen fragen, Kontext navigierbar machen und aus Feedback Verbesserungen ableiten. Ariadne ist stärker auf **modellgebundene Berechnung, explizite Autoritätsgrenzen und prüfbare Antworten** zugeschnitten. Für Ariadne lohnt sich vor allem naos Kontext-Arbeitsweise – nicht die vollständige Chat-/Auth-/Deployment-Plattform. [N-readme] [N-setup] [N-rules] [A-query] [A-context]

Der Context Builder ist kein einzelner Modellaufruf und keine Vektordatenbank. Er besteht aus Konfiguration, Provider-Synchronisation, messender Introspektion, Markdown-Renderern, optionalen LLM-Zusammenfassungen und darauf aufbauender agentischer Kontextpflege. Der Standard-Agent kombiniert einen Routing-Prompt mit gezieltem Datei-Listing, Glob-Suche, Grep und Read. Persönliche Memories und Recommendations liegen dagegen in der Anwendungsdatenbank: Nicht die gesamte nao-Anwendung ist ein Markdown-Store. [N-sync] [N-engine] [N-agent] [N-search] [N-memory] [N-recommend]

## 2. Der vollständige Hauptablauf

```text
nao_config.yaml + vom Owner gewählter Scope
    ↓ nao init
Projektstruktur / RULES.md / Ignore-Datei / Agent-Erweiterungspunkte
    ↓ nao sync [-p provider:connection] [-s schema.table] [--threads N]
Provider → Warehouse-Metadaten / Messungen / Repo- und Dokumentsnapshots
    ↓ Tabellen-Templates und zusätzliche Projekt-Jinja-Templates
Versionierbare Dateien + Metadaten für Query-Guards
    ↓ setup-context / write-context-rules / audit-context
Geschäftliche Rückfragen, schlanke Context Map, gezielte Regeln
    ↓ normaler Analytics-Agent
Regeln + Kontextwegweiser → gezielte Dateilektüre → Query → Antwort
    ↓ Feedback / Kontext-Recommendations
Diagnose → vorgeschlagener Patch oder Upstream-Anleitung → Review Request
```

Dieser Weg hat kein generelles Ariadne-artiges Staging-/Admission-Gate zwischen jeder Sync-Datei und Agent-Lektüre. Git-/Review-Workflows existieren, sind aber von Quellensynchronisation, Empfehlung und tatsächlicher Aktivierung zu unterscheiden. [N-sync] [N-rules] [N-pr] [N-explorer]

### 2.1 Konfiguration und Setup

`NaoConfig` modelliert Datenbanken, Repositories, Notion, Confluence, Obsidian, LLM, MCP, Semantic Layer und weitere Integrationen. Env-Referenzen werden beim Laden aufgelöst. Bei `nao sync` dürfen ungültige optionale Sections mit Warnung fallen gelassen werden; Datenbank-/Repo-Konfiguration gehört nicht zu dieser optionalen Liste. Ein erfolgreicher Gesamtstatus allein beweist deshalb nicht, dass jede ursprünglich gewünschte optionale Integration aktiv war. [N-config]

Die Database-Type-Enum enthält 15 Varianten: Athena, BigQuery, ClickHouse, DuckDB, DuckLake, MotherDuck, Databricks, Fabric, Snowflake, MSSQL, MySQL, Postgres, Redshift, StarRocks und Trino. Das ist belegte Connector-Breite, keine hier getestete Gleichwertigkeit aller Backends. Der gemeinsame Zugang verwendet Ibis, ergänzt durch backend-spezifische Metadaten- und SQL-Methoden. [N-db-base]

`nao init --no-tty` unterstützt eine vorab geschriebene Konfiguration. Das Scaffold legt u. a. `databases/`, `docs/`, `semantics/`, `repos/`, Agent-Tools/-MCPs/-Skills/-Prompts, `tests/`, eine leere `RULES.md` und `.naoignore` an. Der Setup-Skill empfiehlt einen kleinen Scope (Ziel etwa 20, Skill-Grenze etwa 100 Tabellen). Diese Grenze ist **Skill-Guidance**, kein Runtime-Limit der Sync-Schleife. Er sammelt Warehouse, Scope, Zusatzquellen und LLM-Auswahl zusammen und verlangt Bestätigung der Config-Zusammenfassung vor dem Sync. [N-init] [N-setup]

**Wichtige Default-Nuance:** Das Config-Modell und der Setup-Skill verwenden `columns` und `preview`. Die interaktive Initialisierung fügt `ai_summary` hinzu, wenn ein LLM konfiguriert wird. „Standard-Sync ist immer ohne LLM“ wäre daher ungenau: Ohne AI-Template sind Metadaten/Messung deterministisch; AI-Templates benötigen den Annotation-Provider. [N-db-base] [N-config] [N-engine]

### 2.2 Scope und Orchestrierung

Die tatsächliche Sync-Registry besitzt sechs Provider: Notion, Confluence, Obsidian, Repositories, Databases und Semantics. Eine Config-Section allein bedeutet nicht, dass sie ein Sync-Provider ist; insbesondere ist die generische Repo-Synchronisation nicht automatisch ein dbt-/BI-Semantikparser. [N-providers]

`-p databases:name` begrenzt die Verbindung; `-s analytics.orders` bzw. Globs begrenzen Tabellen zusätzlich zu `include`/`exclude`. Selektionsmuster sind case-insensitive, die allgemeinen Config-Patterns verwenden direkt `fnmatch`. Bei einer Teilselektion bleibt die Tabellen-/Schema-Cleanup-Phase aus. `--threads` parallelisiert hier Datenbankverbindungen und verschiedene Provider-Items, nicht generell jede Spalte oder Tabelle einer einzelnen Datenbank. Provider laufen nacheinander; Fehler eines Providers verhindern nicht die Bearbeitung späterer Provider. Zurückgemeldete Provider- und Projekt-Template-Fehler führen am Ende zu Exit 1. [N-sync] [N-db-sync]

### 2.3 Was pro Tabelle entsteht

Typischer Pfad:

```text
databases/type=<type>/database=<identity>/schema=<schema>/table=<table>/
  columns.md       # Typen, Beschreibungen, Zeilenzahl, verfügbare physische Hinweise
  preview.md       # bis zu zehn Beispieldatensätze; kein repräsentatives Sample
  profiling.md     # opt-in: Spaltenstatistiken
  query_history.md # opt-in: beobachtete Nutzung und SQL-Muster
  ai_summary.md    # optionaler LLM-Überblick
  annotations.md   # einmal angelegte manuelle Hinweise
```

Generierte Tabellen-Dateien erhalten `type: generated`; `annotations.md` erhält `type: manual` und wird bei späteren Syncs nicht überschrieben. **Aber:** Das schützt nicht vor Entfernung ihres ganzen Tabellenverzeichnisses durch Cleanup. [N-markers] [N-cleanup]

Die Rollen werden dem Agenten ausdrücklich erklärt: Preview zeigt Formate, nicht Verteilungen; AI Summary dient Orientierung, nicht Ground Truth; Profiling liefert gemessene Werte; manuelle Annotationen haben im nao-Prompt bei Widerspruch Vorrang vor generierten Dateien. Dieser Vorrang ist naos Verhaltensregel und sollte nicht ungeprüft Ariadnes abgestufte Autorität ersetzen. [N-structure]

### 2.4 Introspektion und Profiling

`DatabaseContext` lädt Tabellen- und Spaltenmetadaten lazy und cached bestimmte Werte innerhalb eines Sync-Laufs. Unterklassen ergänzen z. B. Warehouse-Kommentare, Partitionierung, Clustering, Index-/Tabellendefinitionen und komplexe Typbehandlung. `columns.md` enthält bereits `row_count`; selbst ein kleiner Template-Satz ist also nicht durchgehend ein reiner Schema-Metadatenabruf. [N-db-context] [N-columns]

Profiling ermittelt Nulls, Distinct Counts, Min/Max sowie bei passenden numerischen Spalten Mean/Stddev. Integer-Spalten mit `_id`-Suffix, außer exakt `id`, werden von numerischen Lageparametern ausgenommen. Für kategoriale, nicht numerische und nicht zeitartige Spalten werden bei Distinct Count ≤50 bis zu zehn häufige Werte abgefragt. Arrays/komplexe Typen erhalten backendabhängig UNNEST-/String-Cast-Auswertung oder nur Null-Statistik. Einzelne fehlgeschlagene Spalten können aus dem Profil verschwinden; ein vollständig erfolgreicher Messumfang darf nicht aus dem Vorhandensein einer Profil-Datei abgeleitet werden. [N-db-context]

Backend-Anpassungen sind praktisch wertvoll: BigQuery nutzt für partitionierte Tabellen `INFORMATION_SCHEMA.PARTITIONS` zur Zeilenzahl und begrenzt Previews bei erforderlichen Partition-Filtern. Dieser Scope ist nicht gleich einem Volltabellen-Sample. Der Fehlerpfad der Zeilenzahl kann dort `0` zurückgeben; für Ariadne wäre ein explizites Unknown/Unavailable-Signal vorzuziehen. [N-bq]

**Ariadne besitzt Profiling bereits:** `profiler._profile_table` enthält zusätzlich Quartile, Approximate Unique und gemessene Key-Kandidaten. Die relevante Übernahmelücke ist nicht das Messen, sondern der Weg zur Agent-Nutzung: `_observation_facts` übernimmt in die generierten Tabellen-Beobachtungen derzeit nur Null-/Distinct Counts, Row Count, Scope und Key-Kandidaten. `top_values` und weitere Profilwerte sind in Authoring-Inputs vorhanden, aber nicht in diesem generierten Beobachtungsblock. [A-profile] [A-observations] [A-inputs]

### 2.5 Templates und LLM

Per-Table-Jinja-Templates haben Zugriff auf `db`; lokale Overrides unter `templates/databases/` gehen den mitgelieferten Templates vor. Zusätzliche Projekt-`*.j2` werden nach den Providern separat gerendert: z. B. `docs/report.md.j2` → `docs/report.md`, mit `nao.file`, `nao.notion`, `nao.obsidian` und `nao.config`. Template-Bearbeitung ist vertrauenswürdige Projekt-Autorentätigkeit, keine neue Governance- oder Sicherheitsgrenze. Der Datenbank-Template-Selector filtert über die konfigurierten Enum-Namen; die allgemeine Jinja-Phase ist davon verschieden. [N-engine] [N-render] [N-template-context]

`ai_summary` reicht Beschreibung, Spalten, bis zu zehn Preview-Zeilen und vorhandene Profiling-Daten an `prompt(...)`. Ohne Profiling werden Qualitäts-/Verteilungsbehauptungen ausdrücklich untersagt; die Preview wird als nicht repräsentativ bezeichnet. Ein fälliger AI Summary kann Profiling neu berechnen, auch wenn die separat geschriebene Profiling-Datei eingefroren bleibt. Die gelesenen Refresh-Tests dokumentieren dieses Verhalten. [N-ai] [N-refresh-tests]

Für Ariadne: nützliche Präsentation kann deterministisch sein; keine frei programmierbare Template-/LLM-Schicht nötig, solange vorhandene OKF-Renderer die Aufgabe erfüllen. Preview-Werte, Kategorien und SQL-Literale können sensibel sein. Source Approval und bewusste Offenlegung bleiben wichtig; ein AI-Prompt mit Warnhinweis ist keine Redaction oder fachliche Verifikation.

### 2.6 Refresh und Wiederaufnahme – genauer als „inkrementell“

Für Profiling und AI Summary gibt es `always`, `once`, `interval`. Die Entscheidung hängt von Dateiexistenz und bei Intervall von `**Computed at:**` im Markdown ab, nicht generell von Schema-/Daten-/Config-/Template-Hashes. `once` kann trotz geänderter Quelle alte Evidenz stehen lassen. `columns` und `preview` werden im ausgewählten Scope normalerweise erneut gerendert. Es gibt keinen in diesem Datenbank-Sync sichtbaren universellen, persistierten Per-Stage-Resume-Graph. [N-db-sync] [N-db-base]

**Confluence ist tatsächlich versionsinkrementell:** gespeicherte Page-ID/Version plus aus Suchresultaten bekannte Version erlauben Wiederverwendung unveränderter Dateien. Explizit einzeln konfigurierte Pages/Tree-Roots ohne Versionshinweis werden weiter geholt. Bei Fetch-/Write-Teilfehlern wird destruktives Stale-Cleanup ausgelassen. Notion besitzt ebenfalls einen solchen Teilfehler-Cleanup-Schutz. [N-confluence] [N-notion]

**Repositories sind anders:** Git-Quellen werden neu in einen temporären Ordner geklont, gefiltert, `.git` entfernt und anschließend ersetzt. Lokale Repo-Pfade werden kopiert; der aktuelle Runtime-Code unterstützt sie, obwohl `setup-context` nur SSH-URLs empfiehlt. Obsidian kopiert Markdown-Snapshots aus dem Vault, überspringt versteckte Pfade und entfernt nicht mehr gesyncte Markdown-Dateien. Das ist nicht Lumios Claim-/Page-Graph oder öffentliche Retrieval-API. [N-repos] [N-obsidian] [N-setup]

**Ariadne hat bereits einen gezielten Refresh:** `refresh_schema` akzeptiert explizite `(source, catalog, schema, table)`-Assets, liest nur die angeforderten Tabellen über die genehmigte Source Identity, bindet Änderungen an die Candidate Revision, bewahrt Autorenbedeutung und archiviert entfernte/typgeänderte Bedeutung. Identische Eingaben sind ein No-op. Deshalb kein zweites Select-/Schema-Refresh-System bauen. Zusätzlicher Wert wäre Ressourcen-/Stufen-Frische und gezielte Wiederaufnahme für einen konkret teuren Importweg. [A-refresh] [A-table]

### 2.7 Query History: Muster, nicht freigegebene Joins

Der Builder holt SQL-Historie über die bereits offene Sync-Verbindung, unterstützt backendabhängige oder eigene History-SQL-Abfragen und Regex-Ausschlüsse. SQLGlot extrahiert Table References und Join-Paare; CTE-Referenzen werden berücksichtigt, bei Referenzen existiert ein Regex-Fallback. Pro Tabelle werden Usage Count, häufige Join-Partner und Top SQL gerendert. [N-db-sync] [N-history] [N-history-template]

Zwei wichtige Grenzen:

- Die Statistik zählt die gelieferten Query-Text-Einträge. Postgres liest `query_text` aus `pg_stat_statements`, jedoch weder `calls` als Gewicht noch eine echte `{days}`-Zeitbegrenzung in seiner Standardabfrage. Die Zahl ist dort nicht automatisch historische Ausführungshäufigkeit im angezeigten Zeitfenster. [N-pg] [N-history]
- `_matches_table` akzeptiert auch allein den letzten Tabellennamen. Gleichnamige Tabellen verschiedener Schemas können dadurch derselben historischen SQL zugerechnet werden. Solche heuristische Zuordnung wäre in Ariadne nur unsichere Evidenz, keine vollqualifizierte Bindung. Beobachtete Join-Partner beweisen weder Join-Bedingung noch Kardinalität oder sicheren Grain. [N-history] [A-refresh] [A-query]

Das ist ein nützlicher eigenständiger Import-Kandidat. **#68 speichert dagegen SQL aus ausdrücklich bestätigten künftigen Ariadne-Examples; es importiert keine externe SQL-Historie.**

## 3. Agentische Kontextarbeit: die eigentliche Stärke

### 3.1 `RULES.md` als Wegweiser

Der Standard-Systemprompt lädt Projektregeln, konfigurierte Verbindungen, Fähigkeiten, Kontextpräsenz und optionale User Memories. `write-context-rules` verlangt zunächst eine Bestandsaufnahme: existierende Tabellen-Dokumentation, dbt-/ETL-Repos, Domänendokumente und Semantic Layer. Danach entstehen Business Overview, Datenarchitektur, Context Map, knappe Tabellenzeiger, Datumsregeln und Analysis Process. [N-agent] [N-rules]

**Keine zweite Wahrheit:** Metrikformeln werden nicht in `RULES.md` wiederholt, wenn sie bereits im Semantic Layer oder in einer Quelldefinition liegen. Tabellen-Details werden ausgelassen, wenn bessere Dokumentation existiert. Das ist eine konkrete Stale-/Token-Vermeidungsstrategie, nicht nur die Empfehlung „halte den Prompt kurz“. [N-rules]

Gezielte Fragen schließen echte fachliche Lücken: Wochenbeginn, laufende versus abgeschlossene Perioden, Geschäftsjahr, Metrikquelle und unklare Definition. Der Prozess lautet: Definition klären → relevante Docs → Tabellen → beobachtete Filterwerte → Query → Plausibilitätsprüfung → Interpretation. Profiling-Top-Werte sind eine begrenzte Beobachtung, keine vollständige Enum-Domäne. Ein fehlender Top-Wert darf deshalb nicht beweisen, dass ein Filterwert nicht existiert. [N-rules] [N-db-context]

Ariadnes bestehende Skill-Routen, Unified Discovery, OKF-Indizes sowie Listing/Read liefern hierfür bereits viele Primitive. Übernehmen sollte man **projektbezogene Wegweisung und bessere Priorisierung**, nicht daneben eine zweite Definitionssammlung. [A-skill] [A-context]

### 3.2 Kontext-Audit

`audit-context` untersucht Anschluss-/Sync-Stand, Scope, Regeln, Tabellenabdeckung, widersprüchliche Metrikdefinitionen, unklare Felder/Einheiten, Testfehler und Token-Bloat. Fehler werden unterschieden: Datenmodell, Datum, falscher Test, Interpretation und Metrikdefinition. Der Skill diagnostiziert, statt sofort selbst zu reparieren. Das ist stärker als nur ein Syntaxvalidator, bleibt aber agentisches Urteil und kein deterministischer Beweis vollständiger fachlicher Abdeckung. [N-audit]

Für Ariadne lohnt ein kleiner **semantischer Gap Report** in vorhandener Status-/Review-Guidance: Welche reale Frage ist nicht durch freigegebene Definitionen abgedeckt? Welche bekannte Definition widerspricht einer anderen? Was ist unbekannt? Kein künstliches Ziel „jede Tabelle braucht einen Test“ und keine pauschale Scope-Grenze ohne Ariadne-spezifische Evidenz.

### 3.3 Feedback → Verbesserungsvorschlag → Review

nao speichert Up/Down-Feedback mit optionaler Erklärung zu konkreten Nachrichten und benachrichtigt das Data Team. Die Recommendation-Analyse verarbeitet Nutzungs-/Feedback-Evidenz und teure Kontextdateien, priorisiert Findings, dedupliziert über Fingerprints und führt den Recommendation-Lifecycle. Ein beschränkter Analyse-Agent sammelt Vorschläge statt beliebiger Live-Änderungen. [N-feedback] [N-recommend]

Der Fix Collector speichert Before/After-Edits; generierte Warehouse-Dateien werden nicht direkt gepatcht. Stattdessen entstehen Änderungen an menschlichen Dateien, an verknüpften Upstream-Repos oder eine manuelle Anleitung. Review Requests verwenden einen frischen Clone, Branch, Commit und Push, ohne den Live-Kontext dabei direkt zu mutieren. Der Context Explorer arbeitet bei bearbeitbaren Git-Dateien in einem separaten Worktree und prüft `expectedHash`; generierte, gerenderte und synchronisierte Dateien werden im Editor als read-only geroutet. [N-fix] [N-pr] [N-explorer]

**Status-Nuance:** Der optionale Auto-PR-Modus markiert Recommendations beim Öffnen eines PR bereits als `applied`; das beweist weder Merge noch Live-Aktivierung. In Ariadne müssen proposed/reviewed/admitted/published weiterhin getrennt bleiben. [N-pr]

**Keine gleichwertigen Speicherereignisse:** ein Thumbs-up, User Memory, historisches SQL und ein ausdrücklich bestätigtes Answer Example erfüllen verschiedene Verträge. naos aktivierbare Memory-Extraktion schreibt persönliche Fakten/Instruktionen im Hintergrund und injiziert sie später; das ist kein Vorbild für stilles Ariadne-Example-Lernen. Der Owner hat für die gewünschte aktive Rückfrage „Ariadne-Skill“ und „nur ohne passendes reviewed Example“ ausgewählt; der Zuschnitt ist inzwischen in Spec 0023 Revision 2 und #68 festgehalten, aber nicht implementiert. [N-memory] [A-examples] [A-example-adr]

### 3.4 Evaluation

`nao test` lädt Prompt-/Reference-SQL-YAML und optionale Tool-Call-Assertions, ruft den echten Agenten über seinen Backend-Client und erfasst Kosten, Tokens, Laufzeit und Ergebnisse. DataFrame-Vergleich berücksichtigt konfigurierte Toleranzen. Die Verifikation lässt außerdem eine Query über bereits erhaltene Ergebnis-Tabellen erzeugen; deshalb ist dies nicht bloß ein deterministischer Vergleich der sichtbaren Antwortprosa. Eine gute Referenz muss unabhängig korrekt sein. [N-test-case] [N-test] [N-verification]

Ariadnes eigene Zahl-/Compiler-Fixtures bleiben wertvoll; reale Agent-Checks sind nach Owner-Entscheidung manuell. **Kein Wiedereinführen des Recorded-Trace-Tiers und kein neuer Live-Agent-Testservice durch diese Recherche.** Eine kleine manuelle Fragesammlung mit unabhängigem Erwartungswert und Caveats wäre eine gesonderte, bedarfsgebundene Weiterentwicklung, nicht automatisch eine Portierung von `nao test`.

## 4. nao hat echte Runtime-Gates – trotzdem andere Governance

Die Aussage „nao ist nur freies SQL plus Prompt“ ist im untersuchten Stand falsch:

- Der Backend-SQL-Pfad blockiert standardmäßig schreibendes SQL; gefährliche Schreibrechte sind ein ausdrückliches Setting. Bestimmte Server-Passthrough-Funktionen werden zusätzlich blockiert. [N-sql]
- Die Python-Ausführungskette unterstützt kontextbasierte Tabellen-Allowlisting-/Gruppen-Checks, ausgeschlossene Spalten und Row-Security-Rewriting. Welche Policies in einem Deployment aktiviert und wirksam sind, wurde hier nicht getestet. [N-fastapi] [N-allowlist]
- MetricFlow kann aus einem `dbt parse`-Manifest lokal Definitionen kompilieren. Die Modes sind u. a. `prioritized` und `exclusive`; der Default bei vorhandenem Semantic Layer ist `prioritized`. `exclusive` verweigert handgeschriebenes Warehouse-SQL, erlaubt aber weiter lokale DuckDB-Abfragen über Dateien/Ergebnisse. [N-sem-config] [N-sem-sync] [N-sem-runtime] [N-types] [N-sql]

**Skill und Runtime nicht verwechseln:** `add-semantic-layer` unterscheidet noch lesbare YAML-/Markdown-Semantikdateien von einem ausführbaren Metric Store. Sein dbt-Pfad führt über dbt Cloud/MCP und sagt für diesen Pfad, lokales dbt Core sei nicht unterstützt. Der aktuelle native Runtime-Pfad unterstützt dagegen das lokale MetricFlow-Manifest ausdrücklich ohne dbt-Cloud-Plan. Ein `semantics/semantic.yaml` aus dem Skill ist daher nicht automatisch ein nativer kompilierbarer MetricFlow-Vertrag. Für Übernahmen immer die konkrete Schnittstelle und den Quellstand benennen, nicht nur den Begriff „Semantic Layer“. [N-sem-skill] [N-sem-config] [N-sem-sync]

Ariadnes Unterscheidungsmerkmal liegt nicht in „nao kennt keinen Semantic Layer“, sondern in der eigenen durchgängigen Kombination aus Source Approval, versionierten Proposals, Compile-/Bind-/Live-Grain-Checks, Human Admission und typisiertem OKF-Policy-/Caveat-Kontext am Ergebnis. nao bietet dagegen zusätzliche Mehrbenutzer-/UI-Zugriffspfade, deren Berechtigungssystem nicht mit Ariadnes fachlicher Admission gleichzusetzen ist. Kein pauschales Sicherheitsranking aus unterschiedlichem Produktumfang ableiten. [A-refresh] [A-query] [A-context]

## 5. Konkrete Grenzen, die wir nicht übernehmen sollten

**Statisch nachvollziehbar, nicht in einem laufenden nao reproduziert:**

1. **Per-Table-Template-Fehler können erfolgreiche Provider-Ergebnisse überleben.** `sync_database` fängt Render-Fehler ab, schreibt eine Datei mit `Error generating content` und zählt den Fehler lokal. Der zurückgegebene `DatabaseSyncState` trägt diesen Fehler nicht als Provider-Failure; der Provider baut seine Failure-Liste aus Exceptions. Projekt-Jinja-Fehler werden dagegen sauber bis zum CLI-Exit zurückgemeldet. Die gelesenen Logging-Tests erwarten ausdrücklich die Error-Datei. Für Ariadne dürfen solche Platzhalter keine erfolgreiche validierte Evidenz sein. [N-db-sync] [N-cleanup] [N-render] [N-error-tests]
2. **Database-Cleanup ist nicht so konservativ wie Notion/Confluence-Cleanup.** Scheitert `list_tables` für ein Schema, wird es als failed markiert, aber nicht als gesynct in den Context-Tree-State aufgenommen. Beim vollen Lauf kann nachher `cleanup_stale_paths` das frühere Schema-Verzeichnis einschließlich manueller Annotationen entfernen. Die Column-Catalog-Merge-Logik erhält fehlgeschlagene Schemas für den Guard-Katalog, schützt damit aber nicht denselben Context-Dateibaum. Teilselektion unterdrückt diesen Cleanup. Ariadne sollte aus fehlender Beobachtung keine Löschberechtigung ableiten. [N-db-sync] [N-cleanup]
3. **Zeitbasierte Refresh-Policies beweisen keine Source-Frische.** `once`/`interval` brauchen in Ariadne eine bewusst festgelegte Gültigkeit, Input-Identität und Unknown-/Stale-Signale; kein stilles „noch gültig“. [N-db-sync]
4. **History-Muster sind keine Join-/Grain-Autorität.** Basename-Matching, unterschiedliche History-Zeitfenster und nicht gewichtete Text-Einträge begrenzen die Aussagekraft. [N-history] [N-pg]
5. **Preview/Summary benötigen Offenlegungsentscheidungen.** Zehn Rohzeilen sind echte Daten, nicht anonymisierte Metadaten. Statistische Beobachtungen sind keine deklarierten Constraints. [N-preview] [N-ai] [A-table]
6. **Lizenz ist nicht pauschal Apache für jedes File.** Root `LICENSE` nimmt `@license Enterprise`-Dateien ausdrücklich aus. Vor tatsächlicher Codeübernahme pro Datei prüfen; diese Untersuchung empfiehlt vor allem Muster, keine ungeprüfte Codekopie. [N-license]

## 6. Vergleich: stärker, einfacher, besser – mit Scope

| Aspekt | nao | Ariadne heute | Urteil |
| --- | --- | --- | --- |
| Vorhandenes Warehouse-/Repo-/Wiki-Wissen anschließen | 15 DB-Types, sechs Sync-Provider, versionierte Dokumentimporte | DuckDB-Registry, Dokument-Ingestion, Source-Proposals/Harness-Inputs | nao breiter und bequemer für vorhandene Warehouse-Stacks |
| Kontext für Agenten verständlich machen | Projekt-Context-Map, Definition-vor-Tabelle, explizite File-Rollen | Generischer Skill, OKF-Indizes, Discovery und fachliche Policies | nao konkreter im projektbezogenen Routing; Primitive in Ariadne bereits vorhanden |
| Physisches Profiling | Backend-spezifische Hinweise und gut lesbares JSONL | Bereits umfangreiche Statistik, Key-/FK-Kandidaten und Scope | Kein pauschaler nao-Sieg; Agent-Surfacing ist der sinnvolle Gap |
| Generiertes vs. menschliches Wissen | Separate Dateien/Editor-Ownership | Getrennte Core-/Meaning-/History-Sections, revisionierter Refresh | nao einfacher sichtbar; Ariadne bereits differenziert und nicht neu zu bauen |
| Partial Refresh | CLI-Select, zeitbasierte Policies; Confluence-Versionen | Exakte Assets, Source Approval, No-op, Bedeutungserhalt | Ergänzende Stärken; „Ariadne hat keinen inkrementellen Refresh“ wäre falsch |
| Business-Konventionen aufnehmen | Kleine gezielte Fragen im Rules-Skill | Policies/Glossar/References mit Review | Interview-Methode übernehmen, Ergebnisse als Proposals |
| Context-Lifecycle/Feedback | UI, Diagnose, priorisierte konkrete Fixes und PRs | Bestätigte Examples und vorhandene Proposal-/Admission-Routen | nao hat den reicheren geschlossenen Verbesserungsprozess |
| Berechnung und Autorität | Raw SQL mit Guards; optional MetricFlow exklusiv | Modellgebundener Compiler, Grain und Human Admission | Ariadne stärker auf den eigenen Governance-Vertrag fokussiert |
| Einfachheit des Einstiegs | Wenige Kommandos vom Init zum nutzbaren Chat | Mehr ausdrückliche Autoritäts-/Review-Schritte; verbessertes Setup vorhanden | nao weniger Reibung; nicht jede Reibung ist unnötig |
| Betrieb als Komponente für externe Agenten | Zusätzlich eigener UI/TS-/Python-/App-DB-Stack | Lokales Python-/DuckDB-Paket, CLI/optionales MCP | Ariadne schlanker; nao als Gesamtprodukt nicht „einfacher“ |

## 7. Priorisierte Übernahmekandidaten – kein Implementierungsauftrag

1. **Projektbezogenes Context Routing.** Bestehende OKF-Indizes/Discovery/Skill-Guidance um knappe Wegweisung ergänzen: Wo ist die gültige Definition, die Datums-Policy, die Tabellen-Evidenz? Keine zweite Metrikdefinition und kein neuer Indexdienst. Kleine Shape-/Guidance-Änderung.
2. **Bereits gemessene Filterwerte nutzbar machen.** Bestehende Profilwerte bounded und mit Scope/Observed-at in Agent-lesbarer Evidenz darstellen; vor Filtern tatsächliche Kategorien prüfen. Keine neue Profiling-Engine. Top-Werte sind kein vollständiger Wertebereich; fehlende Evidenz bleibt Unknown. Benötigt einen definierten Sichtbarkeits-/Freshness-Vertrag.
3. **Gezieltes Business-Onboarding.** Wenige konkrete Fragen zu Wochenbeginn, unvollständigen Perioden, Quelle/Einheit und unklarer Bedeutung. Antworten werden source-linked Staging-/Git-Proposals, nicht automatisch autoritative `RULES.md`-Formeln. Geeigneter Bestandteil bestehender Setup-/Authoring-Guidance.
4. **Einen realen Wissensimport.** dbt-/BI-/SQL-History- oder Wiki-Quelle nach tatsächlichem Bestand wählen. Der Repo-Import kann zuerst Evidenz aufnehmen; echte Semantikübersetzung ist ein eigener Mapping-/Review-Vertrag. Keine 15-Connector-Portierung und kein Wechsel von OSI/DuckDB zu Ibis/MetricFlow.
5. **Ressourcen-/Stufen-Frische auf einem teuren Pfad.** Vorhandenen selektiven Refresh nutzen; eine konkrete teure Dokument-/Import-Stufe mit Input-Fingerprint, erfolgreichem Stand und wiederaufnehmbaren Teilfehlern ergänzen. Keine pauschale Scheduling-/Sync-Plattform, keine destruktive Löschung nach Teilfehlern.
6. **Feedback → überprüfbarer Vorschlag.** Fachliche Korrektur an konkrete Definition/Policy/Methode binden und einen Proposal-Diff vorbereiten. Ariadnes ausdrückliche Zustimmung zur Aufbewahrung bleibt nötig; Feedback, Example, Verbesserungsvorschlag und Admission bleiben unterschiedliche Ereignisse. Die in #68 geplante aktive Skill-Rückfrage ist ein kleiner erster Teil, nicht bereits der vollständige nao-Recommendation-Service.
7. **Kleiner Context-Gap-Audit.** Vorhandene Status-/Review-Oberflächen um reale semantische Lücken, bekannte Widersprüche und Stale-/Unknown-Zustände ergänzen. Kein generisches Tabellen-Testquotenziel und keine weitere Prozess-Ledger-Datei.

**Für die derzeitige Reihenfolge:** #68 umfasst bereits SQL-Provenienz **und aktive zustimmungsgebundene Skill-Rückfragen**; #66/#67 bleiben Verbatim/Native DuckDB. Diese Recherche erweitert keine dieser Ausführungsfreigaben. Danach sehe ich Routing + Filterwert-Evidenz als besonders kleine, konkrete Ergänzungen und einen realen Wissensimport als größten zusätzlichen Produktnutzen. Hybride Suche bleibt wie vom Owner entschieden zurückgestellt; naos dateibasierter Builder belegt, dass bessere Kontextorganisation nicht auf Embeddings warten muss.

**Speicherfolgerung:** Das bestätigt die Eignung von OKF als kanonischer, reviewbarer Example-Store außerhalb des Context Layers. Eine spätere LanceDB kann einen wiederaufbaubaren Suchindex liefern; dafür ist weder eine Umwandlung historischer Examples in Policies noch eine Ablösung der OKF-Quelle nötig. Das ist eine Anschlussfolgerung, keine durch nao bewiesene LanceDB-Qualitätsaussage. [A-example-adr] [A-examples] [N-structure]

## Design follow-up

The owner selected a reviewed Context Routing Map, explicitly selected filter-value columns and skill-led Business Onboarding, then approved the complete V1 in-chat design with “Ja passt”. [Specification 0024](../specs/2026-10-13-0024-context-routing-filter-evidence-and-onboarding.md) captures this bounded subset; the owner approved its complete written revision 1 with “Passt” on 2026-10-13, including type-bound selection and the 8-KiB value-evidence limit. The broader import, refresh, recommendation and audit candidates above remain research, not approved implementation scope. No ticket or execution authority follows from this design capture.

## Quellen

Alle GitHub-nao-Quellen sind auf den oben genannten Commit gepinnt. Die lokalen Ariadne-Codequellen wurden unverändert am genannten Runtime-HEAD gelesen; lokale Feature-Dokumente sind als noch nicht implementiert markiert. Live-Dokumentation kann vom gepinnten Code abweichen; die alte, im Suchergebnis genannte URL unter `context-engineering/context-builder` lieferte 404. Die korrekten Docs liegen unter `context-builder/...`.

[N-readme]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/README.md
[N-config]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/config/base.py
[N-init]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/init.py
[N-setup]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/skills/setup-context/SKILL.md
[N-providers]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/sync/providers/__init__.py
[N-sync]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/sync/__init__.py
[N-db-base]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/config/databases/base.py
[N-db-context]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/config/databases/context.py
[N-db-sync]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/sync/providers/databases/provider.py
[N-markers]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/sync/markers.py
[N-cleanup]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/sync/cleanup.py
[N-columns]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/templates/defaults/databases/columns.md.j2
[N-preview]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/templates/defaults/databases/preview.md.j2
[N-bq]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/config/databases/bigquery.py
[N-engine]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/templates/engine.py
[N-render]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/templates/render.py
[N-template-context]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/templates/context.py
[N-ai]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/templates/defaults/databases/ai_summary.md.j2
[N-refresh-tests]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/tests/nao_core/commands/sync/test_provider_refresh.py
[N-error-tests]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/tests/nao_core/commands/sync/test_provider_error_logging.py
[N-confluence]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/sync/providers/confluence/provider.py
[N-notion]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/sync/providers/notion/provider.py
[N-repos]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/sync/providers/repositories/provider.py
[N-obsidian]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/sync/providers/obsidian/provider.py
[N-history]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/sync/providers/databases/query_history.py
[N-history-template]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/templates/defaults/databases/query_history.md.j2
[N-pg]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/config/databases/postgres.py
[N-rules]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/skills/write-context-rules/SKILL.md
[N-audit]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/skills/audit-context/SKILL.md
[N-agent]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/services/agent.ts
[N-structure]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/components/ai/nao-context-structure.tsx
[N-search]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/agents/tools/search.ts
[N-feedback]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/trpc/feedback.routes.ts
[N-memory]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/services/memory.ts
[N-recommend]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/services/context-recommendations.service.ts
[N-fix]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/agents/tools/propose-context-fix.ts
[N-pr]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/services/context-pr.service.ts
[N-explorer]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/services/context-explorer.service.ts
[N-test-case]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/test/case.py
[N-test]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/test/runner.py
[N-verification]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/services/test-agent-verification.ts
[N-sql]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/agents/tools/execute-sql.ts
[N-fastapi]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/fastapi/main.py
[N-allowlist]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/config/databases/allow_listed_only_guard.py
[N-sem-skill]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/skills/add-semantic-layer/SKILL.md
[N-sem-config]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/config/semantic_layer/__init__.py
[N-sem-sync]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/cli/nao_core/commands/sync/providers/semantic_layer/provider.py
[N-sem-runtime]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/backend/src/services/semantic-layer.service.ts
[N-types]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/apps/shared/src/types.ts
[N-license]: https://github.com/getnao/nao/blob/94ae6c9844cbb1e4f9cc5a5276d951c195aa0fc0/LICENSE
[A-query]: ../../src/ariadne/query.py
[A-context]: ../../src/ariadne/context.py
[A-profile]: ../../src/ariadne/profiler.py
[A-observations]: ../../src/ariadne/context.py#L1053
[A-inputs]: ../../src/ariadne/authoring.py
[A-refresh]: ../../src/ariadne/authoring.py#L2335
[A-table]: ../../src/ariadne/context.py#L1110
[A-skill]: ../../src/ariadne/skill_assets/SKILL.md
[A-examples]: ../specs/2026-09-29-0007-answer-examples.md
[A-example-adr]: ../adr/0015-separate-answer-example-store.md

**Offizielle ergänzende Quellen (live, nicht commit-gepinnt):** [Synchronisation](https://docs.getnao.io/nao-agent/context-builder/synchronization), [Database Context](https://docs.getnao.io/nao-agent/context-builder/databases), [Rules](https://docs.getnao.io/nao-agent/context-builder/rules-context), [Context Stack](https://getnao.io/blog/how-to-build-context-stack-for-agentic-analytics/). Produkt-/Benchmark-Behauptungen dieses Blogs wurden nicht als unabhängiger Qualitätsnachweis übernommen.
