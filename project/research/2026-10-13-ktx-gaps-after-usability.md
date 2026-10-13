# Verbleibender ktx-Mehrwert nach Ariadne #60–#65

Datum: 2026-10-13. **Research-Evidence, keine Spezifikation oder Implementierungsfreigabe.** planning-contract v1; installierte Skill-Provenienz unbekannt.

Verglichen: Ariadne `a8d24b1` und ktx `49a4ae6f5b28c904da921afc0ee72da6db7ac202` (GitHub-HEAD bei Prüfung). Primärquellen: aktuelle Ariadne-Funktionskörper, ktx-Dokumentation und ausgewählte Adapterquellen. Keine Connector-, Performance- oder Live-Agent-Tests. Vault-Abfrage lieferte keine einschlägigen ktx-Seiten; die ältere [Vergleichsstudie](2026-09-23-ariadne-ktx-nao-omnigraph-comparison.md) ist nur Hintergrund, nicht der aktuelle Ariadne-Funktionsstand.

## Was nicht mehr fehlt

#60–#65 liefern Context-Seiten-Listing/Read, Skill-Leseregel, Status, Setup, Unified Discovery und Human Review. Ariadne besitzt außerdem Multi-Fact-Planung, dokumentbezogene opt-in Evidence-Reconciliation, gezielten Schema-Refresh mit Erhalt verfasster Bedeutung, Terminologieauflösung und gespeicherte Antwortbeispiele. Diese Fähigkeiten sind keine neuen ktx-Lücken. Insbesondere ersetzt Unified Discovery keine semantische Suche: `context.search_pages` rankt weiterhin nach lexikalischer Tokenfrequenz. [A-search], [A-refresh], [A-reconcile], [A-discovery]

## Kandidaten und Priorisierung

### 1. Autoritative Inhalte ohne LLM-Umschreiben aufnehmen

ktx `ingest --file ... --verbatim` erhält den Dokumentkörper unverändert; Metadaten können ergänzt werden, und der Pfad funktioniert ohne LLM-Backend. Identische Wiederholung ist ein No-op; anderer Inhalt unter demselben Schlüssel wird abgelehnt statt überschrieben. Ariadnes Dokument-Ingestion konvertiert und distilliert dagegen über ein LLM. Direktes manuelles Schreiben von OKF-Dateien ist bereits möglich; die Lücke ist ein unterstützter, idempotenter Aufnahmeweg, nicht die grundsätzliche Möglichkeit, Markdown aufzubewahren. [K-ingest], [A-distill]

**Nutzen:** freigegebene Glossare, Formeln und Policies nicht paraphrasieren lassen. **Kleinster Ariadne-Schritt:** unveränderte Markdown-Inhalte mit korrekter Quellenbindung als validierte Staging-/Proposal-Artefakte aufnehmen. Human Admission/Promotion bleibt nötig; weder raw Text noch ein Import begründen automatisch Governance. Sehr guter nächster Schritt für den dokumentzentrierten Einsatz.

### 2. Bestehendes Analytics-Wissen importieren

ktx besitzt Context-Adapter für dbt, MetricFlow, LookML, Looker, Metabase, Notion, Sigma und Google Drive. Beispielsweise liefern dbt-YAMLs Beschreibungen, Tests/Constraints und deklarierte Relationships. Zusätzlich übernimmt `--query-history` historische SQL-Muster; der Postgres-Adapter liest hierzu `pg_stat_statements` einschließlich Aufrufhäufigkeit und Nutzung. Ariadne bietet generische Dokumentaufnahme, Quellenprofiling und Harness-Authoring, aber keine entsprechende fertige Adapterpalette oder Query-History-Ingestion. [K-context], [K-pgss], [A-distill], [A-author]

**Nutzen:** nicht neu erfinden, was bereits in SQL, Dashboards und Modellen steckt. **Kleinster Ariadne-Schritt:** genau einen tatsächlich vorhandenen Quellenbestand aufnehmen — lokale dbt-YAMLs oder exportierte SQL-/BI-Definitionen — und daraus nachvollziehbare Vorschläge erzeugen. Historische SQL-Nutzung ist Evidenz, keine Richtigkeitsbestätigung und keine Erlaubnis, SQL ungeprüft auszuführen. Gespeicherte Ariadne-Antwortbeispiele ersetzen keinen automatisch erschlossenen Bestand an SQL-Mustern.

### 3. Inkrementelle, wiederaufnehmbare Context-Pflege

ktx beschreibt Eingabe-Hashes pro Enrichment-Stufe, selektive Wiederberechnung und Wiederaufnahme fehlgeschlagener Tabellen. Nicht ausgewählte, inzwischen veraltete Stufen werden sichtbar gemeldet statt still neu berechnet. Ariadne hat bereits punktuellen, idempotenten Schema-Refresh und Dokumentvergleiche; der Legacy-Author-Loop profiliert dagegen erneut und generiert ein Bundle im begrenzten Retry-Loop. Ein vergleichbar allgemeiner, ressourcen-/stufenbezogener Resume-Weg fehlt. [K-ingest], [A-refresh], [A-author], [A-reconcile]

**Nutzen:** bei vielen Quellen nicht für unveränderte Tabellen erneut Modellzeit bezahlen, und nach Teilfehlern nicht alles von vorne bearbeiten. **Kleinster Ariadne-Schritt:** an genau einem Import-/Refresh-Pfad Fingerprints und Wiederaufnahme einführen; neue Evidenz gegen angenommene Artefakte vergleichen, Owner-Änderungen nicht automatisch überschreiben. Kein Scheduling-Dienst oder automatische Admission nötig.

### 4. Semantische/hybride Context-Suche

ktx kombiniert FTS5/BM25, Embeddings und Token-Overlap mit RRF; fehlende Lanes fallen zurück auf die verfügbaren. Ariadne sucht lexikalisch und hat explizit deklarierbare Terminologie-Aliase, aber keine vergleichbare Embedding-Lane. Eine deutsche Frage kann daher ohne passende deklarierte Aliase eine englisch formulierte Policy verfehlen. [K-retrieval], [A-search]

**Nutzen:** Synonyme, Paraphrasen und größere Bestände besser finden. **Priorität bedingt:** zunächst mit echten manuellen Fragen prüfen, ob jetzt verfügbares Listing/Read, Unified Discovery und deklarierte Aliase bereits genügen. Falls nicht, billigste ausreichende Verbesserung zuerst; FTS5 allein ist keine Übersetzung oder semantische Suche. Embeddings nicht zum Pflichtbestandteil von Governance oder Paketbetrieb machen. Kein neues Recorded-Trace-Testsystem vorgeschlagen.

### 5. Native lokale DuckDB-Dateien als registrierte Quelle

ktx hat einen `duckdb`-Connector für vorhandene `.duckdb`-Dateien. Ariadnes `SOURCE_TYPES` umfasst SQLite, CSV, JSON, Parquet, Delta, Iceberg, DuckLake und Postgres, jedoch keinen nativen `duckdb`-Dateityp. DuckDB als Ausführungsengine ist nicht dasselbe wie eine vorhandene DuckDB-Datei als Quelle deklarieren zu können. [K-primary], [A-sources]

**Nutzen:** vorhandene lokale Analyse-Datenbanken ohne Export einbinden. Ein relativ begrenzter Quick Win, falls solche Dateien tatsächlich verwendet werden. Weitere Warehouse-Connectoren wie BigQuery/Snowflake wären wesentlich größere, bedarfsgebundene Änderungen und keine Pflicht zur ktx-Parität.

## Empfehlung

Für den bisherigen dokument-/dateizentrierten Einsatz zuerst **verbatim Aufnahme**, dann **inkrementelle Pflege** und ein **konkret benötigter Wissensimport**. Native DuckDB-Dateien bei realem Bedarf als separaten kleinen Schritt. Hybride Suche nur nach beobachteten Retrieval-Lücken.

Nicht übernehmen: freies Raw SQL als Ersatz für den Compile-Gate; pro-User-Scratch-Wissen, das still freigegebene Regeln überschattet; automatische Entfernung nicht auflösbarer Verweise als Ersatz für Human Review; weitere Produkt-/Agent-Shells ohne konkreten Verbraucher. Ktx-Verfügbarkeit belegt eine vorhandene Funktion, nicht geringe Implementierungskosten oder nachgewiesene Qualität in Ariadnes Einsatzumgebung.

## Konkretisierung nach Owner-Rückmeldung

Der Owner priorisiert Verbatim-Ingestion und möchte native DuckDB-Dateiquellen einbauen. Wiki-/LLM-Wiki-Anbindung bleibt eine separate Erweiterung; `../lumio-wiki` ist ein Kandidat. Weitere Connectoren kommen nur bei Bedarf. Lernen aus Frage→Antwort-Beispielen bleibt ein dauerhafter Schwerpunkt. Die ausgewählten Designrichtungen sind durch den Owner bestätigt; die vollständigen schriftlichen Spezifikationen [0021 Verbatim](../specs/2026-10-13-0021-verbatim-document-ingestion.md) und [0022 DuckDB](../specs/2026-10-13-0022-native-duckdb-sources.md) wurden als vollständige schriftliche Revision 1 mit „approved.“ in derselben Pi-Konversation am 2026-10-13 freigegeben. Die getrennten [Pläne 0021](../plans/2026-10-13-0021-verbatim-document-ingestion.md) und [0022](../plans/2026-10-13-0022-native-duckdb-sources.md) stehen zur Freigabe der Ausführungszerlegung. [ADR-0022](../adr/0022-trusted-native-duckdb-catalogs.md) hält die ausdrücklich gewählte Trusted-Catalog-Grenze fest. Runtime-Code wurde nicht geändert; die neuen Features wurden nicht ausgeführt.

### Verbatim: den Erhaltungsumfang benennen

Empfohlen: bestehende Dokumentkonvertierung verwenden, danach kein LLM-Aufruf und kein Umschreiben. Pro Dokument entsteht zunächst eine Reference unter `staging/context_layer/references/`, mit mechanischen Metadaten und Quellenbindung. „Verbatim“ bezeichnet den erhaltenen Markdown-Text; bei PDF/Office ist das Konverterausgabe, keine Garantie identischer Layouts oder originaler Binärdateien. Die vorhandene `_assemble`-Routine verwendet `.strip()` am Körper und ist deshalb nicht unverändert als Renderer für exakte Texterhaltung geeignet. Quell-Frontmatter darf keine Ariadne-Status-/Freigabefelder setzen. Secret-, Seitenvertrags-, Symlink- und Human-Gates bleiben bestehen. [A-distill]

Gewählte Richtung nach Owner-Abgleich: alle vorhandenen Konverter, identische erneute Aufnahme derselben Quelle als Staging-No-op, geänderte Inhalte als neue Draft-Version ohne Überschreiben; `--verbatim --reconcile` zunächst explizit ablehnen. Die schriftliche Spezifikation grenzt Idempotenz auf einen noch vorhandenen unveränderten Draft im ausgewählten Staging ein, nicht auf einen dauerhaften Aufnahme-Ledger oder post-Promotion-Deduplizierung. Automatische Policy-/Table-Klassifikation und Admission bleiben ausgeschlossen.

### DuckDB: native Dateien und View-Kataloge

Der verlinkte DuckDB-Blog beschreibt **keinen neuen `VIEW_ONLY`-Schalter**, sondern eine normale persistente `.duckdb`-Datei, die ausschließlich View-Definitionen enthält. Konsumenten verwenden `ATTACH '…' AS name (READ_ONLY)`. Die Views können etwa lokale oder entfernte Parquet-Dateien lesen. Der Read-only-Katalog ist kein Snapshot seiner referenzierten Daten; deren Inhalt wird bei Abfragen aktuell gelesen. Absolute Pfade/URLs verhindern Abhängigkeit vom Arbeitsverzeichnis; Konsumenten brauchen Zugriff auf Katalog und referenzierte Daten. [D-views]

Ariadne kann dies durch einen zusätzlichen Registry-Typ `duckdb` im vorhandenen Builder unterstützen, ohne einen neuen Backend-Layer oder Compile-Bypass. Der existierende Attach-Katalog bildet bereits vollständige Catalog/Schema/Table-Identitäten ab. Lokale DuckDB-Tabellen und Views gehören zum kleinsten Umfang. Der Owner hat HTTPS-/S3-Katalogdateien ausdrücklich eingeschlossen: `httpfs`, vorhandene Operator-Credentials und separate Remote-Validierung sind dafür nötig. Die gewählte erste Version nimmt nur operator-geprüfte vertrauenswürdige Kataloge samt erlaubten Backing-Zugriffen auf, nicht beliebige unbekannte View-SQL-Dateien. Sie verspricht keine technisch erzwungene transitive Ressourcen-Allowlist. Extern erzeugte Views werden durch Aufnahme als Quelle nicht automatisch zu governed Ariadne-Metriken. Installiertes Ariadne-DuckDB bei Prüfung: 1.5.6; weder lokale noch entfernte Attach-Features wurden in dieser Untersuchung ausgeführt. [A-sources], [D-views]

### Answer Examples und SQL-Historie: verbinden, nicht gleichsetzen

Ein Ariadne Answer Example ist bereits reichhaltiger als ein SQL-Log: Frage, Interpretation, strukturierte Ariadne-Methode, Ergebnis-Auszug, explizite fachliche Bestätigung und Review-/Dependency-Status. Aber die aktuelle Implementierung speichert **den SQL-Text nicht**: `result.sql` wird verlangt und validiert; `save_example` speichert einen Digest des vollständigen Resultats sowie einen Auszug aus `metric/governed/columns/rows`, nicht das SQL. Aus dem Digest lässt es sich nicht rekonstruieren. [A-examples]

Sinnvolle spätere Kombination: kompiliertes SQL als begrenzte, nicht ausführbare Provenienz am bestehenden Example bewahren. Externe SQL-Historie bleibt zunächst importierte Reference/Evidence; oft fehlen Frage, Bedeutung, historische Ergebnisse und fachliche Bestätigung. Erst nach Interpretation, Übersetzung in einen gültigen Ariadne-Aufruf und bestätigter aktueller Antwort kann daraus ein echtes Example werden. Kein erfundener Result-Envelope und kein direktes SQL-Replay. Lernen bedeutet hier gepflegtes Projektwissen und überprüfte Methoden, nicht automatisches Modelltraining oder neue Autorität. [A-example-spec]

Der Owner stellt die größere semantische/hybride Such-Erweiterung vorerst zurück und priorisiert SQL-Provenienz am bestehenden Example-Lernen. Am 2026-10-13 wurden SQL-Aufbewahrung bei jedem ausdrücklich bestätigten künftigen Save und SQL-Abruf nur auf Anfrage gewählt; „Ja passt“ bestätigt den vollständigen begrenzten In-Chat-Entwurf. [Spezifikation 0023](../specs/2026-10-13-0023-answer-example-sql-provenance.md) hält diesen Entwurf fest; der Owner hat anschließend ihre vollständige schriftliche Revision 1 mit „approved“ in derselben Pi-Konversation am 2026-10-13 freigegeben. Damit kann die Umsetzung geplant werden. Kein SQL-Replay, externer History-Import, zusätzlicher Query-Typ oder Implementierungsauftrag wurde dadurch freigegeben.

Auf die separate Owner-Freigabe für ein einzelnes GitHub-Ticket wurde [#68 — Examples E1: SQL provenance](https://github.com/legout/ariadne/issues/68) erstellt und sein vollständiger Body exakt zurückgelesen. Dieses Ticket besitzt die kanonische Ausführungszerlegung für Spec 0023; als begrenzte Erweiterung mit einem Owner benötigt es keinen zusätzlichen Planfile. Ausführungsfreigabe und Quellenübergabe stehen weiterhin aus; #66/#67 und ihre Reihenfolge bleiben unverändert.

### Ergänzung: aktive Rückfrage und kanonische Example-Ablage

Der Owner hat anschließend die aktive Rückfrage im Ariadne-Skill gewählt und die entsprechende Anpassung von #68 beauftragt. [Spec 0023 revision 2](../specs/2026-10-13-0023-answer-example-sql-provenance.md) ergänzt: nach einer abgeschlossenen `get_metric`-/`define_metric`-Antwort einmal nach fachlicher Stimmigkeit und expliziter Speicherung des gezeigten Records fragen, wenn kein fachlich passendes, geprüftes und nicht veraltetes Example genutzt werden kann. Ein Draft genügt nicht zur Unterdrückung der Rückfrage. Bei passendem reviewed Example frisch rechnen, ohne zusätzliche Speicherfrage; ein ausdrücklicher Speicherauftrag bleibt möglich. Zustimmung ohne Speicherauftrag oder eine Korrektur speichert nichts; bestätigtes Speichern erzeugt nur einen Draft. Feedback belegt keine unabhängige Zahlenvalidierung.

Die kanonische Ablage bleibt gemäß ADR-0015 OKF im separaten `answer_examples`-Store, nicht im Context Layer. LanceDB ist später ein abgeleiteter, wiederaufbaubarer Suchindex mit erhaltenen Herkunfts-/Review-/Staleness-Labels, kein Ersatz für den kanonischen Record. Indexbau und Lumio-Anbindung bleiben zurückgestellt und benötigen bei Aufnahme eigene Gestaltung und Tickets. Für diese Skill-Regel reicht die Erweiterung von #68; #66/#67 sowie #18/#52 bleiben unverändert. Keine Implementierung oder Ausführungsfreigabe.

### Was hybride Suche tatsächlich benötigt

1. Eine konkrete Retrieval-Lücke aus den manuellen realen Fragen, mit vom Owner benannten passenden Seiten/Examples; kein neu eingeführtes Recorded-Agent-Trace-System.
2. Eine abgeleitete Indexeinheit mit Seiten-/Passagenpfad, Inhaltshash, Root-/Draft-Identität und Zitierposition. Chunking darf Kontext/Policies nicht verfälschen.
3. Eine lexikalische BM25-Lane; bei sprachübergreifenden Paraphrasen zusätzlich ein geeignetes mehrsprachiges Embedding-Modell. BM25 allein übersetzt nicht.
4. Explizite Modell-/Providerwahl, Kosten und Datenschutzgrenze. Remote Embeddings senden Kontextinhalt nach außen und dürfen nicht still aktiviert werden; lokale Modelle erhöhen Paket-/Runtime-Gewicht.
5. Fusion der Trefferlisten, beispielsweise RRF, mit Deduplizierung. Similarity ist keine Authority: Review, Staleness, Draft-/served-Unterscheidung, Quellenprüfung und Compile-Gate bleiben verbindlich.
6. Hash-basierte Index-Aktualisierung und klarer lexikalischer Fallback bei fehlendem/veraltetem/unverfügbarem Index. Der Index ist löschbar und aus den kanonischen Artefakten wiederaufbaubar.

LanceDB ist eine mögliche Implementation, keine Voraussetzung. Vor einer eigenen neuen Infrastruktur sollte die separate Lumio-Anbindung bewertet werden; ein externer Wiki-Index kann jedoch nicht ungeprüft Ariadnes eigene Snapshot-/Governance-Semantik übernehmen. Verbesserter Recall und vertretbare Laufzeit sind mit echten Fragen noch zu belegen. [A-search], [K-retrieval], [L-index]

### Lumio/LanceDB über DuckDB

Die aktuelle offizielle DuckDB-Dokumentation beschreibt die `lance`-Extension für Lance-Datasets: `INSTALL lance; LOAD lance; SELECT * FROM '…/dataset.lance'`. Außerdem sind Vector-, FTS- und Hybrid-Suchfunktionen dokumentiert. Das belegt den Datenformat-Zugang, nicht die vollständige Kompatibilität mit Lumios installierten Indexformaten oder dessen KnowledgeBase-API. Es wurde keine Extension installiert und keine Verbindung ausgeführt. [D-lance]

Lumios optionaler Adapter hält getrennte `evidence`, `pages` und `evidence_vectors`-Tabellen sowie Fingerprint-/Embedding-Modell-Sidecars. Er prüft Indexfrische und Modellidentität und bietet einen wahrheitsgemäß markierten Zero-Index-Fallback. Direkter SQL-Zugriff auf die Lance-Dateien ruft diese Lumio-Vertragsprüfungen nicht automatisch auf. Für eine Wiki-Erweiterung empfiehlt sich daher die öffentliche Lumio-Retrieval-Schnittstelle; DuckDB-Scans sind eine mögliche Zusatzbrücke für Datenzugriff/Analyse. LanceDB bleibt optional und außerhalb Ariadnes Basisabhängigkeiten. [L-index], [L-location]

### Nachprüfung: LanceDB als bevorzugter Suchbackend-Kandidat

Auf die Owner-Frage nach Wiederverwendung des bereits in Lumio verwendeten LanceDB wurde dessen Eignung anhand offizieller Dokumentation und des aktuellen Lumio-Adapters nachgeprüft. Die Vault-Seite `projects/lumio/lumio-architecture.md` stammt vom Juli 2026 und nennt Hybrid-Suche noch als geplant; für den heutigen Funktionsstand gelten die aktuellen Quellen. Geprüfter Lumio-Checkout: HEAD `93951f84f0dfe0c60f8e42ae3d607074a8c262cf`. Kein Live-Suchlauf, Benchmark oder Installation.

- **Technisch geeignet:** LanceDB OSS kann lokal eingebettet betrieben werden, bietet BM25-Volltext- und Vektorsuche und unterstützt Hybrid-Fusion mit RRF. Die offizielle Hybrid-Dokumentation zeigt auch explizite Text-/Vektorübergabe; das Embedding-Modell muss nicht von LanceDB gewählt werden. [LD-hybrid], [LD-fts]
- **Bereits im Lumio-Code:** `search_hybrid_index` fusioniert getrennte lexikalische und semantische Treffer mit RRF und Deduplizierung. `LanceDBRetrievalAdapter.retrieve` prüft Fingerprint und Modellidentität, filtert auf zulässige Seiten und erhält Citation/Trace. Fehlender/veralteter/unverfügbarer Index kann auf Zero-Index-Retrieval zurückfallen; Modellinkompatibilität wird ausdrücklich als Fehler gemeldet, nicht kaschiert. [L-index]
- **Empfehlung, keine Architekturfreigabe:** LanceDB ist aufgrund vorhandener Lumio-Erfahrung der bevorzugte Kandidat für eine optionale Ariadne-Suchverbesserung. Für externe Wiki-Inhalte weiterhin Lumios öffentliche Retrieval-Schnittstelle nutzen; ein Index über Ariadnes eigene Artefakte benötigt deren Root-/Draft-/Snapshot-Verträge. Gleicher Backend-Typ bedeutet weder einen gemeinsamen Index noch gemeinsame Autorität.
- **Kein ungeprüfter Paket-Drop-in:** `lumio-lancedb` 0.1.2 verlangt Python ≥3.14 und Lumio-Domain-Typen; Ariadne 0.2.0 unterstützt Python ≥3.12. Direkte Paketkopplung, öffentliche Schnittstelle oder begrenzte Wiederverwendung müssen deshalb separat gestaltet werden, ohne still Ariadnes Mindestversion anzuheben. [L-package], [A-package]
- **Noch zu belegen:** tatsächlicher Recall-Gewinn für eigene Fragen, mehrsprachige Modellqualität, Provider-/Datenschutzgrenze und Index-Pflegekosten. LanceDB allein übersetzt keine Fragen. Diese Prüfung verändert weder die freigegebenen Specs 0021/0022 noch deren ausstehende Ausführungsfreigabe.

## Primärquellen

[A-search]: ../../src/ariadne/context.py "search_pages: vollständige Seiten und lexikalisches Token-Ranking"
[A-discovery]: ../../src/ariadne/discovery.py "DiscoveryRuntime: artefaktbasierte native Reads"
[A-refresh]: ../../src/ariadne/authoring.py "AuthoringProject.refresh_schema: gezielt, revision-geprüft, Bedeutungen erhalten"
[A-distill]: ../../src/ariadne/ingest.py "_distill und main: LLM-Distillation, kein verbatim CLI-Modus"
[A-reconcile]: ../specs/2026-09-23-0004-evidence-reconciliation.md "Begrenzte dokumentbezogene Reconciliation; reconcile_ingest ist implementiert"
[A-author]: ../../src/ariadne/author.py "author: vollständiges Profiling und Bundle-Generation mit Retry"
[A-sources]: ../../src/ariadne/sources.py "SOURCE_TYPES, plan und _catalog_entry: noch kein nativer duckdb-Dateityp; gemeinsame Attach-Identitäten"
[A-examples]: ../../src/ariadne/answer_examples.py "_normalize_submission, _validate_result und save_example: strukturierte Methode, Ergebnis-Digest ohne gespeicherten SQL-Text"
[A-example-spec]: ../specs/2026-09-29-0007-answer-examples.md "Example-Autorität, Bestätigung, Provenienz und aktuelle Neu-Ausführung"
[D-views]: https://duckdb.org/2026/10/07/view-only-mode "A DuckDB Database with No Data in It: Views als normaler Read-only-Attach-Katalog"
[D-lance]: https://duckdb.org/docs/current/core_extensions/lance.html "Lance-Datasets, Vector-, FTS- und Hybrid-Suchfunktionen; Live-Kompatibilität ungeprüft"
[L-index]: ../../../lumio-wiki/packages/lumio-lancedb/src/lumio_lancedb/index.py "Getrennte abgeleitete Indextabellen, Fingerprint/Modellidentität und Zero-Index-Fallback"
[L-location]: ../../../lumio-wiki/packages/lumio-lancedb/src/lumio_lancedb/location.py "Lokale und entfernte IndexLocations mit Metadaten-Sidecars"
[L-package]: ../../../lumio-wiki/packages/lumio-lancedb/pyproject.toml "Adapter 0.1.2: Python ≥3.14, Lumio-Domain-Kopplung und optionale lokale Embeddings"
[A-package]: ../../pyproject.toml "Ariadne 0.2.0: Python ≥3.12 und schlanke Basisabhängigkeiten"
[LD-hybrid]: https://docs.lancedb.com/search/hybrid-search "Lokales OSS-Beispiel, getrennte Text-/Vektorübergabe, RRF und Metadatenfilter"
[LD-fts]: https://docs.lancedb.com/search/full-text-search "BM25-Volltextsuche in LanceDB"
[K-ingest]: https://github.com/Kaelio/ktx/blob/49a4ae6f5b28c904da921afc0ee72da6db7ac202/docs-site/content/docs/cli-reference/ktx-ingest.mdx "Verbatim, Query-History, per-stage Caching und Resume"
[K-context]: https://github.com/Kaelio/ktx/blob/49a4ae6f5b28c904da921afc0ee72da6db7ac202/docs-site/content/docs/integrations/context-sources.mdx "dbt/BI/Docs-Adapter"
[K-pgss]: https://github.com/Kaelio/ktx/blob/49a4ae6f5b28c904da921afc0ee72da6db7ac202/packages/cli/src/context/ingest/adapters/historic-sql/postgres-pgss-reader.ts "Konkreter SQL-History-Reader"
[K-retrieval]: https://github.com/Kaelio/ktx/blob/49a4ae6f5b28c904da921afc0ee72da6db7ac202/docs-site/content/docs/concepts/wiki-retrieval.mdx "Hybrid-Retrieval, RRF, Referenzen"
[K-primary]: https://github.com/Kaelio/ktx/blob/49a4ae6f5b28c904da921afc0ee72da6db7ac202/docs-site/content/docs/integrations/primary-sources.mdx "Native DuckDB-Dateien und Warehouse-Connectoren"
