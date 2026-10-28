# Inventory: what the plugin is and how its modules fit together

This file is the map. `inventory.json` has every module: its key, its type, its display name where that is
not internal, the contract class where the contract fixes one, a purpose, its group, related modules and
the externally visible parts of its declaration (`contract`). `SPEC.md` gives the exact contract and
behaviour; `claims.jsonl` the testable statements.

## 1. The plugin

The plugin (key `com.almworks.jira.structure`, display name "Structure", version 9.14.1, built for Jira
Data Center 9.12) lets users arrange Jira issues and other things into **structures**: named, permissioned,
multi-level hierarchies that can span projects. A structure is shown and edited in a spreadsheet-like
**grid** with configurable columns, totals rolled up the hierarchy, formulas and inline editing.

The hierarchy can be built by hand (drag and drop) or by **automation**. Automation rules are rows in the
structure that pull in issues by query, add children by links or sub-tasks, group, sort and filter. They
are re-evaluated whenever the data changes, so the hierarchy stays current. Changes in the grid can be
written back to Jira: moving an issue under another creates a link or changes a field. Two mechanisms do
that write-back at scale: continuously running **synchronizers** and user-triggered **effectors** with
preview and undo.

The plugin also provides:
- its own query language over hierarchies, S-JQL, with a JQL function and workflow checks built on it;
- saved views;
- per-structure history;
- Excel and printable export;
- dashboard gadgets, including a cumulative flow diagram;
- backup, restore and server-to-cloud migration;
- a public Java API and its own extension points, which companion apps build on.

## 2. Modules by type

608 modules (each key counted once; 41 keys are declared more than once in the original, one declaration per
Jira version range, and `contract.declared_per_jira_range` marks them).

| Type | Count | What they are |
|---|---:|---|
| component | 211 | back-end services; 45 are exported to other plugins (`contract.public`, `contract.exports`) |
| web-resource | 84 | front-end bundles: the grid, pages, dialogs, admin screens, third-party libraries |
| structure-attribute-loader-provider | 63 | read side of the grid: values for columns, formulas, aggregates |
| structure-effect-provider | 40 | write side of automation: one kind of change to Jira each |
| structure-item-type | 34 | kinds of things a row can hold (issue, project, version, folder, memo, ...) |
| web-item | 24 | menu entries, admin links |
| module-type | 19 | the plugin's own extension points |
| structure-export-renderer-provider | 19 | how each column kind is exported |
| web-section | 12 | menu and admin sections |
| structure-performance-log-provider | 10 | sections of the downloadable performance log |
| velocity-allowlist | 10 | what server-rendered pages may call, one per page family |
| structure-filter | 9 | automation: filters |
| servlet-filter | 8 | request interceptors and page decorators |
| structure-grouper | 8 | automation: groupers |
| structure-synchronizer | 5 | synchronizers |
| structure-inserter | 5 | automation: inserters |
| structure-query-constraint | 5 | S-JQL functions |
| web-panel | 4 | issue page, Agile board tab, project sidebar |
| structure-extender | 4 | automation: extenders |
| new-structure-template | 4 | templates of the Create Structure wizard |
| structure-effector | 4 | effectors |
| rest | 3 | REST APIs: `/rest/structure/1.0`, `/rest/structure/2.0`, `/rest/cfd/1.0` |
| structure-sorter | 3 | automation: sorters |
| simple-link-factory | 2 | lazily filled menu lists (recent, favourite structures) |
| gadget | 2 | dashboard gadgets |
| one each | 16 | servlet (Excel export), webwork (all `.jspa` pages), JQL function, workflow condition and validator, Active Objects schema, custom field type and searcher, activity stream, keyboard shortcut, web-resource transformer, calendar provider, core extension, and three user-data handlers |

## 3. How the modules fit together

**Extension points first.** Most of the plugin is built from its own extension points (the 19
`module-type` modules): item types, inserters, extenders, groupers, sorters, filters, synchronizers,
effectors, effect providers, attribute loader providers, export renderer providers, new-structure
templates, S-JQL constraints, calendar, backup, core extension, performance log, query skeleton and
integration details. At run time an extension registry collects every module of each kind, from this
plugin and from companion apps alike. Three of these points have no implementation in this plugin:
query skeleton factory, backup provider and integration details provider. They exist for companion apps.

Modules are addressed by their **full key**, `com.almworks.jira.structure:<key>`, and the plugin stores
these keys in its data:
- item type ids with rows;
- generator and effector module keys with their instances;
- synchronizer keys with sync instances;
- effect provider keys and parameter names with saved effects and undo records.

So module keys are stored data, not only descriptor names.

**The core model.**
- **Item.** Anything addressable by item type and id: an issue, a version, a folder, a memo, and so on.
  Item types turn ids into objects, decide what a user may see, and detect deleted items.
- **Row.** One occurrence of an item in a hierarchy. Rows are either persistent (stored) or transient
  (produced in memory by automation); one row service hides the difference.
- **Forest.** An ordered tree of rows.
- **Structure.** A named, permissioned container of a forest.

The structure manager owns structures and their stored forests. The forest service turns a *forest
specification* into a live forest: a stored structure, a query, a transformed forest or a clipboard.
On the way it runs the automation rows through the generation engine, within time limits, and then
applies the manual adjustments users made to generated content.

**Change tracking.** An item tracker is the change journal that forests and values poll. It is fed by:
- Jira events, through an issue event bridge and bridges for structure-relevant platform and app events;
- user and group events;
- reindex notifications. The *Structure Index Monitor* custom field exists only to be told when an issue
  is reindexed, and the plugin creates and locks it itself;
- servlet filters that catch changes Jira makes without events: rank, sub-task order, watchers,
  epic links, some Tempo edits.

On Data Center the journal and the synchronizer event queue are shared between nodes through database
tables, and caches are cleared cluster-wide.

**Attributes (read side).** The grid asks for *attribute values* by *attribute spec*: an id, a value format
and parameters. The attribute service offers each spec to the 63 loader providers in turn, and the first
that accepts it supplies a loader. Loaders range from item basics (key, summary, icon) through every kind
of Jira field, dates, time in status, work logged, progress and links, to tree aggregates (sum, min/max,
count, join) and the formula language (`expr`). Any attribute can be used as a formula variable. Values
are cached with dependency tracking, streamed to the browser through subscriptions, filtered by an
admin-set sensitivity mode, and recorded in performance logs.

**Effects (write side).** Effectors and drag-and-drop on generated rows do not change Jira directly. They
produce *effects*: an effect provider key plus parameters. The provider with that key validates an effect
against Jira's own services and permissions, describes it for preview, and applies it, returning an undo
effect. Effector processes (preview, confirm, apply, undo, resume) are stored together with their effect
records. Synchronizers are the older, continuously running way to keep a structure and Jira consistent:
saved filter, links, Agile, sub-tasks and status rollup.

**Query.** S-JQL is a query language over a forest. A query constraint registry is filled by the
`structure-query-constraint` modules, and a parser also accepts plain JQL and text search. S-JQL is used by
the `structure()` JQL function, the S-JQL automation filter, and the workflow condition and validator
"Issue Matches Structure Query".

**Persistence.** The Active Objects schema has 39 tables with the prefix `AO_8BAD1B_` (`contract.tables`
of module `ao`). They hold structures, forests and their change log, rows, item types, generators, views,
folders, favourites, properties, history, sync state and audit, effectors and effect records, generic items
(memos, planning tasks) and their history, notes, saved columns and process state. Global settings live in
Jira application properties and user preferences.

**Views and columns.** Seven default views are created on first use. Views are stored with per-structure
view settings. Saved columns come from a bundled source and from user-stored ones, which can be personal or
global. Notes columns are named, shareable and permissioned.

**Jobs and processes.** The plugin runs work on named thread pools and periodic jobs. Long-running
processes expose progress and cancellation. A scheduled maintenance task runs under a cluster lock and
covers cleanup and backups. Heavy REST calls run as resumable background jobs.

**Front end.** One webwork module registers all ~50 `.jspa` pages and dialogs, for example
`/secure/StructureBoard.jspa`, the printable page, the management and admin pages, and the external gadget.
Ten Velocity allowlists say what each page family's templates may call. The grid is a layered stack of web
resources:
- isolated third-party libraries at the bottom;
- shared utilities, events and an i18n bundle generated per locale above them;
- the grid itself (`widget-bare`), then the `widget` umbrella on top.

Few resources attach to Jira pages directly:
- the issue page panel;
- the Agile board tab;
- the project sidebar;
- the Create Structure wizard, on every page.

Pages showing a structure also request the contexts `structure.widget` and `structure.printable`, which are
hooks for companion apps. The export menu is open to other plugins through the web-item location
`structure.export.menu`.

**Jira integration surface.**
- Navigation: the top menu "Structure" (shortcut `g s`), project sidebar and project settings entries,
  and an admin section. The web item `wi-structure-jira-home-51` can be a user's Jira home page, which
  Jira stores by its full key.
- Dashboard gadgets: Structure, and the cumulative flow diagram with its own REST API.
- Excel export servlet, activity stream provider, and handlers for user key change, anonymisation and
  ownership transfer.
- Integrations with Jira Software, Jira Service Management, Advanced Roadmaps, Tempo, Assets/Insight,
  ScriptRunner Behaviours, Epic Sum Up, STAGIL and Tree custom field. Each is found at run time and
  degrades gracefully when the other app is absent.

**Platform.** Many back-end services exist twice, once per Jira line (9–10 versus 11+), behind one interface.
For Jira 9.12 only the 9–10 declarations apply; `contract` shows those. Around them are lifecycle and
initialisation, licensing and end-of-life banners, an optional daily usage report that is sent only after an
admin opts in, a support zip and performance logs.

## 4. External contract fixed by the inventory

The full contract is in `SPEC.md`. These facts are visible here already:
- **Plugin key and module keys and types:** every `key`/`type` in `inventory.json`, kept exactly. Keys are
  also stored data (section 3), including the misspelt `spic-sum-up-integration`.
- **REST:** `/rest/structure/1.0`, `/rest/structure/2.0`, `/rest/cfd/1.0`.
- **Pages:** the webwork aliases in `contract.actions` of `ww-structure`, as `/secure/<alias>.jspa` (and
  `<alias>!<command>.jspa`).
- **Servlet and filter URL patterns:** `contract.url_patterns`.
- **Database:** the Active Objects namespace `com.almworks.jira.structure` (table prefix `AO_8BAD1B_`) and
  the 39 table names.
- **Workflow:** Jira stores the condition and validator by the class name in the module's `class`, and their
  arguments by name (`SPEC.md`).
- **Exported services:** the interfaces in `contract.exports`. All of them are public API types except one,
  `com.almworks.jira.structure.generic.GenericItemHistoryManager`, which `SPEC.md` specifies as well.
- **Web fragments other apps use:** web-resource keys, the contexts above, sections and locations,
  and the gadget locations (`contract.location`). Dashboards store gadgets by module key and location.

## 5. Module index by group

`inventory.json` has each module's purpose. Groups:

<!-- index:start -->
**core-model** (56): Structures, forests, rows and items: the hierarchy model and its storage-facing managers.

`clipboard-manager` (component), `favorite-manager` (component), `folder-manager` (component), `forest-service` (component), `generic-item-field-accessor-manager` (component), `generic-item-field-config-service` (component), `generic-item-manager` (component), `generic-item-service` (component), `generic-item-type-helper` (component), `issue-to-planning-task-converter` (component), `item-identity-mapper` (component), `item-resolver` (component), `item-type-registry` (component), `jira-field-visibility-service` (component), `memo-manager` (component), `planning-task-manager` (component), `structure-field-manager` (component), `structure-field-type-manager` (component), `structure-manager` (component), `structure-row-manager` (component), `sub-task-issue-cache` (component), `transient-row-manager` (component), `type-attachment` (structure-item-type), `type-cf-option` (structure-item-type), `type-change-history-group` (structure-item-type), `type-change-history-item` (structure-item-type), `type-comment` (structure-item-type), `type-effector` (structure-item-type), `type-folder` (structure-item-type), `type-generator` (structure-item-type), `type-group` (structure-item-type), `type-insight-object` (structure-item-type), `type-issue` (structure-item-type), `type-issue-link` (structure-item-type), `type-issue-link-type` (structure-item-type), `type-issuetype` (structure-item-type), `type-label` (structure-item-type), `type-loop-marker` (structure-item-type), `type-memo` (structure-item-type), `type-memo-change-history-group` (structure-item-type), `type-missing` (structure-item-type), `type-planning-task` (structure-item-type), `type-priority` (structure-item-type), `type-project` (structure-item-type), `type-project-component` (structure-item-type), `type-remote-link` (structure-item-type), `type-resolution` (structure-item-type), `type-sd-request-type` (structure-item-type), `type-sprint` (structure-item-type), `type-status` (structure-item-type), `type-structure` (structure-item-type), `type-tempo-account` (structure-item-type), `type-user` (structure-item-type), `type-version` (structure-item-type), `type-version-name` (structure-item-type), `type-worklog` (structure-item-type)

**generators** (37): Automation that builds or reshapes a forest: inserters, extenders, groupers, sorters, filters.

`adjustment-service` (component), `agile-board` (structure-inserter), `effect-based-issue-movers` (component), `extender-agile` (structure-extender), `extender-links` (structure-extender), `extender-portfolio-children` (structure-extender), `extender-subtasks` (structure-extender), `filter-attribute` (structure-filter), `filter-by-field` (structure-filter), `filter-inserter-extender-duplicates` (structure-filter), `filter-item` (structure-filter), `filter-jql` (structure-filter), `filter-number-attribute` (structure-filter), `filter-sjql` (structure-filter), `filter-sprint` (structure-filter), `filter-text` (structure-filter), `generation-manager` (component), `generator-manager` (component), `grouper-agile-epic` (structure-grouper), `grouper-field` (structure-grouper), `grouper-links` (structure-grouper), `grouper-portfolio-parent` (structure-grouper), `grouper-sprint` (structure-grouper), `grouper-tempo-account` (structure-grouper), `grouper-text` (structure-grouper), `grouper-version-name` (structure-grouper), `inserter-jql` (structure-inserter), `inserter-recent-issues` (structure-inserter), `inserter-substructure` (structure-inserter), `inserter-text` (structure-inserter), `issue-links-support` (component), `recent-issue-inserter` (component), `sorter-agile-rank` (structure-sorter), `sorter-attribute` (structure-sorter), `sorter-manual` (structure-sorter), `structure-generators-allowlist` (velocity-allowlist), `transient-generator-manager` (component)

**attributes** (77): Values shown in columns and used by formulas: loaders, aggregates, expressions.

`aggregate-function-provider` (structure-attribute-loader-provider), `aggregate-order-provider` (structure-attribute-loader-provider), `attribute-aware-process-registry` (component), `attribute-loader-cache` (component), `attribute-sensitivity-rc` (web-resource), `attribute-service` (component), `attribute-service-support` (component), `attribute-subscription-service` (component), `attribute-troubleshooting-rc` (web-resource), `basic-generation-info-provider` (structure-attribute-loader-provider), `bulk-comment-reader` (component), `change-history-provider` (structure-attribute-loader-provider), `children-automations-hint-provider` (structure-attribute-loader-provider), `comments-item-provider` (structure-attribute-loader-provider), `custom-field-resolver` (component), `customfield-provider` (structure-attribute-loader-provider), `date-field-provider` (structure-attribute-loader-provider), `displayable-provider` (structure-attribute-loader-provider), `done-provider` (structure-attribute-loader-provider), `editable-provider` (structure-attribute-loader-provider), `enum-customfield-order-provider` (structure-attribute-loader-provider), `epic-issue-provider` (structure-attribute-loader-provider), `error-provider` (structure-attribute-loader-provider), `expr-attribute` (structure-attribute-loader-provider), `extended-value-tools` (component), `field-information-provider` (component), `formatted-number-provider` (structure-attribute-loader-provider), `formula-icons` (web-resource), `generic-item-attribute-provider` (structure-attribute-loader-provider), `generic-item-fields-provider` (structure-attribute-loader-provider), `generic-item-history-based-fields-provider` (structure-attribute-loader-provider), `generic-item-history-provider` (structure-attribute-loader-provider), `icon-provider` (structure-attribute-loader-provider), `is-user-added-automation-provider` (structure-attribute-loader-provider), `issue-comment-provider` (structure-attribute-loader-provider), `issue-field-item-provider` (structure-attribute-loader-provider), `issue-field-order-provider` (structure-attribute-loader-provider), `issue-field-provider` (structure-attribute-loader-provider), `issue-field-rendering-provider` (structure-attribute-loader-provider), `issue-field-text-provider` (structure-attribute-loader-provider), `issue-link-objects-provider` (structure-attribute-loader-provider), `issue-parent-provider` (structure-attribute-loader-provider), `issue-time-field-provider` (structure-attribute-loader-provider), `item-provider` (structure-attribute-loader-provider), `key-provider` (structure-attribute-loader-provider), `links-count` (structure-attribute-loader-provider), `main-provider` (structure-attribute-loader-provider), `manually-adjusted-provider` (structure-attribute-loader-provider), `non-unique-items-provider` (structure-attribute-loader-provider), `notes-provider` (structure-attribute-loader-provider), `number-sum-provider` (structure-attribute-loader-provider), `original-generator-kind-provider` (structure-attribute-loader-provider), `parent-provider` (structure-attribute-loader-provider), `primitives-provider` (structure-attribute-loader-provider), `progress-provider` (structure-attribute-loader-provider), `project-category-provider` (structure-attribute-loader-provider), `project-parameters-provider` (structure-attribute-loader-provider), `query-match-provider` (structure-attribute-loader-provider), `remote-link-objects-provider` (structure-attribute-loader-provider), `run-as-user-provider` (structure-attribute-loader-provider), `sequence-provider` (structure-attribute-loader-provider), `simple-calendar-provider` (structure-calendar-provider), `sprint-parameters-provider` (structure-attribute-loader-provider), `status-attributes-provider` (structure-attribute-loader-provider), `status-category-provider` (structure-attribute-loader-provider), `subtasks-provider` (structure-attribute-loader-provider), `tempo-provider` (structure-attribute-loader-provider), `time-in-status-provider` (structure-attribute-loader-provider), `transition-date-provider` (structure-attribute-loader-provider), `user-property-provider` (structure-attribute-loader-provider), `value-path-provider` (structure-attribute-loader-provider), `value-text-converter` (component), `version-name-provider` (structure-attribute-loader-provider), `version-parameters-provider` (structure-attribute-loader-provider), `wiki-rendering-provider` (structure-attribute-loader-provider), `worklog-objects-provider` (structure-attribute-loader-provider), `worklogged-provider` (structure-attribute-loader-provider)

**effects** (52): Write-back from structure changes or attribute values to Jira (effect providers, effectors).

`add-comment-effect-provider` (structure-effect-provider), `affects-versions-effect-provider` (structure-effect-provider), `assignee-effect-provider` (structure-effect-provider), `cascade-custom-field-effect-provider` (structure-effect-provider), `components-effect-provider` (structure-effect-provider), `conversion-effect-provider` (structure-effect-provider), `date-custom-field-effect-provider` (structure-effect-provider), `date-time-custom-field-effect-provider` (structure-effect-provider), `delay-effect-provider` (structure-effect-provider), `delete-comment-effect-provider` (structure-effect-provider), `description-effect-provider` (structure-effect-provider), `due-date-effect-provider` (structure-effect-provider), `effect-provider-helper` (component), `effect-service` (component), `effector-attribute-to-field` (structure-effector), `effector-audit` (web-resource), `effector-common` (web-resource), `effector-conversion` (structure-effector), `effector-delay` (structure-effector), `effector-instance-manager` (component), `effector-process-manager` (component), `effector-processes` (web-resource), `effector-status-rollup` (structure-effector), `environment-effect-provider` (structure-effect-provider), `fix-versions-effect-provider` (structure-effect-provider), `insight-object-custom-field-effect-provider` (structure-effect-provider), `labels-effect-provider` (structure-effect-provider), `memo-field-effect-provider` (structure-effect-provider), `multi-group-custom-field-effect-provider` (structure-effect-provider), `multi-labels-custom-field-effect-provider` (structure-effect-provider), `multi-select-custom-field-effect-provider` (structure-effect-provider), `multi-user-custom-field-effect-provider` (structure-effect-provider), `multi-versions-custom-field-effect-provider` (structure-effect-provider), `number-custom-field-effect-provider` (structure-effect-provider), `original-estimate-effect-provider` (structure-effect-provider), `portfolio-team-custom-field-effect-provider` (structure-effect-provider), `priority-effect-provider` (structure-effect-provider), `project-picker-custom-field-effect-provider` (structure-effect-provider), `remaining-estimate-effect-provider` (structure-effect-provider), `reporter-effect-provider` (structure-effect-provider), `resolution-effect-provider` (structure-effect-provider), `script-runner-single-issue-picker-effect-provider` (structure-effect-provider), `single-group-custom-field-effect-provider` (structure-effect-provider), `single-select-custom-field-effect-provider` (structure-effect-provider), `single-user-custom-field-effect-provider` (structure-effect-provider), `single-version-custom-field-effect-provider` (structure-effect-provider), `sprint-effect-provider` (structure-effect-provider), `status-effect-provider` (structure-effect-provider), `structure-effectors-allowlist` (velocity-allowlist), `summary-effect-provider` (structure-effect-provider), `text-custom-field-effect-provider` (structure-effect-provider), `warning-effect-provider` (structure-effect-provider)

**sync** (16): Synchronizers keeping a structure and Jira data (links, sub-tasks, Agile, filters) in step.

`filtersync-config-js` (web-resource), `ghsync-config-js` (web-resource), `linksync-config-js` (web-resource), `reindex-locker` (component), `statusup-config-js` (web-resource), `structure-sync-allowlist` (velocity-allowlist), `sync-audit-log` (component), `sync-audit-log-view-rc` (web-resource), `sync-events-manager` (component), `sync-filter` (structure-synchronizer), `sync-gh` (structure-synchronizer), `sync-hide-helper` (component), `sync-links` (structure-synchronizer), `sync-manager` (component), `sync-status-rollup` (structure-synchronizer), `sync-subtasks` (structure-synchronizer)

**query** (23): Structured JQL (S-JQL), the structure() JQL function and query constraints.

`constraint-folder` (structure-query-constraint), `constraint-item` (structure-query-constraint), `constraint-memo` (structure-query-constraint), `constraint-planningtask` (structure-query-constraint), `constraint-rowId` (structure-query-constraint), `expr-aggregation-provider` (component), `expr-constraints` (component), `expr-function-provider` (component), `expr-function-services` (component), `expr-parser` (component), `index-flusher` (component), `index-search-service` (component), `item-query-constraint` (component), `jql-structure` (jql-function), `lucene-helper` (component), `query-result-cache` (component), `sjql-troubleshooting` (web-resource), `structure-issue-index` (component), `structure-query-builder-factory` (component), `structure-query-constraint-registry` (component), `structure-query-parser` (component), `user-display-name-searcher` (component), `various-query-parser` (component)

**views-columns** (11): Saved views, column definitions, notes columns.

`ao-based-view-manager` (component), `bundled-column-source` (component), `issue-constant-icon-cache` (component), `item-property-editors` (component), `note-searcher` (component), `saved-column-manager` (component), `stored-column-source` (component), `structure-views-js` (web-resource), `user-field-renderer` (component), `user-icon-cache` (component), `view-manager` (component)

**persistence** (18): Database tables (Active Objects), properties, locks and stored settings.

`adjustment-store` (component), `ao` (ao), `ao-based-statistics-service` (component), `ao-helper` (component), `ao-lock` (component), `effector-process-io` (component), `history-recorder-io` (component), `note-manager` (component), `notes-manager` (component), `ordering-io` (component), `persistent-generator-manager` (component), `persistent-row-manager` (component), `perspective-io` (component), `process-io` (component), `property-service` (component), `saved-column-io` (component), `structure-database-provider` (component), `structure-property-service` (component)

**history-events** (16): Change tracking, issue events, structure history and activity streams.

`data-tracker` (component), `event-bridge` (component), `generic-item-history-manager` (component), `history-recorder` (component), `history-service` (component), `issue-change-interceptor` (servlet-filter), `issue-reindex-tracker` (component), `item-tracker` (component), `reindex-manager` (component), `statistics-manager` (component), `structure-deleted-event-listener` (component), `structure-event-bridge` (component), `structure-features-statistic-source` (component), `structure-usage-tracker` (component), `structure-users-event-bridge` (component), `wf-statistics` (component)

**permissions-security** (11): Structure permissions, access checks and security filters.

`attribute-sensitivity-manager` (component), `bulk-permission-checker` (component), `forest-permissions-cache` (component), `partitioned-cookie-header-filter` (servlet-filter), `permission-scheme-manager` (component), `permissions-cache` (component), `permissions-calculator` (component), `permissionsEditor` (web-resource), `project-scope-cache` (component), `security-filter` (servlet-filter), `structure-permissions` (web-resource)

**jobs-processes** (5): Background jobs and long-running user processes with progress.

`issue-cloner` (component), `jira-thread-env-factory` (component), `job-manager` (component), `process-handle-manager` (component), `scheduled-job-manager` (component)

**backup-migration** (7): Backup, restore, server-to-cloud migration.

`backup-manager` (component), `cloud-data-migrator` (component), `dashboard-gadget-data-exporter` (component), `migrateOptions` (web-resource), `migration-configuration-manager` (component), `migration-configurations-rc` (web-resource), `upgrade.001` (component)

**export** (23): Export and print renderers (Excel, printable view, JSON).

`excel-export` (servlet), `export-structure-as-json` (web-item), `exportrenderer-attribute` (structure-export-renderer-provider), `exportrenderer-comment` (structure-export-renderer-provider), `exportrenderer-excel-field` (structure-export-renderer-provider), `exportrenderer-excel-joined` (structure-export-renderer-provider), `exportrenderer-formula` (structure-export-renderer-provider), `exportrenderer-itemid` (structure-export-renderer-provider), `exportrenderer-main` (structure-export-renderer-provider), `exportrenderer-notes` (structure-export-renderer-provider), `exportrenderer-print-field` (structure-export-renderer-provider), `exportrenderer-print-icons` (structure-export-renderer-provider), `exportrenderer-print-joined` (structure-export-renderer-provider), `exportrenderer-progress` (structure-export-renderer-provider), `exportrenderer-querymatch` (structure-export-renderer-provider), `exportrenderer-rowid` (structure-export-renderer-provider), `exportrenderer-seq` (structure-export-renderer-provider), `exportrenderer-tempo-timeplanned` (structure-export-renderer-provider), `exportrenderer-tempo-worklogged` (structure-export-renderer-provider), `exportrenderer-timeinstatus` (structure-export-renderer-provider), `exportrenderer-worklogged` (structure-export-renderer-provider), `printable-rc` (web-resource), `user-printable-icon-cache` (component)

**integrations** (25): Integrations with other apps (Agile, Advanced Roadmaps, Tempo, Assets/Insight, Service Management, ScriptRunner and others).

`bulk-change-interceptor` (servlet-filter), `bulk-link-processor` (component), `confluence-auth-utils` (web-resource), `confluence-templates` (web-resource), `gh-integration` (component), `hidden-links-helper` (component), `insight-expr-converter` (component), `insight-integration-supplier` (component), `issue-links-bulk-source` (component), `macro-resources` (web-resource), `mail-sender` (component), `portfolio-bridge` (component), `portfolio-children-gatherer-factory` (component), `portfolio-integration` (component), `scriptrunner-integration` (component), `sd-integration-supplier` (component), `spic-sum-up-integration` (component), `sprint-tracker` (component), `stagil-integration` (component), `structure-activity-provider` (activity-streams-provider), `structure-workflow-condition` (workflow-condition), `structure-workflow-validator` (workflow-validator), `tempo-integration` (component), `tempo-internal-issues-interceptor` (servlet-filter), `treefield-integration` (component)

**ui-pages** (55): Front-end resources and server-rendered pages: board, grid, dialogs, admin pages.

`adjustIssuePage` (web-resource), `adjustIssuePageCond` (web-resource), `agile-structure` (new-structure-template), `backlog-structure` (new-structure-template), `create-structure-allowlist` (velocity-allowlist), `details-common` (web-resource), `details-providers` (web-resource), `dialog-common` (web-resource), `empty-structure` (new-structure-template), `favoriteEditor` (web-resource), `favorites` (web-resource), `ghTab` (web-resource), `greenhopper-tab` (web-panel), `help-rc` (web-resource), `help-widget` (web-resource), `hints` (web-resource), `issue-details` (web-resource), `issuePageDecorator` (web-resource), `login-page-renderer` (component), `manage-structure-service` (component), `manage-structures-allowlist` (velocity-allowlist), `manageAjaxTabs` (web-resource), `manageSearchType` (web-resource), `manageSpa` (web-resource), `new-structure-wizard-js` (web-resource), `option-source-service` (component), `option-source-tools` (component), `page-rc` (web-resource), `page-util` (web-resource), `pageCommons` (web-resource), `personal-backlog-structure` (new-structure-template), `perspective-mail-sender` (component), `perspective-manager` (component), `planning-task-common` (web-resource), `planningTaskCreationDialog` (web-resource), `react-components-common` (web-resource), `recents-search-service` (component), `structure-board-allowlist` (velocity-allowlist), `structure-helper-panel` (web-panel), `structure-welcome-allowlist` (velocity-allowlist), `structuremodule` (web-panel), `suggested-sprint-boards-service` (component), `template-agile` (web-resource), `template-backlog` (web-resource), `template-common` (web-resource), `template-personal-backlog` (web-resource), `ui-configurator` (component), `welcome` (web-resource), `widget` (web-resource), `widget-bare` (web-resource), `widget-css` (web-resource), `wiki-editor-theme-observer` (web-resource), `wp-projectnav-structure` (web-panel), `wr-project-page` (web-resource), `ww-structure` (webwork1)

**ui-navigation** (40): Menus, web sections and items, web panels, keyboard shortcut.

`goto.structure` (keyboard-shortcut), `slf-favorite-structures-factory` (simple-link-factory), `slf-structure-configs-factory` (simple-link-factory), `structure-admin` (web-section), `structure-admin-main` (web-section), `structure-admin-other` (web-section), `structure-available-on-issue-page-checker` (component), `structure-available-to-user-checker` (component), `structure-projectnav-css` (web-resource), `wi-admin-project-structure` (web-item), `wi-attributes` (web-item), `wi-backup-link` (web-item), `wi-default-project-structure` (web-item), `wi-default-system-structure` (web-item), `wi-help-link` (web-item), `wi-license-link` (web-item), `wi-maintenance-link` (web-item), `wi-migrate-link` (web-item), `wi-migrate-to-cloud-link` (web-item), `wi-processes` (web-item), `wi-projectnav-structure` (web-item), `wi-restore-link` (web-item), `wi-structure-admin` (web-item), `wi-structure-create-wiz` (web-item), `wi-structure-defaults` (web-item), `wi-structure-jira-home-51` (web-item), `wi-structure-link` (web-item), `wi-structure-manage` (web-item), `wi-structure-query` (web-item), `wi-structure-setup-guide` (web-item), `wi-support-link` (web-item), `wi-welcome-to-structure` (web-item), `ws-admin-project-structure` (web-section), `ws-default-structures` (web-section), `ws-favorite-structures` (web-section), `ws-processes-section` (web-section), `ws-structure-configs` (web-section), `ws-structure-manage-section` (web-section), `ws-structure-query-section` (web-section), `ws-welcome-to-structure` (web-section)

**rest-api** (8): REST modules and their resources.

`field-value-options` (component), `rest-cfd` (rest), `rest-subjects-searcher` (component), `rest-user-builder` (component), `rest-v1` (rest), `rest-v2` (rest), `structure-async-request-handler` (component), `structure-resource-service` (component)

**admin-config** (7): Global and per-project configuration and defaults.

`dark-features-rc` (web-resource), `help-content-manager` (component), `maintenance-manager` (component), `maintenanceParamsForm` (web-resource), `structure-admin-allowlist` (velocity-allowlist), `structure-configuration` (component), `wr-setup-guide` (web-resource)

**licensing-support** (13): Licensing, end-of-life notices, support tools, statistics.

`app-support-client` (component), `app-support-connector` (component), `app-support-store` (component), `certificate-manager` (component), `end-of-life` (web-resource), `end-of-life-decorator` (servlet-filter), `license-manager` (component), `plugin-manager-helper` (servlet-filter), `plugin-manager-helper-rc` (web-resource), `plugin-update-checker` (component), `stats-offer` (web-resource), `stats-offer-decorator` (servlet-filter), `structure-info` (web-resource)

**platform** (45): Jira-version adaptation, lifecycle, caching, cluster and utility services.

`action-context-bridge` (component), `ao-initializer` (component), `attachment-config-bridge` (component), `cluster-messaging-service-wrapper` (component), `dependency-watcher` (component), `events` (web-resource), `fonts` (web-resource), `format-helper` (component), `helper` (component), `http-request-emulator` (component), `http-servlet-variables-bridge` (component), `index-monitor-cf-searcher` (customfield-searcher), `index-monitor-cf-type` (customfield-type), `jira-components` (component), `jira-helper-factory` (component), `jquery` (web-resource), `jquery-ui` (web-resource), `jsutil` (web-resource), `lifecycle` (component), `momentjs` (web-resource), `pinger` (component), `react` (web-resource), `render-helper` (component), `servlet-bridges` (component), `stacktrace.js` (web-resource), `stateful-manager` (component), `structure-aui` (web-resource), `structure-cache-helper` (component), `structure-datetime-formatter` (component), `structure-general-allowlist` (velocity-allowlist), `structure-misc-allowlist` (velocity-allowlist), `sync-tools-factory` (component), `tslib` (web-resource), `uikit` (web-resource), `velocity-request-context-factory-bridge` (component), `vendors` (web-resource), `webresource-manager-bridge` (component), `webresource-url-provider-bridge` (component), `widget-atlas-deps` (web-resource), `widget-i18n` (web-resource), `widget-i18n-transformer` (url-reading-web-resource-transformer), `widget-i18n-transformer-cache` (component), `widget-i18n-transformer-common` (component), `widget-local-deps` (web-resource), `xml-datatype-converter-bridge` (component)

**cfd** (9): Cumulative flow diagram gadget and its back end.

`c3` (web-resource), `cfd-completion-service` (component), `cfd-distribution` (component), `cfd-gadget` (gadget), `cfd-gadget-bare` (web-resource), `cfd-gadget-resources` (web-resource), `cfd-issue-loader` (component), `cfd-meta-maker` (component), `cfd-simulator` (component)

**extension-points** (22): Module types and services the plugin offers to companion apps.

`extension-service` (component), `new-structure-template` (module-type), `structure-admin-extensions` (web-section), `structure-attribute-loader-provider` (module-type), `structure-backup-provider` (module-type), `structure-calendar-provider` (module-type), `structure-components` (component), `structure-core-extension` (module-type), `structure-effect-provider` (module-type), `structure-effector` (module-type), `structure-export-renderer-provider` (module-type), `structure-extender` (module-type), `structure-filter` (module-type), `structure-grouper` (module-type), `structure-inserter` (module-type), `structure-integration-details-provider` (module-type), `structure-item-type` (module-type), `structure-performance-log-provider` (module-type), `structure-query-constraint` (module-type), `structure-query-skeleton-factory` (module-type), `structure-sorter` (module-type), `structure-synchronizer` (module-type)

**gadgets** (5): Dashboard gadgets.

`gadget-bare` (web-resource), `gadget-resources` (web-resource), `remote-gadget-extension` (structure-core-extension), `structure-gadget` (gadget), `visibility-observer` (web-resource)

**performance** (21): Performance logging and monitoring.

`attribute-detailed-log-provider` (component), `attribute-performance-tracker` (component), `attribute-service-performance-log-provider` (structure-performance-log-provider), `effect-application-performance-log-provider` (structure-performance-log-provider), `effect-observer` (component), `effect-preparation-performance-log-provider` (structure-performance-log-provider), `forest-performance-log-provider` (structure-performance-log-provider), `forest-stats-container` (component), `forest-update-observer` (component), `forest-update-performance-log-provider` (structure-performance-log-provider), `forest-update-statistics-collector` (component), `item-tracker-performance-log-provider` (structure-performance-log-provider), `jira-configuration-cache` (component), `perf-audit-log-view-rc` (web-resource), `performance-observer` (component), `saved-structure-filters-log-provider` (structure-performance-log-provider), `structure-info-performance-log-provider` (structure-performance-log-provider), `sync-observer` (component), `sync-performance-log-provider` (structure-performance-log-provider), `value-cache-cleaner` (component), `version-info-performance-log-provider` (structure-performance-log-provider)

**user-data** (6): User key changes, anonymisation and ownership transfer (GDPR).

`recents-manager` (component), `structure-anonymize-handler` (component), `structure-ownership-transfer-handler` (ownership-transfer-handler), `structure-user-anonymization-handler` (user-anonymization-handler), `structure-user-key-change-handler` (user-key-change-handler), `view-anonymize-handler` (component)
<!-- index:end -->
