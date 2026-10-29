# SPEC: the plugin being replaced

Written by the analyst from the original plugin. It describes what the original does as seen from outside,
never how its code does it. Read `INVENTORY.md` first for what the plugin is and how its parts fit together.

**How to read this file.**
- **Part 1, the external contract**, lists everything the replacement must keep exactly, because Jira, other
  plugins, browsers, stored data or users' bookmarks depend on it. "Exactly" means byte for byte: keys, paths,
  parameter names, JSON keys, table and column names, persisted strings.
- **Part 2, the public Java API**, is in its own file, `API.md`: the types and signatures other plugins
  compile against. It is contract too.
- **Part 3, behaviour**, is in `claims.jsonl`: one testable behaviour per line, by module or by public API type.
- Everything not named here is your own design: class names, packages, internal structure, algorithms.
- Where this file and `inventory.json` differ on a contract fact, this file wins; `CHANGES-*.md` files win
  over both.
- Sections between `<!-- BEGIN generated -->` markers are generated from the original; they are complete
  lists.

The pinned platform is Jira 9.12 (see `pom.xml`). Where the original declares something differently for later
Jira versions, only the Jira 9.12 declaration is described.

# Part 1. The external contract

## 1.1 Plugin identity

| what | value | contract? |
|---|---|---|
| plugin key | `com.almworks.jira.structure` | yes |
| OSGi `Bundle-SymbolicName` | `com.almworks.jira.structure` (the plugin key) | yes |
| `plugins-version` | `2` (an OSGi plugin) | yes |
| display name, vendor, description, version, icons | the original's are the vendor's | **no: use your own** |

The replacement is installed in place of the original, so it keeps the key. It is not the vendor's product:
it never uses the original's display name or vendor name, and never claims to be the vendor's (product
owner decision, 2026-10-28).

**`plugin-info` parameters to keep,** because Jira and the plugin manager follow them:
- `configure.url` = `/secure/admin/StructureAdmin!view.jspa`
- `post.install.url` = `/secure/admin/StructureSetupGuide.jspa`
- `post.update.url` = `/secure/admin/StructureSetupGuide.jspa?update=true`
- `atlassian-data-center-compatible` = `true`, `atlassian-data-center-status` = `compatible`

**No licensing and no licence checking** (product owner decisions, 2026-10-28). The original declares
`atlassian-licensing-enabled`; the replacement does not, and it is never sold through the Marketplace. The
replacement contains no licence checking at all: it reads, validates and stores no licence, serial,
certificate or blocked-serial data, and nothing is ever refused, restricted, made read-only or warned about
on licence grounds. Where the public API, REST or the UI must report a licence state, it reports a fixed
"licensed, valid, not expiring" for the plugin and for every extension it recognises. The licence-related
modules keep their keys and types (they are contract) but do no licence work. Wherever this spec mentions an
unlicensed, expired, blocked or read-only licence, that state never occurs in the replacement.

**OSGi exports.** Other plugins compile against the public Java API (Part 2) and import it from this bundle.
The replacement exports exactly these packages:
- every package of the public API (`com.almworks.jira.structure.api` and its subpackages, listed in Part 2),
  at version `17.26.13`;
- the integer collections library the API's signatures use, `com.almworks.integers`,
  `com.almworks.integers.func`, `com.almworks.integers.segmented` and `com.almworks.integers.wrappers`, at
  version `1.1.3` (bundle the public `com.almworks.integers:integers` 1.1.3 and its wrappers from the offline
  repository).

The original also exports a few internal packages and bundled third-party libraries; those are not contract
and the replacement must not export internal packages (product owner decision, 2026-10-28).

**OSGi services.** The modules whose `contract.exports` in `inventory.json` names an interface publish a
service under that interface, and other plugins look the services up by it. All of those interfaces are public
API types except one, `com.almworks.jira.structure.generic.GenericItemHistoryManager`, which is contract as
well (Part 2 gives its signatures).

## 1.2 Modules

Every module of the original, with its key and type. The replacement declares each one with the same key and
type in its `atlassian-plugin.xml`. A *contract class* is a class name stored outside the plugin (in Jira's
workflow XML) and must be used as given; every other class name is yours. The externally visible attributes
of each declaration (URL patterns, locations, sections, web-resource contexts and dependencies, labels,
weights, exported interfaces, REST paths, webwork aliases) are listed per module in `inventory.json` under
`contract`, and are part of this contract.

**Module types are contract twice.** The 19 `module-type` modules define XML elements that *other* plugins
use in their own descriptors to extend this one (for example a `structure-attribute-loader-provider`
element). The element name is the module type's key. Their attributes and child elements are described
with each module type's claims.

**Module keys are stored data.** Jira stores complete module keys (`com.almworks.jira.structure:<key>`) in
its own database: in custom fields (custom field type and searcher), workflows, dashboards (gadgets) and
user preferences. Section 1.6 lists those uses.

<!-- BEGIN generated: modules -->
| key | type | contract class | group |
|---|---|---|---|
| `structure-components` | `component` |  | extension-points |
| `app-support-store` | `component` |  | licensing-support |
| `job-manager` | `component` |  | jobs-processes |
| `process-handle-manager` | `component` |  | jobs-processes |
| `backup-manager` | `component` |  | backup-migration |
| `structure-configuration` | `component` |  | admin-config |
| `event-bridge` | `component` |  | history-events |
| `favorite-manager` | `component` |  | core-model |
| `view-manager` | `component` |  | views-columns |
| `structure-query-builder-factory` | `component` |  | query |
| `structure-query-parser` | `component` |  | query |
| `structure-row-manager` | `component` |  | core-model |
| `attribute-service` | `component` |  | attributes |
| `attribute-subscription-service` | `component` |  | attributes |
| `structure-manager` | `component` |  | core-model |
| `generator-manager` | `component` |  | generators |
| `item-resolver` | `component` |  | core-model |
| `folder-manager` | `component` |  | core-model |
| `sync-manager` | `component` |  | sync |
| `sync-audit-log` | `component` |  | sync |
| `helper` | `component` |  | platform |
| `scheduled-job-manager` | `component` |  | jobs-processes |
| `property-service` | `component` |  | persistence |
| `structure-property-service` | `component` |  | persistence |
| `item-tracker` | `component` |  | history-events |
| `forest-service` | `component` |  | core-model |
| `generic-item-service` | `component` |  | core-model |
| `generic-item-manager` | `component` |  | core-model |
| `generic-item-history-manager` | `component` |  | history-events |
| `effect-service` | `component` |  | effects |
| `statistics-manager` | `component` |  | history-events |
| `effector-process-manager` | `component` |  | effects |
| `effector-instance-manager` | `component` |  | effects |
| `memo-manager` | `component` |  | core-model |
| `planning-task-manager` | `component` |  | core-model |
| `structure-synchronizer` | `module-type` |  | extension-points |
| `structure-export-renderer-provider` | `module-type` |  | extension-points |
| `structure-item-type` | `module-type` |  | extension-points |
| `structure-inserter` | `module-type` |  | extension-points |
| `structure-extender` | `module-type` |  | extension-points |
| `structure-grouper` | `module-type` |  | extension-points |
| `structure-filter` | `module-type` |  | extension-points |
| `structure-sorter` | `module-type` |  | extension-points |
| `structure-attribute-loader-provider` | `module-type` |  | extension-points |
| `new-structure-template` | `module-type` |  | extension-points |
| `structure-query-constraint` | `module-type` |  | extension-points |
| `structure-effector` | `module-type` |  | extension-points |
| `structure-core-extension` | `module-type` |  | extension-points |
| `structure-performance-log-provider` | `module-type` |  | extension-points |
| `structure-query-skeleton-factory` | `module-type` |  | extension-points |
| `structure-effect-provider` | `module-type` |  | extension-points |
| `structure-backup-provider` | `module-type` |  | extension-points |
| `structure-calendar-provider` | `module-type` |  | extension-points |
| `structure-integration-details-provider` | `module-type` |  | extension-points |
| `rest-v1` | `rest` |  | rest-api |
| `rest-v2` | `rest` |  | rest-api |
| `rest-cfd` | `rest` |  | rest-api |
| `remote-gadget-extension` | `structure-core-extension` |  | gadgets |
| `sync-tools-factory` | `component` |  | platform |
| `maintenance-manager` | `component` |  | admin-config |
| `ao-based-statistics-service` | `component` |  | persistence |
| `performance-observer` | `component` |  | performance |
| `structure-features-statistic-source` | `component` |  | history-events |
| `process-io` | `component` |  | persistence |
| `ao-initializer` | `component` |  | platform |
| `lucene-helper` | `component` |  | query |
| `reindex-locker` | `component` |  | sync |
| `index-search-service` | `component` |  | query |
| `index-flusher` | `component` |  | query |
| `permissions-calculator` | `component` |  | permissions-security |
| `permissions-cache` | `component` |  | permissions-security |
| `lifecycle` | `component` |  | platform |
| `pinger` | `component` |  | platform |
| `dependency-watcher` | `component` |  | platform |
| `perspective-manager` | `component` |  | ui-pages |
| `perspective-io` | `component` |  | persistence |
| `recent-issue-inserter` | `component` |  | generators |
| `ao-based-view-manager` | `component` |  | views-columns |
| `sprint-tracker` | `component` |  | integrations |
| `sync-events-manager` | `component` |  | sync |
| `ordering-io` | `component` |  | persistence |
| `issue-constant-icon-cache` | `component` |  | views-columns |
| `user-icon-cache` | `component` |  | views-columns |
| `user-printable-icon-cache` | `component` |  | export |
| `structure-query-constraint-registry` | `component` |  | query |
| `item-query-constraint` | `component` |  | query |
| `expr-function-services` | `component` |  | query |
| `expr-parser` | `component` |  | query |
| `expr-function-provider` | `component` |  | query |
| `expr-aggregation-provider` | `component` |  | query |
| `expr-constraints` | `component` |  | query |
| `jira-components` | `component` |  | platform |
| `value-text-converter` | `component` |  | attributes |
| `generation-manager` | `component` |  | generators |
| `notes-manager` | `component` |  | persistence |
| `item-property-editors` | `component` |  | views-columns |
| `effector-process-io` | `component` |  | persistence |
| `attribute-loader-cache` | `component` |  | attributes |
| `attribute-sensitivity-manager` | `component` |  | permissions-security |
| `attribute-aware-process-registry` | `component` |  | attributes |
| `attribute-service-support` | `component` |  | attributes |
| `attribute-detailed-log-provider` | `component` |  | performance |
| `value-cache-cleaner` | `component` |  | performance |
| `jira-configuration-cache` | `component` |  | performance |
| `structure-usage-tracker` | `component` |  | history-events |
| `http-request-emulator` | `component` |  | platform |
| `jira-helper-factory` | `component` |  | platform |
| `jira-thread-env-factory` | `component` |  | jobs-processes |
| `structure-issue-index` | `component` |  | query |
| `cfd-completion-service` | `component` |  | cfd |
| `cfd-issue-loader` | `component` |  | cfd |
| `cfd-distribution` | `component` |  | cfd |
| `cfd-simulator` | `component` |  | cfd |
| `cfd-meta-maker` | `component` |  | cfd |
| `end-of-life-decorator` | `servlet-filter` |  | licensing-support |
| `stats-offer-decorator` | `servlet-filter` |  | licensing-support |
| `issue-change-interceptor` | `servlet-filter` |  | history-events |
| `bulk-change-interceptor` | `servlet-filter` |  | integrations |
| `plugin-manager-helper` | `servlet-filter` |  | licensing-support |
| `tempo-internal-issues-interceptor` | `servlet-filter` |  | integrations |
| `security-filter` | `servlet-filter` |  | permissions-security |
| `partitioned-cookie-header-filter` | `servlet-filter` |  | permissions-security |
| `license-manager` | `component` |  | licensing-support |
| `greenhopper-tab` | `web-panel` |  | ui-pages |
| `structure-helper-panel` | `web-panel` |  | ui-pages |
| `structuremodule` | `web-panel` |  | ui-pages |
| `wi-projectnav-structure` | `web-item` |  | ui-navigation |
| `wp-projectnav-structure` | `web-panel` |  | ui-pages |
| `wr-project-page` | `web-resource` |  | ui-pages |
| `wi-structure-link` | `web-item` |  | ui-navigation |
| `ws-welcome-to-structure` | `web-section` |  | ui-navigation |
| `wi-welcome-to-structure` | `web-item` |  | ui-navigation |
| `ws-structure-configs` | `web-section` |  | ui-navigation |
| `ws-favorite-structures` | `web-section` |  | ui-navigation |
| `ws-default-structures` | `web-section` |  | ui-navigation |
| `wi-default-project-structure` | `web-item` |  | ui-navigation |
| `wi-default-system-structure` | `web-item` |  | ui-navigation |
| `slf-structure-configs-factory` | `simple-link-factory` |  | ui-navigation |
| `slf-favorite-structures-factory` | `simple-link-factory` |  | ui-navigation |
| `ws-structure-query-section` | `web-section` |  | ui-navigation |
| `wi-structure-query` | `web-item` |  | ui-navigation |
| `ws-structure-manage-section` | `web-section` |  | ui-navigation |
| `wi-structure-create-wiz` | `web-item` |  | ui-navigation |
| `wi-structure-manage` | `web-item` |  | ui-navigation |
| `ws-processes-section` | `web-section` |  | ui-navigation |
| `wi-processes` | `web-item` |  | ui-navigation |
| `wi-structure-jira-home-51` | `web-item` |  | ui-navigation |
| `structure-admin` | `web-section` |  | ui-navigation |
| `structure-admin-main` | `web-section` |  | ui-navigation |
| `structure-admin-extensions` | `web-section` |  | extension-points |
| `structure-admin-other` | `web-section` |  | ui-navigation |
| `wi-structure-setup-guide` | `web-item` |  | ui-navigation |
| `wi-migrate-to-cloud-link` | `web-item` |  | ui-navigation |
| `wi-structure-admin` | `web-item` |  | ui-navigation |
| `wi-structure-defaults` | `web-item` |  | ui-navigation |
| `ws-admin-project-structure` | `web-section` |  | ui-navigation |
| `wi-admin-project-structure` | `web-item` |  | ui-navigation |
| `wi-backup-link` | `web-item` |  | ui-navigation |
| `wi-restore-link` | `web-item` |  | ui-navigation |
| `wi-migrate-link` | `web-item` |  | ui-navigation |
| `wi-maintenance-link` | `web-item` |  | ui-navigation |
| `wi-license-link` | `web-item` |  | ui-navigation |
| `wi-support-link` | `web-item` |  | ui-navigation |
| `wi-attributes` | `web-item` |  | ui-navigation |
| `wi-help-link` | `web-item` |  | ui-navigation |
| `ww-structure` | `webwork1` |  | ui-pages |
| `page-rc` | `web-resource` |  | ui-pages |
| `hints` | `web-resource` |  | ui-pages |
| `end-of-life` | `web-resource` |  | licensing-support |
| `wr-setup-guide` | `web-resource` |  | admin-config |
| `stats-offer` | `web-resource` |  | licensing-support |
| `sjql-troubleshooting` | `web-resource` |  | query |
| `sync-audit-log-view-rc` | `web-resource` |  | sync |
| `perf-audit-log-view-rc` | `web-resource` |  | performance |
| `attribute-troubleshooting-rc` | `web-resource` |  | attributes |
| `stacktrace.js` | `web-resource` |  | platform |
| `events` | `web-resource` |  | platform |
| `jsutil` | `web-resource` |  | platform |
| `printable-rc` | `web-resource` |  | export |
| `dark-features-rc` | `web-resource` |  | admin-config |
| `widget-i18n` | `web-resource` |  | platform |
| `structure-permissions` | `web-resource` |  | permissions-security |
| `widget-i18n-transformer` | `url-reading-web-resource-transformer` |  | platform |
| `widget-i18n-transformer-common` | `component` |  | platform |
| `widget-i18n-transformer-cache` | `component` |  | platform |
| `confluence-templates` | `web-resource` |  | integrations |
| `widget-css` | `web-resource` |  | ui-pages |
| `structure-aui` | `web-resource` |  | platform |
| `structure-projectnav-css` | `web-resource` |  | ui-navigation |
| `c3` | `web-resource` |  | cfd |
| `widget-bare` | `web-resource` |  | ui-pages |
| `dialog-common` | `web-resource` |  | ui-pages |
| `issue-details` | `web-resource` |  | ui-pages |
| `react-components-common` | `web-resource` |  | ui-pages |
| `details-common` | `web-resource` |  | ui-pages |
| `details-providers` | `web-resource` |  | ui-pages |
| `planning-task-common` | `web-resource` |  | ui-pages |
| `widget` | `web-resource` |  | ui-pages |
| `widget-atlas-deps` | `web-resource` |  | platform |
| `widget-local-deps` | `web-resource` |  | platform |
| `structure-info` | `web-resource` |  | licensing-support |
| `ghTab` | `web-resource` |  | ui-pages |
| `planningTaskCreationDialog` | `web-resource` |  | ui-pages |
| `pageCommons` | `web-resource` |  | ui-pages |
| `issuePageDecorator` | `web-resource` |  | ui-pages |
| `adjustIssuePageCond` | `web-resource` |  | ui-pages |
| `adjustIssuePage` | `web-resource` |  | ui-pages |
| `favorites` | `web-resource` |  | ui-pages |
| `manageSearchType` | `web-resource` |  | ui-pages |
| `manageAjaxTabs` | `web-resource` |  | ui-pages |
| `vendors` | `web-resource` |  | platform |
| `manageSpa` | `web-resource` |  | ui-pages |
| `favoriteEditor` | `web-resource` |  | ui-pages |
| `wiki-editor-theme-observer` | `web-resource` |  | ui-pages |
| `page-util` | `web-resource` |  | ui-pages |
| `permissionsEditor` | `web-resource` |  | permissions-security |
| `migrateOptions` | `web-resource` |  | backup-migration |
| `maintenanceParamsForm` | `web-resource` |  | admin-config |
| `structure-views-js` | `web-resource` |  | views-columns |
| `new-structure-wizard-js` | `web-resource` |  | ui-pages |
| `template-common` | `web-resource` |  | ui-pages |
| `template-backlog` | `web-resource` |  | ui-pages |
| `template-personal-backlog` | `web-resource` |  | ui-pages |
| `template-agile` | `web-resource` |  | ui-pages |
| `effector-common` | `web-resource` |  | effects |
| `effector-audit` | `web-resource` |  | effects |
| `effector-processes` | `web-resource` |  | effects |
| `fonts` | `web-resource` |  | platform |
| `jquery` | `web-resource` |  | platform |
| `jquery-ui` | `web-resource` |  | platform |
| `react` | `web-resource` |  | platform |
| `uikit` | `web-resource` |  | platform |
| `momentjs` | `web-resource` |  | platform |
| `plugin-manager-helper-rc` | `web-resource` |  | licensing-support |
| `tslib` | `web-resource` |  | platform |
| `attribute-sensitivity-rc` | `web-resource` |  | attributes |
| `migration-configurations-rc` | `web-resource` |  | backup-migration |
| `help-rc` | `web-resource` |  | ui-pages |
| `help-widget` | `web-resource` |  | ui-pages |
| `welcome` | `web-resource` |  | ui-pages |
| `formula-icons` | `web-resource` |  | attributes |
| `goto.structure` | `keyboard-shortcut` |  | ui-navigation |
| `sync-filter` | `structure-synchronizer` |  | sync |
| `filtersync-config-js` | `web-resource` |  | sync |
| `sync-links` | `structure-synchronizer` |  | sync |
| `linksync-config-js` | `web-resource` |  | sync |
| `sync-gh` | `structure-synchronizer` |  | sync |
| `ghsync-config-js` | `web-resource` |  | sync |
| `sync-status-rollup` | `structure-synchronizer` |  | sync |
| `statusup-config-js` | `web-resource` |  | sync |
| `sync-subtasks` | `structure-synchronizer` |  | sync |
| `confluence-auth-utils` | `web-resource` |  | integrations |
| `bulk-link-processor` | `component` |  | integrations |
| `item-type-registry` | `component` |  | core-model |
| `structure-database-provider` | `component` |  | persistence |
| `ao-lock` | `component` |  | persistence |
| `ao-helper` | `component` |  | persistence |
| `item-identity-mapper` | `component` |  | core-model |
| `persistent-row-manager` | `component` |  | persistence |
| `transient-row-manager` | `component` |  | core-model |
| `transient-generator-manager` | `component` |  | generators |
| `persistent-generator-manager` | `component` |  | persistence |
| `forest-permissions-cache` | `component` |  | permissions-security |
| `project-scope-cache` | `component` |  | permissions-security |
| `sub-task-issue-cache` | `component` |  | core-model |
| `data-tracker` | `component` |  | history-events |
| `history-recorder` | `component` |  | history-events |
| `history-recorder-io` | `component` |  | persistence |
| `history-service` | `component` |  | history-events |
| `ui-configurator` | `component` |  | ui-pages |
| `issue-cloner` | `component` |  | jobs-processes |
| `stateful-manager` | `component` |  | platform |
| `gh-integration` | `component` |  | integrations |
| `portfolio-bridge` | `component` |  | integrations |
| `portfolio-integration` | `component` |  | integrations |
| `portfolio-children-gatherer-factory` | `component` |  | integrations |
| `tempo-integration` | `component` |  | integrations |
| `treefield-integration` | `component` |  | integrations |
| `spic-sum-up-integration` | `component` |  | integrations |
| `scriptrunner-integration` | `component` |  | integrations |
| `sd-integration-supplier` | `component` |  | integrations |
| `app-support-connector` | `component` |  | licensing-support |
| `app-support-client` | `component` |  | licensing-support |
| `certificate-manager` | `component` |  | licensing-support |
| `extension-service` | `component` |  | extension-points |
| `clipboard-manager` | `component` |  | core-model |
| `recents-manager` | `component` |  | user-data |
| `cluster-messaging-service-wrapper` | `component` |  | platform |
| `structure-cache-helper` | `component` |  | platform |
| `format-helper` | `component` |  | platform |
| `rest-subjects-searcher` | `component` |  | rest-api |
| `forest-stats-container` | `component` |  | performance |
| `forest-update-observer` | `component` |  | performance |
| `attribute-performance-tracker` | `component` |  | performance |
| `sync-observer` | `component` |  | performance |
| `effect-observer` | `component` |  | performance |
| `adjustment-store` | `component` |  | persistence |
| `adjustment-service` | `component` |  | generators |
| `query-result-cache` | `component` |  | query |
| `various-query-parser` | `component` |  | query |
| `plugin-update-checker` | `component` |  | licensing-support |
| `attachment-config-bridge` | `component` |  | platform |
| `cloud-data-migrator` | `component` |  | backup-migration |
| `migration-configuration-manager` | `component` |  | backup-migration |
| `dashboard-gadget-data-exporter` | `component` |  | backup-migration |
| `user-field-renderer` | `component` |  | views-columns |
| `bulk-permission-checker` | `component` |  | permissions-security |
| `bulk-comment-reader` | `component` |  | attributes |
| `effect-based-issue-movers` | `component` |  | generators |
| `exportrenderer-excel-field` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-excel-joined` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-print-field` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-print-joined` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-print-icons` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-main` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-progress` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-worklogged` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-attribute` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-seq` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-itemid` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-rowid` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-formula` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-notes` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-timeinstatus` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-querymatch` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-comment` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-tempo-worklogged` | `structure-export-renderer-provider` |  | export |
| `exportrenderer-tempo-timeplanned` | `structure-export-renderer-provider` |  | export |
| `type-structure` | `structure-item-type` |  | core-model |
| `type-issue` | `structure-item-type` |  | core-model |
| `type-project` | `structure-item-type` |  | core-model |
| `type-version` | `structure-item-type` |  | core-model |
| `type-version-name` | `structure-item-type` |  | core-model |
| `type-label` | `structure-item-type` |  | core-model |
| `type-loop-marker` | `structure-item-type` |  | core-model |
| `type-generator` | `structure-item-type` |  | core-model |
| `type-user` | `structure-item-type` |  | core-model |
| `type-folder` | `structure-item-type` |  | core-model |
| `type-status` | `structure-item-type` |  | core-model |
| `type-resolution` | `structure-item-type` |  | core-model |
| `type-issuetype` | `structure-item-type` |  | core-model |
| `type-priority` | `structure-item-type` |  | core-model |
| `type-group` | `structure-item-type` |  | core-model |
| `type-cf-option` | `structure-item-type` |  | core-model |
| `type-sprint` | `structure-item-type` |  | core-model |
| `type-tempo-account` | `structure-item-type` |  | core-model |
| `type-project-component` | `structure-item-type` |  | core-model |
| `type-missing` | `structure-item-type` |  | core-model |
| `type-sd-request-type` | `structure-item-type` |  | core-model |
| `type-effector` | `structure-item-type` |  | core-model |
| `type-memo` | `structure-item-type` |  | core-model |
| `type-planning-task` | `structure-item-type` |  | core-model |
| `type-attachment` | `structure-item-type` |  | core-model |
| `type-comment` | `structure-item-type` |  | core-model |
| `type-worklog` | `structure-item-type` |  | core-model |
| `type-issue-link` | `structure-item-type` |  | core-model |
| `type-issue-link-type` | `structure-item-type` |  | core-model |
| `type-change-history-group` | `structure-item-type` |  | core-model |
| `type-change-history-item` | `structure-item-type` |  | core-model |
| `type-memo-change-history-group` | `structure-item-type` |  | core-model |
| `type-insight-object` | `structure-item-type` |  | core-model |
| `type-remote-link` | `structure-item-type` |  | core-model |
| `inserter-jql` | `structure-inserter` |  | generators |
| `agile-board` | `structure-inserter` |  | generators |
| `inserter-text` | `structure-inserter` |  | generators |
| `inserter-substructure` | `structure-inserter` |  | generators |
| `inserter-recent-issues` | `structure-inserter` |  | generators |
| `extender-subtasks` | `structure-extender` |  | generators |
| `extender-links` | `structure-extender` |  | generators |
| `extender-agile` | `structure-extender` |  | generators |
| `extender-portfolio-children` | `structure-extender` |  | generators |
| `grouper-field` | `structure-grouper` |  | generators |
| `grouper-sprint` | `structure-grouper` |  | generators |
| `grouper-agile-epic` | `structure-grouper` |  | generators |
| `grouper-text` | `structure-grouper` |  | generators |
| `grouper-portfolio-parent` | `structure-grouper` |  | generators |
| `grouper-tempo-account` | `structure-grouper` |  | generators |
| `grouper-version-name` | `structure-grouper` |  | generators |
| `grouper-links` | `structure-grouper` |  | generators |
| `sorter-attribute` | `structure-sorter` |  | generators |
| `sorter-agile-rank` | `structure-sorter` |  | generators |
| `sorter-manual` | `structure-sorter` |  | generators |
| `filter-by-field` | `structure-filter` |  | generators |
| `filter-jql` | `structure-filter` |  | generators |
| `filter-text` | `structure-filter` |  | generators |
| `filter-attribute` | `structure-filter` |  | generators |
| `filter-number-attribute` | `structure-filter` |  | generators |
| `filter-sjql` | `structure-filter` |  | generators |
| `filter-item` | `structure-filter` |  | generators |
| `filter-inserter-extender-duplicates` | `structure-filter` |  | generators |
| `filter-sprint` | `structure-filter` |  | generators |
| `item-provider` | `structure-attribute-loader-provider` |  | attributes |
| `displayable-provider` | `structure-attribute-loader-provider` |  | attributes |
| `number-sum-provider` | `structure-attribute-loader-provider` |  | attributes |
| `error-provider` | `structure-attribute-loader-provider` |  | attributes |
| `main-provider` | `structure-attribute-loader-provider` |  | attributes |
| `key-provider` | `structure-attribute-loader-provider` |  | attributes |
| `done-provider` | `structure-attribute-loader-provider` |  | attributes |
| `editable-provider` | `structure-attribute-loader-provider` |  | attributes |
| `icon-provider` | `structure-attribute-loader-provider` |  | attributes |
| `issue-field-provider` | `structure-attribute-loader-provider` |  | attributes |
| `issue-field-rendering-provider` | `structure-attribute-loader-provider` |  | attributes |
| `issue-field-order-provider` | `structure-attribute-loader-provider` |  | attributes |
| `issue-time-field-provider` | `structure-attribute-loader-provider` |  | attributes |
| `date-field-provider` | `structure-attribute-loader-provider` |  | attributes |
| `enum-customfield-order-provider` | `structure-attribute-loader-provider` |  | attributes |
| `customfield-provider` | `structure-attribute-loader-provider` |  | attributes |
| `progress-provider` | `structure-attribute-loader-provider` |  | attributes |
| `worklogged-provider` | `structure-attribute-loader-provider` |  | attributes |
| `is-user-added-automation-provider` | `structure-attribute-loader-provider` |  | attributes |
| `children-automations-hint-provider` | `structure-attribute-loader-provider` |  | attributes |
| `non-unique-items-provider` | `structure-attribute-loader-provider` |  | attributes |
| `run-as-user-provider` | `structure-attribute-loader-provider` |  | attributes |
| `original-generator-kind-provider` | `structure-attribute-loader-provider` |  | attributes |
| `basic-generation-info-provider` | `structure-attribute-loader-provider` |  | attributes |
| `status-attributes-provider` | `structure-attribute-loader-provider` |  | attributes |
| `primitives-provider` | `structure-attribute-loader-provider` |  | attributes |
| `sequence-provider` | `structure-attribute-loader-provider` |  | attributes |
| `links-count` | `structure-attribute-loader-provider` |  | attributes |
| `expr-attribute` | `structure-attribute-loader-provider` |  | attributes |
| `issue-field-text-provider` | `structure-attribute-loader-provider` |  | attributes |
| `issue-field-item-provider` | `structure-attribute-loader-provider` |  | attributes |
| `comments-item-provider` | `structure-attribute-loader-provider` |  | attributes |
| `worklog-objects-provider` | `structure-attribute-loader-provider` |  | attributes |
| `change-history-provider` | `structure-attribute-loader-provider` |  | attributes |
| `issue-parent-provider` | `structure-attribute-loader-provider` |  | attributes |
| `epic-issue-provider` | `structure-attribute-loader-provider` |  | attributes |
| `subtasks-provider` | `structure-attribute-loader-provider` |  | attributes |
| `issue-link-objects-provider` | `structure-attribute-loader-provider` |  | attributes |
| `remote-link-objects-provider` | `structure-attribute-loader-provider` |  | attributes |
| `user-property-provider` | `structure-attribute-loader-provider` |  | attributes |
| `formatted-number-provider` | `structure-attribute-loader-provider` |  | attributes |
| `notes-provider` | `structure-attribute-loader-provider` |  | attributes |
| `aggregate-order-provider` | `structure-attribute-loader-provider` |  | attributes |
| `value-path-provider` | `structure-attribute-loader-provider` |  | attributes |
| `parent-provider` | `structure-attribute-loader-provider` |  | attributes |
| `aggregate-function-provider` | `structure-attribute-loader-provider` |  | attributes |
| `manually-adjusted-provider` | `structure-attribute-loader-provider` |  | attributes |
| `wiki-rendering-provider` | `structure-attribute-loader-provider` |  | attributes |
| `version-name-provider` | `structure-attribute-loader-provider` |  | attributes |
| `time-in-status-provider` | `structure-attribute-loader-provider` |  | attributes |
| `status-category-provider` | `structure-attribute-loader-provider` |  | attributes |
| `project-category-provider` | `structure-attribute-loader-provider` |  | attributes |
| `transition-date-provider` | `structure-attribute-loader-provider` |  | attributes |
| `query-match-provider` | `structure-attribute-loader-provider` |  | attributes |
| `issue-comment-provider` | `structure-attribute-loader-provider` |  | attributes |
| `version-parameters-provider` | `structure-attribute-loader-provider` |  | attributes |
| `sprint-parameters-provider` | `structure-attribute-loader-provider` |  | attributes |
| `project-parameters-provider` | `structure-attribute-loader-provider` |  | attributes |
| `tempo-provider` | `structure-attribute-loader-provider` |  | attributes |
| `generic-item-fields-provider` | `structure-attribute-loader-provider` |  | attributes |
| `generic-item-attribute-provider` | `structure-attribute-loader-provider` |  | attributes |
| `generic-item-history-provider` | `structure-attribute-loader-provider` |  | attributes |
| `generic-item-history-based-fields-provider` | `structure-attribute-loader-provider` |  | attributes |
| `empty-structure` | `new-structure-template` |  | ui-pages |
| `personal-backlog-structure` | `new-structure-template` |  | ui-pages |
| `backlog-structure` | `new-structure-template` |  | ui-pages |
| `agile-structure` | `new-structure-template` |  | ui-pages |
| `constraint-folder` | `structure-query-constraint` |  | query |
| `constraint-memo` | `structure-query-constraint` |  | query |
| `constraint-item` | `structure-query-constraint` |  | query |
| `constraint-rowId` | `structure-query-constraint` |  | query |
| `constraint-planningtask` | `structure-query-constraint` |  | query |
| `version-info-performance-log-provider` | `structure-performance-log-provider` |  | performance |
| `structure-info-performance-log-provider` | `structure-performance-log-provider` |  | performance |
| `saved-structure-filters-log-provider` | `structure-performance-log-provider` |  | performance |
| `forest-performance-log-provider` | `structure-performance-log-provider` |  | performance |
| `sync-performance-log-provider` | `structure-performance-log-provider` |  | performance |
| `forest-update-performance-log-provider` | `structure-performance-log-provider` |  | performance |
| `attribute-service-performance-log-provider` | `structure-performance-log-provider` |  | performance |
| `item-tracker-performance-log-provider` | `structure-performance-log-provider` |  | performance |
| `effect-application-performance-log-provider` | `structure-performance-log-provider` |  | performance |
| `effect-preparation-performance-log-provider` | `structure-performance-log-provider` |  | performance |
| `assignee-effect-provider` | `structure-effect-provider` |  | effects |
| `priority-effect-provider` | `structure-effect-provider` |  | effects |
| `description-effect-provider` | `structure-effect-provider` |  | effects |
| `environment-effect-provider` | `structure-effect-provider` |  | effects |
| `resolution-effect-provider` | `structure-effect-provider` |  | effects |
| `summary-effect-provider` | `structure-effect-provider` |  | effects |
| `due-date-effect-provider` | `structure-effect-provider` |  | effects |
| `reporter-effect-provider` | `structure-effect-provider` |  | effects |
| `status-effect-provider` | `structure-effect-provider` |  | effects |
| `cascade-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `project-picker-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `script-runner-single-issue-picker-effect-provider` | `structure-effect-provider` |  | effects |
| `single-select-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `portfolio-team-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `single-user-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `single-group-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `single-version-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `text-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `number-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `date-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `date-time-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `labels-effect-provider` | `structure-effect-provider` |  | effects |
| `multi-versions-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `affects-versions-effect-provider` | `structure-effect-provider` |  | effects |
| `fix-versions-effect-provider` | `structure-effect-provider` |  | effects |
| `components-effect-provider` | `structure-effect-provider` |  | effects |
| `multi-select-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `multi-user-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `multi-group-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `multi-labels-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `insight-object-custom-field-effect-provider` | `structure-effect-provider` |  | effects |
| `warning-effect-provider` | `structure-effect-provider` |  | effects |
| `delay-effect-provider` | `structure-effect-provider` |  | effects |
| `original-estimate-effect-provider` | `structure-effect-provider` |  | effects |
| `remaining-estimate-effect-provider` | `structure-effect-provider` |  | effects |
| `sprint-effect-provider` | `structure-effect-provider` |  | effects |
| `add-comment-effect-provider` | `structure-effect-provider` |  | effects |
| `delete-comment-effect-provider` | `structure-effect-provider` |  | effects |
| `memo-field-effect-provider` | `structure-effect-provider` |  | effects |
| `conversion-effect-provider` | `structure-effect-provider` |  | effects |
| `effector-attribute-to-field` | `structure-effector` |  | effects |
| `effector-status-rollup` | `structure-effector` |  | effects |
| `effector-delay` | `structure-effector` |  | effects |
| `effector-conversion` | `structure-effector` |  | effects |
| `simple-calendar-provider` | `structure-calendar-provider` |  | attributes |
| `visibility-observer` | `web-resource` |  | gadgets |
| `gadget-bare` | `web-resource` |  | gadgets |
| `gadget-resources` | `web-resource` |  | gadgets |
| `macro-resources` | `web-resource` |  | integrations |
| `structure-gadget` | `gadget` |  | gadgets |
| `cfd-gadget-bare` | `web-resource` |  | cfd |
| `cfd-gadget-resources` | `web-resource` |  | cfd |
| `cfd-gadget` | `gadget` |  | cfd |
| `jql-structure` | `jql-function` |  | query |
| `excel-export` | `servlet` |  | export |
| `structure-activity-provider` | `activity-streams-provider` |  | integrations |
| `structure-workflow-condition` | `workflow-condition` | `com.almworks.jira.structure.workflow.StructureWorkflowChecker` | integrations |
| `structure-workflow-validator` | `workflow-validator` | `com.almworks.jira.structure.workflow.StructureWorkflowChecker` | integrations |
| `wf-statistics` | `component` |  | history-events |
| `ao` | `ao` |  | persistence |
| `upgrade.001` | `component` |  | backup-migration |
| `export-structure-as-json` | `web-item` |  | export |
| `index-monitor-cf-type` | `customfield-type` |  | platform |
| `index-monitor-cf-searcher` | `customfield-searcher` |  | platform |
| `issue-reindex-tracker` | `component` |  | history-events |
| `issue-links-bulk-source` | `component` |  | integrations |
| `reindex-manager` | `component` |  | history-events |
| `stagil-integration` | `component` |  | integrations |
| `hidden-links-helper` | `component` |  | integrations |
| `issue-links-support` | `component` |  | generators |
| `sync-hide-helper` | `component` |  | sync |
| `structure-event-bridge` | `component` |  | history-events |
| `structure-users-event-bridge` | `component` |  | history-events |
| `structure-anonymize-handler` | `component` |  | user-data |
| `view-anonymize-handler` | `component` |  | user-data |
| `structure-deleted-event-listener` | `component` |  | history-events |
| `structure-datetime-formatter` | `component` |  | platform |
| `mail-sender` | `component` |  | integrations |
| `perspective-mail-sender` | `component` |  | ui-pages |
| `extended-value-tools` | `component` |  | attributes |
| `field-information-provider` | `component` |  | attributes |
| `custom-field-resolver` | `component` |  | attributes |
| `help-content-manager` | `component` |  | admin-config |
| `rest-user-builder` | `component` |  | rest-api |
| `render-helper` | `component` |  | platform |
| `field-value-options` | `component` |  | rest-api |
| `user-display-name-searcher` | `component` |  | query |
| `saved-column-io` | `component` |  | persistence |
| `bundled-column-source` | `component` |  | views-columns |
| `stored-column-source` | `component` |  | views-columns |
| `saved-column-manager` | `component` |  | views-columns |
| `effect-provider-helper` | `component` |  | effects |
| `forest-update-statistics-collector` | `component` |  | performance |
| `note-manager` | `component` |  | persistence |
| `structure-field-type-manager` | `component` |  | core-model |
| `structure-field-manager` | `component` |  | core-model |
| `permission-scheme-manager` | `component` |  | permissions-security |
| `manage-structure-service` | `component` |  | ui-pages |
| `structure-resource-service` | `component` |  | rest-api |
| `option-source-service` | `component` |  | ui-pages |
| `option-source-tools` | `component` |  | ui-pages |
| `recents-search-service` | `component` |  | ui-pages |
| `suggested-sprint-boards-service` | `component` |  | ui-pages |
| `note-searcher` | `component` |  | views-columns |
| `generic-item-field-config-service` | `component` |  | core-model |
| `jira-field-visibility-service` | `component` |  | core-model |
| `generic-item-type-helper` | `component` |  | core-model |
| `generic-item-field-accessor-manager` | `component` |  | core-model |
| `issue-to-planning-task-converter` | `component` |  | core-model |
| `insight-integration-supplier` | `component` |  | integrations |
| `insight-expr-converter` | `component` |  | integrations |
| `login-page-renderer` | `component` |  | ui-pages |
| `structure-async-request-handler` | `component` |  | rest-api |
| `webresource-url-provider-bridge` | `component` |  | platform |
| `structure-available-to-user-checker` | `component` |  | ui-navigation |
| `structure-available-on-issue-page-checker` | `component` |  | ui-navigation |
| `webresource-manager-bridge` | `component` |  | platform |
| `servlet-bridges` | `component` |  | platform |
| `velocity-request-context-factory-bridge` | `component` |  | platform |
| `http-servlet-variables-bridge` | `component` |  | platform |
| `action-context-bridge` | `component` |  | platform |
| `xml-datatype-converter-bridge` | `component` |  | platform |
| `structure-ownership-transfer-handler` | `ownership-transfer-handler` |  | user-data |
| `structure-user-key-change-handler` | `user-key-change-handler` |  | user-data |
| `structure-user-anonymization-handler` | `user-anonymization-handler` |  | user-data |
| `create-structure-allowlist` | `velocity-allowlist` |  | ui-pages |
| `structure-board-allowlist` | `velocity-allowlist` |  | ui-pages |
| `structure-generators-allowlist` | `velocity-allowlist` |  | generators |
| `structure-effectors-allowlist` | `velocity-allowlist` |  | effects |
| `manage-structures-allowlist` | `velocity-allowlist` |  | ui-pages |
| `structure-sync-allowlist` | `velocity-allowlist` |  | sync |
| `structure-admin-allowlist` | `velocity-allowlist` |  | admin-config |
| `structure-welcome-allowlist` | `velocity-allowlist` |  | ui-pages |
| `structure-general-allowlist` | `velocity-allowlist` |  | platform |
| `structure-misc-allowlist` | `velocity-allowlist` |  | platform |
<!-- END generated: modules -->

## 1.3 REST API

<!-- BEGIN generated: rest-conventions -->
#### Authentication and access
- Paths: module `rest-v1` is served under `/rest/structure/1.0`, module `rest-cfd` under `/rest/cfd/1.0` (Jira 9.x).
- Authentication is Jira's usual (session cookie, basic auth, tokens). An endpoint without an anonymous marker requires a logged-in user; anonymous calls get 401 from the platform. Endpoints marked anonymous-allowed carry both platform annotations for anonymous access (classic anonymous access and anonymous site access), so they also answer anonymous callers; what an anonymous caller then sees depends on the plugin's own checks.
- Common access gate (all `rest-v1` and `rest-v2` resources except the gadget resource `/gadget/*`; not applied to `rest-cfd`). Before the method runs: (1) if the query string has `loggedIn=true` and the caller is anonymous, the reply is 401 with no body; (2) if the method or its resource is marked administrator-only, the caller must be a Jira administrator (or system administrator where so marked), else 403 with plain-text body `permission violation`; (3) otherwise the caller must hold the plugin's 'use' application permission (configured by the Jira admin; may be granted to anonymous users), else 403 `permission violation`, unless the method is explicitly exempt.
- Administrator-only endpoints in these modules: `GET /config/license`, `GET /config/licenses`, `PUT /statistics/enableSending`, `PUT /statistics/dismissOffer`. None of them requires websudo; the only websudo-protected resource of the plugin is the dark-features resource of `rest-v2`.
- XSRF: the platform's standard protection applies to mutating methods (POST, PUT, DELETE): requests with form or plain-text content types are rejected unless they carry `X-Atlassian-Token: no-check`; JSON requests pass. No endpoint opts out. Some POSTs take a dummy JSON body only to force a JSON content type.
- No CORS opt-in.

#### Error responses
Errors come in two body formats:
- Plain text (`Content-Type: text/plain`): the message(s), several joined by newlines, or an empty body. Used for most explicit validation failures (400), permission failures (403 `permission violation`), not-found (404), and server errors (500, body = exception message).
- Structured error object, [`structure-error`](#shape-structure-error), as JSON, for errors raised by the plugin's domain layer.

For `rest-v1` (and `rest-v2`) an exception mapper translates uncaught exceptions:
- unparseable request JSON: 400, error object with `error` = `Cannot parse request JSON` plus the parser's message;
- plugin stopped or a background job failure: 503, plain text `service unavailable`;
- an explicit 'error response' raised by the code: exactly that response (status, headers, body);
- invalid input (illegal argument, invalid data): 400, error object with `error` = `Invalid request data` and `message`;
- forest lock timeout: 500, plain text;
- a domain error: error object with `code`, `error` (the error name), `message`, `localizedMessage` and, when known, `structureId`, `viewId`, `rowId`, `itemId`, `itemDescription`; status from the error's category: not found 404, no permission 403, invalid input 400, anything else 500;
- anything else: 500, plain text with the exception message (and an error in the server log).

Note that the plugin reports 'does not exist' and 'not visible to you' with the same 404 so as not to reveal existence.

#### The plugin's own error codes
Besides the public codes of `StructureErrors` (Part 2, `API.md`), the plugin raises its own domain errors with codes 6000–6099. Their `code`, `error` (name) and category are part of the contract: they reach clients in the structure-error object above and Java callers through `StructureException`. The name is the exact wire string.

| code | `error` | category | raised when |
|---|---|---|---|
| 6001 | `JIRA_DATA_ACCESS_EXCEPTION` | `INTERNAL` | reading Jira data failed |
| 6002 | `SEARCH_ERROR` | `INTERNAL` | a Jira search failed |
| 6003 | `INVALID_JQL` | `INVALID_INPUT` | a JQL text does not parse or validate |
| 6004 | `INACCESSIBLE_FILTER` | `NOT_FOUND` | a saved filter does not exist or the user may not see it |
| 6005 | `INVALID_SJQL` | `INVALID_INPUT` | an S-JQL (structure query) text does not parse or validate |
| 6006 | `PERMISSION_RULE_APPLICATION_FORMS_CYCLE` | `INVALID_INPUT` | structure permission rules that apply other structures' rules form a cycle |
| 6007 | `APPLY_RULE_NOT_APPLICABLE` | `INVALID_INPUT` | a permission rule applies a structure whose rules cannot be applied |
| 6008 | `ACTING_USER_NOT_FOUND` | `NO_PERMISSION` | the user a forest source or job should act as no longer exists |
| 6009 | `CAPABILITY_NOT_SUPPORTED_BY_MODULE` | `GENERAL` | an extension module does not support the requested operation |
| 6010 | `GROUP_NOT_EXISTS_OR_INACCESSIBLE` | `NOT_FOUND` | a group named in permission rules does not exist |
| 6011 | `PROJECT_NOT_EXISTS_OR_INACCESSIBLE` | `NOT_FOUND` | a project named in permission rules does not exist |
| 6012 | `PROJECT_ROLE_NOT_EXISTS_OR_INACCESSIBLE` | `NOT_FOUND` | a project role named in permission rules does not exist |
| 6013 | `USER_NOT_EXISTS_OR_INACCESIBLE` | `NOT_FOUND` | a user named in permission rules does not exist (the name is spelled this way, with one S in INACCESIBLE) |
| 6014 | `CONCURRENT_UPDATE_FAILED` | `INTERNAL` | a change could not be saved after repeated concurrent changes |
| 6015 | `INVALID_EXPR` | `INVALID_INPUT` | a formula (expression) does not parse or validate |
| 6016 | `ATTRIBUTE_LOADER_PROBLEM` | `INTERNAL` | an attribute could not be loaded |
| 6017 | `ENTITY_NOT_EXISTS_OR_INACCESSIBLE` | `NOT_FOUND` | an object that is neither a structure, view nor item (for example an effector process) does not exist or the user may not see it |

`rest-cfd` has no such mapper: its failures surface as the platform's generic error reply (normally 500).

#### Caching and other headers
- Responses carry `Cache-Control: no-cache, no-store` unless the endpoint itself set `Cache-Control` or an `ETag` (applies to all gated resources and the gadget resource; `rest-cfd` sets it only on its validate call).
- On Data Center, the polling and attribute-subscription resources of `rest-v2` add a cookie `X-Structure-DC-Meta` = URL-encoded `<node id>|<retry count>` (retry count = live nodes times a multiplier, at least 1), unless switched off by the system property `structure.dcRestInterceptor.disabled`.

#### Rate limiting
Only the structure search endpoints of `rest-v2` are rate limited: one request per user per configured interval (anonymous callers share one bucket); a faster request gets 429 with `Retry-After: <seconds>` and a localized plain-text message. Nothing in `rest-v1` or `rest-cfd` is rate limited.

#### Content types and conventions
- Requests and responses are JSON (`application/json`, UTF-8) unless stated; the gadget resource also accepts form-encoded requests; the S-JQL logs endpoint streams `application/zip`.
- Many replies use the acknowledgement object `{"empty": true}` ([`empty-ok`](#shape-empty-ok)) instead of an empty body.
- Optional values are usually omitted or null when not applicable; clients must treat absent and null alike.
- Ids: structure, view, row, issue and project ids are JSON integers; Jira issue type, status and constant ids are strings. Times are epoch milliseconds unless stated.
- Long-running `rest-v2` requests use the asynchronous job protocol described with [`extensible-async-request`](#shape-extensible-async-request).
<!-- END generated: rest-conventions -->

### 1.3.1 Endpoints

<!-- BEGIN generated: rest-endpoints -->
### Module `rest-v1`

#### `GET /rest/structure/1.0/config/dateFormatStyle`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

Lists the date/time display styles the plugin can use when rendering date values in columns and exports, each with a sample rendering of the current moment in the caller's locale and time zone. Read-only.

**Response.** 200 with [`date-style-list`](#shape-date-style-list).

**Errors.** 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/config/fields/forCreate`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `sample` | query | integer |  | Issue id (numeric) of a sample issue. Optional. If the issue does not exist or the caller cannot browse it, the reply is 200 with a top-level `error` and no fields. |
| `project` | query | integer |  | Project id (numeric). Required together with `issuetype` unless `sample` is given; overrides the sample's project. |
| `issuetype` | query | string |  | Issue type id (string). Required together with `project` unless `sample` is given; overrides the sample's type. |
| `field` | query | array<string> |  | Repeatable; Jira field ids to render (e.g. `assignee`, `customfield_10010`, `status`). Omitted or empty: every field on the create screen except issue links, time logged and attachments. |

Returns the Jira create-screen editor HTML for fields, so the client can show inline issue creation. The prospective issue is defined either by a sample issue (its project, issue type and, for sub-tasks, parent are reused, and copyable field values are pre-filled from it) or by an explicit project and issue type; other fields get Jira's defaults. Project, summary and (unless a sub-task) issue type are never rendered. Special case: when no sample is given and `field` lists exactly `project` and `issuetype`, only the project and issue-type pickers are rendered and the reply lists the projects where the caller may create issues and the plugin is enabled. Nothing is created or changed. A field the caller cannot use is still listed but carries a per-field `error` text instead of HTML (field hidden for this issue, made read-only by a third-party scripting app, or rendering failed); requested field ids that are not on the relevant screen get an entry with only an `error`.

**Response.** 200 with [`issue-field-editors`](#shape-issue-field-editors) where `forCreate` is true and `fields` holds `createHtml` per field id.

**Errors.** 400 (plain text) when neither a sample nor both project and issue type are given, when the project id is rejected by Jira, or when the issue type does not exist. 403 (plain text `permission violation`) when the caller lacks the plugin's 'use' permission.

#### `GET /rest/structure/1.0/config/fields/forGenericItemUpdate`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `type` | query | string |  | Short item type name: `memo` or `planning-task`. Required; any other value gives 400. |
| `id` | query | integer |  | Numeric item id. If omitted, 0 is used (no such item, so the reply carries an `error`). |
| `field` | query | string |  | Id of the plugin-level item field to edit (e.g. a summary/description-like field of the memo). Required. |

Returns the inline-edit HTML for one field of a plugin-native item (only memos and planning tasks support fields). The item is identified by its short type name and numeric id; the item type id is formed by prefixing the plugin key, e.g. `com.almworks.jira.structure:type-memo`. Read-only.

**Response.** 200 with [`item-field-editors`](#shape-item-field-editors). When the item does not exist, the field is unknown or not visible for that item type, or the field is not editable, the reply has a top-level `error` and no `fields`; when rendering fails the single field entry carries an `error`.

**Errors.** 400 (plain text) when `type` or `field` is missing or the type does not support fields. 403 (plain text) when the caller lacks the plugin's 'use' permission.

#### `GET /rest/structure/1.0/config/fields/forMemoUpdate`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `memoId` | query | integer |  | Numeric memo id. Required in practice: when omitted the call fails with a server error (500). |
| `fieldId` | query | string |  | Id of the memo field to edit. Required (400 when missing). |

Shortcut for the generic-item variant with the item type fixed to memo: returns the inline-edit HTML for one field of a memo.

**Response.** 200 with [`item-field-editors`](#shape-item-field-editors), same rules as the generic-item variant.

**Errors.** 400 (plain text) when `fieldId` is missing; 500 when `memoId` is missing; 403 (plain text) without the plugin's 'use' permission.

#### `GET /rest/structure/1.0/config/fields/forUpdate`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `issue` | query | integer |  | Issue id (numeric). Required. Unknown or not browsable by the caller: 200 with a top-level `error`. |
| `field` | query | array<string> |  | Repeatable; Jira field ids to render. Omitted or empty: all edit-screen fields except issue links, time logged and attachments. |

Returns Jira edit-screen editor HTML for fields of an existing issue, current values pre-filled, so the client can edit cells inline. If `status` is among the requested fields, a status editor is rendered that offers the workflow transitions the caller can execute on the issue. Also reports whether the original estimate may be changed (false when time is already logged and Jira's legacy time-tracking mode is on). Read-only. A field the caller cannot use is still listed but carries a per-field `error` text instead of HTML (field hidden for this issue, made read-only by a third-party scripting app, or rendering failed); requested field ids that are not on the relevant screen get an entry with only an `error`.

**Response.** 200 with [`issue-field-editors`](#shape-issue-field-editors) where `fields` holds `editHtml` per field id.

**Errors.** 400 (plain text) when `issue` is missing; 403 (plain text) without the plugin's 'use' permission.

#### `GET /rest/structure/1.0/config/groups`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `assignable` | query | boolean |  | Boolean; default false (see summary). |

Lists Jira user groups by name. With `assignable=true` it returns the groups the caller may use in plugin permission rules: the caller's own groups, or all groups when the caller is a Jira administrator or the instance property `structure.permissions.allowAllUserGroups` is on; anonymous callers get an empty list. Without it, all groups are returned, which requires Jira administrator or the global 'browse users' permission.

**Response.** 200 with [`jira-group-list`](#shape-jira-group-list).

**Errors.** 403 (plain text) when listing all groups without administrator or 'browse users' permission; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/config/license`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

Returns the effective license of the plugin (type, licensee, serial, user limit, expiry dates, source). Jira administrators only.

**Response.** 200 with [`license-info`](#shape-license-info); expiry dates are formatted in the caller's locale.

**Errors.** 403 (plain text `permission violation`) for non-administrators; 401 for anonymous callers with `loggedIn=true`.

#### `GET /rest/structure/1.0/config/licenses`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

Returns the licenses of the plugin and of every installed companion app (extension) that reports license information. Jira administrators only.

**Response.** 200 with a JSON object keyed by app key: `com.almworks.jira.structure` for this plugin, plus each companion app's product key; each value is a [`license-info`](#shape-license-info).

**Errors.** 403 (plain text `permission violation`) for non-administrators.

#### `GET /rest/structure/1.0/config/projects`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `permission` | query | string |  | Jira short permission name; only `browse` (default, browse projects) and `create` (create issues) are accepted. Any other value gives 400. |
| `withRoles` | query | boolean |  | Boolean, default false. When true, every project gets `userRoles` and the reply gets `roles`. Note: `userRoles` is the list of ids of all project roles defined in Jira (the same list for every project, not the caller's actual memberships); it is empty for anonymous callers, and `roles` is then omitted. |

Lists the projects in which the plugin is enabled and on which the caller has the given project permission, sorted by project name. Optionally attaches project-role information.

**Response.** 200 with [`project-list`](#shape-project-list); each project's `iconUrl` is the small avatar URL.

**Errors.** 400 (plain text `invalid permission requested`) for an unsupported permission; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/config/roles`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

Lists all project roles defined in Jira. Logged-in callers only.

**Response.** 200 with [`project-role-list`](#shape-project-role-list).

**Errors.** 403 with no body for anonymous callers; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/config/statuses`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `projects` | query | string |  | Comma-separated project ids, or `*` for all projects that are enabled for the plugin and browsable by the caller (ids outside that set are ignored). Omitted or empty means no projects, so the result is empty. |
| `types` | query | string |  | Comma-separated issue type ids, or `*` for all types of the selected projects. Omitted or empty means no types (empty result). |

Lists the issue statuses used by the workflows that apply to the given projects and issue types, ordered by status category (to do, in progress, done), each with its category color.

**Response.** 200 with [`issue-constant-list`](#shape-issue-constant-list) whose elements are [`issue-status-constant`](#shape-issue-status-constant).

**Errors.** 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/config/timezone`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `name` | query | string |  | Optional time zone id such as `Europe/Berlin`. Unknown ids resolve to `GMT`. |

Returns a time zone id and its current offset. Without `name` it is the caller's Jira time zone (the default user time zone for anonymous callers).

**Response.** 200 with [`time-zone-info`](#shape-time-zone-info).

**Errors.** 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/config/transitions`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `projects` | query | string |  | Comma-separated project ids, or `*` for all projects that are enabled for the plugin and browsable by the caller (ids outside that set are ignored). Omitted or empty means no projects, so the result is empty. |
| `types` | query | string |  | Comma-separated issue type ids or `*`; omitted or empty means no types (empty result). |
| `status` | query | string |  | Status id (string). Required. |

Lists the workflow transitions that lead into the given status in the workflows that apply to the given projects and issue types (transitions whose target is that status; the issue-creation transition is excluded). Each transition names its workflow, action id and source statuses.

**Response.** 200 with [`workflow-transition-list`](#shape-workflow-transition-list).

**Errors.** 400 (plain text) when `status` is missing (`must have status`) or not a known status (`unknown status`); 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/config/types`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `projects` | query | string |  | Comma-separated project ids, or `*` for all projects that are enabled for the plugin and browsable by the caller (ids outside that set are ignored). Omitted or empty means no projects, so the result is empty. |

Lists the issue types available in the given projects (union over their issue type schemes).

**Response.** 200 with [`issue-constant-list`](#shape-issue-constant-list) whose elements are [`issue-type-constant`](#shape-issue-type-constant).

**Errors.** 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/config/ui`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `structure3.navigation.hint` | cookie | string |  | Optional navigation hint cookie set by the client when the user opens an issue from a structure. Format `<structure id>\|<anything>\|<issue key>`; when its issue key equals the current issue and 'keep structure when navigating' is on (default), that structure is shown initially if the caller can view it. |
| `forIssue` | query | integer |  | Issue id (numeric) of the issue page. |
| `forProject` | query | string |  | Project key of the project page. |
| `forAgileBoard` | query | integer |  | Agile board id; marks the request as coming from an agile board (an issue in a project where the plugin is disabled is then tolerated). |
| `preferredStructure` | query | integer |  | Structure id to show initially if the caller can view it. |

Computes the configuration of the structure panel embedded in a Jira issue page, project page or agile board: which structure to show initially, the default structure, the caller's panel preferences and whether the caller may change them. The page type is taken from the most specific context given (agile board, else project, else issue). The initial structure is chosen in this order: the only structure visible to the caller (if exactly one), `preferredStructure`, the structure from the navigation hint cookie, then according to the auto-switch mode (structure containing the issue, default structure, or most recently used). Read-only.

**Response.** 200 with [`panel-configuration`](#shape-panel-configuration).

**Errors.** 400 (plain text) when no context is given. For `forIssue`: the issue's problem mapped to a status (404 not found or not visible, 403 no permission, 400 plugin not enabled for the project unless an agile board is given, 500 otherwise), plain text. 404 (plain text) when `forProject` is unknown or not browsable. 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/1.0/config/ui`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `structure3.navigation.hint` | cookie | string |  | Optional navigation hint cookie set by the client when the user opens an issue from a structure. Format `<structure id>\|<anything>\|<issue key>`; when its issue key equals the current issue and 'keep structure when navigating' is on (default), that structure is shown initially if the caller can view it. |
| (body) | body | [`panel-preferences-update`](#shape-panel-preferences-update) |  | [`panel-preferences-update`](#shape-panel-preferences-update): the context (`forIssue`/`forProject`/`forAgileBoard`, at least one) plus any of the preference keys. |

Saves the caller's structure-panel preferences (auto-switch mode, auto-collapse, keep structure when navigating) for the project of the given context, then returns the recomputed panel configuration like the GET variant. The auto-switch mode is stored for the issue page when `forIssue` is given, otherwise for the project page. Only keys present in the body are changed; with none present nothing is written. Logged-in callers only.

**Request.** Exactly what the structure panel should show on a Jira page; at least one of `forIssue`, `forProject`, `forAgileBoard` must be given (a positive id or non-empty key). `autoSwitch` must be `off`, `withIssue` or `default`.

**Response.** 200 with [`panel-configuration`](#shape-panel-configuration) (computed without a preferred structure).

**Errors.** 403 (plain text `permission violation`) for anonymous callers; 400 (plain text) for a missing body, missing context or unknown `autoSwitch` value; issue/project errors as in the GET variant.

#### `GET /rest/structure/1.0/config/userPickerPermission`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

Tells whether the caller has Jira's global 'browse users' (user picker) permission.

**Response.** 200 with a bare JSON boolean (`true` or `false`).

**Errors.** 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/config/widget`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

Returns the bootstrap configuration of the structure grid client for the caller: plugin and Jira versions, cluster node, available Jira fields, the caller's capabilities (create issues, bulk change, create/share views, create perspectives, manage global saved columns, admin, anonymous), installed companion-app settings, export menu links, third-party item types, polling back-off, help visibility and a global error notice (shown when Jira's index consistency check failed). Read-only.

**Response.** 200 with [`grid-bootstrap`](#shape-grid-bootstrap).

**Errors.** 403 (plain text `permission violation`) without the plugin's 'use' permission; 500 (plain text) when Jira cannot list the caller's navigable fields.

#### `GET /rest/structure/1.0/config/widget/issueLinkAction`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

Returns what happens when the caller clicks an issue link in a structure grid: the caller's own preference if set, else the instance default (system property `structure.board.issueLinkAction`), else show details.

**Response.** 200 with [`issue-link-click-action`](#shape-issue-link-click-action); `type` is `showDetails`, `openIssuePage` or `doNothing`.

**Errors.** 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/1.0/config/widget/issueLinkAction`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`issue-link-click-action`](#shape-issue-link-click-action) |  | [`issue-link-click-action`](#shape-issue-link-click-action) with `type` one of `showDetails`, `openIssuePage`, `doNothing`. |

Stores the caller's preferred issue-link click action in the caller's Jira user preferences.

**Response.** 200 with [`empty-ok`](#shape-empty-ok).

**Errors.** 400 (plain text) for anonymous callers; 400 with [`structure-error`](#shape-structure-error) for an unknown `type`; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/gadget/meta`

Access: anonymous users allowed. Consumes: `application/json`, `application/x-www-form-urlencoded`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `structureId` | query | integer |  | Structure id; ignored when absent or not positive. Not viewable or missing: a general error `s.g.no-such-structure` is added. |
| `viewId` | query | integer |  | View id for the normal gadget mode; silently omitted from the reply if missing or not viewable. |
| `canvasViewId` | query | integer |  | View id for the maximized (canvas) gadget mode; same rules as `viewId`. |
| `filterId` | query | integer |  | Jira saved filter id; when not accessible, Jira's error messages are added as general errors. |

Returns what the structure dashboard gadget needs to render: the current user, the configured structure, view, canvas-mode view and saved filter (each only if the caller can see it), the Jira issue operations available as links, and any problems found. This resource is not behind the plugin's common access gate; it checks the 'use' permission itself.

**Response.** 200 with [`structure-gadget-meta`](#shape-structure-gadget-meta). When the caller lacks the 'use' permission, `errors` holds the general error key `s.g.structure-unavailable` and structure, views and filter are omitted.

**Errors.** No error statuses of its own; problems are reported inside `errors`.

#### `GET /rest/structure/1.0/gadget/structures`

Access: anonymous users allowed. Consumes: `application/json`, `application/x-www-form-urlencoded`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Optional name search text. |

Structure picker for the gadget configuration form. With a non-blank `query`, searches all structures the caller can view by name (matched text highlighted in the HTML label), returning at most 8 items plus a 'N more' footer when there are more than 9 matches. Without a query, suggests up to 8 structures: the caller's recent structures and favorites, balanced 4/4 when both lists are long. This resource is not behind the plugin's common access gate; it checks the 'use' permission itself.

**Response.** 200 with [`picker-search-result`](#shape-picker-search-result) (one group per category; each item's `entity` is a [`structure-summary`](#shape-structure-summary)). When the caller lacks the 'use' permission: 200 with [`validation-errors`](#shape-validation-errors) holding the key `s.g.structure-unavailable`.

**Errors.** None of its own.

#### `GET /rest/structure/1.0/gadget/validate`

Access: anonymous users allowed. Consumes: `application/json`, `application/x-www-form-urlencoded`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `structureId` | query | string |  | Structure id (as text). Required. |
| `viewId` | query | string |  | View id (as text). Required. |
| `canvas-viewId` | query | string |  | View id for canvas mode; checked only when `useCanvasSettings` is true. |
| `filterType` | query | string |  | Required: `none`, `text`, `jql`, `sjql` or `saved`. |
| `filterQuery` | query | string |  | URL-encoded query text; required for `text`, `jql` (validated as JQL for the caller) and `sjql` (parsed and validated as a structure query). |
| `filterId` | query | string |  | For `saved`: `filter-<numeric id>` of a Jira saved filter the caller can access. |
| `numRows` | query | string |  | Number of rows to show, 2 to 50. Required. |
| `canvas-numRows` | query | string |  | Rows in canvas mode, 2 to 50; checked only when `useCanvasSettings` is true. |
| `useCanvasSettings` | query | boolean |  | Boolean, default false: whether separate canvas-mode settings are in use. |

Validates the gadget configuration form. Checks the structure (present and viewable), the view (and the canvas-mode view when canvas settings are used), the filter settings and the row counts (whole numbers 2 to 50). This resource is not behind the plugin's common access gate; it checks the 'use' permission itself.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) when everything is valid.

**Errors.** 400 with [`validation-errors`](#shape-validation-errors) listing field errors (keyed by the parameter names above). Error texts are message keys (e.g. `s.g.config.err.no.structureId`, `s.g.config.err.bad.numRows` with the bounds as params), except JQL/S-JQL problems which are already-localized messages. Missing 'use' permission is reported as a `structureId` field error.

#### `GET /rest/structure/1.0/gadget/views`

Access: anonymous users allowed. Consumes: `application/json`, `application/x-www-form-urlencoded`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `structureId` | query | string |  | Structure id (text) whose view menu to suggest from; ignored if not viewable. |
| `query` | query | string |  | Optional name search text. |

View picker for the gadget configuration form. With a non-empty `query`, searches all views the caller can view by name (at most 8 items plus a 'N more' footer above 9 matches). Otherwise suggests up to 8 views from the menu configured for the given structure (or the global default menu) on the gadget page. This resource is not behind the plugin's common access gate; it checks the 'use' permission itself.

**Response.** 200 with [`picker-search-result`](#shape-picker-search-result) (each item's `entity` is a [`grid-view`](#shape-grid-view)). Without the 'use' permission: 200 with [`validation-errors`](#shape-validation-errors) holding `s.g.structure-unavailable`.

**Errors.** None of its own.

#### `GET /rest/structure/1.0/gadget/widgetConfigs`

Access: anonymous users allowed. Consumes: `application/json`, `application/x-www-form-urlencoded`. Produces: `application/json`.

Returns client tuning for the gadget grid in local (same Jira) and remote (gadget shown in another application) modes: poll interval, minimum cached rows and preload factor, plus node-wandering and retry back-off settings for Data Center. Defaults: local 15000 ms / 20 rows / 2.0; remote 15000 ms / 100 rows / 5.0 on Server and 30000 ms / 500 rows / 10.0 on Data Center; each overridable by system properties `structure.gadget.<local|remote>.<pollInterval|minCachedRows|preloadRowsFactor>`. No permission check.

**Response.** 200 with [`gadget-grid-tuning`](#shape-gadget-grid-tuning); `remote` is a [`gadget-remote-grid-tuning`](#shape-gadget-remote-grid-tuning).

**Errors.** None.

#### `POST /rest/structure/1.0/perspective/share`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`shared-perspective`](#shape-shared-perspective) |  | [`shared-perspective`](#shape-shared-perspective) without `id`; `spec` is any JSON value (normally an object) describing the page state. |

Stores a perspective (a snapshot of the structure page state: structure, view, filters, expansion and so on, as opaque JSON) and returns it with a new id, so it can be shared as a link. The id is a random positive 31-bit integer. Requires a logged-in caller who has the 'use' permission while the plugin is licensed. Stored perspectives are deleted automatically after a period without access.

**Response.** 200 with [`shared-perspective`](#shape-shared-perspective) holding the new `id` and the stored `spec` echoed as raw JSON.

**Errors.** 400 (plain text) for a missing body, a body with an `id`, or an empty `spec`; 403 with [`structure-error`](#shape-structure-error) when the caller may not create perspectives (anonymous, unlicensed plugin); 401 for anonymous callers (platform default).

#### `POST /rest/structure/1.0/perspective/shareByEmail`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`perspective-email-request`](#shape-perspective-email-request) |  | [`perspective-email-request`](#shape-perspective-email-request). |

E-mails a link to a stored perspective to Jira users, with an optional personal message (default text when empty). Side effect: if the perspective shows a structure, the caller is an administrator of that structure and has the 'browse users' permission, each recipient who cannot view that structure is granted view access by a new user rule prepended to the structure's permissions. Also counts the share in usage statistics.

**Request.** `perspectiveId` and a non-empty `recipients` list of Jira user keys are required; every key must resolve to an existing user.

**Response.** 200 with [`empty-ok`](#shape-empty-ok).

**Errors.** 400 (plain text) when `perspectiveId` or recipients are missing, an unknown user key is given (message names the key), or Jira outgoing mail is not configured. 404 with [`structure-error`](#shape-structure-error) when the perspective does not exist; 404/403 with [`structure-error`](#shape-structure-error) when the perspective's structure is not viewable by the caller. 401 for anonymous callers.

#### `GET /rest/structure/1.0/perspective/{id}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Perspective id (positive integer). |

Returns the stored page-state JSON of a perspective. Any caller with the 'use' permission (anonymous included when granted it) can read any perspective by id; there is no owner check. Reading refreshes the perspective's last-used time (protecting it from cleanup) and counts an access and an active user in usage statistics. Saved-column references inside the stored view specifications are refreshed to current definitions before returning.

**Response.** 200 with the perspective's `spec` JSON value itself (not wrapped in an object).

**Errors.** 400 (plain text) for an id below 1; 404 (plain text) when no perspective has that id; 403 (plain text) without the 'use' permission.

#### `GET /rest/structure/1.0/sjqlTroubleshooting/check`

Access: logged-in user. Consumes: any. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `structure` | query | string |  | Structure id or exact structure name (as in the `structure()` JQL function's first argument). Empty means the default structure. A name matching several viewable structures is an error. |
| `query` | query | string |  | Structure query (S-JQL) text, as the function's second argument; empty means a query matching every row. |

Validates the two arguments of the plugin's `structure()` JQL function for the caller without running it: the structure must exist and be viewable, its automation must not be stopped, and the structure query must parse and validate. Logged-in callers only.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) when valid.

**Errors.** 400 with a JSON array of message strings (all errors sorted alphabetically, then all warnings sorted). 401 for anonymous callers; 403 (plain text) without the 'use' permission.

#### `GET /rest/structure/1.0/sjqlTroubleshooting/logs`

Access: logged-in user. Consumes: any. Produces: `application/zip`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `structure` | query | string |  | Structure id or exact structure name (as in the `structure()` JQL function's first argument). Empty means the default structure. A name matching several viewable structures is an error. |
| `query` | query | string |  | Structure query (S-JQL) text, as the function's second argument; empty means a query matching every row. |
| `includeRelOutput` | query | boolean |  | Boolean, default false: also capture the step-by-step relation evaluation output (very verbose). |
| `messagePattern` | query | string |  | Optional log line layout pattern (log4j pattern syntax) for the captured lines; default layout when omitted. |

Runs the `structure()` JQL function arguments with maximum logging and streams the captured trace log as a ZIP download (`Content-Disposition: attachment; filename="S-JQL_Troubleshooting.zip"`) containing one entry `S-JQL_Troubleshooting.log`. While it runs, trace logging of the plugin's query subsystem is captured into the archive; if the arguments are invalid nothing is executed and the log entry stays empty (the messages go to the server log instead). Logged-in callers only; no administrator check. Writes start/finish warnings to the server log.

**Response.** 200 `application/zip` streamed body, never cached.

**Errors.** 401 for anonymous callers; 403 (plain text) without the 'use' permission. Argument errors do not change the status.

#### `PUT /rest/structure/1.0/statistics/dismissOffer`

Access: anonymous users allowed. Consumes: `application/json`. Produces: any.

Records that the calling administrator declined the offer to send anonymous usage statistics to the vendor, so the offer is no longer shown to them. Jira administrators only.

**Response.** 200 with [`empty-ok`](#shape-empty-ok).

**Errors.** 403 (plain text `permission violation`) for non-administrators.

#### `PUT /rest/structure/1.0/statistics/enableSending`

Access: anonymous users allowed. Consumes: `application/json`. Produces: any.

Records the administrator's consent to send usage statistics (the original then sends them, with the Jira server id, to its vendor every day). The replacement stores the setting and never uploads anything (section 1.8). Jira administrators only.

**Response.** 200 with [`empty-ok`](#shape-empty-ok).

**Errors.** 403 (plain text `permission violation`) for non-administrators.

#### `POST /rest/structure/1.0/statistics/record`

Access: anonymous users allowed. Consumes: `application/json`. Produces: any.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`usage-counters`](#shape-usage-counters) |  | [`usage-counters`](#shape-usage-counters). |

Adds client-side usage counters to the plugin's local usage statistics for the given time: each entry of `stats` is added as a total count, the caller is counted as a unique user, and also as an active user if any key is one of the interactive actions (e.g. `expandAll`, `view.switch`, `layout.switch`, `search.toggle`). Any counter name is accepted. Silently does nothing for anonymous callers or when `stats` is empty or `timestamp` is missing.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) in all accepted cases.

**Errors.** 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/view`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `ids` | query | string |  | Comma-separated view ids; non-numeric or non-positive entries are skipped; ids the caller cannot access are silently left out. |
| `name` | query | string |  | Name search text (word-prefix match, same rules as the pickers); ignored if it contains nothing searchable. |
| `permission` | query | string |  | Minimum permission level the caller must have on each view, case-insensitive: `none`, `view`, `edit`, `automate`, `admin` (`edit_generators` is a deprecated alias). Levels at or below `view` mean `view`. Default `view`. |
| `withPermissions` | query | boolean |  | Boolean, default false: include each view's permission rules (only for views the caller administers). |
| `withOwner` | query | boolean |  | Boolean, default false: include the owner as a user object when the caller is the owner, a Jira administrator or has 'browse users'; otherwise only `hasOwner` is set. |

Searches views (saved grid column layouts) the caller can access at the requested level, optionally restricted to given ids and/or a name pattern.

**Response.** 200 with [`grid-view-list`](#shape-grid-view-list) (`preferred` absent).

**Errors.** 400 (plain text) when `ids` is given but yields no valid id; 400 with [`structure-error`](#shape-structure-error) (`error` = `Invalid request data`, `message` listing known levels) for an unknown permission level; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/1.0/view`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`grid-view`](#shape-grid-view) |  | [`grid-view`](#shape-grid-view) without `id`; `name` required (non-blank after trimming); `description`, `spec`, `permissions` optional. |

Creates a new view. The caller must be allowed to create views (plugin setting) and, to give it sharing rules, to share views. The caller becomes the owner. Returns the created view with permissions and owner included.

**Response.** 200 with [`grid-view`](#shape-grid-view).

**Errors.** 400 (plain text) for a missing body, a body with an `id`, or a blank name; 400 with [`structure-error`](#shape-structure-error) for invalid columns or permission rules; 403 with [`structure-error`](#shape-structure-error) when the caller may not create or share views or the plugin license does not allow changes; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/view/default`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `forStructure` | query | integer |  | Structure id. Omitted: use the global default view settings. Not viewable: no default. |
| `forPage` | query | string |  | Page id: `structure`, `structure-with-details`, `issue`, `project`, `component`, `version`, `navigator`, `gadget`, `greenhopper` (agile board). Omitted: no page restriction. |

Returns the view that is preferred (default) for a structure on a page, taken from the structure's view menu, or the global default menu when the structure has none.

**Response.** 200 with [`grid-view`](#shape-grid-view) (no permissions/owner) or [`empty-ok`](#shape-empty-ok) when there is no preferred view.

**Errors.** 400 with the JSON string `unknown page` for an unknown `forPage`; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/view/menu`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `forStructure` | query | integer |  | Structure id; omitted uses the global default menu; a structure the caller cannot view gives an empty menu. |
| `forPage` | query | string |  | Page id as for the default view; omitted means the menu for no specific page. |

Returns the views shown in the view menu of a structure on a page (structure's own menu, or the global default menu when the structure has none), keeping only views the caller can view. The preferred view, if any, comes first.

**Response.** 200 with [`grid-view-list`](#shape-grid-view-list) where `preferred` lists the ids of views that are the default on that page.

**Errors.** 400 with the JSON string `unknown page` for an unknown page id; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/view/{id}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | View id. |
| `withPermissions` | query | boolean |  | Boolean, default false: include each view's permission rules (only for views the caller administers). |
| `withOwner` | query | boolean |  | Boolean, default false: include the owner as a user object when the caller is the owner, a Jira administrator or has 'browse users'; otherwise only `hasOwner` is set. |

Returns one view the caller can view.

**Response.** 200 with [`grid-view`](#shape-grid-view).

**Errors.** 404 with [`structure-error`](#shape-structure-error) when the view does not exist or is not viewable by the caller; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `DELETE /rest/structure/1.0/view/{id}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | View id (positive). |

Deletes a view and its associations with structures. Requires administer permission on the view.

**Response.** 200 with [`empty-ok`](#shape-empty-ok).

**Errors.** 400 (no body) for a non-positive id; 404 with [`structure-error`](#shape-structure-error) (no message) when the view does not exist or is not viewable; 403 with [`structure-error`](#shape-structure-error) when viewable but not administrable or the license does not allow changes; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/1.0/view/{id}/associations`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | View id. |

Lists the structures whose view menu includes this view (only structures the caller can view) and whether the view is in the global default view menu.

**Response.** 200 with [`view-usage`](#shape-view-usage).

**Errors.** 403 (no body) when the view does not exist or is not viewable; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/1.0/view/{id}/makeDefault`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | View id. |
| (body) | body | [`make-default-view-request`](#shape-make-default-view-request) |  | [`make-default-view-request`](#shape-make-default-view-request); required (a missing body fails with 500). |

Makes the view the default (preferred) view of a structure on a page. Requires administer permission on the structure and view permission on the view. If the structure has no own view settings, the global defaults are copied into its settings first. The view is added to the menu (first position) if not already present; any other view's default flag for that page is removed. No-op if it is already the default.

**Response.** 200 with [`grid-view`](#shape-grid-view) (no permissions/owner).

**Errors.** 400 with the JSON string `unknown page` for an unknown `pageId`; 403/404 with [`structure-error`](#shape-structure-error) when the structure is not administrable or the view not viewable; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/1.0/view/{id}/makePublic`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | View id. |
| (body) | body | map<string, any> |  | Any JSON object (content ignored). Its only purpose is to force a JSON request body, which protects the call against cross-site form posts. |

Makes the view visible to everyone by adding an 'anyone can view' rule to its permissions, if it is not public already. Requires administer permission on the view.

**Response.** 200 with [`grid-view`](#shape-grid-view) including permissions and owner.

**Errors.** 403/404 with [`structure-error`](#shape-structure-error) when the view is not administrable or does not exist; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/1.0/view/{id}/update`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | View id. |
| (body) | body | [`grid-view`](#shape-grid-view) |  | [`grid-view`](#shape-grid-view); `id`, if given, must equal the path id. |

Updates a view's name, description, owner, permissions and/or specification. Requires administer permission on the view. Only keys present (non-null) in the body are changed. An owner given by user name alone must resolve to an existing user.

**Response.** 200 with [`grid-view`](#shape-grid-view) including permissions and owner.

**Errors.** 400 (plain text) for a missing body, a mismatching `id`, or an unknown owner name; 400 with [`structure-error`](#shape-structure-error) for invalid columns/rules; 403/404 with [`structure-error`](#shape-structure-error) when the view is not administrable or does not exist; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/1.0/view/{id}/updateSpec`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | View id. |
| (body) | body | [`view-layout`](#shape-view-layout) |  | [`view-layout`](#shape-view-layout). |

Replaces only the view's specification (columns, display modes, pins). Requires edit permission on the view (not administer).

**Response.** 200 with [`grid-view`](#shape-grid-view) including permissions and owner.

**Errors.** 400 (plain text) for a missing body; 400 with [`structure-error`](#shape-structure-error) for invalid columns; 403/404 with [`structure-error`](#shape-structure-error) when the view is not editable or does not exist; 403 (plain text) when the caller lacks the plugin's 'use' permission (enforced by the common access gate, see conventions); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

### Module `rest-v2`

#### `GET /rest/structure/2.0/attribute-sensitivity`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

Returns the instance-wide attribute sensitivity settings: the mode and the attributes explicitly declared non-sensitive (sorted by attribute id). Sensitive attributes do not reveal, in totals and other values computed over several items, data from items the viewer cannot see. Jira administrators only.

**Response.** 200 with a [`attribute-sensitivity-settings`](#shape-attribute-sensitivity-settings).

**Errors.** 401 for anonymous callers; 403 text/plain `permission violation` when the caller is not a Jira administrator.

#### `PUT /rest/structure/2.0/attribute-sensitivity`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`attribute-sensitivity-settings`](#shape-attribute-sensitivity-settings) |  | [`attribute-sensitivity-settings`](#shape-attribute-sensitivity-settings): `sensitivityMode` code is required; an empty or missing list clears the non-sensitive attributes. |

Replaces the attribute sensitivity settings (mode and the list of non-sensitive attributes). Takes effect for subsequent value calculations. Jira administrators only.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) (`{}`).

**Errors.** 400 with no body when the body is missing; 400 text/plain when the mode code is not 0, 1 or 2 or an attribute spec has an unknown format (message names the problem); 401 anonymous; 403 `permission violation` for non-administrators.

#### `POST /rest/structure/2.0/attribute-sensitivity/validate`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | string |  | The JSON text of one [`attribute-spec`](#shape-attribute-spec) (`id`, `format`, optional `params`). |

Checks whether a single attribute spec is acceptable for the sensitivity settings, without storing anything. Jira administrators only.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) (`{}`) when the spec parses and its `format` is a known value format.

**Errors.** 400 text/plain when the body is empty (`attribute spec is empty`-style message) or the spec cannot be parsed / has an unknown format (message gives the reason); 401 anonymous; 403 `permission violation` for non-administrators.

#### `POST /rest/structure/2.0/attribute/subscription`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `valuesUpdate` | query | boolean |  | When `true`, the reply includes `valuesUpdate` with attribute values; otherwise only the subscription id and window are returned. |
| `valuesTimeout` | query | integer |  | Milliseconds to wait for value loading before answering (only with `valuesUpdate=true`). Default 1000 (configurable), clamped to 0..60000. Values not loaded in time are reported later with `stillLoading`. |
| (body) | body | [`attribute-subscription-window`](#shape-attribute-subscription-window) |  | [`attribute-subscription-window`](#shape-attribute-subscription-window): `forestSpec`, `rows` and `attributes` are all required for a new subscription. |

Creates an attribute-value subscription owned by the caller for a window (a forest, a set of its rows and a set of attributes) and optionally loads values right away. Subscriptions live in server memory on the node that created them, are private to their creator, expire after a period without use and are capped in number (10000 by default; oldest unused are dropped). Anonymous callers may subscribe. When clustered, the response sets a cookie `X-Structure-DC-Meta` = percent-encoded `<node id>|<retry count>` so the client can stick to the node.

**Response.** 200 with a [`attribute-subscription`](#shape-attribute-subscription): the new subscription id, the window as stored, and, with `valuesUpdate=true`, a full values update.

**Errors.** 400 when the forest spec is missing or invalid; attribute specs with unknown formats are silently dropped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/attribute/subscription/{id}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Subscription id returned at creation. |
| `valuesUpdate` | query | boolean |  | When `true`, the reply includes `valuesUpdate` with attribute values; otherwise only the subscription id and window are returned. |
| `valuesTimeout` | query | integer |  | Milliseconds to wait for value loading before answering (only with `valuesUpdate=true`). Default 1000 (configurable), clamped to 0..60000. Values not loaded in time are reported later with `stillLoading`. |
| `signature` | query | integer |  | Signature of the last values version the client holds (from `valuesUpdate.version`). Used with `version`; if either is missing the update is full (from version zero). |
| `version` | query | integer |  | Version number the client holds, paired with `signature`; the update then only carries values that changed since that version. |
| `skipLoading` | query | boolean |  | When `true`, does not start or wait for value loading; reports only what is already loaded. |

Returns the subscription's current window and, with `valuesUpdate=true`, the values that changed since the client's version. Also reports rows the caller cannot see and attribute loading errors collected since the last call.

**Response.** 200 with a [`attribute-subscription`](#shape-attribute-subscription).

**Errors.** 404 with a [`structure-error`](#shape-structure-error) (code 4800) when the subscription does not exist, has expired, or belongs to another user. 400 when the window's forest spec is invalid. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `PUT /rest/structure/2.0/attribute/subscription/{id}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Subscription id. |
| `valuesUpdate` | query | boolean |  | When `true`, the reply includes `valuesUpdate` with attribute values; otherwise only the subscription id and window are returned. |
| `valuesTimeout` | query | integer |  | Milliseconds to wait for value loading before answering (only with `valuesUpdate=true`). Default 1000 (configurable), clamped to 0..60000. Values not loaded in time are reported later with `stillLoading`. |
| `signature` | query | integer |  | Signature of the last values version the client holds (from `valuesUpdate.version`). Used with `version`; if either is missing the update is full (from version zero). |
| `version` | query | integer |  | Version number the client holds, paired with `signature`; the update then only carries values that changed since that version. |
| (body) | body | [`attribute-subscription-window`](#shape-attribute-subscription-window) |  | [`attribute-subscription-window`](#shape-attribute-subscription-window) with all three parts. |

Replaces the whole window of an existing subscription (forest, rows and attributes) and optionally returns values for the new window.

**Response.** 200 with a [`attribute-subscription`](#shape-attribute-subscription).

**Errors.** 404 with a [`structure-error`](#shape-structure-error) (code 4800) when the subscription does not exist, has expired, or belongs to another user. 400 when the window's forest spec is invalid. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `DELETE /rest/structure/2.0/attribute/subscription/{id}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Subscription id. |

Drops a subscription of the caller and stops its value loading.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) (`{}`).

**Errors.** 404 with a [`structure-error`](#shape-structure-error) (code 4800) when the subscription does not exist, has expired, or belongs to another user. 400 when the window's forest spec is invalid. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/attribute/subscription/{id}/patch`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Subscription id. |
| `valuesUpdate` | query | boolean |  | When `true`, the reply includes `valuesUpdate` with attribute values; otherwise only the subscription id and window are returned. |
| `valuesTimeout` | query | integer |  | Milliseconds to wait for value loading before answering (only with `valuesUpdate=true`). Default 1000 (configurable), clamped to 0..60000. Values not loaded in time are reported later with `stillLoading`. |
| `signature` | query | integer |  | Signature of the last values version the client holds (from `valuesUpdate.version`). Used with `version`; if either is missing the update is full (from version zero). |
| `version` | query | integer |  | Version number the client holds, paired with `signature`; the update then only carries values that changed since that version. |
| (body) | body | [`attribute-subscription-window`](#shape-attribute-subscription-window) |  | [`attribute-subscription-window`](#shape-attribute-subscription-window); any of its keys may be omitted. |

Changes only the parts of a subscription's window that are present in the body (a missing `forestSpec`, `rows` or `attributes` keeps the current one) and optionally returns values.

**Response.** 200 with a [`attribute-subscription`](#shape-attribute-subscription).

**Errors.** 404 with a [`structure-error`](#shape-structure-error) (code 4800) when the subscription does not exist, has expired, or belongs to another user. 400 when the window's forest spec is invalid. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/author-picker`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Text to match, case-insensitive, as a literal substring (no wildcards). Users match on username, display name or email; groups and roles on name. Empty or omitted: no filtering. |
| `noRoles` | query | boolean |  | true to leave out the project-role group. Default false. |
| `noUsers` | query | boolean |  | true to leave out the user group. Default false. |
| `limit` | query | integer |  | Maximum items per group. Missing, zero or negative means 10. |

Search box backend for picking 'authors' (users, groups and project roles), used by worklog-style column settings. Returns up to three result groups in this order: users, groups, project roles. Users come from Jira's user search (inactive users included, email may match); groups are the groups the caller may see (all groups for Jira admins or when the instance-wide setting that exposes all groups is on, otherwise the caller's own groups; for anonymous callers all groups only if anonymous holds the Browse Users global permission, else none); roles are all project roles and are omitted for anonymous callers. Read-only.

**Response.** 200 with a [`picker-search-result`](#shape-picker-search-result) (`query` is not set). Each non-empty group is included with a localized label ('Users', 'Groups', 'Project roles'). Item `value` (and `id`) is `author:<user key>`, `group:<group name>` or `role:<numeric role id>`; `label` is the display name (user) or name (group, role); `html` is the user label 'Display Name (username)' (with ' - email' after the display name when the caller may see emails) or the group/role name, HTML-escaped, with the matched part wrapped in a span of class s-match, all inside an outer span. Groups and roles are sorted by name; users keep the order of Jira's search. A group's `footer` is a localized 'there are more results, refine your search' text when items were cut by the limit, otherwise null.

**Errors.** 403 when the caller may not use the app. Never fails on bad query text (returns an empty result).

#### `GET /rest/structure/2.0/author-picker/project-role/{key}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `key` | path | string |  | Project role id (decimal) or project role name. |

Looks up one Jira project role, by numeric id or (if the key is not a number) by exact name. Read-only.

**Response.** 200 with a [`project-role-ref`](#shape-project-role-ref).

**Errors.** 400 with a [`structure-error`](#shape-structure-error) body when no role has that id or name. 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/author-picker/users`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `keys` | query | string |  | Comma-separated user keys. Blank entries are skipped. Empty or omitted: empty result. |

Resolves a list of user keys into display data for showing already-selected users. Requires the Jira global Browse Users permission. Unknown keys are not an error: they are echoed back as their own name.

**Response.** 200 with a JSON array, one object per non-blank key in input order, with string keys `key` (the key as given), `name` (username, or the key if no such user), `displayName` (display name; for an inactive user the localized 'Name (Inactive)' form; the key if no such user) and `avatarUrl` (absolute URL `<base url>/secure/useravatar?ownerId=<key>&ts=<current time in ms>` for a known user, Jira's anonymous avatar URL for an unknown key).

**Errors.** 403 with no body when the caller lacks Browse Users; 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/automation`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

Lists the automation modules the grid can offer: every available generator (inserters, groupers, extenders, sorters, filters) with its presets, every available effector, and whether the caller holds the Structure app permissions to configure generators and effectors.

**Response.** 200 with a [`automation-catalog`](#shape-automation-catalog). Modules whose plugin is unavailable are left out.

**Errors.** 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/calendar/list`

Access: logged-in user. Consumes: any. Produces: `application/json`.

Lists the work calendars available for scheduling-related features, from every installed calendar provider. Calendars of the built-in provider come first, then other providers ordered by provider key. Read-only; requires a logged-in user.

**Response.** 200 with a [`work-calendar-list`](#shape-work-calendar-list). The built-in provider offers two calendars: id `com.almworks.jira.structure:simple-calendar-provider/0` (all time is working time, the default) and `.../1` (09:00 to 17:00 Monday to Friday in Jira's default time zone), with localized names and descriptions.

**Errors.** 401 when not logged in; 403 when the caller may not use the app.

#### `POST /rest/structure/2.0/cloudmigration/stats/{id}`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Structure id (positive integer). |
| (body) | body | [`async-job-ticket`](#shape-async-job-ticket) |  | A [`async-job-ticket`](#shape-async-job-ticket): send `{}` (or `jobId` null) to start a new computation; send the `jobId` returned earlier to keep waiting for that job. |

Computes statistics about one structure for the cloud migration assistant: how many rows of each kind its current forest has and which projects its issues belong to. Jira system administrators only. Runs as a background job: the call waits up to the async timeout (default 3 seconds, configurable by an instance property) and, if the job has not finished, returns the job id so the caller can poll by repeating the call with that id. Read-only; does not contact any external server.

**Response.** 200 with a [`structure-migration-stats`](#shape-structure-migration-stats) when the job finished within the wait; the job is then discarded. 200 with a [`async-job-ticket`](#shape-async-job-ticket) (only `jobId` set) when still running.

**Errors.** 400 with no body when `id` is missing, zero or negative. 403 when the caller is not a system administrator. 404 with a [`structure-error`](#shape-structure-error) when the given `jobId` is unknown (or already collected); errors raised by the computation (e.g. structure not found) are reported in the same error form with their usual status. 503 when the app is stopping.

#### `GET /rest/structure/2.0/configuration/permissions`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

Returns the app-level permission settings (who may use the app, create structures, and so on). Jira administrators only. Read-only.

**Response.** Body: map<string, [`app-permission-setting`](#shape-app-permission-setting)>. 200 with a JSON object whose keys are the nine app permission keys, always all present, in this order: `use`, `createStructure`, `synchronization`, `automation`, `configureGenerators`, `configureEffectors`, `executeEffectors`, `executeEffectorsOnQueries`, `manageGlobalSavedColumns`; each value is a [`app-permission-setting`](#shape-app-permission-setting) with both fields filled.

**Errors.** 401 when not logged in; 403 when the caller is not a Jira administrator.

#### `PUT /rest/structure/2.0/configuration/permissions`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | map<string, [`app-permission-setting`](#shape-app-permission-setting)> |  | JSON object mapping app permission key to a [`app-permission-setting`](#shape-app-permission-setting). Keys not mentioned are left unchanged. |

Changes several app permissions at once. Jira administrators only. Every entry is validated first; only if all are valid are the changes applied, so a bad entry changes nothing. For each entry, `allowedForAnyone` (if given) sets the 'anyone' flag and `subjects` (if given) replaces the whole subject list.

**Request.** At least one entry. Each entry must have at least one of `allowedForAnyone` and `subjects`. In `subjects` only `group` subjects (group must exist) and `projectRole` subjects (role must exist; `projectId` must be 0 or an existing project) are accepted.

**Response.** 200 with a [`empty-ok`](#shape-empty-ok).

**Errors.** 400 text/plain when the body is missing or empty, a key is not a known permission key (message lists the valid keys), an entry sets neither field, a subject is null, malformed, of type `user` or `anyone`, or refers to a group, role or project that does not exist. 401/403 as for the GET.

#### `GET /rest/structure/2.0/configuration/permissions/{key}`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `key` | path | string |  | App permission key, one of `use`, `createStructure`, `synchronization`, `automation`, `configureGenerators`, `configureEffectors`, `executeEffectors`, `executeEffectorsOnQueries`, `manageGlobalSavedColumns` (case-sensitive). |

Returns one app permission setting. Jira administrators only. Read-only.

**Response.** 200 with a [`app-permission-setting`](#shape-app-permission-setting).

**Errors.** 400 text/plain when the key is unknown (message lists the valid keys). 401 when not logged in; 403 when not a Jira administrator.

#### `PUT /rest/structure/2.0/configuration/permissions/{key}`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `key` | path | string |  | App permission key (see GET). |
| (body) | body | [`app-permission-setting`](#shape-app-permission-setting) |  | A [`app-permission-setting`](#shape-app-permission-setting); at least one field must be set. Subjects are restricted as in PUT /configuration/permissions. |

Changes one app permission: `allowedForAnyone` (if given) sets the 'anyone' flag, `subjects` (if given) replaces the subject list. Validation happens before any change. Jira administrators only.

**Response.** 200 with a [`empty-ok`](#shape-empty-ok).

**Errors.** 400 text/plain for an unknown key, an empty body or entry, or an invalid subject (same rules as the bulk PUT). 401/403 as for the GET.

#### `POST /rest/structure/2.0/configuration/permissions/{key}/add`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `key` | path | string |  | App permission key (see GET). |
| (body) | body | array<[`permission-subject`](#shape-permission-subject)> |  | JSON array of [`permission-subject`](#shape-permission-subject); non-empty. Only `group` subjects of existing groups and `projectRole` subjects of existing roles (with `projectId` 0 or an existing project) are accepted. |

Adds subjects to one app permission's subject list (duplicates are ignored; order of existing entries kept, new ones appended). Saves only if something was actually added. Jira administrators only.

**Response.** 200 with `{"updated": true|false}`: whether the stored list changed.

**Errors.** 400 text/plain when the body is missing or an empty array, the key is unknown, or a subject is null, malformed, of a disallowed type or refers to something that does not exist. 401/403 as for the GET.

#### `POST /rest/structure/2.0/configuration/permissions/{key}/remove`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `key` | path | string |  | App permission key (see GET). |
| (body) | body | array<[`permission-subject`](#shape-permission-subject)> |  | JSON array of [`permission-subject`](#shape-permission-subject); non-empty. |

Removes subjects from one app permission's subject list. Subjects only need to be well-formed (any of the four subject types is accepted and existence is not checked); subjects not in the list are ignored. Saves only if something was removed. Jira administrators only.

**Response.** 200 with `{"updated": true|false}`.

**Errors.** 400 text/plain when the body is missing or an empty array, the key is unknown, or a subject is null or malformed (missing `subject`, unknown subject type, missing id field for its type). 401/403 as for the GET.

#### `GET /rest/structure/2.0/configuration/projects`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

Returns in which Jira projects the app is enabled: all projects, or an explicit list of picked projects. Jira administrators only. Read-only.

**Response.** 200 with a [`app-project-scope`](#shape-app-project-scope) with both fields set (the picked list is kept even while 'all projects' is on).

**Errors.** 401 when not logged in; 403 when not a Jira administrator.

#### `PUT /rest/structure/2.0/configuration/projects`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`app-project-scope`](#shape-app-project-scope) |  | A [`app-project-scope`](#shape-app-project-scope) with at least one field set. Every picked id must be a non-null id of an existing project; duplicates collapse. |

Changes the project enablement. `enabledForAllProjects` (if given) sets the all-projects flag; `pickedProjectIds` (if given) replaces the picked-project list. Jira administrators only.

**Response.** 200 with a [`empty-ok`](#shape-empty-ok).

**Errors.** 400 text/plain when the body is missing or both fields are absent ('empty request'), or a picked id is null or names no existing project (the flag may already have been applied when the list is rejected). 401/403 as for the GET.

#### `POST /rest/structure/2.0/configuration/projects/add`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | array<integer> |  | Non-empty JSON array of project ids (integers); each must be an existing project. |

Adds project ids to the picked-project list (does not touch the all-projects flag). Saves only if the list changed. Jira administrators only.

**Response.** 200 with `{"updated": true|false}`.

**Errors.** 400 text/plain when the array is missing or empty, contains null, or contains the id of a project that does not exist. 401/403 as for the GET.

#### `POST /rest/structure/2.0/configuration/projects/remove`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | array<integer> |  | Non-empty JSON array of project ids (integers). |

Removes project ids from the picked-project list. Ids need not exist. Saves only if the list changed. Jira administrators only.

**Response.** 200 with `{"updated": true|false}`.

**Errors.** 400 text/plain when the array is missing or empty or contains null. 401/403 as for the GET.

#### `GET /rest/structure/2.0/create-structure/agile-boards`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Text typed by the user; items whose name matches (case-insensitive word/prefix match; empty matches everything) are returned best match first, with the matching part wrapped in `<b>` in the item's html label. |
| `maxResults` | query | integer |  | Maximum number of items; only values between 1 and the server limit (20 by default) lower the limit. When results are cut, the group carries a footer text with shown/total counts. |

Suggests agile boards visible to the caller (item value = board id, label and title = board name). Empty when Jira Software is absent.

**Response.** 200 with a [`picker-search-result`](#shape-picker-search-result) holding at most one group per category (no group when nothing matches).

**Errors.** 403 with no body for anonymous callers. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/create-structure/projects`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Text typed by the user; items whose name matches (case-insensitive word/prefix match; empty matches everything) are returned best match first, with the matching part wrapped in `<b>` in the item's html label. |
| `maxResults` | query | integer |  | Maximum number of items; only values between 1 and the server limit (20 by default) lower the limit. When results are cut, the group carries a footer text with shown/total counts. |

Suggests Jira projects that are enabled for Structure and browseable by the caller (item value = project id, title = project description).

**Response.** 200 with a [`picker-search-result`](#shape-picker-search-result) holding at most one group per category (no group when nothing matches).

**Errors.** 403 with no body for anonymous callers. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/create-structure/share-with`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Text typed by the user; items whose name matches (case-insensitive word/prefix match; empty matches everything) are returned best match first, with the matching part wrapped in `<b>` in the item's html label. |
| `maxResults` | query | integer |  | Maximum number of items; only values between 1 and the server limit (20 by default) lower the limit. When results are cut, the group carries a footer text with shown/total counts. |

Suggests permission subjects for sharing a new structure: a `private` choice (item value `private.nobody`) when its label matches, Jira project roles (value = role id, title = role description) and Jira groups the caller may use (value = group name). Logged-in users only.

**Response.** 200 with a [`picker-search-result`](#shape-picker-search-result) holding at most one group per category (no group when nothing matches). Groups appear in the order private, roles, groups.

**Errors.** 403 with no body for anonymous callers. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/create-structure/versions`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Text typed by the user; items whose name matches (case-insensitive word/prefix match; empty matches everything) are returned best match first, with the matching part wrapped in `<b>` in the item's html label. |
| `maxResults` | query | integer |  | Maximum number of items; only values between 1 and the server limit (20 by default) lower the limit. When results are cut, the group carries a footer text with shown/total counts. |
| `projectIds` | query | string |  | Comma-separated decimal Jira project ids; blank entries are ignored; omitted means no projects (no group). |

Suggests unarchived versions of the given projects (item value = version id, label = version name, extra item params `versionFullName` = `<version> (<project name>)` and `projectId`). With more than one project, matching and sorting use the full name. The projects are not checked for browse permission.

**Response.** 200 with a [`picker-search-result`](#shape-picker-search-result) holding at most one group per category (no group when nothing matches).

**Errors.** 400 when a project id is not a number. 403 with no body for anonymous callers. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/dark-features`

Access: Jira administrator with websudo. Consumes: `application/json`. Produces: `application/json`.

Lists the app's tuning properties ('dark features') currently set, for the admin page. A property is any key starting with `com.almworks.`, `almworks.`, `structure.` or `testy.` found either in Jira's application properties or in the JVM system properties, except protected keys (license-related keys of the app, profiler agent keys, keys under `com.almworks.jira.structure.config.`, and keys ending in `:build`). Jira administrators with a websudo session only. Read-only.

**Response.** Body: array<[`tuning-property-state`](#shape-tuning-property-state)>. 200 with a JSON array of [`tuning-property-state`](#shape-tuning-property-state), sorted by key.

**Errors.** 401 when not logged in or no websudo session; 403 when not a Jira administrator.

#### `POST /rest/structure/2.0/dark-features`

Access: Jira administrator with websudo. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | string |  | The property key as the raw request body text (not a JSON object). Must be non-blank, start with one of the allowed prefixes (see GET) and not be a protected key. |

Validates a property key and returns its current state, so the admin page can add a row for it. Stores nothing. Jira administrators with a websudo session only.

**Response.** 200 with a [`tuning-property-state`](#shape-tuning-property-state) for that key (value from application properties if set, else from JVM system properties, else null).

**Errors.** 400 text/plain with a localized message when the key is blank or has a wrong prefix or is protected. 401/403 as for the GET.

#### `PUT /rest/structure/2.0/dark-features`

Access: Jira administrator with websudo. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`tuning-property-update`](#shape-tuning-property-update) |  | A [`tuning-property-update`](#shape-tuning-property-update); `key` must pass the same checks as for POST. |

Sets a tuning property in Jira's application properties (persisted, instance-wide). A null value removes the stored value. Failures to write are swallowed. Jira administrators with a websudo session only.

**Response.** 204 with no body.

**Errors.** 400 when the body is missing (no message) or the key is invalid (localized text/plain message). 401/403 as for the GET.

#### `DELETE /rest/structure/2.0/dark-features`

Access: Jira administrator with websudo. Consumes: `application/json`. Produces: `text/plain`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | string |  | The property key as the raw request body text; same checks as for POST. |

Removes a tuning property from Jira's application properties. The JVM system property of the same name, if any, is not affected and becomes the effective value again. Jira administrators with a websudo session only.

**Response.** Body: string. 200 text/plain whose body is the remaining JVM system property value for that key; 204 with no body when there is none.

**Errors.** 400 text/plain with a localized message for an invalid key. 401/403 as for the GET.

#### `GET /rest/structure/2.0/date/validate`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `date` | query | string |  | The date text in the caller's date-picker format (as configured in Jira for the logged-in user). |

Checks whether a date typed by the user is valid in the caller's Jira date-picker format, and converts it to ISO form. Read-only.

**Response.** 200 with a [`date-check-result`](#shape-date-check-result). An unparseable or missing date is not an HTTP error: `isValid` is false and `error` holds the localized parser message.

**Errors.** 403 when the caller may not use the app.

#### `POST /rest/structure/2.0/effect/redo`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`effect-undo-redo-request`](#shape-effect-undo-redo-request) |  | [`effect-undo-redo-request`](#shape-effect-undo-redo-request). |

Re-applies effect batches that were undone with the undo call; same contract as undo. Runs as a server job: when the result is not ready within the asynchronous wait (3 s by default, configurable) the call answers 200 with only [`async-job-ticket`](#shape-async-job-ticket) (`{"jobId": n}`) instead; the client repeats the call with that `jobId` in the body (other fields are then ignored) until the real response arrives. An unknown or finished-and-collected `jobId` gives 404 with a [`structure-error`](#shape-structure-error) (code 4603); a `jobId` of another kind of job gives 400.

**Request.** `forest.spec` is required and must denote a generated (transformable) forest; `effectIds` lists effect batch ids previously reported in `undoEffects` or `effects[].batchId`. `forest.version` (optional) asks for a forest update from that version; `items.version` (optional) asks for an items update.

**Response.** 200 with a [`effect-undo-redo-response`](#shape-effect-undo-redo-response); `successfulActions` is always 1, failures go into `updateError`.

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when the forest spec or effect ids are missing or the forest does not support redo. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/effect/undo`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`effect-undo-redo-request`](#shape-effect-undo-redo-request) |  | [`effect-undo-redo-request`](#shape-effect-undo-redo-request). |

Reverts the given batches of effects that earlier grid actions caused in Jira (for example, field or link changes made by generators when rows were moved), then reports the resulting forest and item changes. Runs as a server job: when the result is not ready within the asynchronous wait (3 s by default, configurable) the call answers 200 with only [`async-job-ticket`](#shape-async-job-ticket) (`{"jobId": n}`) instead; the client repeats the call with that `jobId` in the body (other fields are then ignored) until the real response arrives. An unknown or finished-and-collected `jobId` gives 404 with a [`structure-error`](#shape-structure-error) (code 4603); a `jobId` of another kind of job gives 400.

**Request.** `forest.spec` is required and must denote a generated (transformable) forest; `effectIds` lists effect batch ids previously reported in `undoEffects` or `effects[].batchId`. `forest.version` (optional) asks for a forest update from that version; `items.version` (optional) asks for an items update.

**Response.** 200 with a [`effect-undo-redo-response`](#shape-effect-undo-redo-response). A failed undo is reported inside the body (`updateError`), not by status; `successfulActions` is always 1.

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when the forest spec or effect ids are missing or the forest does not support undo. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/effectorProcess/acknowledge`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | array<integer> |  | JSON array of effector process ids; null entries are ignored. |

Marks finished effector processes as acknowledged by the user, so they stop being reported as background processes in polls. Ids that cannot be acknowledged (unknown, not the caller's, unfinished) are skipped silently.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) (`{}`).

**Errors.** 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/effectorProcess/list`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`effector-page-request`](#shape-effector-page-request) |  | [`effector-page-request`](#shape-effector-page-request): `startAt` (0-based) and `maxResults` (`-1` = all; an omitted value counts as 0 and yields an empty page). `params` may hold `user` (user key; forced to the caller for non-administrators), `status` (a process status name; unknown values mean no filter) and `structure` (structure id). |

Lists effector processes (runs of effectors that write to Jira) for the audit view. Administrators see all processes and may filter; other users only ever see their own.

**Response.** 200 with a [`effector-page-response`](#shape-effector-page-response) whose `items` are [`effector-process`](#shape-effector-process); `pagination.total` = number of matching processes, `errors` = 0.

**Errors.** 404 with no body for anonymous callers. 400 text/plain when `startAt` is negative or `maxResults` is below -1; 400 when `startAt` is beyond the end of the list. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/effectorProcess/{processId}/cancel`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `processId` | path | integer |  | Effector process id. |
| (body) | body | map<string, any> |  | Any JSON object (e.g. `{}`); ignored. Required only so that the call is a JSON POST. |

Requests cancellation of an effector process (its calculation or application stops at the next opportunity). Does not wait.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) (`{}`).

**Errors.** A process is visible only to the user who started it and to Jira administrators; any other caller (and an unknown id) gets 404 with a [`structure-error`](#shape-structure-error) (code 6017). 500 with a [`structure-error`](#shape-structure-error) when the process's progress handle is gone. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/effectorProcess/{processId}/cancelAndWait`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `processId` | path | integer |  | Effector process id. |
| (body) | body | map<string, any> |  | Any JSON object (e.g. `{}`); ignored. Required only so that the call is a JSON POST. |

If the process is pending, calculating, calculated, queued or in progress, requests cancellation, waits about half a second and returns the process; in any other status returns it unchanged.

**Response.** 200 with a [`effector-process`](#shape-effector-process) (state after the wait).

**Errors.** A process is visible only to the user who started it and to Jira administrators; any other caller (and an unknown id) gets 404 with a [`structure-error`](#shape-structure-error) (code 6017). 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/effectorProcess/{processId}/preview`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `processId` | path | integer |  | Effector process id. |
| (body) | body | [`effector-page-request`](#shape-effector-page-request) |  | [`effector-page-request`](#shape-effector-page-request): `startAt` (0-based) and `maxResults` (`-1` = all; an omitted value counts as 0 and yields an empty page). `params` is ignored. |

Returns a page of the effects a calculated process would apply (its preview), with the affected items, and counts how many previewed effects are only warnings or cannot be applied.

**Response.** 200 with a [`effector-page-response`](#shape-effector-page-response) whose `items` are [`effect-record`](#shape-effect-record) (with `index` = position in the preview); `pagination.total` = number of previewed effects, `pagination.errors` = number of warning or unresolvable effects.

**Errors.** 404 text/plain `No preview found` when the process has no preview. A process is visible only to the user who started it and to Jira administrators; any other caller (and an unknown id) gets 404 with a [`structure-error`](#shape-structure-error) (code 6017). 400 text/plain when `startAt` is negative or `maxResults` is below -1; 400 when `startAt` is beyond the end of the list. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/effectorProcess/{processId}/records`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `processId` | path | integer |  | Effector process id. |
| (body) | body | [`effector-page-request`](#shape-effector-page-request) |  | [`effector-page-request`](#shape-effector-page-request): `startAt` (0-based) and `maxResults` (`-1` = all; an omitted value counts as 0 and yields an empty page). `params.itemKey` filters records by affected item: an issue key (contains `-`, case-insensitive), `MEMO:<id>` or `PT:<id>` (planning task); an unrecognised key gives an empty list. |

Returns a page of the effects a process actually applied (its audit records), each with its undo description, time and affected items; optionally only records touching one item.

**Response.** 200 with a [`effector-page-response`](#shape-effector-page-response) whose `items` are [`effect-record`](#shape-effect-record); `pagination.total` = number of (filtered) records, `errors` = 0.

**Errors.** A process is visible only to the user who started it and to Jira administrators; any other caller (and an unknown id) gets 404 with a [`structure-error`](#shape-structure-error) (code 6017). 400 text/plain when `startAt` is negative or `maxResults` is below -1; 400 when `startAt` is beyond the end of the list. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/effectorProcess/{processId}/resume`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `processId` | path | integer |  | Effector process id. |
| (body) | body | map<string, any> |  | Any JSON object (e.g. `{}`); ignored. Required only so that the call is a JSON POST. |

Resumes applying a process whose application was interrupted (status `APPLY_INTERRUPTED`), waits about half a second and returns it; in any other status returns it unchanged.

**Response.** 200 with a [`effector-process`](#shape-effector-process).

**Errors.** A process is visible only to the user who started it and to Jira administrators; any other caller (and an unknown id) gets 404 with a [`structure-error`](#shape-structure-error) (code 6017). 500 with a [`structure-error`](#shape-structure-error) when resuming fails. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/effectorProcess/{processId}/status`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `processId` | path | integer |  | Effector process id. |

Returns a process's status, completion percentage and whether cancellation was requested; polled by the progress dialog.

**Response.** 200 with a [`effector-process-progress`](#shape-effector-process-progress).

**Errors.** A process is visible only to the user who started it and to Jira administrators; any other caller (and an unknown id) gets 404 with a [`structure-error`](#shape-structure-error) (code 6017). 500 with a [`structure-error`](#shape-structure-error) when the progress handle is gone. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/effectorProcess/{processId}/undo`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `processId` | path | integer |  | Id of the process to revert. |
| (body) | body | map<string, any> |  | Any JSON object (e.g. `{}`); ignored. Required only so that the call is a JSON POST. |

Starts a new effector process that reverts the successfully applied effects of a finished process (completed, completed with errors, interrupted or stopped). The new process is queued for application immediately and remembers which process it reverts.

**Response.** 200 with a bare JSON number: the id of the new undo process.

**Errors.** Body is a [`structure-error`](#shape-structure-error): 403 (code 4501) when the caller lacks the app permission to run effectors; 400 when the process is not finished or has nothing to undo; 404 (code 6017) when the process is unknown or not the caller's. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/expr/validate`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`formula-check-request`](#shape-formula-check-request) |  | A [`formula-check-request`](#shape-formula-check-request). |

Parses an expression in the app's formula language and reports syntax errors and every variable, function, aggregation and comment with its character range, for the formula editor (highlighting, hints, documentation links). Also increments the app's local usage counters (expression validations, valid/invalid, functions used, complexity distribution); nothing is sent anywhere.

**Request.** `expr` is required. `definedVariables` lists variable names the caller already has bound (for example by column configuration); they are compared after the language's name normalization (case-insensitive, ignoring the characters the language ignores in names), and a free variable counts as resolved only if it is in this list.

**Response.** 200 with a [`formula-check-result`](#shape-formula-check-result). Each validation problem appears exactly once: attached to the usage or declaration range it belongs to (that range's `error`), otherwise in `errors`. Texts are in the caller's language.

**Errors.** 400 text/plain when `expr` is missing. 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/forest/latest`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `s` | query | string |  | The forest spec as JSON text ([`forest-spec`](#shape-forest-spec)), URL-encoded into the query string. Required. |

Returns the current content of a forest (a structure, a past version of one, a query result, the clipboard, optionally with transformations applied) as an encoded forest with its version.

**Response.** 200 with a [`forest-snapshot`](#shape-forest-snapshot) echoing the spec.

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when the forest spec is invalid (missing, more than one of `structureId`/`sQuery`/clipboard, `version` or `title` without `structureId`, unsupported query type); 404 when the structure does not exist or is not visible. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/forest/latest`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`forest-spec`](#shape-forest-spec) |  | [`forest-spec`](#shape-forest-spec). |

Same as the GET form, with the forest spec as the request body.

**Response.** 200 with a [`forest-snapshot`](#shape-forest-snapshot) echoing the spec.

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when the forest spec is invalid (missing, more than one of `structureId`/`sQuery`/clipboard, `version` or `title` without `structureId`, unsupported query type); 404 when the structure does not exist or is not visible. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/forest/update`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`forest-update-request`](#shape-forest-update-request) |  | [`forest-update-request`](#shape-forest-update-request). |

Applies a list of editing actions (add, copy, move, remove rows) to a forest in order, as the grid does on drag-and-drop, paste and delete. Each action may be accepted, refused with an error, or answered with a question (e.g. which generator should handle the change) that the client resolves by resending the remaining actions with the chosen value in the action's `parameters`. Processing stops at the first action that fails or asks a question. Effects in Jira caused by generators (field changes, links...) are reported for undo. A cut-and-paste between forests is an `add` with `cutFrom`: the removal from the source is first tried without changes, then the add is applied, then the removal; if the removal then fails, the add is undone where possible. When the cut went through the clipboard, the caller's clipboard is cleared after success. Usage counters are recorded. Runs as a server job: when the result is not ready within the asynchronous wait (3 s by default, configurable) the call answers 200 with only [`async-job-ticket`](#shape-async-job-ticket) (`{"jobId": n}`) instead; the client repeats the call with that `jobId` in the body (other fields are then ignored) until the real response arrives. An unknown or finished-and-collected `jobId` gives 404 with a [`structure-error`](#shape-structure-error) (code 4603); a `jobId` of another kind of job gives 400.

**Request.** `spec` (the forest to edit) and `version` (the version the client's coordinates refer to) are required, `actions` is the ordered list. If the forest's version signature changed since `version` and an action refers to transient rows (odd positive row ids, which only exist in generated content), that action fails with a signature-mismatch error (code 5006) instead of being applied.

**Response.** 200 with a [`forest-update-response`](#shape-forest-update-response). Refusals and questions are reported in `updateError` with status 200.

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when `version` is missing, an action name is unknown (`add`, `copy`, `move`, `remove` are valid), a forest/row list required by the action is missing or unparsable, `cutFrom` lacks `version` or `rowIds`, or `copy` has `originalRowIds` of the wrong length. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/generation/generatorDescriptions`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | array<integer> |  | JSON array of generator ids (the numeric id of the generator item). |

Describes generators by id for the health/stop banner: an HTML snippet with the generator's icon and summary. Unknown or inaccessible ids are left out.

**Response.** 200 with a JSON array of [`generator-description`](#shape-generator-description).

**Errors.** 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/generation/resume`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`generation-control-request`](#shape-generation-control-request) |  | [`generation-control-request`](#shape-generation-control-request): `forestSpecs` lists the forests. Specs with a `version` or of the clipboard are ignored. |

Resumes automatic generation for the given forests and every forest they are built from (for a transformed view: the underlying structure and intermediate transformation steps). Each resume is logged on the server.

**Response.** 200 with a [`generation-control-request`](#shape-generation-control-request) whose `forestSpecs` lists every forest that was considered for resuming (the requested ones and their dependencies).

**Errors.** 404 with a [`structure-error`](#shape-structure-error) when a structure in a spec is not visible; 400 for an invalid spec. 401 for anonymous callers. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/generation/stop`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`generation-control-request`](#shape-generation-control-request) |  | [`generation-control-request`](#shape-generation-control-request): `forestSpecs` lists the forests. Specs with a `version` or of the clipboard are ignored. |

Stops generation of the given forests: running generations are cancelled and the forest is kept as is (marked stopped in its health status) until resumed. Logged on the server.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) (`{}`).

**Errors.** 404 with a [`structure-error`](#shape-structure-error) when a structure in a spec is not visible; 400 for an invalid spec. 401 for anonymous callers. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/generation/stopIfRunning`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`generation-control-request`](#shape-generation-control-request) |  | [`generation-control-request`](#shape-generation-control-request): `forestSpecs` lists the forests. Specs with a `version` or of the clipboard are ignored. |

Like stop, but only takes effect for a forest whose generation is currently running (used when a generation takes too long).

**Response.** 200 with [`empty-ok`](#shape-empty-ok) (`{}`).

**Errors.** 404 with a [`structure-error`](#shape-structure-error) when a structure in a spec is not visible; 400 for an invalid spec. 401 for anonymous callers. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/genericItem/creationFields/{itemType}/{projectId}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `itemType` | path | string |  | Full item type key; only `com.almworks.jira.structure:type-planning-task` yields fields. |
| `projectId` | path | integer |  | Jira project id whose issue types are offered; 0 = no project restriction. |

Returns the field descriptors needed to create a planning task: `project` and `issuetype`, both required, visible and editable, with their option sources (issue types limited to the given project). For any other item type returns an empty object.

**Response.** 200 with a JSON object mapping field id (`project`, `issuetype`) to a [`generic-item-field`](#shape-generic-item-field); `{}` for other item types.

**Errors.** 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/genericItem/details/{itemType}/{id}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `itemType` | path | string |  | Full item type key of a generic item type (e.g. `com.almworks.jira.structure:type-memo`). |
| `id` | path | integer |  | Numeric item id. |

Returns the details panel content of a generic item (memo, planning task): its summary, description (raw wiki text and rendered HTML), visible field values, colour and icon, plus the descriptors of all generic-item fields as configured for this item.

**Response.** 200 with a [`generic-item-details`](#shape-generic-item-details).

**Errors.** 400 text/plain when the item type is not a generic item type; 404 with a [`structure-error`](#shape-structure-error) when the item does not exist or is not visible to the caller. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/genericItem/{itemType}/validate`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `itemType` | path | string |  | Must be `com.almworks.jira.structure:type-planning-task`. |
| (body) | body | map<string, any> |  | JSON object of new-item values: `summary` (text; `*` is assumed when absent) and `params` (object with `project` and `issuetype` ids as numbers or numeric strings, plus other field values). |

Validates the values of a planning task that is about to be created and returns a preview of the item with defaults filled in: when the project is missing or not browseable the first browseable project is used; when the issue type is missing or unknown the project's first non-sub-task issue type (by name) is used. Nothing is stored.

**Response.** 200 with a [`generic-item-validation`](#shape-generic-item-validation); when `params` is absent, only an empty `fieldErrors` is returned.

**Errors.** 400 with a [`structure-error`](#shape-structure-error) for other item types or when the caller can browse no project; 401 for anonymous callers. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/group-picker`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Case-insensitive literal substring of the group name. Blank or omitted: all visible groups. |
| `maxResults` | query | integer |  | Maximum items; used only when positive and lower than the instance limit (default 20, adjustable by an instance property). |

Search box backend for picking Jira groups (used in sharing and permission dialogs). Searches the groups the caller may see: all groups for Jira admins or when the instance-wide setting that exposes all groups is on, otherwise only the caller's own groups. Requires a logged-in user. Read-only.

**Response.** 200 with a [`picker-search-result`](#shape-picker-search-result) holding no group when nothing matches, else one group labelled with the localized word 'Groups'. Matches are ordered by name length (shortest first). Item `value`, `id` and `label` are the group name; `html` is the HTML-escaped name with the matched part wrapped in `<b>`. `footer` is a localized 'Showing N of M matching groups' text only when results were cut.

**Errors.** 403 with no body when not logged in; 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/history/{id}/version/{v}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Structure id. |
| `v` | path | integer |  | Version number. |

Returns one version of a structure's history in full: the change entries with the moved/added/removed sub-forests and their positions before and after, plus the whole forest as it was right after that version.

**Response.** 200 with a [`structure-history-version`](#shape-structure-history-version) including `fullForest` and the per-change position fields.

**Errors.** 403 text/plain when the structure does not exist or is not viewable; 400 text/plain when the version is missing; other failures (e.g. unknown version) as text/plain with the status of the error category (404/403/400/500). 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/history/{id}/versions`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Structure id. |
| `minVersion` | query | integer |  | Accepted but ignored. |
| `maxVersion` | query | integer |  | Start the listing at this version (going back); omitted = from the latest. |
| `maxCount` | query | integer |  | Maximum number of versions; omitted = no limit. Combined with `withVersion`, the listing continues past `maxCount` until `withVersion` is reached. |
| `withVersion` | query | integer |  | Keep listing until a version less than or equal to this one has been included. |

Lists the change history of a structure, newest first, one entry per stored version with who/what changed it and a short description of each change (no forest content).

**Response.** 200 with a [`structure-history-page`](#shape-structure-history-page).

**Errors.** 403 text/plain when the structure does not exist or the caller cannot view it. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/info-popup`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

Data for the app's 'about' popup: app version, license, update availability, the Jira cluster node id, and the same for four companion add-ons (Gantt, Pages, Deliver, Testy). IMPORTANT: the original asks the Atlassian Marketplace (an external server) whether a newer version of the app and of each installed companion is available (results cached for a long time; failures count as 'no update'). The replacement must not contact the Marketplace; it reports `false` for every update flag.

**Response.** 200 with a [`about-popup-data`](#shape-about-popup-data). License objects are null for anonymous callers. For the app, the license shown is the effective license if it is a Marketplace license or 'disabled'; otherwise the bundle license (null when the bundle license is disabled). Companions: one entry each for plugin keys `com.almworks.structure.gantt`, `com.almworks.structure.pages`, `com.almworks.structure.deliver`, `com.almworks.testy`, in that order, always present even when not installed (then `version` is null and `updateAvailable` false).

**Errors.** 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/issue-field`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

Lists the Jira issue fields for which the app can offer a value picker (used by 'filter by field' and similar generator settings): the navigable fields the caller can see that have an option source, i.e. project, status, issue type, affects and fix versions, priority, reporter, creator, assignee, labels, components, resolution, and custom fields of user, multi-user, multi-group, version, labels, select, multi-select, cascading select, project, sprint, Advanced Roadmaps team, Tempo team and Assets object types (the last four only when that integration is present). When the app is not enabled for all projects, a custom field is listed only if it applies to at least one enabled project. Read-only.

**Response.** 200 with a JSON array of [`pickable-issue-field`](#shape-pickable-issue-field) sorted by field name.

**Errors.** 403 when the caller may not use the app. Failure to read the field list yields an empty array.

#### `GET /rest/structure/2.0/issue-field/options`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `fieldId` | query | string |  | Jira field id, e.g. `status`, `fixVersions`, `customfield_10010`. Required. An unknown or unsupported field gives an empty `groups` array. |
| `query` | query | string |  | Optional filter: an option matches when one of the words in its label starts with the query text (case-insensitive). User, group and user-picker custom fields are not searchable this way (they return no options); labels fields use Jira's label suggestions for the text. |
| `limit` | query | integer |  | Maximum options per group; zero, negative or omitted means no limit. |

Searches the selectable values of one supported issue field (see GET /issue-field), limited to the app-enabled projects the caller can browse. Read-only.

**Response.** 200 with a [`issue-field-option-list`](#shape-issue-field-option-list). Issue type options come in two groups (standard and sub-task types, localized labels); every other field has one group with an empty label. If the field has a 'no value' option (id `special:EMPTY`, localized label such as 'No version', 'Unassigned', 'Unresolved') and its label contains the query (always true for an empty query), it is put first in each group, in addition to the limit. Option `id` formats are described in [`issue-field-option`](#shape-issue-field-option).

**Errors.** 400 text/plain when `fieldId` is blank. 403 when the caller may not use the app.

#### `POST /rest/structure/2.0/issue-field/options`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`issue-field-option-lookup`](#shape-issue-field-option-lookup) |  | A [`issue-field-option-lookup`](#shape-issue-field-option-lookup); `fieldId` must be non-blank and `fieldValues` non-empty. |

Resolves known option ids of one supported issue field into displayable options (e.g. to render the current selection). Read-only.

**Response.** 200 with a [`issue-field-option-list`](#shape-issue-field-option-list) holding a single group (empty label, `total` = number of options returned). Options follow the order of `fieldValues`; an id that cannot be resolved (or is not visible) still yields an option with that id and the placeholder label `option_<id>`. The 'no value' id `special:EMPTY`, if requested and the field has such an option, is moved to the end.

**Errors.** 400 text/plain when `fieldId` is blank or `fieldValues` is missing or empty. 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/issue/{issueId}/actions-and-operations`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `issueId` | path | integer |  | Numeric Jira issue id. |

Returns what the caller can do with an issue from the grid's issue menu: available workflow transitions, Jira's issue operation links (operations, restore and admin sections of the issue operations bar), the label for 'view issue', and a fresh XSRF token for the caller's session.

**Response.** 200 with a [`issue-actions-and-operations`](#shape-issue-actions-and-operations).

**Errors.** 404 with no body when the issue does not exist or the caller cannot see it. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/item/create`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`create-item-request`](#shape-create-item-request) |  | [`create-item-request`](#shape-create-item-request). |

Creates a new item (issue, folder, memo, planning task... of the given type) or takes an existing item, and inserts it as one row into a forest at the given position. Before creating a new item the insertion is tried without changes; if it would be refused, the response asks whether to create the item anyway (question parameter `0:CreateAnyway`, value `true`), and nothing is created until the request is resent with `parameters` `{"0:CreateAnyway": true}` (a boolean or the string `true`). If a generator in the forest already shows the new item somewhere (e.g. because it matches a query), that generated row is reused and moved to the requested position when possible instead of inserting a second row. Special keys `itemproperty.notes` and `itemproperty.dc_note_<note id>` in the item values (at any nesting level) set per-structure notes of the new item instead of item fields. Usage counters are recorded. Runs as a server job: when the result is not ready within the asynchronous wait (3 s by default, configurable) the call answers 200 with only [`async-job-ticket`](#shape-async-job-ticket) (`{"jobId": n}`) instead; the client repeats the call with that `jobId` in the body (other fields are then ignored) until the real response arrives. An unknown or finished-and-collected `jobId` gives 404 with a [`structure-error`](#shape-structure-error) (code 4603); a `jobId` of another kind of job gives 400.

**Request.** `forest.spec`, `forest.version`, `items.version` and `item` are required. `item.itemId` (existing item) or `item.type` plus `item.values` (new item) must be given. `rowId` is the temporary (negative) id the client gave the new row; `under`/`after`/`before` position it (0 = none).

**Response.** 200 with a [`create-item-response`](#shape-create-item-response). Item validation errors go into `formErrors`/`fieldErrors`, insertion refusals and questions into `updateError`, all with status 200.

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when `item.type` is missing or `item.itemId` cannot be parsed; 404/400/500 with a [`structure-error`](#shape-structure-error) when the type is unknown, cannot create items, or its module fails; an error when the forest does not accept actions. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/item/update`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`update-item-request`](#shape-update-item-request) |  | [`update-item-request`](#shape-update-item-request). |

Updates fields of an existing item (through its item type, e.g. summary of a folder or fields of an issue) and/or its per-structure notes (`itemproperty.notes`, `itemproperty.dc_note_<note id>` keys with string values), then reports forest and item changes since the client's versions. Runs as a server job: when the result is not ready within the asynchronous wait (3 s by default, configurable) the call answers 200 with only [`async-job-ticket`](#shape-async-job-ticket) (`{"jobId": n}`) instead; the client repeats the call with that `jobId` in the body (other fields are then ignored) until the real response arrives. An unknown or finished-and-collected `jobId` gives 404 with a [`structure-error`](#shape-structure-error) (code 4603); a `jobId` of another kind of job gives 400.

**Request.** `item.itemId` (full item id, e.g. `10001` for an issue or `com.almworks.jira.structure:type-folder/5`) and `item.values` are required, as are `forest.spec`, `forest.version` and `items.version`.

**Response.** 200 with a [`update-item-response`](#shape-update-item-response); validation failures give `success` = false with `formErrors`/`fieldErrors`.

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when the item id is missing or unparsable, the item type is unknown, or the type does not support updates while non-note values are given; 500 when the item type module fails. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/label-picker`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Label prefix to complete; omitted means Jira's default suggestions. |
| `customFieldId` | query | integer |  | Numeric id of a labels custom field (the number in `customfield_<n>`). Omitted: the system Labels field. |

Returns Jira's label suggestions for the caller, either for the system Labels field or for one labels-type custom field. Read-only.

**Response.** 200 with a JSON array of label strings, as suggested by Jira.

**Errors.** 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/macro/search-filters`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Filter name search text. |

Finds Jira saved filters by name for the Confluence macro editor (called from a linked Confluence). Returns at most 10 filters visible to the caller whose name matches the query as a word-wildcard search. Read-only.

**Response.** 200 with a [`macro-filter-search-result`](#shape-macro-filter-search-result). If the search fails, `error` holds the failure message and `savedfilters` whatever was found so far.

**Errors.** 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/macro/settings`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `ping` | query | boolean |  | true: return only `{"structureInstalled": true}` and ignore everything else. |
| `savedFilterId` | query | integer |  | With `oneSavedFilter=true`: id of the one saved filter to return (if the caller can see it). |
| `oneSavedFilter` | query | boolean |  | true: return only the filter named by `savedFilterId` (none if absent or not visible). Otherwise all saved filters shared with the caller are returned. |

Configuration lists for the Confluence macro editor: the structures and views the caller can view, and saved filters. Works even when the caller may not use the app (then it reports that in `error`). Also serves as an 'is the app installed' probe. Read-only.

**Response.** 200 with a [`macro-editor-settings`](#shape-macro-editor-settings) (or the ping object). When the caller may not use the app, only `error` (localized 'app not available to the current user') and `supportedOptions` are set. If reading fails midway, `error` holds the message and the lists hold what was collected.

**Errors.** No error statuses of its own; problems are reported in `error`.

#### `GET /rest/structure/2.0/manage-structures/all`

Access: anonymous users allowed. Consumes: any. Produces: `application/json`.

Returns the table of the structure management page for all structures the caller can view, archived ones included, with favourite flags, popularity, last-opened dates, synchronizers, copy processes, integrating add-ons and problems. Rate-limited per user (anonymous callers share one bucket): a call while the same user's previous call is still running, or within 500 ms of it (configurable), is refused.

**Response.** 200 with a [`managed-structures-table`](#shape-managed-structures-table).

**Errors.** 429 text/plain with a `Retry-After` header (seconds) when rate-limited. 403 with a [`structure-error`](#shape-structure-error) (code 4010) when the caller may not use Structure. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/manage-structures/favorites`

Access: anonymous users allowed. Consumes: any. Produces: `application/json`.

Returns the management table restricted to the caller's favourite structures (archived ones included).

**Response.** 200 with a [`managed-structures-table`](#shape-managed-structures-table).

**Errors.** 403 with a [`structure-error`](#shape-structure-error) (code 4010) when the caller may not use Structure. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/manage-structures/one`

Access: anonymous users allowed. Consumes: any. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | query | integer |  | Structure id. Required. |

Returns the management table row for a single structure (to refresh one row).

**Response.** 200 with a [`managed-structures-table`](#shape-managed-structures-table).

**Errors.** 404 with a [`structure-error`](#shape-structure-error) when the structure does not exist or is not viewable. 403 with a [`structure-error`](#shape-structure-error) (code 4010) when the caller may not use Structure. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/manage-structures/page-details`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | array<integer> |  | JSON array of structure ids; at most 20 (configurable). |

Returns, for the structures on the currently displayed page of the management table, the rendered description and the number of effector rows. Structures the caller cannot view are left out.

**Response.** Body: map<string, [`managed-structure-page-details`](#shape-managed-structure-page-details)>. 200 with a JSON object mapping each structure id (as a string key) to a [`managed-structure-page-details`](#shape-managed-structure-page-details).

**Errors.** 400 with a [`structure-error`](#shape-structure-error) (`Invalid request data`) when more ids than the limit are sent. 403 with a [`structure-error`](#shape-structure-error) (code 4010) when the caller may not use Structure. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/manage-structures/recent-ids`

Access: anonymous users allowed. Consumes: any. Produces: `application/json`.

Returns the ids of the structures the caller opened recently, most recent first.

**Response.** Body: array<integer>. 200 with a JSON array of structure ids.

**Errors.** 403 with a [`structure-error`](#shape-structure-error) (code 4010) when the caller may not use Structure. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/manage-structures/recents`

Access: anonymous users allowed. Consumes: any. Produces: `application/json`.

Returns the management table restricted to the caller's recently opened structures.

**Response.** 200 with a [`managed-structures-table`](#shape-managed-structures-table).

**Errors.** 403 with a [`structure-error`](#shape-structure-error) (code 4010) when the caller may not use Structure. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/mapping`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`row-mapping-request`](#shape-row-mapping-request) |  | [`row-mapping-request`](#shape-row-mapping-request): `forestSpecs` and `rows`, both required. |

Translates row ids into the corresponding rows of other forests: for each forest, each requested row is traced back through the rows it was copied or generated from until a row present in that forest is found. Used to keep the selection when switching views or transformations.

**Response.** 200 with a [`row-mapping-response`](#shape-row-mapping-response): one mapping per forest spec, in request order, each with one mapped row per requested row (0 when none).

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when the forest spec is invalid (missing, more than one of `structureId`/`sQuery`/clipboard, `version` or `title` without `structureId`, unsupported query type); 404 when the structure does not exist or is not visible. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/note`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`note-create-request`](#shape-note-create-request) |  | A [`note-create-request`](#shape-note-create-request). |

Creates a stored note (a named, separately editable text attribute that can be shown as a column) owned by a structure; whoever may edit that structure may later rename or archive it. The name is trimmed. Requires edit permission on the given structure. Persisted in the NOTE table.

**Request.** `structureId` must be non-zero; `name` must be non-blank and at most 190 characters.

**Response.** 200 with a [`note-record`](#shape-note-record) for the new note (id `dc_note_<n>`).

**Errors.** 400 text/plain (localized) when `structureId` is missing or 0. 400 with a [`structure-error`](#shape-structure-error) when the name is blank or too long. 403 with a [`structure-error`](#shape-structure-error) when the caller cannot edit the structure (also when it does not exist). 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/note/search`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `name` | query | string |  | Case-insensitive literal substring of the note name; empty string matches every note. Should always be sent. |
| `structureId` | query | integer |  | Structure the picker is open in; decides the 'Used in structure' group. 0 or omitted: no such group. |
| `limit` | query | integer |  | Maximum total notes over all groups; omitted means unlimited. |

Note picker search: finds non-archived notes whose name contains the text, grouped for display relative to a structure. Read-only.

**Response.** 200 with a [`note-search-result`](#shape-note-search-result). Groups, in order and only when non-empty: (1) untitled group with the built-in default note (id `notes`) if it matches; (2) 'Used in structure': matching notes that have values in the given structure, if the caller can view it; (3) only if the limit is not yet exceeded, 'Other notes': matching notes used in other structures the caller can view, plus unused notes the caller may view. Within a group notes are sorted by name, then id. The limit cuts the group in which it is reached; `hasMore` is true when more matches existed than the limit.

**Errors.** 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/note/{noteId}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `noteId` | path | string |  | `notes` or a stored note id `dc_note_<n>` (the prefix may be omitted). |

Returns one note by id, including whether the caller may edit it. The id `notes` returns the built-in default note (localized name 'Notes (Default)', never editable). No view-permission check is made on stored notes. Read-only.

**Response.** 200 with a [`note-record`](#shape-note-record).

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when the id is not of the form `dc_note_<integer>` / `<integer>`. 404 text/plain (localized 'note not found') when no such note exists. 403 when the caller may not use the app.

#### `PUT /rest/structure/2.0/note/{noteId}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `noteId` | path | string |  | Stored note id `dc_note_<n>`. |
| (body) | body | [`note-rename-request`](#shape-note-rename-request) |  | A [`note-rename-request`](#shape-note-rename-request); `name` non-blank, at most 190 characters. |

Renames a stored note. Requires edit permission on the note's owning structure; archived notes cannot be renamed; the built-in default note cannot be renamed. The new name is trimmed.

**Response.** 200 with the updated [`note-record`](#shape-note-record).

**Errors.** 400 text/plain (localized) for `notes`. 400 with a [`structure-error`](#shape-structure-error) for a malformed id, an archived note, or a blank or too long name. 403 (same error form) when the caller cannot edit the owning structure. 404 (same error form) when the note does not exist. 403 when the caller may not use the app.

#### `PUT /rest/structure/2.0/note/{noteId}/archive`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `noteId` | path | string |  | Stored note id `dc_note_<n>`. |

Archives a stored note: it disappears from note search and becomes read-only, but values and columns referring to it keep working. Requires edit permission on the owning structure. Archiving an archived note succeeds again. There is no un-archive endpoint. The built-in default note cannot be archived.

**Response.** 200 with the updated [`note-record`](#shape-note-record) (`archived` true, name shown with the localized '(Archived)' suffix).

**Errors.** 400 text/plain (localized) for `notes`. 400 with a [`structure-error`](#shape-structure-error) for a malformed id. 403 (same error form) when the caller cannot edit the owning structure. 404 (same error form) when the note does not exist. 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/options-picker/list`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `spec` | query | string |  | URL-encoded JSON object describing the source: `sourceKey` (one of `PROJECTS`, `ISSUE_TYPES`, `PRIORITIES`, `VERSIONS`, `COMPONENTS`, `SPRINTS`, `USERS`, `GROUPS`, `FIELD_OPTIONS`, `EMPTY`), `projectId` (project the options are for; required for issue types, priorities, versions and components, which are empty without it or when the caller cannot browse that project) and `filters` (object of boolean flags: `excludeSubtasks` for issue types; `excludeInactive` to drop archived projects/versions/components, closed sprints, inactive users, disabled field options; `checkCreateIssues` and `checkStructureConfig` for projects (caller may create issues / app enabled in the project); `checkAssignable` for users (assignable in `projectId`); plus string `customField` (custom field id) and `issueTypeId` for `FIELD_OPTIONS`). |

Returns every option of an option source (projects, issue types, priorities, versions, components, sprints, users, groups or custom field options), for drop-downs in item-creation forms. Read-only.

**Response.** 200 with a JSON array of [`picker-option`](#shape-picker-option) (`html` null), sorted by the source's order (group, then name; custom field options by their configured order). Projects, versions and components are limited to projects the caller can browse and view issues in. When `spec` is missing or not valid JSON, the source key is unknown or `EMPTY`, or the source is not selectable for the caller (`USERS` requires the Browse Users global permission), the response is 200 with a [`empty-ok`](#shape-empty-ok) instead.

**Errors.** 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/options-picker/search`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `spec` | query | string |  | Option source description, as for /options-picker/list. |
| `query` | query | string |  | Search text. Blank: behaves like /options-picker/suggestions with no ids. Otherwise options whose label contains the text (case-insensitive, literal) are returned; for users, Jira's user search is used instead. |

Searches an option source for a picker. Returns at most N options, where N is the smaller of the source's search threshold (default 50) and the page size (default 10); both adjustable by instance properties. Read-only.

**Response.** 200 with a JSON array of [`picker-option`](#shape-picker-option); for a non-blank query `html` is the HTML-escaped label inside a span with the match wrapped in a span of class s-match. Same [`empty-ok`](#shape-empty-ok) fallback as /list.

**Errors.** 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/options-picker/suggestions`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `spec` | query | string |  | Option source description, as for /options-picker/list. |
| `ids` | query | string |  | URL-encoded JSON array of option ids that are currently selected; each one that exists and is valid for the source is included even beyond N. Omitted or invalid JSON: none. |

Initial content of an option picker: the caller's recent items for the source (recent projects, recently used users, sprints of suggested boards) topped up with other options up to N (as in /search; users are not topped up), plus the currently selected options given by id. Read-only.

**Response.** 200 with a JSON array of [`picker-option`](#shape-picker-option) (`html` null) without duplicates, sorted in the source's order. Same [`empty-ok`](#shape-empty-ok) fallback as /list.

**Errors.** 403 when the caller may not use the app.

#### `POST /rest/structure/2.0/poll`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`poll-request`](#shape-poll-request) |  | [`poll-request`](#shape-poll-request). |

The grid's periodic poll. In one call it returns: for each watched forest, the changes since the client's version (or the whole forest); the list of items changed since the client's items version; extension data; the caller's running or unacknowledged effector processes; and, for attribute subscriptions, value updates. Subscription value loading is started first; after the forest part is computed the server waits up to about 1 s in total (configurable) for values before answering. When clustered, sets the cookie `X-Structure-DC-Meta` (see attribute subscriptions). Runs as a server job: when the result is not ready within the asynchronous wait (3 s by default, configurable) the call answers 200 with only [`async-job-ticket`](#shape-async-job-ticket) (`{"jobId": n}`) instead; the client repeats the call with that `jobId` in the body (other fields are then ignored) until the real response arrives. An unknown or finished-and-collected `jobId` gives 404 with a [`structure-error`](#shape-structure-error) (code 4603); a `jobId` of another kind of job gives 400.

**Request.** All parts are optional. Each forest entry needs `spec` and `version`; version `{signature: 0, version: -1}` asks for an initial load, which may first return a cached snapshot flagged `needsUpdate`. At most 20 subscription entries (configurable), each with `id` and `version`.

**Response.** 200 with a [`poll-response`](#shape-poll-response). Forest entries whose spec is invalid are silently left out of `forestUpdates`; a forest that cannot be read is reported with `error` in its update; an unknown subscription is reported with `error` in its subscription update.

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when more subscriptions than the limit are sent or a subscription entry lacks `id` or `version`. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/process/{id}/cancel`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Process handle id. |
| (body) | body | map<string, any> |  | Any JSON object (e.g. `{}`); ignored. Required only so that the call is a JSON POST. |

Requests cancellation of a background process (any long-running Structure operation tracked with a progress handle, such as an effector run, export or copy) and returns its state.

**Response.** 200 with a [`background-process-info`](#shape-background-process-info).

**Errors.** 403 text/plain `permission violation` when the caller may not use Structure; 404 text/plain when the process does not exist or is not visible to the caller (a process is visible to the user who started it, and every process to Jira administrators).

#### `GET /rest/structure/2.0/process/{id}/info`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Process handle id. |

Returns the display state of a background process: localized name, status, current activity, progress and optional buttons.

**Response.** 200 with a [`background-process-info`](#shape-background-process-info).

**Errors.** 403 text/plain `permission violation` when the caller may not use Structure; 404 text/plain when the process does not exist or is not visible to the caller (a process is visible to the user who started it, and every process to Jira administrators).

#### `GET /rest/structure/2.0/projects-picker`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Case-insensitive literal substring of project name or key. Blank or omitted: all. |
| `maxResults` | query | integer |  | Total number of items to show; positive values are capped at 20; missing, zero or negative means 20. |
| `applyLimit` | query | boolean | `true` | Default true. false: no limit at all (every matching project is returned). |

Search box backend for picking Jira projects in which the app is enabled and which the caller can view. Results are split into 'Recent Projects' (from the caller's Jira project history) and 'All Projects' (the rest). Read-only.

**Response.** 200 with a [`picker-search-result`](#shape-picker-search-result). The recent group (if any match) gets up to the limit; the all group gets the limit minus the number of matching recent projects (omitted if that is not positive or nothing remains). Both sorted by project name in the caller's locale. Item `value`/`id` is the project id (decimal string), `label` the project name, `icon` the small project avatar URL, `html` 'Name (KEY)' HTML-escaped with the first match wrapped in `<b>`. Each group always has a localized label and a 'Showing N of M matching projects' footer.

**Errors.** 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/query/validate`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `q` | query | string |  | The query text. Leading/trailing problem characters are sanitized first. |
| `type` | query | string |  | `jql` (Jira query, validated by Jira for the caller), `sjql` (the app's structure query language, parsed only) or `text` (plain text search, turned into a Jira text query). |

Checks a query for syntax and semantic errors before it is used in a query-based feature. Read-only.

**Response.** 200 with a [`query-check-result`](#shape-query-check-result): `errors` is null when the query is valid; otherwise a list of localized messages. A blank query or an unknown `type` is reported this way too (one message), not as an HTTP error.

**Errors.** 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/saved-column`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

Returns all saved-column lists visible to the caller: first the bundled list (read-only preset columns shipped with the app, source `bundled`, list `bundled`), then the stored lists of source `stored`: `global` (shared columns) and `user` (the caller's own columns; empty for anonymous). Read-only.

**Response.** 200 with a JSON array of [`saved-column-list`](#shape-saved-column-list): bundled, then global, then user.

**Errors.** 403 with a [`structure-error`](#shape-structure-error) (or the generic access 403) when the caller may not use the app.

#### `PUT /rest/structure/2.0/saved-column/{columnSource}/{id}`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `columnSource` | path | string |  | `stored` (the bundled source cannot be changed). |
| `id` | path | integer |  | Saved column id (integer). |
| (body) | body | [`saved-column-input`](#shape-saved-column-input) |  | A [`saved-column-input`](#shape-saved-column-input). |

Replaces all properties of a stored saved column (name, description, type and parameters; absent fields become null, absent parameters become an empty object). The caller must own the column (user column) or hold the 'manage global saved columns' app permission (global column). Not available while the app license is invalid (read-only mode). Persisted in the SAVED_COLUMN table.

**Response.** 200 with a [`empty-ok`](#shape-empty-ok).

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when the source is unknown. 404 (same form) when the column does not exist or belongs to another user. 403 (same form) when a global column is changed without the permission, an anonymous caller changes a user column, or the caller may not use the app. 500 for the bundled source or in license read-only mode. 401 when not logged in.

#### `DELETE /rest/structure/2.0/saved-column/{columnSource}/{id}`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `columnSource` | path | string |  | `stored`. |
| `id` | path | integer |  | Saved column id. |

Deletes a stored saved column. Same ownership/permission rules as PUT. Views that used it keep their own copy of the column configuration.

**Response.** 200 with a [`empty-ok`](#shape-empty-ok).

**Errors.** 400 text/plain (localized 'column not found') when the column does not exist or belongs to another user. 500 text/plain carrying the message for every other failure, including an unknown source, missing permission for a global column and license read-only mode; 500 also for the bundled source. 401 when not logged in.

#### `POST /rest/structure/2.0/saved-column/{columnSource}/{id}/edit`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `columnSource` | path | string |  | `stored`. |
| `id` | path | integer |  | Saved column id. |
| (body) | body | [`saved-column-input`](#shape-saved-column-input) |  | A [`saved-column-input`](#shape-saved-column-input); only `name` and `description` are used. |

Changes only the name and/or description of a stored saved column; type and parameters stay. Fields that are null or absent are left unchanged. Same permission rules as PUT.

**Response.** 200 with a [`empty-ok`](#shape-empty-ok).

**Errors.** 400 text/plain (localized) when the column does not exist or is not readable by the caller (another user's column). 400 with a [`structure-error`](#shape-structure-error) for an unknown source. 403 (same form) when editing a global column without the permission or when the caller may not use the app. 500 in license read-only mode or for the bundled source. 401 when not logged in.

#### `POST /rest/structure/2.0/saved-column/{columnSource}/{id}/move/{newListKey}`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `columnSource` | path | string |  | `stored`. |
| `id` | path | integer |  | Saved column id. |
| `newListKey` | path | string |  | Target list; only `global` is accepted. |
| (body) | body | map<string, any> |  | Any JSON object (for example `{}`); ignored, present only so the request is a non-simple POST. |

Moves a user's own saved column into the global list (it loses its owner and becomes shared). Only the move to `global` exists; it requires that the caller owns the column and holds the 'manage global saved columns' app permission. Not available in license read-only mode.

**Response.** 200 with a [`empty-ok`](#shape-empty-ok).

**Errors.** 400 text/plain (localized messages joined by '. ') when the source is unknown or bundled, the column does not exist, is already global, belongs to another user, the target is not `global`, or the caller lacks the permission. 500 in license read-only mode. 401 when not logged in.

#### `POST /rest/structure/2.0/saved-column/{columnSource}/{id}/updateParameters`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `columnSource` | path | string |  | `stored`. |
| `id` | path | integer |  | Saved column id. |
| (body) | body | [`saved-column-input`](#shape-saved-column-input) |  | A [`saved-column-input`](#shape-saved-column-input); only `parameters` is used. |

Replaces only the parameters of a stored saved column; name, description and type stay. A missing `parameters` clears them to an empty object. Same permission rules as PUT.

**Response.** 200 with a [`empty-ok`](#shape-empty-ok).

**Errors.** Same as POST .../edit.

#### `GET /rest/structure/2.0/saved-column/{columnSource}/{listKey}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `columnSource` | path | string |  | `bundled` or `stored`. |
| `listKey` | path | string |  | `bundled` (for source `bundled`), `global` or `user` (for source `stored`). |

Returns one saved-column list. Read-only.

**Response.** 200 with a [`saved-column-list`](#shape-saved-column-list).

**Errors.** 404 with no body when the source or list is unknown. 403 when the caller may not use the app.

#### `POST /rest/structure/2.0/saved-column/{columnSource}/{listKey}`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `columnSource` | path | string |  | `stored`. |
| `listKey` | path | string |  | `user` or `global`. |
| (body) | body | [`saved-column-input`](#shape-saved-column-input) |  | A [`saved-column-input`](#shape-saved-column-input) with the column's name, description, type and parameters. |

Saves a new column into a list: into `user` as a personal column of the caller, or into `global` as a shared column (requires the 'manage global saved columns' app permission). No validation of name, type or parameters. Not available in license read-only mode. Persisted in the SAVED_COLUMN table.

**Response.** 200 with the new [`saved-column`](#shape-saved-column).

**Errors.** 400 with a [`structure-error`](#shape-structure-error) for an unknown source or an unknown list key. 403 (same form) for `global` without the permission or when the caller may not use the app. 500 for the bundled source and in license read-only mode. 401 when not logged in.

#### `GET /rest/structure/2.0/structure`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `name` | query | string |  | Case-insensitive substring of the structure name; blank = all. |
| `limit` | query | integer |  | Page size, default 10, capped at 100 (configurable). |
| `page` | query | integer |  | 1-based page number; omitted = first page. |
| `permission` | query | string |  | Minimum permission level name (`NONE`, `VIEW`, `EDIT`, `AUTOMATE`, `ADMIN`, case-insensitive); levels below `VIEW` mean `VIEW`; default `VIEW`. |
| `withPermissions` | query | boolean |  | Include each structure's permission rules in the result. |
| `withOwner` | query | boolean |  | Include each structure's owner (only when the caller may browse users or is the owner). |
| `archived` | query | boolean |  | When `true`, archived structures are included. |
| `filterById` | query | boolean |  | When `true`, `name` also matches structures whose id contains the text, and a structure whose id equals the text is listed first. |
| `skip` | query | string |  | Structure ids to exclude, separated by `.`; non-numbers ignored. |

Searches the structures the caller can access with at least the requested permission, by name, returning one page. Rate-limited per user (anonymous callers share one bucket): a search while the same user's previous search is still running is refused with a retry hint of 1 s (a minimum interval between searches can be configured).

**Response.** 200 with a [`structure-summary-list`](#shape-structure-summary-list); it signals when more pages exist.

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when `permission` is not a known level name; 429 text/plain with `Retry-After` (seconds) when rate-limited. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/structure`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`structure-summary`](#shape-structure-summary) |  | [`structure-summary`](#shape-structure-summary) with the properties of the new structure (name, description, permissions, etc.; `id` is ignored). |

Creates a new structure from the given properties, owned by the caller. Requires the Structure app permission to create structures.

**Response.** 201 Created with a `Location` header (the relative URI `/<new id>` resolved by the REST framework) and the created [`structure-summary`](#shape-structure-summary) including permissions and owner.

**Errors.** 403 with a [`structure-error`](#shape-structure-error) (code 4006) when the caller may not create structures; 400 when the body is missing or invalid. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/structure/list`

Access: anonymous users allowed. Consumes: `application/json`, `application/x-www-form-urlencoded`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `anchorIssue` | query | integer |  | Issue id; when visible to the caller, structures containing it are listed and its project's default structure is used. |
| `forProject` | query | string |  | Jira project key whose default structure is included (takes precedence over the anchor issue's project). |

Returns the data for the structure selector shown next to an issue or in a project: recent, favourite and default structures (the project's default and the global default), and, for an anchor issue, the structures containing it with recently used ones first. Lists are truncated to slightly more than the display size.

**Response.** 200 with a [`structure-picker-list`](#shape-structure-picker-list).

**Errors.** 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `PUT /rest/structure/2.0/structure/recents`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | query | integer |  | Structure id. |

Records that the caller opened a structure, moving it to the front of the caller's recent structures. No permission check on the structure; a missing id does nothing.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) (`{}`).

**Errors.** 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/structure/{id}`

Access: anonymous users allowed. Consumes: `application/json`, `application/x-www-form-urlencoded`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Structure id (positive). |
| `withPermissions` | query | boolean |  | Include the permission rules. |
| `withOwner` | query | boolean |  | Include the owner (only when the caller may browse users or is the owner). |

Returns one structure's properties (name, description and its rendered HTML, flags, the caller's permissions on generators/effectors, favourite flag) if the caller can view it.

**Response.** 200 with a [`structure-summary`](#shape-structure-summary).

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when the id is missing or not positive; 404 with a [`structure-error`](#shape-structure-error) when the structure does not exist or is not viewable. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `DELETE /rest/structure/2.0/structure/{id}`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Structure id. |

Deletes a structure together with its forest, change history and index entries. Requires administer permission on the structure and a writable licence.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) (`{}`).

**Errors.** 400 when the id is missing or not positive; 404 with a [`structure-error`](#shape-structure-error) when the structure is not viewable; 403 with a [`structure-error`](#shape-structure-error) when the caller can view but not administer it. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/structure/{id}/description-shown`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Structure id. |

Tells whether the structure is configured to show its description above the grid.

**Response.** 200 with a [`structure-description-shown-flag`](#shape-structure-description-shown-flag) (false when never set).

**Errors.** 403 text/plain when the structure does not exist or is not viewable. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/structure/{id}/favorite`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Structure id. |

Tells whether the structure is one of the caller's favourites (always false for anonymous callers).

**Response.** 200 with a [`structure-favorite-flag`](#shape-structure-favorite-flag).

**Errors.** 403 text/plain when the structure does not exist or is not viewable. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `PUT /rest/structure/2.0/structure/{id}/favorite`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Structure id. |
| (body) | body | [`structure-favorite-flag`](#shape-structure-favorite-flag) |  | [`structure-favorite-flag`](#shape-structure-favorite-flag) with the wanted state. |

Adds the structure to, or removes it from, the caller's favourites. For anonymous callers nothing is stored and the answer is `false`.

**Response.** 200 with a [`structure-favorite-flag`](#shape-structure-favorite-flag): the request echoed back (or `false` for anonymous).

**Errors.** 403 text/plain when the structure does not exist or is not viewable. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/structure/{id}/quick-transforms`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Structure id. |

Returns the structure's configured quick transformations (the preset transformation buttons and groups shown above the grid).

**Response.** 200 with the stored JSON array of [`quick-transform-entry`](#shape-quick-transform-entry) returned verbatim (`[]` when none).

**Errors.** 403 text/plain when the structure does not exist or is not viewable. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `PUT /rest/structure/2.0/structure/{id}/quick-transforms`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Structure id. |
| (body) | body | string |  | JSON array of [`quick-transform-entry`](#shape-quick-transform-entry); every item id, including ids of transformations inside groups, must be unique. |

Replaces the structure's quick transformations. Requires administer permission on the structure.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) (`{}`).

**Errors.** 403 text/plain when the structure does not exist or the caller cannot administer it; 400 with a [`structure-error`](#shape-structure-error) when the body is missing, unparsable or has duplicate ids. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/structure/{id}/update`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `id` | path | integer |  | Structure id. |
| (body) | body | [`structure-summary`](#shape-structure-summary) |  | [`structure-summary`](#shape-structure-summary) with the properties to change. |

Changes a structure's properties; properties absent from the body are kept. Requires administer permission. Setting `isArchived` to true on an active structure also disables its synchronizers. The owner can be changed (value `user:<key>` or a bare user key) only by Jira administrators, or by users with the user-picker permission who administer the structure or own it; an unknown user is ignored (logged).

**Response.** 200 with the updated [`structure-summary`](#shape-structure-summary) including permissions and owner.

**Errors.** 400 when the body is missing or invalid; 404 or 403 with a [`structure-error`](#shape-structure-error) when the structure is not visible or not administrable. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/structureWelcome/search`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Case-insensitive literal substring of the structure name. Blank or omitted: recent structures. |

Structure finder on the app's welcome page. Without a query it returns the caller's recently opened structures; with a query, the structures the caller can view whose name contains the text. At most 10 are returned. Requires a logged-in user. Read-only.

**Response.** 200 with a JSON object: `result`, array of at most 10 [`structure-summary`](#shape-structure-summary) whose `name` is HTML (HTML-escaped; for a query, the first match wrapped in `<b>`), and `total`, the number of recent structures or of all matching structures before the cut.

**Errors.** 401 when not logged in; 403 when the caller may not use the app.

#### `POST /rest/structure/2.0/synchronizers/undo`

Access: logged-in user. Consumes: any. Produces: any.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`synchronizer-undo-batch`](#shape-synchronizer-undo-batch) |  | [`synchronizer-undo-batch`](#shape-synchronizer-undo-batch): `actionGroups[i]` is a JSON-array text of audit-log action objects and `syncModuleKeys[i]` the complete module key of the synchronizer that performed them (paired by index). |

Undoes groups of actions previously performed by synchronizers (as recorded in the synchronizer audit log), processing the groups last to first. Only synchronizers that support undo do anything (the links synchronizer recreates or removes issue links; the agile synchronizer reverts epic and rank changes); for others a failure description is returned. The undo is performed as the caller and recorded in the synchronizer audit log. Logged-in users only; there is no structure or synchronizer permission check, and the undo operations use Jira's managers directly, so Jira permissions such as 'link issues' are not checked. Runs as a server job: when the result is not ready within the asynchronous wait (3 s by default, configurable) the call answers 200 with only [`async-job-ticket`](#shape-async-job-ticket) (`{"jobId": n}`) instead; the client repeats the call with that `jobId` in the body (other fields are then ignored) until the real response arrives. An unknown or finished-and-collected `jobId` gives 404 with a [`structure-error`](#shape-structure-error) (code 4603); a `jobId` of another kind of job gives 400.

**Response.** 200 with a [`synchronizer-undo-batch`](#shape-synchronizer-undo-batch): `syncModuleKeys` echoed, `actionGroups` holding, for each input group in reverse order, the JSON-array text of the resulting undo actions or failure descriptions (`result`: `failure`, optional `reason`, optional `exception`).

**Errors.** 401 for anonymous callers. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `GET /rest/structure/2.0/tempo/accounts`

Access: anonymous users allowed. Consumes: any. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Search text, passed to Tempo's account search. |
| `limit` | query | integer |  | Maximum number of accounts, passed to Tempo; omitted means Tempo's default. |
| `ids` | query | string |  | Comma-separated numeric account ids to restrict the search to. Omitted: no restriction. |

Searches Tempo accounts through the Tempo Accounts add-on installed in the same Jira (an in-process call, no external server). Open and closed accounts are included; archived accounts are included unless an instance property says to skip them. Read-only.

**Response.** 200 with a JSON object: `options`, array of [`tempo-account-option`](#shape-tempo-account-option), and `total`, the total number of matching accounts reported by Tempo. When Tempo Accounts is absent or fails: `options` empty and `total` 0.

**Errors.** 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/tempo/roles`

Access: anonymous users allowed. Consumes: any. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Case-insensitive substring of the role name (trimmed). Blank: all roles. |
| `limit` | query | integer |  | Maximum number returned; missing, 0 or above Jira's 'stable search max results' setting means that setting. |
| `ids` | query | string |  | Comma-separated numeric role ids to keep. A non-numeric id makes the whole result empty. |

Lists Tempo team roles through the Tempo Teams add-on installed in the same Jira (in-process, no external server). Read-only.

**Response.** 200 with a JSON object: `options`, array of [`tempo-team-role-option`](#shape-tempo-team-role-option) (first `limit` matches in Tempo's order), and `total`, the number of matches before the limit. Empty with `total` 0 when Tempo Teams is absent or fails.

**Errors.** 403 when the caller may not use the app.

#### `GET /rest/structure/2.0/tempo/teams`

Access: anonymous users allowed. Consumes: any. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `query` | query | string |  | Team search text, passed to Tempo. |
| `limit` | query | integer |  | Maximum number returned; missing, 0 or above Jira's 'stable search max results' setting means that setting. |
| `ids` | query | string |  | Comma-separated numeric team ids to keep. A non-numeric id makes the whole result empty. |

Searches Tempo teams through the Tempo Teams add-on installed in the same Jira (in-process, no external server); Tempo applies its own search and visibility rules. Read-only.

**Response.** 200 with a JSON object: `options`, array of [`tempo-team-option`](#shape-tempo-team-option), and `total`, the number of matches before the limit. Empty with `total` 0 when Tempo Teams is absent or fails.

**Errors.** 403 when the caller may not use the app.

#### `POST /rest/structure/2.0/value`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`row-values-request`](#shape-row-values-request) |  | [`row-values-request`](#shape-row-values-request). |

Computes attribute values (column data) for given rows of one or more forests in one shot, without a subscription. Rows whose item no longer exists or is not visible to the caller get no values and are listed as inaccessible. Runs as a server job: when the result is not ready within the asynchronous wait (3 s by default, configurable) the call answers 200 with only [`async-job-ticket`](#shape-async-job-ticket) (`{"jobId": n}`) instead; the client repeats the call with that `jobId` in the body (other fields are then ignored) until the real response arrives. An unknown or finished-and-collected `jobId` gives 404 with a [`structure-error`](#shape-structure-error) (code 4603); a `jobId` of another kind of job gives 400.

**Request.** `requests` is required; each entry needs a valid `forestSpec`; entries without rows or attributes produce an entry with only the spec. Attribute specs with unknown formats are dropped.

**Response.** 200 with a [`row-values-response`](#shape-row-values-response) with one entry per request entry, in order.

**Errors.** 400 with a [`structure-error`](#shape-structure-error) when a forest spec is invalid. Failures raised by Structure are answered with a [`structure-error`](#shape-structure-error) body and a status from the error category: 404 not found or not accessible, 403 no permission, 400 invalid input, 500 otherwise. Malformed JSON gives 400 with a [`structure-error`](#shape-structure-error) whose `error` is a parse-failure text; invalid request data gives 400 with `error` = `Invalid request data` and `message` = the reason; 503 (text) while Structure is stopped. 403 text/plain `permission violation` when the caller is not allowed to use Structure (plugin-wide user restriction); 401 when the query string carries `loggedIn=true` and the caller is anonymous.

#### `POST /rest/structure/2.0/wiki-markup/render`

Access: logged-in user. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | map<string, string> |  | JSON object mapping caller-chosen keys to wiki-markup strings. |

Renders several Jira wiki-markup texts to HTML in one call, with Jira's wiki renderer (no issue context). If the wiki renderer is not available, or returns nothing for a value, the value is returned HTML-escaped instead. Requires a logged-in user. No side effects.

**Response.** 200 with a JSON object with the same keys (same order), each mapped to the rendered HTML string.

**Errors.** 401 when not logged in; 403 when the caller may not use the app. 400 with a [`structure-error`](#shape-structure-error) when the body is not a JSON object of strings.

### Module `rest-cfd`

#### `POST /rest/cfd/1.0/gadget/meta`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`cfd-gadget-settings`](#shape-cfd-gadget-settings) |  | [`cfd-gadget-settings`](#shape-cfd-gadget-settings). |

Validates a predictive-CFD gadget configuration and returns what the gadget needs to render: the current user and the scope and training structures (if viewable by the caller). When the feature is disabled, only a general error is returned. The predictive cumulative-flow (CFD) feature can be switched off by the system property `structure.pcfd.enabled=false` (on by default). These endpoints are not behind the plugin's common access gate.

**Request.** Checks: both structures viewable; `trainingPeriod` one of -1, 7, 14, 21, 28, 42, 56; `teamAttributeSpec` and `whenCompletedAttributeSpec` present; `targetDate` (if given) in `YYYY-MM-DD` form; `ignoreThreshold` (if given) 0 to 100; `estimationIssueTypes` and `scopeIssueTypes` non-empty lists of existing issue type ids that do not overlap. `adjustments` is not checked.

**Response.** 200 with [`cfd-gadget-meta`](#shape-cfd-gadget-meta); problems are listed in `errors` as field errors keyed by the request key (localized messages), the reply status stays 200.

**Errors.** None of its own; a malformed JSON body is not translated by the plugin and gets the platform's generic error reply.

#### `GET /rest/cfd/1.0/gadget/status`

Access: anonymous users allowed. Consumes: any. Produces: `application/json`.

Tells whether the predictive-CFD feature is enabled on this instance. The predictive cumulative-flow (CFD) feature can be switched off by the system property `structure.pcfd.enabled=false` (on by default). These endpoints are not behind the plugin's common access gate.

**Response.** 200 with [`cfd-feature-status`](#shape-cfd-feature-status).

**Errors.** None.

#### `GET /rest/cfd/1.0/gadget/validate`

Access: anonymous users allowed. Consumes: any. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| `scopeStructureId` | query | integer |  | Structure id holding the work to forecast. |
| `trainingStructureId` | query | integer |  | Structure id holding historical work used to learn throughput. |
| `trainingPeriod` | query | integer |  | History window in days: 7, 14, 21, 28, 42 or 56, or -1 for all history. |
| `estimationIssueTypes` | query | array<string> |  | Repeatable; issue type ids of the container items (e.g. epics) whose size is estimated from history. |
| `scopeIssueTypes` | query | array<string> |  | Repeatable; issue type ids of the work items (e.g. stories) that are counted. |
| `teamAttributeSpec` | query | string |  | JSON text of an attribute spec giving each item's team; unparseable JSON counts as absent. |
| `targetDate` | query | string |  | Delivery target date `YYYY-MM-DD`. |
| `whenAppearedAttributeSpec` | query | string |  | JSON attribute spec giving when an item appeared. |
| `whenWorkStartedAttributeSpec` | query | string |  | JSON attribute spec giving when work on an item started. |
| `whenCompletedAttributeSpec` | query | string |  | JSON attribute spec giving when an item was completed. Required. |
| `ignoreThreshold` | query | integer |  | Percentage 0 to 100 (see simulation). |

Same validation as the POST meta call, taking the settings as query parameters, and answering only with the errors. The predictive cumulative-flow (CFD) feature can be switched off by the system property `structure.pcfd.enabled=false` (on by default). These endpoints are not behind the plugin's common access gate.

**Response.** 200 with [`empty-ok`](#shape-empty-ok) when valid. When the feature is disabled the reply is 400 with the 'not enabled' general error.

**Errors.** 400 with [`validation-errors`](#shape-validation-errors) (localized messages, field errors keyed by parameter name).

#### `POST /rest/cfd/1.0/simulation/cfd`

Access: anonymous users allowed. Consumes: `application/json`. Produces: `application/json`.

| parameter | in | type | default | meaning |
|---|---|---|---|---|
| (body) | body | [`cfd-simulation-request`](#shape-cfd-simulation-request) |  | [`cfd-simulation-request`](#shape-cfd-simulation-request). |

Runs a Monte Carlo forecast of when the work in the scope structure will be finished, per team and overall, and returns the cumulative-flow chart (past plus simulated future) and per-team statistics. Throughput per team is learned from items completed in the training structure within the training period; containers without enough child items get extra predicted items based on the historical average per container. Per-team percentage adjustments and an ignore threshold (teams whose share of the total item count is at most that percentage are not simulated and are lumped together as `Other` when there are several) shape the result. Items without a team value belong to team `No Team`. The reply includes a human-readable calculation trace unless the system property `structure.cfd.disableTracing` is on. Read-only; dates use the caller's Jira time zone. The predictive cumulative-flow (CFD) feature can be switched off by the system property `structure.pcfd.enabled=false` (on by default). These endpoints are not behind the plugin's common access gate.

**Request.** `scopeStructureId`, `trainingStructureId` and `config` (with both issue type lists) are required. `simulations` defaults to 50 runs.

**Response.** 200 with [`cfd-forecast-result`](#shape-cfd-forecast-result).

**Errors.** Missing required input or a disabled feature raise errors that this module does not translate (no plugin exception mapper is installed for it): expect the platform's generic error response, normally status 500. A `targetDate` not in `YYYY-MM-DD` form fails the same way.
<!-- END generated: rest-endpoints -->

### 1.3.2 JSON shapes

The JSON objects the endpoints read and write. A shape lists every key the original writes; a request may
omit keys, as described per endpoint.

<!-- BEGIN generated: rest-shapes -->
<a id="shape-about-companion-addon"></a>

#### Shape `about-companion-addon`

Status of one companion add-on in the about popup.

| key | JSON type | meaning |
|---|---|---|
| `key` | string | Plugin key, e.g. `com.almworks.structure.gantt`. |
| `name` | string | Product name: `Structure.Gantt`, `Structure.Pages`, `Structure.Deliver` or `Structure.Testy`. |
| `version` | string | Installed version, or null when the add-on is not installed and enabled. |
| `licenseInfo` | [`about-license-summary`](#shape-about-license-summary) | The add-on's license summary when the add-on is installed, registered with the app and the caller is logged in; null otherwise (always null for Testy). |
| `updateAvailable` | boolean | Whether the Marketplace offers a newer version. Always false in the replacement (no Marketplace access). |
| `links` | [`about-companion-links`](#shape-about-companion-links) | Static links to the vendor's documentation for this add-on. |

<a id="shape-about-companion-links"></a>

#### Shape `about-companion-links`

Fixed documentation links shown for a companion add-on (static strings pointing to the vendor's public site; the server does not fetch them).

| key | JSON type | meaning |
|---|---|---|
| `gettingStarted` | string | URL of the getting-started guide. |
| `documentation` | string | URL of the product documentation. |
| `tryIt` | string | URL of a demo or trial page; null for Deliver. |

<a id="shape-about-license-summary"></a>

#### Shape `about-license-summary`

Short license description for the about popup.

| key | JSON type | meaning |
|---|---|---|
| `licenseSEN` | string | Support entitlement number (serial) of the license; null when unlicensed. |
| `unlicensed` | boolean | true when there is no usable license (license disabled); then `licenseSEN` is null. |

<a id="shape-about-popup-data"></a>

#### Shape `about-popup-data`

Content of the app's about popup.

| key | JSON type | meaning |
|---|---|---|
| `structureVersion` | string | Installed version of the app (plugin version string). |
| `structureUpdateAvailable` | boolean | Whether a newer compatible version exists on the Marketplace. The replacement never contacts the Marketplace and always reports false. |
| `structureLicenseInfo` | [`about-license-summary`](#shape-about-license-summary) | The app's license summary; null for anonymous callers or when no license applies. |
| `jiraClusterNodeId` | string | Id of the Jira cluster node that served the request; null on a non-clustered Jira. |
| `plugins` | array<[`about-companion-addon`](#shape-about-companion-addon)> | Companion add-ons (Gantt, Pages, Deliver, Testy), always these four in this order. |

<a id="shape-access-level"></a>

#### Shape `access-level`

Access level on a structure or view; each level includes the ones below it. In JSON request fields the names are accepted case-insensitively and are usually written in lowercase.

A JSON string, one of:

| value | meaning |
|---|---|
| `NONE` | No access. |
| `VIEW` | May see it. |
| `EDIT` | May change its content (or a view's columns). |
| `EDIT_GENERATORS` | Deprecated name with the same rank as automate. |
| `AUTOMATE` | May edit and configure automation. |
| `ADMIN` | Full control, including permissions and deletion. |

<a id="shape-access-rule"></a>

#### Shape `access-rule`

One permission rule of a structure or view. Rules are evaluated in order; later rules override earlier ones.

| key | JSON type | meaning |
|---|---|---|
| `subject` | string | For `set` rules: `anyone`, `user`, `group` or `projectRole` (case-insensitive). |
| `groupId` | string | Group name, for subject `group`. |
| `projectId` | integer | Project id, for subject `projectRole`. |
| `roleId` | integer | Project role id, for subject `projectRole`. |
| `userKey` | string | Jira user key, for subject `user`. |
| `rule` | string | `set` (give the subject a level) or `apply` (inherit the rules of another structure). Required. |
| `structureId` | integer | For `apply`: the structure whose rules are applied. |
| `level` | string | For `set`: `none`, `view`, `edit`, `automate` or `admin` (lowercase on output). |
| `error` | string | Output only: set when a stored rule could not be represented. |

<a id="shape-app-permission-setting"></a>

#### Shape `app-permission-setting`

Who holds one app-level permission. A user holds it when `allowedForAnyone` is true or the user matches one of the subjects.

| key | JSON type | meaning |
|---|---|---|
| `allowedForAnyone` | boolean | true: every user (including anonymous where applicable) has the permission. Always set in responses; in requests null/absent means 'leave unchanged'. |
| `subjects` | array<[`permission-subject`](#shape-permission-subject)> | Users, groups or project roles granted the permission, as [`permission-subject`](#shape-permission-subject). Always set in responses (possibly empty); in requests absent means 'leave unchanged' and a value replaces the whole list. |

<a id="shape-app-project-scope"></a>

#### Shape `app-project-scope`

Where the app is enabled: all projects, or a list of picked projects.

| key | JSON type | meaning |
|---|---|---|
| `enabledForAllProjects` | boolean | true: the app is enabled in every project and the picked list is ignored. In requests null/absent means unchanged. |
| `pickedProjectIds` | array<integer> | Jira project ids of the projects explicitly enabled (used when the flag is false). In requests null/absent means unchanged; a value replaces the list. |

<a id="shape-applied-effect"></a>

#### Shape `applied-effect`

One change made outside the forest as a consequence of a grid action (e.g. a field updated or a link created by a generator).

| key | JSON type | meaning |
|---|---|---|
| `generatorRowId` | integer | Row id of the generator that caused it. |
| `external` | boolean | True when the change was made in Jira data (outside Structure). |
| `description` | string | Human-readable description. |
| `reversible` | boolean | True when it can be undone. |

<a id="shape-applied-effect-batch"></a>

#### Shape `applied-effect-batch`

A group of effects applied together; the unit of undo/redo.

| key | JSON type | meaning |
|---|---|---|
| `batchId` | integer | Batch id, to be passed in `effectIds` of an undo/redo request. |
| `effects` | array<[`applied-effect`](#shape-applied-effect)> | The effects in the batch. |

<a id="shape-async-job-ticket"></a>

#### Shape `async-job-ticket`

Handle of a long-running server computation. Sent in a request to resume waiting for an earlier job, and returned when the computation did not finish within the wait time.

| key | JSON type | meaning |
|---|---|---|
| `jobId` | integer | Server-side job id (integer, unique while the app runs). Null or absent in a request means 'start a new job'. Jobs are kept in memory only; an id becomes unknown once its result has been delivered or the app restarted. |

<a id="shape-attribute-sensitivity-settings"></a>

#### Shape `attribute-sensitivity-settings`

Instance-wide policy for whether attribute values may reveal data from items the viewer cannot see.

| key | JSON type | meaning |
|---|---|---|
| `sensitivityMode` | integer | 0 = standard (attributes are sensitive except numbers, booleans, times, durations and the listed ones), 1 = strict (all attributes sensitive except the listed ones), 2 = permissive (no attribute is sensitive; the list is ignored). |
| `nonSensitiveAttributeSpecs` | array<[`attribute-spec`](#shape-attribute-spec)> | Attributes explicitly declared non-sensitive; sorted by id on output. |

<a id="shape-attribute-spec"></a>

#### Shape `attribute-spec`

Identifies one attribute (a column value kind) together with the format in which its values are wanted. Two specs are equal when id, format and params are equal.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Attribute id, e.g. `summary`, `key`, `status`, `duedate`, `created`, `item`, or an id understood by an installed attribute provider (formulas, aggregates, ...). |
| `params` | map<any, any> | Optional JSON object of attribute parameters (may nest other attribute specs, e.g. for totals); null/absent when none. |
| `format` | string | Value format, one of `text`, `html`, `id`, `number`, `boolean`, `time` (milliseconds since the epoch), `duration` (milliseconds), `json` (object), `jsonArray`, `any`. Any other value is rejected (or the spec dropped where noted). |

<a id="shape-attribute-subscription"></a>

#### Shape `attribute-subscription`

An attribute subscription and optionally its value update.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Subscription id. |
| `window` | [`attribute-subscription-window`](#shape-attribute-subscription-window) | The window as currently stored. |
| `valuesUpdate` | [`attribute-subscription-update`](#shape-attribute-subscription-update) | Present only when `valuesUpdate=true` was requested. |

<a id="shape-attribute-subscription-error"></a>

#### Shape `attribute-subscription-error`

A problem loading an attribute.

| key | JSON type | meaning |
|---|---|---|
| `attribute` | [`attribute-spec`](#shape-attribute-spec) | The attribute. |
| `error` | [`structure-error`](#shape-structure-error) | Error details: code 6016, `error` and `message` = the cause's message (or a generic text), plus `rowId` and `itemId` of the item being computed when known. |

<a id="shape-attribute-subscription-poll-entry"></a>

#### Shape `attribute-subscription-poll-entry`

A subscription to update in a poll.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Subscription id (required). |
| `version` | [`data-version`](#shape-data-version) | Values version the client holds (required); `{0,0}` = full update. |

<a id="shape-attribute-subscription-update"></a>

#### Shape `attribute-subscription-update`

Changed attribute values of a subscription since a version.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Subscription id. |
| `full` | boolean | True when the update contains all values (the client must discard what it had), false when only changes since `fromVersion`. |
| `fromVersion` | [`data-version`](#shape-data-version) | The version the update starts from (as requested). |
| `version` | [`data-version`](#shape-data-version) | The values version after applying this update; send it next time. |
| `data` | array<[`attribute-subscription-values`](#shape-attribute-subscription-values)> | Values per attribute. |
| `inaccessibleRows` | array<integer> | Rows of the window whose items the caller cannot see; absent when none. |
| `error` | [`structure-error`](#shape-structure-error) | Present when the subscription could not be read (e.g. code 4800 unknown subscription). |
| `attributeErrors` | array<[`attribute-subscription-error`](#shape-attribute-subscription-error)> | Attribute loading problems collected since the last call (each reported once); absent when none. |
| `stillLoading` | boolean | True when value loading had not finished when the answer was produced; absent otherwise. |

<a id="shape-attribute-subscription-values"></a>

#### Shape `attribute-subscription-values`

Values of one attribute.

| key | JSON type | meaning |
|---|---|---|
| `attribute` | [`attribute-spec`](#shape-attribute-spec) | The attribute spec. |
| `values` | map<string, any> | JSON object from row id (decimal string) to the value encoded per the attribute format; null for no value. Only rows whose value changed (or all, in a full update). |
| `emptyValueRows` | array<integer> | Not used on Jira 9 (absent). |
| `outdated` | array<integer> | Rows whose value is a stale one being recalculated; absent when none. |

<a id="shape-attribute-subscription-window"></a>

#### Shape `attribute-subscription-window`

What a subscription watches: some rows of a forest and some attributes.

| key | JSON type | meaning |
|---|---|---|
| `forestSpec` | [`forest-spec`](#shape-forest-spec) | The forest. |
| `rows` | array<integer> | Row ids (typically the rows visible in the grid). |
| `attributes` | array<[`attribute-spec`](#shape-attribute-spec)> | Attributes to compute; specs with unknown formats are dropped. |

<a id="shape-automation-catalog"></a>

#### Shape `automation-catalog`

Available automation modules and the caller's rights to configure them.

| key | JSON type | meaning |
|---|---|---|
| `generators` | array<[`generator-module-info`](#shape-generator-module-info)> | Available generator modules. |
| `effectors` | array<[`effector-module-info`](#shape-effector-module-info)> | Available effector modules. |
| `generatorConfigurationAllowed` | boolean | True when the caller holds the app permission to configure generators. |
| `effectorConfigurationAllowed` | boolean | True when the caller holds the app permission to configure effectors. |

<a id="shape-background-effector-process"></a>

#### Shape `background-effector-process`

An effector process of the caller that is running or finished but not yet acknowledged, shown in the grid's background-process panel.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Effector process id. |
| `titleHtml` | string | Process name as HTML. |
| `statusHtml` | string | Status as an HTML badge. |
| `percentComplete` | integer | 0..100; absent when unknown. |
| `linkText` | string | Localized label of the 'open' link. |
| `linkUrl` | string | Absolute URL `<base>/secure/StructureBoard.jspa[?s=<structure id>]#effectorProcessDialog=<process id>` opening the process dialog. |
| `finished` | boolean | True when the status is completed, completed with errors, interrupted or stopped. |

<a id="shape-background-process-button"></a>

#### Shape `background-process-button`

A button offered by a background process.

| key | JSON type | meaning |
|---|---|---|
| `url` | string | Link target. |
| `caption` | string | Localized label. |

<a id="shape-background-process-info"></a>

#### Shape `background-process-info`

Display state of a background process.

| key | JSON type | meaning |
|---|---|---|
| `name` | string | Localized process name; null when not set. |
| `buttons` | array<[`background-process-button`](#shape-background-process-button)> | Extra action buttons; absent when none. |
| `status` | integer | 0 = pending, 1 = running, 2 = finished. |
| `statusText` | string | Localized status. |
| `activity` | string | Localized description of the current activity; null when none. |
| `percentComplete` | integer | 0..100; absent when unknown. |
| `percentText` | string | Localized percentage text; absent when unknown. |

<a id="shape-cfd-chart-series"></a>

#### Shape `cfd-chart-series`

One cumulative-flow chart: item counts per workflow state over time.

| key | JSON type | meaning |
|---|---|---|
| `timestamps` | array<integer> | Chart time points, epoch milliseconds, ascending. |
| `dateNames` | array<string> | The same time points as `YYYY-MM-DD` dates in the caller's time zone, same order. |
| `series` | map<string, array<integer>> | Map from state (`todo`, `inProgress`, `done`) to item counts, one per time point. |

<a id="shape-cfd-feature-status"></a>

#### Shape `cfd-feature-status`

Whether the predictive-CFD feature is switched on.

| key | JSON type | meaning |
|---|---|---|
| `enabled` | boolean | True unless disabled by system property. |

<a id="shape-cfd-forecast-date"></a>

#### Shape `cfd-forecast-date`

A forecast completion moment with its spread.

| key | JSON type | meaning |
|---|---|---|
| `mean` | integer | Expected completion time, epoch milliseconds. |
| `deviation` | integer | Standard deviation of the completion time across simulation runs, in milliseconds. |

<a id="shape-cfd-forecast-result"></a>

#### Shape `cfd-forecast-result`

Result of a predictive-CFD simulation.

| key | JSON type | meaning |
|---|---|---|
| `overallChart` | [`cfd-chart-series`](#shape-cfd-chart-series) | Cumulative flow of all teams together (past and simulated), with early time points that carry no activity cut off. |
| `completion` | [`cfd-forecast-date`](#shape-cfd-forecast-date) | Forecast completion of the whole scope: the latest completion among teams that have one. Absent if no team has a forecast. |
| `teamCharts` | map<string, [`cfd-chart-series`](#shape-cfd-chart-series)> | Cumulative flow per team name (teams with no data and no adjustment are left out; small teams may be merged into `Other`). |
| `teamStats` | map<string, [`cfd-team-forecast`](#shape-cfd-team-forecast)> | Per-team statistics keyed by team name. |
| `deliveryTargetDate` | integer | The configured target date at 09:00 in the caller's time zone, epoch ms; absent if none. |
| `trace` | string | Multi-line human-readable log of the calculation, for support; absent when tracing is disabled. |

<a id="shape-cfd-gadget-meta"></a>

#### Shape `cfd-gadget-meta`

Render data and validation result for the predictive-CFD gadget.

| key | JSON type | meaning |
|---|---|---|
| `loggedInUser` | [`user-display-info`](#shape-user-display-info) | The current user as shown in gadgets; absent when the feature is disabled. |
| `scopeStructure` | [`structure-summary`](#shape-structure-summary) | The scope structure if the caller can view it. |
| `trainingStructure` | [`structure-summary`](#shape-structure-summary) | The training structure if the caller can view it. |
| `teamAttributeName` | string | Reserved for the display name of the team attribute; never filled by the current implementation (always absent). |
| `errors` | [`validation-errors`](#shape-validation-errors) | Validation problems; absent when there are none. |

<a id="shape-cfd-gadget-settings"></a>

#### Shape `cfd-gadget-settings`

Saved settings of a predictive-CFD gadget, sent for validation.

| key | JSON type | meaning |
|---|---|---|
| `scopeStructureId` | integer | Structure id of the work to forecast. |
| `trainingStructureId` | integer | Structure id of the historical work used for learning. |
| `trainingPeriod` | integer | History window in days: 7, 14, 21, 28, 42, 56, or -1 / absent for all history. |
| `teamAttributeSpec` | [`attribute-spec`](#shape-attribute-spec) | Attribute whose value (as text) is an item's team; empty values mean team `No Team`. |
| `targetDate` | string | Optional delivery target date, `YYYY-MM-DD`. |
| `whenAppearedAttributeSpec` | [`attribute-spec`](#shape-attribute-spec) | Attribute giving the time (epoch ms) an item appeared. |
| `whenWorkStartedAttributeSpec` | [`attribute-spec`](#shape-attribute-spec) | Attribute giving the time (epoch ms) work on an item started. |
| `whenCompletedAttributeSpec` | [`attribute-spec`](#shape-attribute-spec) | Attribute giving the time (epoch ms) an item was completed. |
| `estimationIssueTypes` | array<string> | Issue type ids of container items (e.g. epics) whose eventual number of children is estimated. |
| `scopeIssueTypes` | array<string> | Issue type ids of the work items that are counted and simulated (e.g. stories). Must not overlap `estimationIssueTypes`. |
| `ignoreThreshold` | integer | Percentage 0 to 100; see simulation parameters. |
| `adjustments` | map<string, [`cfd-team-adjustment`](#shape-cfd-team-adjustment)> | Per-team adjustments keyed by team name; not validated. |

<a id="shape-cfd-hierarchy-settings"></a>

#### Shape `cfd-hierarchy-settings`

How the forecast reads the structures: which issue types are containers and work items and which attributes give team and lifecycle times.

| key | JSON type | meaning |
|---|---|---|
| `estimationIssueTypes` | array<string> | Issue type ids of container items (e.g. epics) whose eventual number of children is estimated. |
| `scopeIssueTypes` | array<string> | Issue type ids of the work items that are counted and simulated (e.g. stories). Must not overlap `estimationIssueTypes`. |
| `teamAttributeSpec` | [`attribute-spec`](#shape-attribute-spec) | Attribute whose value (as text) is an item's team; empty values mean team `No Team`. |
| `targetDate` | string | Optional delivery target date, `YYYY-MM-DD`. |
| `whenAppearedAttributeSpec` | [`attribute-spec`](#shape-attribute-spec) | Attribute giving the time (epoch ms) an item appeared. |
| `whenWorkStartedAttributeSpec` | [`attribute-spec`](#shape-attribute-spec) | Attribute giving the time (epoch ms) work on an item started. |
| `whenCompletedAttributeSpec` | [`attribute-spec`](#shape-attribute-spec) | Attribute giving the time (epoch ms) an item was completed. |
| `trainingPeriod` | integer | History window in days: 7, 14, 21, 28, 42, 56, or -1 / absent for all history. |

<a id="shape-cfd-simulation-request"></a>

#### Shape `cfd-simulation-request`

Input of a predictive-CFD simulation run.

| key | JSON type | meaning |
|---|---|---|
| `scopeStructureId` | integer | Structure id of the work to forecast. Required. |
| `trainingStructureId` | integer | Structure id of historical work. Required. |
| `config` | [`cfd-hierarchy-settings`](#shape-cfd-hierarchy-settings) | Hierarchy and attribute settings. Required. |
| `simulations` | integer | Number of Monte Carlo runs; default 50. |
| `ignoreThreshold` | integer | Percentage 0 to 100: teams whose item count is at most this share of the total are not simulated. 0 or absent: no team is ignored. |
| `adjustments` | map<string, [`cfd-team-adjustment`](#shape-cfd-team-adjustment)> | Per-team adjustments keyed by team name. |

<a id="shape-cfd-team-adjustment"></a>

#### Shape `cfd-team-adjustment`

Manual correction for one team in a forecast, keyed by team name in the enclosing map.

| key | JSON type | meaning |
|---|---|---|
| `throughput` | integer | Percentage change of the team's speed: positive makes the team faster (learned throughput is multiplied by 1 + value/100). Absent or 0: no change. |
| `predictedStories` | integer | Percentage change of the number of predicted (not yet created) work items for the team. Absent or 0: no change. |

<a id="shape-cfd-team-forecast"></a>

#### Shape `cfd-team-forecast`

Forecast statistics for one team.

| key | JSON type | meaning |
|---|---|---|
| `throughput` | number | Learned speed after adjustment, items per week (decimal); absent when not computable. |
| `throughputAdjustment` | integer | Applied speed adjustment in percent. |
| `throughputRaw` | number | Learned speed before adjustment, items per week. |
| `totalStories` | integer | Existing plus predicted work items still counted for the team. |
| `predictedStories` | integer | Number of predicted (not yet created) work items after adjustment. |
| `predictedStoriesAdjustment` | integer | Applied predicted-items adjustment in percent. |
| `predictedStoriesRaw` | integer | Number of predicted work items before adjustment. |
| `completion` | [`cfd-forecast-date`](#shape-cfd-forecast-date) | Forecast completion for the team; absent when it could not be predicted. |
| `predictionProblem` | string | Localized explanation (insufficient data) when no forecast could be made; absent otherwise. |
| `completed` | boolean | True when all the team's work was already done at simulation time. |
| `ignore` | boolean | True when the team fell under the ignore threshold. |

<a id="shape-create-item-request"></a>

#### Shape `create-item-request`

Request to create (or pick) an item and insert it as a row.

| key | JSON type | meaning |
|---|---|---|
| `jobId` | integer | Absent on the first call. Set to the `jobId` returned by an earlier call that timed out, to keep waiting for that job (see the endpoint). |
| `extensionRequests` | map<string, any> | Optional map from core-extension key to an extension-specific request; each installed extension may answer under the same key in `extensionData`. |
| `forest` | [`forest-poll-entry`](#shape-forest-poll-entry) | Forest to insert into and the client's version of it (required). |
| `items` | [`items-poll-entry`](#shape-items-poll-entry) | The client's items version (required); the response reports item changes since it. |
| `rowId` | integer | Temporary row id the client assigned to the new row (negative); reported back in `oldRowIds`. |
| `item` | [`item-content-spec`](#shape-item-content-spec) | The item: an existing `itemId`, or `type` and `values` for a new item. |
| `semantics` | integer | Row semantics number for the new row; 0/absent = none. |
| `under` | integer | Parent row; 0 = top level. |
| `after` | integer | Preceding sibling; 0 = none. |
| `before` | integer | Following sibling; 0 = none. |
| `parameters` | map<string, any> | Answers to earlier questions, e.g. `{"0:CreateAnyway": true}`; null = none. |

<a id="shape-create-item-response"></a>

#### Shape `create-item-response`

Result of creating and inserting an item.

| key | JSON type | meaning |
|---|---|---|
| `successfulActions` | integer | 1 when the row was inserted (or an existing generated row was used), otherwise 0. |
| `updateError` | [`forest-action-failure`](#shape-forest-action-failure) | Present when an action was refused or a question must be answered; absent on success. |
| `forestUpdates` | array<[`forest-update`](#shape-forest-update)> | Forest changes since the client's version(s), so the client can resynchronize. |
| `itemTypes` | map<any, any> | Map from the decimal item-type numbers used in this response's forest or item encodings to full item type keys (e.g. `"3": "com.almworks.jira.structure:type-folder"`). Only types that occur in this response are listed. |
| `oldRowIds` | array<integer> | The client's temporary row id (and other replaced ids), parallel to `newRowIds`. |
| `newRowIds` | array<integer> | The real row id of the inserted row (and other replacements). |
| `effects` | array<[`applied-effect-batch`](#shape-applied-effect-batch)> | Effect batches applied in Jira by this request. |
| `undoEffects` | array<integer> | Not filled in. |
| `problems` | array<[`effect-problem`](#shape-effect-problem)> | Effects that could not be applied. |
| `extensionData` | map<string, any> | Map from core-extension key to extension-specific data returned for the request's `extensionRequests`; absent or null when no extension answered. |
| `formErrors` | array<string> | Item validation messages not tied to a field; absent when none. |
| `fieldErrors` | map<string, string> | Item validation messages by field id; absent when none. |
| `itemId` | string | Full id of the created or inserted item (`<item type key>/<n>`, `<item type key>//<s>`, or bare issue id); absent when nothing was created. |
| `itemsUpdate` | [`items-update`](#shape-items-update) | Item changes since the client's items version. |

<a id="shape-data-version"></a>

#### Shape `data-version`

A position in a server-side change stream (of a forest, of items, of a subscription's values). A client remembers the last version it received and asks for changes since it.

| key | JSON type | meaning |
|---|---|---|
| `signature` | integer | 32-bit number identifying the change stream instance; when the server's signature differs from the client's (e.g. after a restart or cache reset), versions are not comparable and the server sends a full update. 0 = no data yet. |
| `version` | integer | Counter within the stream, increasing with each change. With signature 0, version 0 means 'from scratch'. |

<a id="shape-date-check-result"></a>

#### Shape `date-check-result`

Outcome of validating a user-entered date.

| key | JSON type | meaning |
|---|---|---|
| `isValid` | boolean | true when the text parsed as a date in the caller's date-picker format. |
| `resultDate` | string | When valid, the date in ISO 8601 form `yyyy-MM-dd`; otherwise null. |
| `error` | string | When invalid, the localized parser message; otherwise null. |

<a id="shape-date-style"></a>

#### Shape `date-style`

One date display style.

| key | JSON type | meaning |
|---|---|---|
| `style` | string | Style id: `date-short`, `date-long`, `date-full`, `datetime-short`, `datetime-long`, `jira-date` or `jira-datetime` (the last two follow Jira's own date formats). |
| `sample` | string | The current moment rendered in this style for the caller. |

<a id="shape-date-style-list"></a>

#### Shape `date-style-list`

Available date display styles.

| key | JSON type | meaning |
|---|---|---|
| `styles` | array<[`date-style`](#shape-date-style)> | List of styles, in fixed order. |

<a id="shape-effect-affected-item"></a>

#### Shape `effect-affected-item`

An item touched by an effect.

| key | JSON type | meaning |
|---|---|---|
| `itemId` | string | Full item id (`<item type key>/<n>`, `<item type key>//<s>`). |
| `description` | string | Issue or generic item key, or display text for other items. |
| `url` | string | Link to the item; null when none. |

<a id="shape-effect-problem"></a>

#### Shape `effect-problem`

An effect that a generator wanted to apply but could not.

| key | JSON type | meaning |
|---|---|---|
| `generatorRowId` | integer | Row id of the generator. |
| `description` | string | Human-readable reason. |

<a id="shape-effect-record"></a>

#### Shape `effect-record`

One effect of an effector process: in a preview, a change that would be made; in the audit records, a change that was made.

| key | JSON type | meaning |
|---|---|---|
| `processId` | integer | Effector process id. |
| `affectedItems` | array<[`effect-affected-item`](#shape-effect-affected-item)> | Items the effect touches, with display text and URL. |
| `undo` | string | HTML-escaped description of the reverting change (applied records only; absent for errors). |
| `effect` | string | Description of the change as HTML (escaped text, or provider-supplied HTML). |
| `isError` | boolean | True when the effect failed or cannot be applied (e.g. its provider is not installed); absent otherwise. |
| `timestamp` | integer | When it was applied, milliseconds since the epoch (0 in previews). |
| `index` | integer | Position of the effect in the process's preview. |

<a id="shape-effect-undo-redo-request"></a>

#### Shape `effect-undo-redo-request`

Effect batches to undo or redo.

| key | JSON type | meaning |
|---|---|---|
| `jobId` | integer | Absent on the first call. Set to the `jobId` returned by an earlier call that timed out, to keep waiting for that job (see the endpoint). |
| `extensionRequests` | map<string, any> | Optional map from core-extension key to an extension-specific request; each installed extension may answer under the same key in `extensionData`. |
| `forest` | [`forest-poll-entry`](#shape-forest-poll-entry) | The forest the effects belong to (spec required; version optional, for a forest update). |
| `items` | [`items-poll-entry`](#shape-items-poll-entry) | Items version for an items update; optional. |
| `effectIds` | array<integer> | Effect batch ids (required, non-empty). |

<a id="shape-effect-undo-redo-response"></a>

#### Shape `effect-undo-redo-response`

Result of undoing or redoing effects.

| key | JSON type | meaning |
|---|---|---|
| `successfulActions` | integer | Always 1. |
| `updateError` | [`forest-action-failure`](#shape-forest-action-failure) | Present with an error when the undo/redo failed. |
| `forestUpdates` | array<[`forest-update`](#shape-forest-update)> | One forest update from the request's forest version; absent when no version was given. |
| `itemTypes` | map<any, any> | Map from the decimal item-type numbers used in this response's forest or item encodings to full item type keys (e.g. `"3": "com.almworks.jira.structure:type-folder"`). Only types that occur in this response are listed. |
| `oldRowIds` | array<integer> | Row ids that were replaced (e.g. temporary ids of new rows), parallel to `newRowIds`; absent when none. |
| `newRowIds` | array<integer> | The ids that replaced the corresponding `oldRowIds`. |
| `effects` | array<[`applied-effect-batch`](#shape-applied-effect-batch)> | Effect batches applied in Jira by this request. |
| `undoEffects` | array<integer> | Not filled in. |
| `problems` | array<[`effect-problem`](#shape-effect-problem)> | Effects that could not be applied. |
| `extensionData` | map<string, any> | Map from core-extension key to extension-specific data returned for the request's `extensionRequests`; absent or null when no extension answered. |
| `itemsUpdate` | [`items-update`](#shape-items-update) | Item changes since the request's items version; absent when not asked. |

<a id="shape-effector-module-info"></a>

#### Shape `effector-module-info`

An available effector module.

| key | JSON type | meaning |
|---|---|---|
| `module` | string | Complete module key. |
| `label` | string | Display label. |
| `icon` | string | CSS class of its icon. |
| `title` | string | Title of its configuration dialog. |

<a id="shape-effector-page-info"></a>

#### Shape `effector-page-info`

Paging information of a page.

| key | JSON type | meaning |
|---|---|---|
| `startAt` | integer | Offset, echoed. |
| `maxResults` | integer | Page size, echoed (may be -1). |
| `total` | integer | Total number of elements. |
| `errors` | integer | Number of erroneous elements (preview only; otherwise 0). |

<a id="shape-effector-page-request"></a>

#### Shape `effector-page-request`

Paging and filter parameters for effector process lists.

| key | JSON type | meaning |
|---|---|---|
| `params` | map<string, string> | Filters as string pairs (see the endpoint); null = none. |
| `maxResults` | integer | Page size; -1 = everything; 0 (the default when omitted) = empty page. |
| `startAt` | integer | 0-based offset. |

<a id="shape-effector-page-response"></a>

#### Shape `effector-page-response`

A page of a list.

| key | JSON type | meaning |
|---|---|---|
| `items` | array<any> | The page's elements (type depends on the endpoint). |
| `pagination` | [`effector-page-info`](#shape-effector-page-info) | Paging information. |

<a id="shape-effector-process"></a>

#### Shape `effector-process`

An effector process as listed in the audit view.

| key | JSON type | meaning |
|---|---|---|
| `processId` | integer | Process id. |
| `userKey` | string | Key of the user who started it. |
| `user` | [`user-display-info`](#shape-user-display-info) | Details of that user; null when the user no longer exists. |
| `started` | string | Start time formatted for the caller (complete date-time style); empty string when unknown. |
| `status` | [`effector-process-progress`](#shape-effector-process-progress) | Status and progress. |
| `finished` | string | Finish time formatted the same way; empty when not finished. |
| `structure` | [`effector-process-structure`](#shape-effector-process-structure) | Structure the process ran on; null for one-off runs without a structure. |
| `effectors` | array<[`effector-process-effector`](#shape-effector-process-effector)> | Effectors that ran (or, for a one-off run, a single entry with only a name). |
| `revertedProcessId` | integer | For an undo process, the process it reverts; null otherwise. |

<a id="shape-effector-process-effector"></a>

#### Shape `effector-process-effector`

An effector that took part in a process.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Effector instance id; null for one-off runs. |
| `name` | string | Display name with configuration summary. |

<a id="shape-effector-process-progress"></a>

#### Shape `effector-process-progress`

Status and progress of an effector process.

| key | JSON type | meaning |
|---|---|---|
| `status` | [`effector-process-status`](#shape-effector-process-status) | Life-cycle status. |
| `percentComplete` | integer | 0..100 (0 when unknown). |
| `canceled` | boolean | True when cancellation was requested. |

<a id="shape-effector-process-status"></a>

#### Shape `effector-process-status`

Life-cycle status of an effector process (a run of effectors that computes a preview of changes to Jira and then applies them).

A JSON string, one of:

| value | meaning |
|---|---|
| `PENDING` | Created, not yet started. |
| `CALCULATING` | The preview of effects is being computed. |
| `CALCULATED` | Preview ready; waiting for the user to confirm. |
| `CALCULATION_FAILED` | Computing the preview failed. |
| `CALCULATION_STOPPED` | Computing the preview was cancelled. |
| `QUEUED` | Confirmed and waiting to be applied. |
| `IN_PROGRESS` | Effects are being applied. |
| `COMPLETED` | All effects were applied. |
| `COMPLETED_WITH_ERRORS` | Applied, but some effects failed. |
| `APPLY_INTERRUPTED` | Application was interrupted (e.g. node shutdown); can be resumed. |
| `APPLY_STOPPED` | Application was cancelled by a user. |

<a id="shape-effector-process-structure"></a>

#### Shape `effector-process-structure`

The structure of an effector process.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Structure id. |
| `name` | string | Structure name; null when the caller can no longer view it. |

<a id="shape-empty-ok"></a>

#### Shape `empty-ok`

Acknowledgement without data: the object `{"empty": true}`.

| key | JSON type | meaning |
|---|---|---|
| `empty` | boolean | Always true. |

<a id="shape-export-menu-link"></a>

#### Shape `export-menu-link`

An entry of the grid's export menu (contributed by this plugin or other apps).

| key | JSON type | meaning |
|---|---|---|
| `label` | string | Menu text. |
| `title` | string | Tooltip. |
| `url` | string | Target URL of the export action. |
| `iconClasses` | string | CSS classes for the entry's icon. |
| `moduleKey` | string | Complete key of the contributing web item module. |

<a id="shape-extensible-async-request"></a>

#### Shape `extensible-async-request`

Common part of requests that may run asynchronously and may carry data for companion apps.

| key | JSON type | meaning |
|---|---|---|
| `jobId` | integer | Absent on the first call. If the server cannot answer within its timeout (default 3 s) it replies 200 with only `jobId`; the client repeats the identical request with that `jobId` to collect the result. |
| `extensionRequests` | map<string, any> | Map from companion-app key to that app's request payload; each app's reply is returned under the same key in the response's extension data. |

<a id="shape-field-error"></a>

#### Shape `field-error`

A problem with one input field.

| key | JSON type | meaning |
|---|---|---|
| `field` | string | Name of the offending input (parameter or JSON key). |
| `error` | string | Message text or, where the endpoint says so, a message key for the client to translate. |
| `params` | array<string> | Arguments for the message key (strings); empty when none. |

<a id="shape-forest-action"></a>

#### Shape `forest-action`

One editing action in a forest update request.

| key | JSON type | meaning |
|---|---|---|
| `action` | string | `add` (insert the sub-forest `forest`), `copy` (insert `forest` as copies of existing rows), `move` (move rows), `remove` (remove rows). |
| `rowId` | integer | Single row to move/remove (takes precedence over `rowIds`). |
| `rowIds` | array<integer> | Rows to move/remove. |
| `forest` | string | For `add`/`copy`: the rows to insert. Same row syntax as the forest encoding, but the `<item>` field is percent-decoded and then read as: a bare decimal = issue id; `<item type key>/<n>` or `<item type key>//<s>` with the full item type key (e.g. `com.almworks.jira.structure:type-folder/12`; the colon inside the key must be sent as `%3A`). New rows use negative temporary row ids; the server reports the ids it assigned. |
| `under` | integer | Parent row of the insert/move target; 0 or absent = top level. |
| `after` | integer | Sibling after which to place; 0 or absent = no such constraint (start of the parent). |
| `before` | integer | Sibling before which to place; 0 or absent = none. |
| `originalRowIds` | array<integer> | For `copy`: for each row of `forest`, in order, the existing row it copies; length must equal the number of rows. |
| `cutFrom` | [`forest-action-cut-source`](#shape-forest-action-cut-source) | For `add` (and `move` via clipboard): where the rows were cut from, so they are removed there. |
| `parameters` | map<string, any> | Answers to questions from a previous attempt (question parameter id → chosen value) and other action options; null = none. |

<a id="shape-forest-action-cut-source"></a>

#### Shape `forest-action-cut-source`

The origin of rows being pasted after a cut.

| key | JSON type | meaning |
|---|---|---|
| `viaClipboard` | boolean | True when the rows went through the caller's clipboard; the clipboard is cleared after success. |
| `spec` | [`forest-spec`](#shape-forest-spec) | Forest the rows were cut from; when present, `version` and `rowIds` are required and the rows are removed there. |
| `version` | [`data-version`](#shape-data-version) | Version of the source forest the row ids refer to. |
| `rowIds` | array<integer> | Rows to remove from the source. |

<a id="shape-forest-action-error"></a>

#### Shape `forest-action-error`

Why an action was refused.

| key | JSON type | meaning |
|---|---|---|
| `row` | integer | Row the error is about; 0 when none. |
| `itemDescription` | string | Display text of that row's item (or `row <id>` when unknown). |
| `itemUrl` | string | URL of that item; null when none. |
| `itemCount` | integer | Number of rows the failed action involved. |
| `message` | string | Localized error message. |

<a id="shape-forest-action-failure"></a>

#### Shape `forest-action-failure`

Why the last attempted action did not go through: either an error or a list of questions (one of the two is present).

| key | JSON type | meaning |
|---|---|---|
| `error` | [`forest-action-error`](#shape-forest-action-error) | The error; absent for questions. |
| `interactions` | array<[`forest-action-question`](#shape-forest-action-question)> | Questions to answer; absent for errors. |

<a id="shape-forest-action-question"></a>

#### Shape `forest-action-question`

A question the server needs answered before it can apply an action. The client resends the action with `parameters[parameter]` set to one of the possible values.

| key | JSON type | meaning |
|---|---|---|
| `row` | integer | Row the question is about; 0 when none. |
| `itemDescription` | string | Display text of the row's item. |
| `itemUrl` | string | URL of the item. |
| `itemCount` | integer | Number of rows the action involves. |
| `parameter` | string | Parameter id to answer, e.g. `0:PrimaryGenerator` (which generator should handle the change; value = generator row id) or `0:CreateAnyway` (value `true`). |
| `message` | string | Localized question. |
| `values` | array<[`forest-action-question-option`](#shape-forest-action-question-option)> | Possible answers. |

<a id="shape-forest-action-question-option"></a>

#### Shape `forest-action-question-option`

One possible answer to a question.

| key | JSON type | meaning |
|---|---|---|
| `value` | any | Value to send back (number, string or boolean). |
| `iconHtml` | string | Icon HTML; null when none. |
| `message` | string | Explanation of this choice. |
| `possible` | boolean | False when the choice is shown but not available. |

<a id="shape-forest-health"></a>

#### Shape `forest-health`

How generation of a forest is doing.

| key | JSON type | meaning |
|---|---|---|
| `stopped` | boolean | True when generation is stopped (by a user or automatically) and the content may be outdated. |
| `generatorTimes` | array<[`generator-health-entry`](#shape-generator-health-entry)> | Time spent per generator. |
| `hitLimits` | array<[`generator-health-entry`](#shape-generator-health-entry)> | Generators that hit a size limit. |
| `infiniteUpdateGenerators` | array<[`generator-health-entry`](#shape-generator-health-entry)> | Generators detected as causing endless re-generation. |

<a id="shape-forest-poll-entry"></a>

#### Shape `forest-poll-entry`

A forest the client watches and the version it has.

| key | JSON type | meaning |
|---|---|---|
| `spec` | [`forest-spec`](#shape-forest-spec) | The forest. |
| `version` | [`data-version`](#shape-data-version) | The version the client holds; `{0,0}` = send everything; in a poll, `{0,-1}` = initial load. |

<a id="shape-forest-search-query"></a>

#### Shape `forest-search-query`

A search whose results form a forest of up to 1000 items.

| key | JSON type | meaning |
|---|---|---|
| `query` | string | Query text. Empty = show recently viewed issues (or recently viewed pages for `cql`). |
| `type` | string | `jql` (Jira query), `text` (quick text search), `cql` (Confluence pages, requires the pages add-on), or a type contributed by an installed extension; otherwise the spec is rejected. |

<a id="shape-forest-snapshot"></a>

#### Shape `forest-snapshot`

The current content of a forest.

| key | JSON type | meaning |
|---|---|---|
| `spec` | [`forest-spec`](#shape-forest-spec) | The requested spec, echoed. |
| `formula` | string | Forest encoding: rows in depth-first order separated by `,`; each row is `<rowId>:<depth>:<item>`, followed by `:<semantics>` only when the row's semantics number is positive. Depth 0 is a top-level row; a row's parent is the nearest earlier row whose depth is one less. `<item>` is the decimal issue id for an issue; for any other item it is `<t>/<n>` (numeric item id) or `<t>//<s>` (string item id percent-encoded like the browser function encodeURIComponent), where `<t>` is a decimal item-type number to be looked up in the response's `itemTypes` map. Empty string = empty forest. |
| `itemTypes` | map<any, any> | Map from the decimal item-type numbers used in this response's forest or item encodings to full item type keys (e.g. `"3": "com.almworks.jira.structure:type-folder"`). Only types that occur in this response are listed. |
| `version` | [`data-version`](#shape-data-version) | Version of this content. |

<a id="shape-forest-spec"></a>

#### Shape `forest-spec`

Names a forest the grid can display. Exactly one source must be given: a structure (`structureId`), a search query (`sQuery`), or the caller's clipboard (`type` = `clipboard`, private to the HTTP session); `transforms` then apply transformations on top.

| key | JSON type | meaning |
|---|---|---|
| `structureId` | integer | Structure id for a structure's forest. |
| `version` | integer | History version of the structure to show (read-only past state); only with `structureId`. |
| `sQuery` | [`forest-search-query`](#shape-forest-search-query) | Search query whose results form the forest; see the query shape. |
| `type` | string | `clipboard` for the caller's per-session clipboard forest; any other value is ignored. |
| `transforms` | array<[`forest-transformation`](#shape-forest-transformation)> | Ordered list of transformations (generators applied to the source as a view); null/absent = none. |
| `title` | boolean | When `true`, the forest gets a title row for the structure on top; only with `structureId`. |

<a id="shape-forest-transformation"></a>

#### Shape `forest-transformation`

One transformation step applied to a forest view.

| key | JSON type | meaning |
|---|---|---|
| `module` | string | Complete module key of the generator used as transformation (e.g. a sorter, filter or grouper). |
| `key` | string | Client-side label of the step; ignored by the server and not part of equality. |
| `params` | map<string, any> | Generator parameters as a JSON object; null = defaults. |

<a id="shape-forest-update"></a>

#### Shape `forest-update`

Changes of one forest from a client version to the current version; either a full forest or an incremental change list.

| key | JSON type | meaning |
|---|---|---|
| `spec` | [`forest-spec`](#shape-forest-spec) | The forest spec, echoed. |
| `fromVersion` | [`data-version`](#shape-data-version) | The version the client had (echoed). |
| `version` | [`data-version`](#shape-data-version) | The new version; the client stores it. Absent when the forest could not be read. |
| `formula` | string | Present for a full update (client must replace its forest). Forest encoding: rows in depth-first order separated by `,`; each row is `<rowId>:<depth>:<item>`, followed by `:<semantics>` only when the row's semantics number is positive. Depth 0 is a top-level row; a row's parent is the nearest earlier row whose depth is one less. `<item>` is the decimal issue id for an issue; for any other item it is `<t>/<n>` (numeric item id) or `<t>//<s>` (string item id percent-encoded like the browser function encodeURIComponent), where `<t>` is a decimal item-type number to be looked up in the response's `itemTypes` map. Empty string = empty forest. |
| `updates` | string | Present for an incremental update: changes separated by `\|`, applied in order. `a.<under>.<after>.<forest>` inserts the encoded sub-forest under row `under` (0 = top level) after sibling `after` (0 = first position), depths relative to the insertion point; `m.<under>.<after>.<rows>` moves the comma-separated rows (with their sub-trees) there; `r.<rows>` removes the comma-separated rows; `o.<under>.<rows>` reorders the children of `under` into the given order. Neither present = no change. |
| `healthStatus` | [`forest-health`](#shape-forest-health) | Generation health of the forest; absent when the forest could not be read. |
| `error` | [`structure-error`](#shape-structure-error) | Present when the forest could not be read (e.g. no access). |
| `needsUpdate` | boolean | True when this is an initial-load snapshot that may be stale; the client should poll again from `version`. Absent otherwise. |

<a id="shape-forest-update-request"></a>

#### Shape `forest-update-request`

Editing actions for a forest.

| key | JSON type | meaning |
|---|---|---|
| `jobId` | integer | Absent on the first call. Set to the `jobId` returned by an earlier call that timed out, to keep waiting for that job (see the endpoint). |
| `extensionRequests` | map<string, any> | Optional map from core-extension key to an extension-specific request; each installed extension may answer under the same key in `extensionData`. |
| `spec` | [`forest-spec`](#shape-forest-spec) | Forest to edit (required). |
| `version` | [`data-version`](#shape-data-version) | Version of the forest the row ids in the actions refer to (required). |
| `actions` | array<[`forest-action`](#shape-forest-action)> | Ordered actions. |

<a id="shape-forest-update-response"></a>

#### Shape `forest-update-response`

Result of a forest update.

| key | JSON type | meaning |
|---|---|---|
| `successfulActions` | integer | Number of actions fully applied. |
| `updateError` | [`forest-action-failure`](#shape-forest-action-failure) | Present when an action was refused or a question must be answered; absent on success. |
| `forestUpdates` | array<[`forest-update`](#shape-forest-update)> | Forest changes since the client's version(s), so the client can resynchronize. |
| `itemTypes` | map<any, any> | Map from the decimal item-type numbers used in this response's forest or item encodings to full item type keys (e.g. `"3": "com.almworks.jira.structure:type-folder"`). Only types that occur in this response are listed. |
| `oldRowIds` | array<integer> | Row ids that were replaced (e.g. temporary ids of new rows), parallel to `newRowIds`; absent when none. |
| `newRowIds` | array<integer> | The ids that replaced the corresponding `oldRowIds`. |
| `effects` | array<[`applied-effect-batch`](#shape-applied-effect-batch)> | Effect batches applied in Jira by this request. |
| `undoEffects` | array<integer> | Batch ids of the last successful action's effects, to pass to effect undo. |
| `problems` | array<[`effect-problem`](#shape-effect-problem)> | Effects that could not be applied. |
| `extensionData` | map<string, any> | Map from core-extension key to extension-specific data returned for the request's `extensionRequests`; absent or null when no extension answered. |

<a id="shape-formula-check-request"></a>

#### Shape `formula-check-request`

A formula to validate.

| key | JSON type | meaning |
|---|---|---|
| `expr` | string | Formula text in the app's expression language. Required. |
| `definedVariables` | array<string> | Optional names of variables the caller has already bound; used only to decide whether each free variable is resolved. |

<a id="shape-formula-check-result"></a>

#### Shape `formula-check-result`

Analysis of a formula: validity and the location of every name, comment and problem. All ranges are character offsets into `expr`, half-open (`from` inclusive, `to` exclusive).

| key | JSON type | meaning |
|---|---|---|
| `expr` | string | The analysed formula text, echoed. |
| `valid` | boolean | true when the formula parsed and has no validation errors. |
| `resolved` | boolean | true when every function and aggregation used is known to the language (free variables do not affect this flag). |
| `errorIndex` | integer | Character offset where parsing failed; null when parsing succeeded. |
| `expectedTokens` | array<string> | When parsing failed, the tokens that would have been accepted at `errorIndex`, plus the words `identifier` and/or `literal` when a name or a literal value would have been accepted; null when parsing succeeded. |
| `variables` | array<[`formula-name-usage`](#shape-formula-name-usage)> | Every variable name used: free variables and locally declared ones. |
| `functions` | array<[`formula-name-usage`](#shape-formula-name-usage)> | Every function name used, with documentation when known. |
| `aggregations` | array<[`formula-name-usage`](#shape-formula-name-usage)> | Every aggregation function used, with documentation when known. |
| `comments` | array<[`formula-text-range`](#shape-formula-text-range)> | Ranges of the comments in the text (no `error`). |
| `errors` | array<[`formula-text-range`](#shape-formula-text-range)> | Validation problems not tied to a reported name usage or declaration: each a range with a localized `error`. |

<a id="shape-formula-name-usage"></a>

#### Shape `formula-name-usage`

One distinct name (variable, function or aggregation) used in a formula and where it occurs.

| key | JSON type | meaning |
|---|---|---|
| `name` | string | The name as written. |
| `usage` | array<[`formula-text-range`](#shape-formula-text-range)> | Ranges of every occurrence; an occurrence with a problem carries a localized `error`. |
| `declaration` | [`formula-text-range`](#shape-formula-text-range) | For a variable declared inside the formula (local variable), the range of its declaration (with an `error` if the declaration has a problem); null otherwise. |
| `resolved` | boolean | Local variable: always true. Free variable: true when listed in the request's `definedVariables`. Function or aggregation: true when the language knows it. |
| `description` | string | Localized description of a known function or aggregation; null for variables and unknown names. |
| `documentationUrl` | string | Link to the documentation of a known function or aggregation; null otherwise. |

<a id="shape-formula-text-range"></a>

#### Shape `formula-text-range`

A stretch of the formula text, optionally with a problem.

| key | JSON type | meaning |
|---|---|---|
| `from` | integer | Start character offset (0-based, inclusive). |
| `to` | integer | End character offset (exclusive). |
| `error` | string | Localized problem message for this stretch, or null. |

<a id="shape-gadget-grid-mode-tuning"></a>

#### Shape `gadget-grid-mode-tuning`

Grid tuning for one gadget mode.

| key | JSON type | meaning |
|---|---|---|
| `pollInterval` | integer | Milliseconds between update polls. |
| `minCachedRows` | integer | Minimum rows to keep loaded. |
| `preloadRowsFactor` | number | Multiple of the visible rows to preload. |

<a id="shape-gadget-grid-tuning"></a>

#### Shape `gadget-grid-tuning`

Client tuning for the gadget grid.

| key | JSON type | meaning |
|---|---|---|
| `local` | [`gadget-grid-mode-tuning`](#shape-gadget-grid-mode-tuning) | Settings when the gadget runs in this Jira. |
| `remote` | [`gadget-grid-mode-tuning`](#shape-gadget-grid-mode-tuning) | Settings when the gadget runs on another server; also has `allowNodeWandering`. |
| `retryBackoff` | array<integer> | Data Center only: retry delays (from system property `structure.gadget.dc.retryBackoff`, comma-separated integers); absent otherwise or if unparseable. |

<a id="shape-gadget-remote-grid-tuning"></a>

#### Shape `gadget-remote-grid-tuning`

Grid tuning for the remote gadget mode.

| key | JSON type | meaning |
|---|---|---|
| `pollInterval` | integer | Milliseconds between update polls. |
| `minCachedRows` | integer | Minimum rows to keep loaded. |
| `preloadRowsFactor` | number | Multiple of the visible rows to preload. |
| `allowNodeWandering` | boolean | Whether successive requests may be served by different Data Center nodes (default true; system property `structure.gadget.remote.allowNodeWandering`). |

<a id="shape-generation-control-request"></a>

#### Shape `generation-control-request`

A list of forests for stopping/resuming generation.

| key | JSON type | meaning |
|---|---|---|
| `forestSpecs` | array<[`forest-spec`](#shape-forest-spec)> | The forests. |

<a id="shape-generator-description"></a>

#### Shape `generator-description`

Display description of a generator.

| key | JSON type | meaning |
|---|---|---|
| `description` | string | HTML snippet: a span with the generator's icon followed by its summary text. |
| `id` | integer | Generator id. |

<a id="shape-generator-health-entry"></a>

#### Shape `generator-health-entry`

A per-generator figure in the health status.

| key | JSON type | meaning |
|---|---|---|
| `generatorId` | integer | Generator id (describable with the generator descriptions call). |
| `data` | any | The figure: time spent generating (milliseconds) in `generatorTimes`, the limit reached in `hitLimits`, empty string in `infiniteUpdateGenerators`. |

<a id="shape-generator-module-info"></a>

#### Shape `generator-module-info`

An available generator module.

| key | JSON type | meaning |
|---|---|---|
| `module` | string | Complete module key. |
| `label` | string | Display label. |
| `type` | string | `inserter`, `grouper`, `extender`, `sorter` or `filter`. |
| `presets` | array<[`generator-preset`](#shape-generator-preset)> | Predefined configurations; absent when the generator has none. |
| `notConfigurable` | boolean | True when the generator has no configuration form. |
| `group` | integer | Display group number for ordering in menus; null when none. |

<a id="shape-generator-preset"></a>

#### Shape `generator-preset`

A predefined generator configuration.

| key | JSON type | meaning |
|---|---|---|
| `label` | string | Display label. |
| `params` | string | Generator parameters as JSON text (with `disableActions` true added when an instance-wide switch disables updates for defaults). |
| `description` | string | Description; null when none. |

<a id="shape-generic-item-content"></a>

#### Shape `generic-item-content`

Content of a generic item (memo, planning task) for display or as a validated preview.

| key | JSON type | meaning |
|---|---|---|
| `summary` | string | Summary text. |
| `description` | string | Description in wiki markup; absent when the field is hidden or empty. |
| `descriptionHtml` | string | Description rendered to HTML. |
| `params` | map<string, any> | Values of the item's other visible fields by field id (wiki-rendered fields also get `<field id>Html`), plus `color` and `iconClass` when set. |

<a id="shape-generic-item-details"></a>

#### Shape `generic-item-details`

Details panel data of a generic item.

| key | JSON type | meaning |
|---|---|---|
| `item` | [`generic-item-content`](#shape-generic-item-content) | The item content. |
| `fields` | array<[`generic-item-field`](#shape-generic-item-field)> | Descriptors of all generic-item fields as configured for this item. |
| `editable` | boolean | Not filled in (null). |

<a id="shape-generic-item-field"></a>

#### Shape `generic-item-field`

Descriptor of a field of generic items (memos, planning tasks) for the editor.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Field id (e.g. `summary`, `description`, `project`, `issuetype`). |
| `name` | string | Localized field name. |
| `type` | string | Field type key; multi-line text fields using the wiki renderer report `rich-text`. |
| `required` | boolean | Required in this item's configuration. |
| `visible` | boolean | Shown in this item's configuration. |
| `editable` | boolean | Editable in this item's configuration. |
| `multiple` | boolean | Holds several values. |
| `searchable` | boolean | Its option list supports searching. |
| `selectable` | boolean | Its value is chosen from options. |
| `hasIcons` | boolean | Options have icons. |
| `placeholder` | string | Placeholder text for the editor. |
| `spec` | string | JSON text identifying the option source, to be used when requesting options; absent when the field has no options. |

<a id="shape-generic-item-validation"></a>

#### Shape `generic-item-validation`

Validation result and preview for a new planning task.

| key | JSON type | meaning |
|---|---|---|
| `fieldErrors` | map<string, string> | Messages by field id (e.g. `issuetype` when the project has no issue types); empty object when valid. |
| `item` | [`generic-item-content`](#shape-generic-item-content) | Preview of the item with defaults; its summary is the one sent (null when none). |
| `fields` | array<[`generic-item-field`](#shape-generic-item-field)> | Field descriptors as configured for the previewed item. |

<a id="shape-grid-bootstrap"></a>

#### Shape `grid-bootstrap`

Bootstrap data for the structure grid client.

| key | JSON type | meaning |
|---|---|---|
| `structureVersion` | string | Plugin version. |
| `jiraVersion` | string | Jira version. |
| `jiraClusterNodeId` | string | Id of the serving Data Center node; absent when not clustered. |
| `jiraFields` | array<[`jira-field-descriptor`](#shape-jira-field-descriptor)> | Navigable Jira fields usable as columns, sorted by name (custom fields without a view template are left out). |
| `jiraAgileRankFields` | array<integer> | Numeric ids of the agile Rank custom fields; empty when agile is not installed. |
| `jiraEmailNotificationsEnabled` | boolean | False when Jira outgoing mail is disabled. |
| `jiraDateTimeFormats` | map<string, any> | Jira's date settings: `dateFormat`, `dateTimeFormat`, `datePickerJavascriptFormat`, `datePickerJavaFormat` (format strings) and `firstDayOfWeek` (0 = Sunday ... 6 = Saturday for the caller's locale). |
| `features` | map<string, any> | Client feature switches: `useStructuresActionsLink` (boolean) and, when switched on, `altInitialValuesInDialog: true`. |
| `canCreate` | boolean | Caller can create issues in at least one plugin-enabled project. |
| `licenseInvalid` | boolean | True when the plugin is not validly licensed; absent otherwise. |
| `canBrowseUsers` | boolean | Caller is a Jira administrator or has 'browse users'. |
| `canBulkChange` | boolean | Caller has Jira's bulk change permission. |
| `canCreateViews` | boolean | Caller may create views. |
| `canShareViews` | boolean | Caller may create views and has Jira's 'create shared objects' permission. |
| `canCreatePerspective` | boolean | Caller may create shared perspectives. |
| `canManageGlobalSavedColumns` | boolean | Caller may manage instance-wide saved columns. |
| `admin` | boolean | True for Jira administrators; absent otherwise. |
| `anonymous` | boolean | True for anonymous callers; absent otherwise. |
| `extensions` | map<string, map<string, any>> | Per companion-app key, the client settings that app supplies; absent when none. |
| `exportLinks` | array<[`export-menu-link`](#shape-export-menu-link)> | Export menu entries; absent when none. |
| `externalGenericItemTypes` | array<[`third-party-item-type`](#shape-third-party-item-type)> | Item types contributed by other apps (hidden ones excluded), sorted by weight then title. |
| `restAsyncBackoff` | array<integer> | Delays between re-polls of long-running requests (from system property `structure.rest.async.backoff`, comma-separated); absent when not configured. |
| `globalError` | string | Localized warning shown on every grid (Jira index inconsistent); absent when fine. |
| `hideHelp` | boolean | True when the welcome/help content is switched off. |
| `hideHelpAdminTips` | boolean | True when help is on but no help content is installed. |
| `canRunEffectorsOnQueryResults` | boolean | Caller may run effectors on query-based (non-saved) structures. |
| `enabledPlugins` | array<string> | Which of a fixed list of third-party apps the client integrates with are enabled, by app key (`is.origo.jira.tempo-plugin`, `com.tempoplugin.tempo-plan-core`, `com.jiraeditor.jeditor`). |

<a id="shape-grid-view"></a>

#### Shape `grid-view`

A view: a named, shareable layout of grid columns.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | View id; must be absent when creating. |
| `name` | string | View name. |
| `description` | string | Free-text description. |
| `spec` | [`view-layout`](#shape-view-layout) | Columns and display settings. |
| `writable` | boolean | True when the caller may edit the view's columns (edit level). |
| `adminable` | boolean | True when the caller administers the view. |
| `shared` | boolean | True when the view has sharing rules for anyone besides the owner. |
| `sharedWithAll` | boolean | True when anyone may view it. |
| `permissions` | array<[`access-rule`](#shape-access-rule)> | Sharing rules, in evaluation order; only returned when requested and the caller administers the view. On write, replaces all rules. |
| `owner` | [`user-display-info`](#shape-user-display-info) | Owner user. On write, identifies the new owner by user key, or by user name when the key is absent. |
| `hasOwner` | boolean | Returned instead of `owner` when the owner may not be disclosed to the caller: whether the view has an owner. |

<a id="shape-grid-view-list"></a>

#### Shape `grid-view-list`

List of views.

| key | JSON type | meaning |
|---|---|---|
| `views` | array<[`grid-view`](#shape-grid-view)> | The views. |
| `preferred` | array<integer> | Menu responses only: ids of views that are the default on the requested page. |

<a id="shape-history-synchronizer"></a>

#### Shape `history-synchronizer`

The synchronizer that made a history change.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Synchronizer instance id. |
| `description` | string | Localized description of the synchronizer and its configuration (generic text when it no longer exists). |

<a id="shape-issue-actions-and-operations"></a>

#### Shape `issue-actions-and-operations`

What the caller can do with an issue.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Issue id (string). |
| `key` | string | Issue key. |
| `actions` | array<[`issue-menu-workflow-transition`](#shape-issue-menu-workflow-transition)> | Available workflow transitions, in workflow order. |
| `operations` | array<[`issue-menu-operation-link`](#shape-issue-menu-operation-link)> | Issue operation links. |
| `viewIssue` | string | Localized label for viewing the issue. |
| `atlToken` | string | A fresh XSRF token for the caller's session, for use in the operation links. |

<a id="shape-issue-constant"></a>

#### Shape `issue-constant`

A Jira issue constant (status, type, ...).

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Constant id (string). |
| `name` | string | Name translated for the caller. |
| `description` | string | Translated description. |
| `iconUrl` | string | Absolute icon URL. |
| `sequence` | integer | Jira's ordering number; may be absent. |

<a id="shape-issue-constant-list"></a>

#### Shape `issue-constant-list`

List of issue constants; element type depends on the endpoint (types or statuses).

| key | JSON type | meaning |
|---|---|---|
| `constants` | array<[`issue-constant`](#shape-issue-constant)> | The constants. |

<a id="shape-issue-field-editor"></a>

#### Shape `issue-field-editor`

Editor for one Jira field.

| key | JSON type | meaning |
|---|---|---|
| `name` | string | Field name translated for the caller. |
| `createHtml` | string | HTML of the create-screen editor. |
| `editHtml` | string | HTML of the edit-screen editor (with current value). |
| `error` | string | Localized reason why the field cannot be edited here; when set, no HTML is given. |

<a id="shape-issue-field-editors"></a>

#### Shape `issue-field-editors`

Editor HTML for fields of an existing or prospective issue.

| key | JSON type | meaning |
|---|---|---|
| `issue` | integer | Issue id the editors are for (the sample issue for creation); absent for create without sample. |
| `forCreate` | boolean | True for create-screen editors; absent for edit. |
| `project` | integer | Project id used for creation. |
| `issueType` | string | Issue type id used for creation. |
| `fields` | map<string, [`issue-field-editor`](#shape-issue-field-editor)> | Map from Jira field id to its editor; absent when a top-level `error` is set. |
| `error` | string | Localized reason why no editors could be produced (bad or invisible issue, no screen); absent on success. |
| `canChangeOriginalEstimate` | boolean | False when time has been logged and Jira's legacy time-tracking mode forbids changing the original estimate. |
| `structuredProjects` | array<integer> | For the project/type picker case only: ids of projects where the caller can create issues and the plugin is enabled; absent when the plugin is enabled for all projects. |

<a id="shape-issue-field-option"></a>

#### Shape `issue-field-option`

One selectable value of an issue field in the field value picker. All fields are always present; missing values are empty strings, never null.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Value identifier, format depends on the field: project key (project, and project-picker custom fields); Jira id of the status, issue type, priority or resolution; version or component id (options with the same name in several projects are merged into one, keeping one id); `author:<user key>` or `group:<group name>` for user fields; the label text for labels; option id for select lists and `<parent option id>:<child option id>` for a cascading child; sprint id; team id; Assets object id. `special:EMPTY` is the 'no value' option. |
| `label` | string | Display text, e.g. project name, version name, user display name, 'Parent - Child' for a cascading option. |
| `iconUrl` | string | Icon URL or empty: issue constant icon, `/secure/projectavatar?pid=<project id>&size=small` (relative to the Jira base URL) for projects, an Assets object-type icon path, else empty. |
| `metadata` | string | Extra data as a JSON-encoded string, or empty: for statuses `{"color": <status category color name>}`; for sprints `{"board": <board name>, "state": <sprint state in lower case>}`. |
| `html` | string | Ready-made HTML for the option, or empty; for users it is 'Display Name (username)' (plus email when visible to the caller) HTML-escaped inside a span. |

<a id="shape-issue-field-option-group"></a>

#### Shape `issue-field-option-group`

A titled group of issue field options.

| key | JSON type | meaning |
|---|---|---|
| `label` | string | Group title (localized), or empty string when the field has a single untitled group. |
| `options` | array<[`issue-field-option`](#shape-issue-field-option)> | The options of this page, as [`issue-field-option`](#shape-issue-field-option), possibly cut by the limit; may start with the 'no value' option. |
| `total` | integer | Number of options available in the group regardless of the limit (for most fields the total before the text filter; for labels the number of suggestions found). |

<a id="shape-issue-field-option-list"></a>

#### Shape `issue-field-option-list`

Options of an issue field, grouped.

| key | JSON type | meaning |
|---|---|---|
| `groups` | array<[`issue-field-option-group`](#shape-issue-field-option-group)> | Option groups in display order; empty when the field is unknown or unsupported. |

<a id="shape-issue-field-option-lookup"></a>

#### Shape `issue-field-option-lookup`

Request to resolve option ids of one issue field.

| key | JSON type | meaning |
|---|---|---|
| `fieldId` | string | Jira field id (e.g. `priority`, `customfield_10010`). Required. |
| `fieldValues` | array<string> | Option ids to resolve (formats as in [`issue-field-option`](#shape-issue-field-option)). Required, non-empty. |

<a id="shape-issue-link-click-action"></a>

#### Shape `issue-link-click-action`

What clicking an issue link in a structure grid does.

| key | JSON type | meaning |
|---|---|---|
| `type` | string | `showDetails` (open the details panel), `openIssuePage` or `doNothing`. |

<a id="shape-issue-menu-operation-link"></a>

#### Shape `issue-menu-operation-link`

An issue operation link from Jira's issue operations bar.

| key | JSON type | meaning |
|---|---|---|
| `name` | string | Label. |
| `url` | string | Link URL. |
| `desc` | string | Tooltip. |
| `styleClass` | string | CSS class of the link. |

<a id="shape-issue-menu-workflow-transition"></a>

#### Shape `issue-menu-workflow-transition`

An available workflow transition.

| key | JSON type | meaning |
|---|---|---|
| `action` | string | Transition (action) id as a string. |
| `name` | string | Display name. |
| `desc` | string | Description; null when empty. |

<a id="shape-issue-operation-link"></a>

#### Shape `issue-operation-link`

A Jira issue operation offered as a link.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Link id. |
| `styleClass` | string | CSS class of the link. |
| `url` | string | Link URL; contains the placeholder `{0}` where the issue id goes. |

<a id="shape-issue-status-constant"></a>

#### Shape `issue-status-constant`

An issue status.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Status id. |
| `name` | string | Translated name. |
| `description` | string | Translated description. |
| `iconUrl` | string | Icon URL. |
| `sequence` | integer | Jira's ordering number. |
| `color` | string | Color name of the status category (e.g. `blue-gray`, `yellow`, `green`). |

<a id="shape-issue-type-constant"></a>

#### Shape `issue-type-constant`

An issue type.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Issue type id. |
| `name` | string | Translated name. |
| `description` | string | Translated description. |
| `iconUrl` | string | Icon URL. |
| `sequence` | integer | Jira's ordering number. |
| `subTask` | boolean | True for sub-task types. |

<a id="shape-item-content-spec"></a>

#### Shape `item-content-spec`

An item to create or update.

| key | JSON type | meaning |
|---|---|---|
| `itemId` | string | Full item id of an existing item: bare issue id, `<item type key>/<n>` or `<item type key>//<s>`. |
| `type` | string | For creation: complete item type key of the new item. |
| `values` | map<string, any> | Item field values as defined by the item type (e.g. `summary`); keys `itemproperty.notes` and `itemproperty.dc_note_<id>` (string values) set per-structure notes instead. |

<a id="shape-item-field-editor"></a>

#### Shape `item-field-editor`

Editor for one item field.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Field id. |
| `name` | string | Field name. |
| `createHtml` | string | Create-mode HTML (not produced by the current endpoints). |
| `editHtml` | string | Edit-mode HTML with the current value. |
| `error` | string | Localized reason why rendering failed. |

<a id="shape-item-field-editors"></a>

#### Shape `item-field-editors`

Editor HTML for a field of a plugin-native item (memo, planning task).

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Numeric item id. |
| `itemId` | string | Full item identity `<item type>/<id>`, e.g. `com.almworks.jira.structure:type-memo/42`. |
| `itemType` | string | Full item type id. |
| `forCreate` | boolean | Always absent for this endpoint (reserved for creation). |
| `fields` | map<string, [`item-field-editor`](#shape-item-field-editor)> | Map from field id to editor (one entry); absent when `error` is set. |
| `error` | string | Localized reason why the field cannot be edited (unknown item, field not supported or not editable). |

<a id="shape-items-poll-entry"></a>

#### Shape `items-poll-entry`

The items version the client holds.

| key | JSON type | meaning |
|---|---|---|
| `version` | [`data-version`](#shape-data-version) | Items version; `{0,0}` = all items considered changed. |

<a id="shape-items-update"></a>

#### Shape `items-update`

Which items changed since the client's items version (the client then refreshes their values).

| key | JSON type | meaning |
|---|---|---|
| `fromVersion` | [`data-version`](#shape-data-version) | The client's version. |
| `version` | [`data-version`](#shape-data-version) | The new items version. |
| `updated` | string | Empty string = nothing changed; `*` = everything must be considered changed; otherwise comma-separated item ids in the forest encoding's item form (types in `itemTypes`). |

<a id="shape-jira-field-descriptor"></a>

#### Shape `jira-field-descriptor`

A Jira field usable as a grid column.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Field id (e.g. `summary`, `customfield_10010`). |
| `name` | string | Field name. |
| `type` | string | JSON schema type of the field per Jira's REST API (e.g. `string`, `array`, `user`); absent for fields without a schema. |
| `items` | string | Element type for array fields. |
| `customId` | integer | Numeric custom field id; absent for system fields. |
| `custom` | string | Custom field type key. |
| `visible` | boolean | True when the field appears on at least one Jira screen. |

<a id="shape-jira-group-list"></a>

#### Shape `jira-group-list`

List of Jira groups.

| key | JSON type | meaning |
|---|---|---|
| `groups` | array<[`jira-group-ref`](#shape-jira-group-ref)> | The groups; absent when the source list was empty-null. |

<a id="shape-jira-group-ref"></a>

#### Shape `jira-group-ref`

A Jira user group.

| key | JSON type | meaning |
|---|---|---|
| `name` | string | Group name. |

<a id="shape-license-expiry"></a>

#### Shape `license-expiry`

An expiry moment of a license.

| key | JSON type | meaning |
|---|---|---|
| `timestamp` | integer | Expiry time, epoch milliseconds. |
| `formatted` | string | The same date formatted for the caller's locale. |

<a id="shape-license-info"></a>

#### Shape `license-info`

A license of the plugin or a companion app.

| key | JSON type | meaning |
|---|---|---|
| `type` | string | License type: `disabled`, `commercial`, `developer`, `free`, `evaluation` or `devenv`. |
| `licensee` | string | Organisation name. |
| `serial` | string | License serial number. |
| `unlimitedUsers` | boolean | True when the user count is unlimited. |
| `maxUsers` | integer | Licensed user count (meaningless when unlimited). |
| `serverLocked` | boolean | True when the license is bound to specific server ids. |
| `licensedServers` | array<string> | Server ids the license is bound to; absent when none. |
| `licenseExpiration` | [`license-expiry`](#shape-license-expiry) | License expiry; absent when the license does not expire. |
| `maintenanceExpiration` | [`license-expiry`](#shape-license-expiry) | End of maintenance/support; absent when none. |
| `marketplaceLicense` | boolean | True when the license comes from the Atlassian Marketplace. |
| `source` | string | Where the license comes from: `none`, `marketplace`, `vendor` or `bundle`. |

<a id="shape-macro-choice"></a>

#### Shape `macro-choice`

An id/name pair offered in the Confluence macro editor.

| key | JSON type | meaning |
|---|---|---|
| `key` | string | Numeric id as a decimal string (structure id, view id or saved filter id). |
| `value` | string | Display name. |

<a id="shape-macro-editor-settings"></a>

#### Shape `macro-editor-settings`

Choices for configuring the Confluence macro.

| key | JSON type | meaning |
|---|---|---|
| `structures` | array<[`macro-choice`](#shape-macro-choice)> | Structures the caller can view; null when the app is unavailable to the caller. |
| `views` | array<[`macro-choice`](#shape-macro-choice)> | Views the caller can view; null when the app is unavailable. |
| `savedfilters` | array<[`macro-choice`](#shape-macro-choice)> | Saved filters shared with the caller (or only the requested one); null when the app is unavailable. |
| `error` | string | Error text (app unavailable to the caller, or a failure while reading); otherwise null. |
| `supportedOptions` | [`macro-supported-features`](#shape-macro-supported-features) | Optional features this server supports. |

<a id="shape-macro-filter-search-result"></a>

#### Shape `macro-filter-search-result`

Saved filters found for the Confluence macro editor.

| key | JSON type | meaning |
|---|---|---|
| `savedfilters` | array<[`macro-choice`](#shape-macro-choice)> | Found saved filters (at most 10); null when the caller may not use the app. |
| `error` | string | Localized or technical error text when the app is unavailable to the caller or the search failed; otherwise null. |

<a id="shape-macro-supported-features"></a>

#### Shape `macro-supported-features`

Feature flags telling the Confluence side what this server understands.

| key | JSON type | meaning |
|---|---|---|
| `oneSavedFilter` | boolean | Always true: the server supports returning just one saved filter via `oneSavedFilter`/`savedFilterId`. |

<a id="shape-make-default-view-request"></a>

#### Shape `make-default-view-request`

Target of a make-default-view call.

| key | JSON type | meaning |
|---|---|---|
| `structureId` | integer | Structure id whose view settings change (0 when omitted, which normally fails the structure permission check). |
| `pageId` | string | Page id (`structure`, `issue`, `project`, `gadget`, ...); absent means no specific page. |

<a id="shape-managed-structure-page-details"></a>

#### Shape `managed-structure-page-details`

Extra per-structure data loaded only for the visible page of the management table.

| key | JSON type | meaning |
|---|---|---|
| `effectors` | integer | Number of effector rows in the structure (0 if it cannot be determined). |
| `descriptionHtml` | string | Description rendered from Jira wiki markup to HTML (HTML-escaped text when no renderer). |

<a id="shape-managed-structure-problem"></a>

#### Shape `managed-structure-problem`

A problem flagged for a structure in the management table.

A JSON string, one of:

| value | meaning |
|---|---|
| `USER_INACTIVE` | The owner's account is inactive. |
| `USER_DELETED` | The owner no longer exists. |
| `STOPPED` | Generation of the structure is stopped. |

<a id="shape-managed-structure-row"></a>

#### Shape `managed-structure-row`

One row of the structure management table.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Structure id. |
| `name` | string | Structure name. |
| `archived` | boolean | True for archived structures. |
| `ownerKey` | string | User key of the owner; null when none. |
| `myAccess` | [`access-level`](#shape-access-level) | The caller's effective permission level on the structure. |
| `addons` | array<string> | Names of installed add-ons that integrate with this structure (only add-ons with a product icon), in a stable order. |
| `synchronizers` | array<[`managed-structure-synchronizer`](#shape-managed-structure-synchronizer)> | Installed synchronizers of the structure; empty when synchronization is not enabled. |
| `copyProcesses` | array<[`structure-copy-progress`](#shape-structure-copy-progress)> | Copy operations from this structure visible to the caller (only for logged-in callers). |
| `favorite` | boolean | True when it is one of the caller's favourites. |
| `stars` | integer | Number of users who marked it favourite. |
| `lastOpened` | string | Date the structure was last opened by anyone, formatted for the caller (date only); null when unknown. |
| `lastOpenedForSort` | string | Same date as ISO-8601 `yyyy-MM-dd` for sorting; `0` when unknown. |
| `adjustable` | boolean | True when manual adjustments are enabled for the structure. |
| `adjusted` | boolean | True when manual adjustments exist (only computed when adjustable). |
| `problems` | array<[`managed-structure-problem`](#shape-managed-structure-problem)> | Set of problems to flag, see the problem shape; empty when none. |

<a id="shape-managed-structure-synchronizer"></a>

#### Shape `managed-structure-synchronizer`

An installed synchronizer of a structure as shown in the management table.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Synchronizer instance id. |
| `desc` | string | Localized one-line description of the synchronizer and its configuration. |
| `extra` | string | Further configuration details, comma-separated. |

<a id="shape-managed-structures-table"></a>

#### Shape `managed-structures-table`

Rows of the structure management table plus the users they refer to.

| key | JSON type | meaning |
|---|---|---|
| `structures` | array<[`managed-structure-row`](#shape-managed-structure-row)> | The rows. |
| `users` | array<[`user-display-info`](#shape-user-display-info)> | User details for the owners and the caller; callers who are neither Jira administrators nor allowed to pick users only receive their own entry (or none when anonymous). |

<a id="shape-note-create-request"></a>

#### Shape `note-create-request`

Data for a new note.

| key | JSON type | meaning |
|---|---|---|
| `name` | string | Note name; non-blank, at most 190 characters, trimmed before storing. |
| `structureId` | integer | Id of the structure that owns the note and whose edit permission governs it; required, 0 or absent is rejected. |

<a id="shape-note-edit-permission"></a>

#### Shape `note-edit-permission`

Whether the caller may change a note.

| key | JSON type | meaning |
|---|---|---|
| `allowed` | boolean | true when the caller may rename or archive the note: the note is not archived and the caller has edit permission on the owning structure. Always false for the built-in default note. |
| `reason` | string | When not allowed, a localized explanation (archived; no permission on the named structure; default note cannot be changed); may be null. |

<a id="shape-note-record"></a>

#### Shape `note-record`

A note (named text attribute) and whether the caller may edit it.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Note id: `notes` for the built-in default note, `dc_note_<n>` for stored notes. |
| `name` | string | Display name; for an archived note the localized form 'Name (Archived)'. |
| `archived` | boolean | true when the note has been archived. |
| `editAllowedResponse` | [`note-edit-permission`](#shape-note-edit-permission) | Whether the caller may rename or archive the note, and why not. |

<a id="shape-note-rename-request"></a>

#### Shape `note-rename-request`

New name for a note.

| key | JSON type | meaning |
|---|---|---|
| `name` | string | New name; non-blank, at most 190 characters, trimmed. |

<a id="shape-note-search-group"></a>

#### Shape `note-search-group`

A titled group of found notes.

| key | JSON type | meaning |
|---|---|---|
| `title` | string | Localized group title ('Used in structure', 'Other notes'); null for the group holding the default note. |
| `notes` | array<[`note-search-hit`](#shape-note-search-hit)> | Found notes, sorted by name then id. |

<a id="shape-note-search-hit"></a>

#### Shape `note-search-hit`

A note found by the note search.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Note id (`notes` or `dc_note_<n>`). |
| `name` | string | Note name (plain text). |
| `html` | string | Note name HTML-escaped, with the matched part wrapped in a span of class s-match. |
| `editAllowedResponse` | [`note-edit-permission`](#shape-note-edit-permission) | Whether the caller may change this note. |

<a id="shape-note-search-result"></a>

#### Shape `note-search-result`

Grouped result of a note picker search.

| key | JSON type | meaning |
|---|---|---|
| `groups` | array<[`note-search-group`](#shape-note-search-group)> | Groups in display order; only non-empty groups are present. |
| `hasMore` | boolean | true when more notes matched than the requested limit allowed. |

<a id="shape-panel-configuration"></a>

#### Shape `panel-configuration`

Computed configuration of the structure panel on a Jira page.

| key | JSON type | meaning |
|---|---|---|
| `autoSwitch` | string | Auto-switch mode of the panel: `off` (keep the most recent structure), `withIssue` (switch to a structure containing the issue; default) or `default` (show the default structure). |
| `autoCollapse` | boolean | Issue pages only: whether the panel starts collapsed (default true). |
| `keepStructureWhenNavigating` | boolean | Issue pages only: whether the navigation hint is honoured (default true). |
| `defaultStructure` | [`structure-summary`](#shape-structure-summary) | The default structure for the project (falls back to the global default when the project's one is archived); absent if none or not viewable. |
| `initialStructure` | [`structure-summary`](#shape-structure-summary) | Structure to show first; absent when none applies. |
| `userConfigurable` | boolean | True for logged-in callers (who may save preferences). |
| `projectAdmin` | boolean | Project pages only: whether the caller administers the project. |
| `issueMissingFromInitialStructure` | boolean | Issue pages only: true when the issue is not in the initial structure (or there is none). |
| `singleStructure` | boolean | True when the caller can see exactly one structure (it is then the initial one); absent otherwise. |

<a id="shape-panel-preferences"></a>

#### Shape `panel-preferences`

A user's structure-panel preferences.

| key | JSON type | meaning |
|---|---|---|
| `autoSwitch` | string | Auto-switch mode of the panel: `off` (keep the most recent structure), `withIssue` (switch to a structure containing the issue; default) or `default` (show the default structure). |
| `autoCollapse` | boolean | Whether the structure panel starts collapsed. |
| `keepStructureWhenNavigating` | boolean | Whether the structure the user came from is kept when navigating to an issue. |

<a id="shape-panel-preferences-update"></a>

#### Shape `panel-preferences-update`

Preference changes plus the page context they apply to.

| key | JSON type | meaning |
|---|---|---|
| `autoSwitch` | string | Auto-switch mode of the panel: `off` (keep the most recent structure), `withIssue` (switch to a structure containing the issue; default) or `default` (show the default structure). |
| `autoCollapse` | boolean | Whether the structure panel starts collapsed. |
| `keepStructureWhenNavigating` | boolean | Whether the structure the user came from is kept when navigating to an issue. |
| `forIssue` | integer | Issue id; the issue's project is the scope and the auto-switch mode is stored for issue pages. |
| `forProject` | string | Project key; scope project when no issue is given. |
| `forAgileBoard` | integer | Agile board id (context marker). |

<a id="shape-permission-subject"></a>

#### Shape `permission-subject`

Who a permission or sharing rule applies to: a user, a group, a project role or anyone. Only the id field(s) for the given type are used; the others are null.

| key | JSON type | meaning |
|---|---|---|
| `subject` | string | Subject type: `user`, `group`, `projectRole` or `anyone` (case-insensitive on input; written in this form on output). Required. |
| `groupId` | string | Group name, for `group`. |
| `projectId` | integer | Jira project id, for `projectRole`; 0 means the role in any project. |
| `roleId` | integer | Jira project role id, for `projectRole`. |
| `userKey` | string | Jira user key, for `user`. |

<a id="shape-perspective-email-request"></a>

#### Shape `perspective-email-request`

Request to e-mail a perspective link.

| key | JSON type | meaning |
|---|---|---|
| `perspectiveId` | integer | Id of a stored perspective. |
| `recipients` | array<string> | Jira user keys of the recipients; at least one. |
| `message` | string | Personal message included in the mail; a default sentence is used when empty. |

<a id="shape-pickable-issue-field"></a>

#### Shape `pickable-issue-field`

An issue field for which a value picker is available.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Jira field id, e.g. `status` or `customfield_10010`. |
| `label` | string | Field name in the caller's language (translated name for system fields, custom field name otherwise). |

<a id="shape-picker-option"></a>

#### Shape `picker-option`

One option from an option source.

| key | JSON type | meaning |
|---|---|---|
| `value` | string | Option id as a string: project id, issue type / priority id, version or component id, sprint id, user key, group name, or custom field option id. |
| `label` | string | Display text: 'Name (KEY)' for projects; translated name for issue types and priorities; formatted sprint name; 'Display Name (username)' (with email when visible) for users; name otherwise. |
| `html` | string | Highlighted HTML label for search results (escaped label inside a span, match in a span of class s-match); null elsewhere. |
| `icon` | string | Icon URL: issue type/priority icon, small project avatar, or `<base url>/secure/useravatar?ownerId=<user key>` for users; null when none. |
| `group` | string | Message key (not translated text) of the sub-group the option belongs to, used by the client for grouping and headings: e.g. recent vs other projects, archived projects, released / unreleased / archived versions, archived components, sprints of suggested boards; null when ungrouped. |

<a id="shape-picker-result-group"></a>

#### Shape `picker-result-group`

A labelled group of picker suggestions.

| key | JSON type | meaning |
|---|---|---|
| `label` | string | Localized group heading (e.g. recent, favorites, found). |
| `footer` | string | Localized footer text (e.g. hint or 'N more' notice); absent when none. |
| `items` | array<[`picker-search-item`](#shape-picker-search-item)> | Suggestions in display order. |

<a id="shape-picker-search-item"></a>

#### Shape `picker-search-item`

One entry of a search-box result list (user, group, role or project picker).

| key | JSON type | meaning |
|---|---|---|
| `value` | string | The value to store when the item is chosen (format defined by the endpoint, e.g. `group:<name>` or a project id). |
| `label` | string | Plain display text. |
| `title` | string | Optional tooltip or secondary text; null when not used. |
| `html` | string | Display HTML with the matched part of the search text highlighted; already escaped. |
| `entity` | any | Optional full object for the item; null for the endpoints in this group. |
| `icon` | string | Icon or avatar URL, or null. |
| `id` | string | Always equal to `value`. |
| `params` | map<string, string> | Optional extra string attributes (absent when there are none). |

<a id="shape-picker-search-result"></a>

#### Shape `picker-search-result`

Result of a search-box query: a list of titled groups of items.

| key | JSON type | meaning |
|---|---|---|
| `query` | string | Echo of the search text; null for the endpoints in this group. |
| `groups` | array<[`picker-result-group`](#shape-picker-result-group)> | Groups of results in display order, each a [`picker-result-group`](#shape-picker-result-group); empty array when nothing matched. |

<a id="shape-poll-request"></a>

#### Shape `poll-request`

What the client watches.

| key | JSON type | meaning |
|---|---|---|
| `jobId` | integer | Absent on the first call. Set to the `jobId` returned by an earlier call that timed out, to keep waiting for that job (see the endpoint). |
| `extensionRequests` | map<string, any> | Optional map from core-extension key to an extension-specific request; each installed extension may answer under the same key in `extensionData`. |
| `forests` | array<[`forest-poll-entry`](#shape-forest-poll-entry)> | Watched forests with their versions; null = none. |
| `items` | [`items-poll-entry`](#shape-items-poll-entry) | Items version for item-change tracking; null = none. |
| `subscriptions` | array<[`attribute-subscription-poll-entry`](#shape-attribute-subscription-poll-entry)> | Attribute subscriptions to update, each with `id` and `version`; null = none. |

<a id="shape-poll-response"></a>

#### Shape `poll-response`

Everything that changed for the client.

| key | JSON type | meaning |
|---|---|---|
| `forestUpdates` | array<[`forest-update`](#shape-forest-update)> | One update per watched forest with a valid spec; null when no forests were asked. |
| `itemsUpdate` | [`items-update`](#shape-items-update) | Item changes; null when not asked. |
| `itemTypes` | map<any, any> | Map from the decimal item-type numbers used in this response's forest or item encodings to full item type keys (e.g. `"3": "com.almworks.jira.structure:type-folder"`). Only types that occur in this response are listed. |
| `extensionData` | map<string, any> | Map from core-extension key to extension-specific data returned for the request's `extensionRequests`; absent or null when no extension answered. |
| `subscriptionUpdates` | array<[`attribute-subscription-update`](#shape-attribute-subscription-update)> | One update per requested subscription, in order; null when none asked. |
| `backgroundProcesses` | array<[`background-effector-process`](#shape-background-effector-process)> | The caller's running or unacknowledged effector processes; null for anonymous callers or when none. |

<a id="shape-project-list"></a>

#### Shape `project-list`

List of projects, optionally with role definitions.

| key | JSON type | meaning |
|---|---|---|
| `projects` | array<[`project-ref`](#shape-project-ref)> | Projects in name order. |
| `roles` | array<[`project-role-ref`](#shape-project-role-ref)> | Only with `withRoles` and when non-empty: the project roles referenced by `userRoles`. |

<a id="shape-project-ref"></a>

#### Shape `project-ref`

A Jira project.

| key | JSON type | meaning |
|---|---|---|
| `key` | string | Project key. |
| `id` | integer | Project id. |
| `name` | string | Project name. |
| `description` | string | Project description. |
| `iconUrl` | string | Small avatar URL. |
| `userRoles` | array<integer> | Only with `withRoles`: ids of all project roles defined in Jira (not filtered by the caller's membership). |

<a id="shape-project-role-list"></a>

#### Shape `project-role-list`

List of project roles.

| key | JSON type | meaning |
|---|---|---|
| `roles` | array<[`project-role-ref`](#shape-project-role-ref)> | The roles. |

<a id="shape-project-role-ref"></a>

#### Shape `project-role-ref`

A Jira project role.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Role id. |
| `name` | string | Role name. |
| `description` | string | Role description. |

<a id="shape-query-check-result"></a>

#### Shape `query-check-result`

Outcome of validating a query.

| key | JSON type | meaning |
|---|---|---|
| `errors` | array<string> | Localized error messages; null when the query is valid. |

<a id="shape-quick-transform"></a>

#### Shape `quick-transform`

A saved quick transformation of a structure (a one-click filter, sort, group or similar). Polymorphic with the group variant: an object whose `key` is `group` is read as a group.

| key | JSON type | meaning |
|---|---|---|
| `key` | string | Transformation type key (anything except `group`). |
| `quick` | [`quick-transform-button`](#shape-quick-transform-button) | Button settings (id, label, color). |
| `module` | string | Complete module key of the transformation provider. |
| `params` | map<string, any> | Provider-specific parameters. |

<a id="shape-quick-transform-button"></a>

#### Shape `quick-transform-button`

How a quick transformation appears.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Unique id within the structure's list. |
| `name` | string | Button label. |
| `color` | string | Button color (CSS color value). |

<a id="shape-quick-transform-entry"></a>

#### Shape `quick-transform-entry`

An entry of a structure's quick transformations list: either a transformation or a group (by `key`). Entries without `key` are dropped. Ids must be unique across the list including group members.

| key | JSON type | meaning |
|---|---|---|
| `key` | string | `group` for a group, otherwise the transformation type key. |
| `quick` | [`quick-transform-button`](#shape-quick-transform-button) | Button settings. |

<a id="shape-quick-transform-group"></a>

#### Shape `quick-transform-group`

A group of quick transformations shown together.

| key | JSON type | meaning |
|---|---|---|
| `key` | string | Always `group`. |
| `quick` | [`quick-transform-button`](#shape-quick-transform-button) | Button settings of the group. |
| `transforms` | array<[`quick-transform`](#shape-quick-transform)> | Member transformations. |

<a id="shape-row-mapping-entry"></a>

#### Shape `row-mapping-entry`

Translation of the requested rows into one forest.

| key | JSON type | meaning |
|---|---|---|
| `forestSpec` | [`forest-spec`](#shape-forest-spec) | The forest, echoed. |
| `mappedRows` | array<integer> | One row id per requested row, same order; 0 when no corresponding row exists (-1 maps to -1). |

<a id="shape-row-mapping-request"></a>

#### Shape `row-mapping-request`

Rows to translate into other forests.

| key | JSON type | meaning |
|---|---|---|
| `forestSpecs` | array<[`forest-spec`](#shape-forest-spec)> | Target forests. |
| `rows` | array<integer> | Row ids to translate. |

<a id="shape-row-mapping-response"></a>

#### Shape `row-mapping-response`

Row translations per forest.

| key | JSON type | meaning |
|---|---|---|
| `rows` | array<integer> | The requested rows, echoed. |
| `mappings` | array<[`row-mapping-entry`](#shape-row-mapping-entry)> | One entry per requested forest. |
| `itemsVersion` | [`data-version`](#shape-data-version) | Current items version at the time of the call. |

<a id="shape-row-values-attribute-column"></a>

#### Shape `row-values-attribute-column`

Values of one attribute for the answered rows.

| key | JSON type | meaning |
|---|---|---|
| `attribute` | [`attribute-spec`](#shape-attribute-spec) | The attribute spec as normalized by the server (params null when empty). |
| `values` | array<any> | One value per row of the entry's `rows`, same order, encoded per the attribute's format; null when the row has no value. |
| `trailMode` | string | Not filled in (null). |
| `trails` | array<string> | Always an empty list. |

<a id="shape-row-values-request"></a>

#### Shape `row-values-request`

One-shot request for attribute values of rows in one or more forests.

| key | JSON type | meaning |
|---|---|---|
| `jobId` | integer | Absent on the first call. Set to the `jobId` returned by an earlier call that timed out, to keep waiting for that job (see the endpoint). |
| `requests` | array<[`row-values-request-entry`](#shape-row-values-request-entry)> | List of per-forest requests. |

<a id="shape-row-values-request-entry"></a>

#### Shape `row-values-request-entry`

Rows and attributes wanted from one forest.

| key | JSON type | meaning |
|---|---|---|
| `forestSpec` | [`forest-spec`](#shape-forest-spec) | The forest the rows belong to. |
| `signature` | integer | Accepted and ignored. |
| `rows` | array<integer> | Row ids whose values are wanted; empty/absent = no values. |
| `attributes` | array<[`attribute-spec`](#shape-attribute-spec)> | Attributes wanted for every row; empty/absent = no values. |

<a id="shape-row-values-response"></a>

#### Shape `row-values-response`

Answer to a one-shot values request.

| key | JSON type | meaning |
|---|---|---|
| `responses` | array<[`row-values-response-entry`](#shape-row-values-response-entry)> | One entry per request entry, same order. |
| `itemTypes` | map<any, any> | Always an empty object in this answer. |
| `itemsVersion` | [`data-version`](#shape-data-version) | The oldest items version on which the returned values are based (signature 0, version 0 when nothing was computed); a client can poll item changes from it. |

<a id="shape-row-values-response-entry"></a>

#### Shape `row-values-response-entry`

Values computed for one forest.

| key | JSON type | meaning |
|---|---|---|
| `forestSpec` | [`forest-spec`](#shape-forest-spec) | The spec from the request, echoed. |
| `rows` | array<integer> | The rows actually answered, in request order, without inaccessible rows; absent when no rows or attributes were requested. |
| `data` | array<[`row-values-attribute-column`](#shape-row-values-attribute-column)> | One column per requested attribute (unknown-format attributes omitted). |
| `forestVersion` | [`data-version`](#shape-data-version) | Version of the forest the values were computed against. |
| `inaccessibleRows` | array<integer> | Requested rows whose item is missing or invisible to the caller; absent when none. |

<a id="shape-saved-column"></a>

#### Shape `saved-column`

A reusable column configuration from a saved-column list. Boolean fields are either true or absent/null (never false).

| key | JSON type | meaning |
|---|---|---|
| `composedId` | string | Global column reference `<source id>/<column id>`, e.g. `stored/12` or `bundled/3`; this is what a view column stores to refer to the saved column. |
| `listId` | string | The list the column belongs to, `<source id>/<list key>`, e.g. `stored/global`, `stored/user`, `bundled/bundled`. |
| `name` | string | Column name (localized for bundled columns). |
| `description` | string | Column description (localized for bundled columns); may be null. |
| `type` | string | Column type key, i.e. the kind of column as used in view specifications (bundled columns are all `formula`). |
| `params` | map<string, any> | The column's configuration parameters as a JSON object (as in a view column specification); null when empty. |
| `shouldOpenConfigurator` | boolean | true when the client should open the column settings right after adding the column (some bundled presets); otherwise null. |
| `featured` | boolean | true for columns to be highlighted in the column picker (some bundled presets); otherwise null. |
| `editable` | boolean | true when the caller may change or delete the column (own user column, or global column with the 'manage global saved columns' permission); otherwise null. Bundled columns are never editable. |

<a id="shape-saved-column-input"></a>

#### Shape `saved-column-input`

Properties of a saved column to create or change. Which fields are used depends on the endpoint (full replace, name/description only, or parameters only).

| key | JSON type | meaning |
|---|---|---|
| `name` | string | Column name. |
| `description` | string | Column description. |
| `type` | string | Column type key (kind of column, as in a view column specification). |
| `parameters` | map<string, any> | Column configuration parameters as a JSON object; null is stored as an empty object. |

<a id="shape-saved-column-list"></a>

#### Shape `saved-column-list`

One list of saved columns (bundled presets, global columns, or the caller's own columns).

| key | JSON type | meaning |
|---|---|---|
| `id` | string | List reference `<source id>/<list key>`: `bundled/bundled`, `stored/global` or `stored/user`. |
| `sourceId` | string | Column source: `bundled` or `stored`. |
| `name` | string | Localized list name: 'Bundled', 'Global', 'My Columns'. |
| `columns` | array<[`saved-column`](#shape-saved-column)> | Columns in the list, as [`saved-column`](#shape-saved-column); for the user list only the caller's own columns. |
| `createSupported` | boolean | true when the caller may add columns to this list (user list for logged-in callers; global list with the 'manage global saved columns' permission); otherwise null. Never true for the bundled list. |

<a id="shape-saved-filter-ref"></a>

#### Shape `saved-filter-ref`

A Jira saved filter.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Filter id. |
| `name` | string | Filter name. |

<a id="shape-shared-perspective"></a>

#### Shape `shared-perspective`

A stored, shareable snapshot of the structure page state.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Perspective id: random positive integer below 2^31; absent in a share request. |
| `spec` | any | The page state: any JSON value, stored and returned verbatim (not as a string). The plugin itself reads only `primary.forestSpec.structureId` (the structure shown, used for e-mail sharing) and the view specifications under `primary.viewSpec` and `secondary.viewSpec`. |

<a id="shape-structure-copy-progress"></a>

#### Shape `structure-copy-progress`

A running or recent structure-copy operation started from this structure.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Background process id of the copy. |
| `status` | string | `running` (queued or running), `waiting` (finished successfully, waiting to be acknowledged), or `failed`. |
| `progressPercent` | integer | Completion percentage 0..100. |

<a id="shape-structure-description-shown-flag"></a>

#### Shape `structure-description-shown-flag`

Whether the structure's description is shown above the grid.

| key | JSON type | meaning |
|---|---|---|
| `descriptionShown` | boolean | True when shown. |

<a id="shape-structure-error"></a>

#### Shape `structure-error`

Error details returned by Structure as a JSON body.

| key | JSON type | meaning |
|---|---|---|
| `code` | integer | Numeric error code (e.g. 2400 invalid parameter, 4005 structure missing or not accessible, 4800 unknown subscription). |
| `error` | string | Error name with code, e.g. `INVALID_PARAMETER[2400]`, or a short text for generic errors (`Invalid request data`, `Permission violation`). |
| `structureId` | integer | Structure the error is about; absent when none. |
| `viewId` | integer | View the error is about; absent when none. |
| `rowId` | integer | Row the error is about. |
| `itemId` | string | Full item id the error is about; absent when none. |
| `itemDescription` | string | Display text of that item. |
| `message` | string | Technical message. |
| `localizedMessage` | string | Message in the caller's language. |

<a id="shape-structure-favorite-flag"></a>

#### Shape `structure-favorite-flag`

Favourite state of a structure for the caller.

| key | JSON type | meaning |
|---|---|---|
| `favorite` | boolean | True when favourite. |

<a id="shape-structure-gadget-meta"></a>

#### Shape `structure-gadget-meta`

Render data for the structure dashboard gadget.

| key | JSON type | meaning |
|---|---|---|
| `loggedInUser` | [`user-display-info`](#shape-user-display-info) | The current user as shown in gadgets. |
| `structure` | [`structure-summary`](#shape-structure-summary) | The configured structure if viewable. |
| `view` | [`grid-view`](#shape-grid-view) | View for normal mode if viewable. |
| `canvasView` | [`grid-view`](#shape-grid-view) | View for canvas (maximized) mode if viewable. |
| `filter` | [`saved-filter-ref`](#shape-saved-filter-ref) | The configured saved filter if accessible. |
| `operations` | array<[`issue-operation-link`](#shape-issue-operation-link)> | Issue operation links from Jira's issue operations bar. |
| `errors` | [`validation-errors`](#shape-validation-errors) | Problems found; empty lists when none. General error texts are message keys. |

<a id="shape-structure-history-change"></a>

#### Shape `structure-history-change`

One change within a history version.

| key | JSON type | meaning |
|---|---|---|
| `operation` | string | `add`, `copy`, `move` or `remove`. |
| `moveDirection` | integer | For moves: -1 moved up, 1 moved down, 0 otherwise. |
| `forestSize` | integer | Number of rows affected. |
| `itemId` | string | When exactly one row is affected: its item in the forest encoding's item form; absent otherwise or when the row is gone. |
| `issueKey` | string | When that item is an issue visible to the caller: its key. |
| `issueSummary` | string | ...and its summary. |
| `forest` | string | Single-version call only: the affected sub-forest in the forest encoding. |
| `parentPathFrom` | string | Single-version call only: comma-separated row ids from the top to the parent before the change; null when empty. |
| `precedingSiblingsFrom` | string | Single-version call only: comma-separated row ids of the siblings preceding it before the change; null when empty. |
| `parentPathTo` | string | Same as `parentPathFrom`, after the change. |
| `precedingSiblingsTo` | string | Same as `precedingSiblingsFrom`, after the change. |

<a id="shape-structure-history-page"></a>

#### Shape `structure-history-page`

A list of structure history versions.

| key | JSON type | meaning |
|---|---|---|
| `versions` | array<[`structure-history-version`](#shape-structure-history-version)> | Versions, newest first; absent when there are none. |
| `itemTypes` | map<string, string> | Item-type number map for this list; in practice empty because each version carries its own map. |

<a id="shape-structure-history-version"></a>

#### Shape `structure-history-version`

One version in a structure's history.

| key | JSON type | meaning |
|---|---|---|
| `structure` | integer | Structure id. |
| `version` | integer | Version number. |
| `timestamp` | integer | Time of the change, milliseconds since the epoch. |
| `dateTimeFormatted` | string | Same time formatted for the caller in relative style (e.g. 'yesterday 5:10 PM'). |
| `user` | [`user-display-info`](#shape-user-display-info) | Who made the change (an anonymous placeholder when no user). |
| `synchronizer` | [`history-synchronizer`](#shape-history-synchronizer) | Synchronizer that made the change; absent for manual changes. |
| `changes` | array<[`structure-history-change`](#shape-structure-history-change)> | The changes in this version. |
| `fullForest` | string | Only in the single-version call: the whole forest right after this version, in the forest encoding. |
| `itemTypes` | map<string, string> | Map from the decimal item-type numbers used in this response's forest or item encodings to full item type keys (e.g. `"3": "com.almworks.jira.structure:type-folder"`). Only types that occur in this response are listed. |

<a id="shape-structure-migration-stats"></a>

#### Shape `structure-migration-stats`

Counts describing one structure's current forest, for planning a migration to the cloud. All counts are row counts in the forest (an item appearing in several rows counts several times).

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Structure id. |
| `size` | integer | Total number of rows. |
| `issues` | integer | Rows that are Jira issues. |
| `folders` | integer | Rows that are folders. |
| `memos` | integer | Rows that are memos. |
| `pages` | integer | Rows that are Confluence pages. |
| `generators` | integer | Rows that are generators (automation) of any kind. |
| `inserters` | integer | Generator rows that are inserters. |
| `extenders` | integer | Generator rows that are extenders. |
| `groupers` | integer | Generator rows that are groupers. |
| `filters` | integer | Generator rows that are filters. |
| `sorters` | integer | Generator rows that are sorters. |
| `effectors` | integer | Rows that are effectors. |
| `projects` | array<string> | Names of the distinct projects of the issues (and other project-bearing items) in the forest, sorted by the caller's locale. |

<a id="shape-structure-picker-list"></a>

#### Shape `structure-picker-list`

Data for the structure selector. The id lists refer to entries of `structures`.

| key | JSON type | meaning |
|---|---|---|
| `recent` | array<integer> | The caller's recent structure ids. |
| `favorites` | array<integer> | The caller's favourite structure ids. |
| `defaults` | array<integer> | Default structures: the project's default (if any) and the global default when different; archived or invisible ones omitted. |
| `containingAnchor` | array<integer> | With an anchor issue: viewable structures containing it, recently used first; absent otherwise. |
| `structures` | array<[`structure-summary`](#shape-structure-summary)> | The structures referenced by the lists. |
| `maxItems` | integer | How many entries per list the selector should show: max(4, Jira's dropdown item limit / 2 - 1); lists carry up to 2 more. |
| `totalFavorites` | integer | Total number of favourites before truncation. |
| `totalContainingAnchor` | integer | Total number of structures containing the anchor before truncation; absent without anchor. |
| `anchorIssue` | integer | The anchor issue id, when it was accepted. |

<a id="shape-structure-summary"></a>

#### Shape `structure-summary`

A structure as seen by the caller.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Structure id. |
| `name` | string | Name. |
| `description` | string | Plain-text description. |
| `descriptionHtml` | string | Description rendered as HTML, when requested by the endpoint. |
| `readOnly` | boolean | True when archived or the caller cannot edit; absent otherwise. |
| `generatorConfigurationAllowed` | boolean | True when the caller may configure automation; absent otherwise. |
| `effectorConfigurationAllowed` | boolean | True when the caller may configure effectors; absent otherwise. |
| `effectorExecutionAllowed` | boolean | True when the caller may run effectors; absent otherwise. |
| `adminable` | boolean | True when the caller administers it; absent otherwise. |
| `editable` | boolean | True when the caller can edit; absent otherwise. |
| `editRequiresParentIssuePermission` | boolean | True when moving items under an issue requires edit permission on that parent issue. |
| `permissions` | array<[`access-rule`](#shape-access-rule)> | Permission rules, only when requested and the caller administers it. |
| `owner` | string | Owner as `user:<user key>`, only when requested and the caller may see users or is the owner. |
| `favorite` | boolean | Whether the caller marked it favorite, when the endpoint reports it. |
| `isArchived` | boolean | True when archived. |

<a id="shape-structure-summary-list"></a>

#### Shape `structure-summary-list`

List of structures.

| key | JSON type | meaning |
|---|---|---|
| `haveMore` | boolean | True when more results exist than returned (paged endpoints); absent otherwise. |
| `structures` | array<[`structure-summary`](#shape-structure-summary)> | Structures the caller can view. |

<a id="shape-synchronizer-undo-batch"></a>

#### Shape `synchronizer-undo-batch`

Groups of synchronizer audit-log actions, paired with the synchronizer that made them.

| key | JSON type | meaning |
|---|---|---|
| `jobId` | integer | Absent on the first call. Set to the `jobId` returned by an earlier call that timed out, to keep waiting for that job (see the endpoint). |
| `actionGroups` | array<string> | Each entry is the text of a JSON array of action objects as recorded in the synchronizer audit log (e.g. link actions with `type` `createLink`/`removeLink`, `linkTypeId`, `source.id`, `destination.id`). |
| `syncModuleKeys` | array<string> | Complete module key of the synchronizer for the group at the same index (e.g. `com.almworks.jira.structure:sync-links`). |

<a id="shape-tempo-account-option"></a>

#### Shape `tempo-account-option`

A Tempo account offered in a picker.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Tempo account id (integer). |
| `name` | string | Account name. |
| `key` | string | Account key. |
| `status` | string | Account status as localized display text (open, closed or archived), not a code. |

<a id="shape-tempo-team-option"></a>

#### Shape `tempo-team-option`

A Tempo team offered in a picker.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Tempo team id (integer). |
| `name` | string | Team name. |

<a id="shape-tempo-team-role-option"></a>

#### Shape `tempo-team-role-option`

A Tempo team role offered in a picker.

| key | JSON type | meaning |
|---|---|---|
| `id` | integer | Tempo team role id (integer). |
| `name` | string | Role name. |

<a id="shape-third-party-item-type"></a>

#### Shape `third-party-item-type`

A custom item type contributed by another app that users can add to structures.

| key | JSON type | meaning |
|---|---|---|
| `type` | string | Complete module key identifying the item type. |
| `title` | string | Display name of the type. |
| `newItemTitle` | string | Label for the 'new item of this type' action. |
| `weight` | integer | Sort weight (ascending, then by title); types without one sort last. |

<a id="shape-time-zone-info"></a>

#### Shape `time-zone-info`

A time zone with its current offset.

| key | JSON type | meaning |
|---|---|---|
| `name` | string | Time zone id (e.g. `Europe/Berlin`). |
| `offset` | integer | Current offset in milliseconds with inverted sign: positive west of UTC (UTC+2 gives -7200000). |

<a id="shape-tuning-property-state"></a>

#### Shape `tuning-property-state`

Current state of one app tuning property.

| key | JSON type | meaning |
|---|---|---|
| `key` | string | Property name. |
| `value` | string | Effective value: the value stored in Jira's application properties if non-empty, else the JVM system property value, else null. |
| `removable` | boolean | true when the value comes from Jira's application properties (and can be deleted through this API); false when it comes from a JVM system property or is unset. |

<a id="shape-tuning-property-update"></a>

#### Shape `tuning-property-update`

New value for one app tuning property.

| key | JSON type | meaning |
|---|---|---|
| `key` | string | Property name; must start with `com.almworks.`, `almworks.`, `structure.` or `testy.` and must not be a protected key. |
| `value` | string | New value as a string; null removes the stored value. |

<a id="shape-update-item-request"></a>

#### Shape `update-item-request`

Request to update an existing item.

| key | JSON type | meaning |
|---|---|---|
| `jobId` | integer | Absent on the first call. Set to the `jobId` returned by an earlier call that timed out, to keep waiting for that job (see the endpoint). |
| `extensionRequests` | map<string, any> | Optional map from core-extension key to an extension-specific request; each installed extension may answer under the same key in `extensionData`. |
| `items` | [`items-poll-entry`](#shape-items-poll-entry) | Items version the client holds (required). |
| `item` | [`item-content-spec`](#shape-item-content-spec) | The item id and new values. |
| `forest` | [`forest-poll-entry`](#shape-forest-poll-entry) | Forest the item is shown in and the client's version of it (required); also scopes note updates. |

<a id="shape-update-item-response"></a>

#### Shape `update-item-response`

Result of updating an item.

| key | JSON type | meaning |
|---|---|---|
| `success` | boolean | True when no validation errors occurred. |
| `successfulActions` | integer | Always 1. |
| `formErrors` | array<string> | Messages not tied to a field (on failure). |
| `fieldErrors` | map<string, string> | Messages by field id (on failure). |
| `itemsUpdate` | [`items-update`](#shape-items-update) | Item changes since the client's items version. |
| `itemTypes` | map<any, any> | Map from the decimal item-type numbers used in this response's forest or item encodings to full item type keys (e.g. `"3": "com.almworks.jira.structure:type-folder"`). Only types that occur in this response are listed. |
| `extensionData` | map<string, any> | Map from core-extension key to extension-specific data returned for the request's `extensionRequests`; absent or null when no extension answered. |
| `forestUpdates` | array<[`forest-update`](#shape-forest-update)> | One forest update from the client's forest version. |

<a id="shape-usage-counters"></a>

#### Shape `usage-counters`

A batch of client usage counters.

| key | JSON type | meaning |
|---|---|---|
| `timestamp` | integer | Time the counters belong to, epoch milliseconds. Required. |
| `stats` | map<string, integer> | Map from counter name to the amount to add. |

<a id="shape-user-display-info"></a>

#### Shape `user-display-info`

Display data of a Jira user.

| key | JSON type | meaning |
|---|---|---|
| `name` | string | Username (or a localized 'anonymous' text when unknown). |
| `userKey` | string | User key (empty string for anonymous). |
| `displayName` | string | Display name; marked as inactive for deactivated users. |
| `profileUrl` | string | Absolute URL `<base>/secure/ViewProfile.jspa?name=<username>`; absent for unknown users. |
| `avatarUrl` | string | Avatar image URL. |

<a id="shape-validation-errors"></a>

#### Shape `validation-errors`

Validation problems of a form.

| key | JSON type | meaning |
|---|---|---|
| `errorMessages` | array<string> | General (not field-bound) messages. |
| `errors` | array<[`field-error`](#shape-field-error)> | Field-bound messages. |
| `empty` | boolean | True when both lists are empty. |

<a id="shape-view-column"></a>

#### Shape `view-column`

One grid column.

| key | JSON type | meaning |
|---|---|---|
| `key` | string | Column type key (e.g. `main`, `field`, `progress`, `icons`). Required on write. |
| `name` | string | Custom column header; absent means the type's default header. |
| `csid` | string | Column id unique within the view. Required on write. |
| `params` | map<any, any> | Type-specific settings (e.g. which field to show); keys must be strings. |

<a id="shape-view-layout"></a>

#### Shape `view-layout`

Columns and display options of a view.

| key | JSON type | meaning |
|---|---|---|
| `columns` | array<[`view-column`](#shape-view-column)> | Columns, left to right. |
| `columnDisplayMode` | integer | 1 = auto-fit columns to width, 2 = scrollable fixed widths; 0 or invalid on write keeps the default. |
| `rowDisplayMode` | integer | 11 = one line per row, 12 = wrap text; 0 or invalid on write keeps the default. |
| `pins` | array<string> | Column `csid` values of columns pinned to the left. |

<a id="shape-view-usage"></a>

#### Shape `view-usage`

Where a view is used.

| key | JSON type | meaning |
|---|---|---|
| `associatedStructures` | array<[`structure-summary`](#shape-structure-summary)> | Structures (viewable by the caller) whose view menu includes the view. |
| `associatedDefault` | boolean | True when the view is in the global default menu; absent otherwise. |

<a id="shape-work-calendar-entry"></a>

#### Shape `work-calendar-entry`

A work calendar that scheduling features can use.

| key | JSON type | meaning |
|---|---|---|
| `id` | string | Full calendar id `<provider plugin module complete key>/<calendar number>`, e.g. `com.almworks.jira.structure:simple-calendar-provider/1`; this string is what settings store to refer to the calendar. |
| `name` | string | Localized calendar name, e.g. 'Standard calendar 24/7', 'Standard work calendar 8/5'. |
| `description` | string | Localized description of the calendar's working time. |

<a id="shape-work-calendar-list"></a>

#### Shape `work-calendar-list`

All available work calendars.

| key | JSON type | meaning |
|---|---|---|
| `calendars` | array<[`work-calendar-entry`](#shape-work-calendar-entry)> | Calendars: those of the built-in provider first, then other providers by provider key, each provider's calendars in the provider's order. |

<a id="shape-workflow-transition-list"></a>

#### Shape `workflow-transition-list`

List of workflow transitions.

| key | JSON type | meaning |
|---|---|---|
| `transitions` | array<[`workflow-transition-ref`](#shape-workflow-transition-ref)> | The transitions. |

<a id="shape-workflow-transition-ref"></a>

#### Shape `workflow-transition-ref`

A workflow transition leading into a status.

| key | JSON type | meaning |
|---|---|---|
| `workflow` | string | Workflow name. |
| `action` | integer | Transition (action) id within the workflow. |
| `name` | string | Transition name. |
| `sourceStatuses` | array<[`issue-constant`](#shape-issue-constant)> | Statuses from which the transition starts; empty for global transitions. |
<!-- END generated: rest-shapes -->

## 1.4 Servlets, filters and pages

**Pages (webwork actions).** Module `ww-structure` registers server-rendered pages under
`/secure/<alias>.jspa`, and a command as `/secure/<alias>!<command>.jspa`. Users bookmark them, Jira links to
them (section 1.1) and other modules' web items point at them, so every alias and command is kept. Admin pages
are also reachable under `/secure/admin/<alias>.jspa`. The aliases and commands are listed under
`contract.actions` of `ww-structure` in `inventory.json`. What each page shows and does is described in the
claims.

**Servlet `excel-export`** at `/plugins/servlet/structure/excel` (the module's URL pattern is
`/structure/excel*`). `GET` and `POST` behave the same. It exports a structure as an Excel workbook.
| request parameter | meaning |
|---|---|
| `forestSpec` | required: the forest to export, as the JSON of a [`forest-spec`](#shape-forest-spec) (a public API type); missing or unreadable is a 500 |
| `viewId` | the saved view whose columns to use (a number); or |
| `viewSpec` | a view specification (JSON, see the view shapes), used when there is no `viewId` |
| `expand` | the expansion state of the rows, as the board sends it |
| `clientFilter` | the rows to keep, as the board's quick-filter state |
| `xlsx` | `true` for an `.xlsx` (Office Open XML) workbook; otherwise a legacy `.xls` |
| `s` | the structure id, used only in error reports |

Success: `200` with `Content-Type` `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (xlsx)
or `application/vnd.ms-excel` (xls), and `Content-Disposition: attachment; filename="structure.xlsx";
filename*=UTF-8''<name>` (`.xls` for the legacy format). `<name>` is URL-encoded and built as follows:
- take the forest's display name and keep letters and digits;
- turn each run of other characters into one `_`, and stop once 20 characters are written;
- end with `_` unless it already does; if nothing was kept, use `structure_`;
- append the forest's time as `yyMMdd_HHmm` and the extension.

For example, "Q3 plan: team A" at 14:05 on 2026-10-28 gives `Q3_plan_team_A_261028_1405.xlsx`. Failures: `400` for
invalid input, `403` without permission, `404` when the structure or view does not exist, `503` when an
automation step failed, `500` otherwise; the body is the error message.

**Servlet filters.** Each keeps its key, location, weight and URL patterns (`inventory.json`). What they do:
- `end-of-life-decorator`, `stats-offer-decorator`, `plugin-manager-helper`: add a banner or helper resource
  to some pages (claims). With no Marketplace licensing (section 1.1), the licence banners never show.
- `issue-change-interceptor`, `bulk-change-interceptor`, `tempo-internal-issues-interceptor`: watch Jira and
  other apps' requests that change issues without the usual events, so the plugin can refresh its data
  (claims). They never change the request or the response, except the bulk-change one, as its claims say.
- `security-filter` and `partitioned-cookie-header-filter`: let the external gadget page be embedded in an
  application linked to Jira (claims).

## 1.5 Stored data: the Active Objects schema

The plugin keeps all its data in Jira's database through Active Objects (module `ao`), under the namespace
`com.almworks.jira.structure`. Active Objects prefixes every table with `AO_` and the last six hex digits of
the MD5 of the namespace: `AO_8BAD1B_`. The replacement is installed on instances that already hold the
original's data, so:
- declare one entity per table below, with the same table name (`@Table` without the prefix) and the same
  columns: the same names (`@Accessor`/`@Mutator`, or `@PrimaryKey` for a key column), Java types, string
  lengths (`@StringLength`, where `unlimited` is `StringLength.UNLIMITED`) and constraints (not null,
  indexed, unique, primary key, auto increment). Active Objects then finds the tables unchanged;
- read and write every value in the stored format described per column. Rows written by the original must
  read back the same, and rows the replacement writes must be ones the original could have written;
- create no other tables in the namespace.

The `ID` column of a table that has one is Active Objects' own integer key (an entity that extends `Entity`).
Other tables declare their key column themselves.

<!-- BEGIN generated: ao -->
#### Table `AO_8BAD1B_BOOTSTRAP`

Bootstrap/lock marker table of the shared storage layer. Normally holds exactly one row, created lazily (with C_IS_LOCKED=false) the first time the storage layer is touched or the lock flag is read; it is never deleted. Its only meaningful content is the global 'storage locked' flag, raised while a backup restore or data migration rewrites the plugin tables so that all cluster nodes refuse ordinary writes. If several rows exist, the flag is considered raised when ANY row has it true, and lock/unlock writes the flag to every row.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment surrogate key; no meaning (normally 1). |
| `C_IS_LOCKED` | boolean |  |  | Boolean storage-lock flag. true = the plugin data is exclusively locked by a running restore/migration (other operations must fail or wait); false or NULL = unlocked. Set to true when the lock is taken and back to false when released (also on forced unlock). A row stuck at true after a crash blocks writes until it is reset. |

#### Table `AO_8BAD1B_ITEM_TYPE`

Registry that maps item type keys (strings) to compact integer ids used by other tables. One row per distinct item type key ever used; C_KEY is unique. Rows are created on demand (insert-if-absent, retried on unique-constraint conflict) the first time a type key needs an id, and are never updated or deleted, so an id stays stable forever. Referenced by AO_8BAD1B_ROW.C_ITEM_TYPE and AO_8BAD1B_ITEM_EVENTS_V2.C_TYPEID (and other item-referencing tables).

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment integer item type id. This number is what other tables store as the item type; it is local to this database (not portable between instances; backups store the key string instead). |
| `C_KEY` | String | 190 | not null, unique | Item type key, non-blank, unique, max 190 chars. Item type keys are module complete keys of the form '<plugin key>:<module key>'; the built-in ones all start with 'com.almworks.jira.structure:type-' (e.g. 'com.almworks.jira.structure:type-issue', '...:type-folder', '...:type-generator', '...:type-effector', '...:type-memo', '...:type-project', '...:type-user', '...:type-label', '...:type-status', '...:type-version', '...:type-sprint'); third-party item types use their own plugin key. |

#### Table `AO_8BAD1B_ITEM_EVENTS_V2`

Cluster-wide journal of 'item changed' notifications, used only on Jira Data Center (a single-node server keeps this journal in memory and leaves the table empty). Each row says that one item (issue, folder, generator, user, ...) changed at a given time, so other nodes can invalidate caches and refresh structures. Event ids are allocated from a per-node id partition recorded in AO_8BAD1B_NODE_SIGNS_V2: a node writes consecutive ids C_MINEID, C_MINEID+1, ... below C_MAXEID. Rows are only inserted, never updated. Rows in a node's partition are bulk-deleted whenever that node (re)initialises its partition (node start, partition overflow, or write failure) and the whole table is emptied by the maintenance option 'cleanupItemTracker'. Other nodes read the events of each live node in id order starting after the last id they have seen.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_ID` | long |  | primary key, not null | Event id (bigint), explicitly assigned, not auto-increment. Lies in the half-open range [C_MINEID, C_MAXEID) of the writing node's row in AO_8BAD1B_NODE_SIGNS_V2; consecutive within that node's partition in write order. |
| `C_TIMESTAMP` | long |  | not null | Time the change was recorded, epoch milliseconds (server clock of the writing node). |
| `C_TYPEID` | int |  | not null | Item type of the changed item: an AO_8BAD1B_ITEM_TYPE.ID. |
| `C_ITEMID` | long |  |  | Numeric item id for items identified by a long id (e.g. Jira issue id for '...:type-issue', folder id, generator id, project id). Written as 0 for items identified by a string id. Exactly one of C_ITEMID (non-zero) / C_ITEMSID (non-null, non-blank) identifies the item. |
| `C_ITEMSID` | String | 190 |  | String item id for items identified by a string (e.g. user key for '...:type-user', label text for '...:type-label', status/priority/issue type id for those types); max 190 chars. NULL for long-id items. |

#### Table `AO_8BAD1B_NODE_SIGNS_V2`

One row per Jira Data Center node that has ever written item events: the node's event-id partition and its current runtime signature. Unique by C_NODE. A row is created the first time a node initialises its event journal; afterwards each re-initialisation (node start, overflow, failure recovery) rewrites C_SIGN and C_UPDATED in place and deletes all events of the partition, then restarts numbering at C_MINEID. New nodes get the next partition: C_MINEID = max(C_MAXEID over all rows, starting id) and C_MAXEID = C_MINEID + partition size. Defaults: partition size 1,000,000 and first partition starting at 1,000,000 (both overridable by the dark-feature/system properties 'structure.cluster.event.range' and 'structure.cluster.event.initial'). Rows of dead nodes are ignored by readers but not deleted (except by the maintenance item tracker cleanup, which deletes all rows together with all events). Changes to this table are serialised by the cluster lock 'com.almworks.structure..ievent-signature-lock.0'. A reader that sees another live node's signature change resets its change tracking.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment surrogate key; no meaning. |
| `C_NODE` | String | 190 | not null, unique | Jira cluster node id (as reported by Jira's cluster manager), max 190 chars, unique. The literal '-' is used when the instance is not clustered. |
| `C_MINEID` | long |  |  | First event id (inclusive) of this node's partition in AO_8BAD1B_ITEM_EVENTS_V2.C_ID. |
| `C_MAXEID` | long |  |  | End of this node's partition (exclusive): the node never writes event ids >= this value. Fixed when the row is created. |
| `C_SIGN` | int |  |  | Runtime signature: an arbitrary non-zero 32-bit signed integer generated randomly (time/nanotime based) each time the node re-initialises its partition. A change of this value tells other nodes that the partition was wiped and restarted. 0 is never stored as a valid signature. |
| `C_UPDATED` | long |  |  | Time of the last (re)initialisation of this row, epoch milliseconds. |

#### Table `AO_8BAD1B_ROW`

Persistent forest rows. Each row of a stored structure forest refers to one row record here, which binds a row id to an item (item type + id) and a semantics code. Row records are immutable: they are created when an item is added to a stored forest (or when a backup is restored with its original row ids) and are never updated or deleted by normal operation, even when the forest no longer uses them (one item may have many row records). Public row id mapping: the row id used everywhere else (forests in AO_8BAD1B_FOREST/AO_8BAD1B_FOREST_CHANGE, history, REST, backups, API) is ID * 2 (always even and positive). Odd positive row ids are transient rows produced by generators and never stored here; negative row ids are temporary. To find the record of public row id r, read ID = r / 2. A restore inserts records with explicit ID = r / 2.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment integer key. Public row id = ID * 2 (e.g. ID 7 is row 14). Overflow (ID <= 0) is an error. |
| `C_ITEM_TYPE` | int |  | not null, indexed | Item type of the row's item: AO_8BAD1B_ITEM_TYPE.ID. |
| `C_ITEM_STRING_ID` | String | 190 | indexed | String id of the item when the item type uses string ids (user key, label, status id, priority id, issue type id, resolution id, group name, canonical version name, '/<text>' text folders, ...); max 190 chars. NULL for long-id items. |
| `C_ITEM_LONG_ID` | Long |  | indexed | Numeric id of the item for long-id types: Jira issue id for '...:type-issue', AO_8BAD1B_FOLDER.ID for '...:type-folder', public generator id (AO_8BAD1B_GENERATOR.C_ID * 2) for '...:type-generator', effector id for '...:type-effector', memo/note id, project id, version id, sprint id, etc. Written as 0 (not NULL) for string-id items. |
| `C_SEMANTICS` | long |  | not null | Row semantics code (signed 64-bit) carried with the row and exposed through the public row API. For rows created by users or by synchronisers in a stored structure it is 0; when a row is copied (e.g. restore or migration) the source row's value is kept. Value -1 denotes the virtual super-root and is never stored. Other values are opaque to storage and must be preserved. |

#### Table `AO_8BAD1B_STRUCTURE`

One row per structure (the named, permission-controlled container of a forest). Created when a user/API creates or copies a structure, or by restore with an explicit ID. Updated in place when name, description, owner, archived flag or permissions change. Deleted when the structure is deleted, together with its AO_8BAD1B_FOREST row, all its AO_8BAD1B_FOREST_CHANGE rows, its history and its issue index entries. ID is the public structure id used by every other table (C_STRUCTURE_ID, C_OWNING_STRUCTURE columns) and in the API/REST.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment structure id (public, positive). Explicit values are inserted on restore. |
| `C_NAME` | String | 190 | not null | Structure name as shown to users, required, max 190 chars. |
| `C_DESCRIPTION` | String | unlimited |  | Free-text description (unlimited text). NULL when empty. |
| `C_OWNER` | String | 190 |  | Jira user key (not user name) of the owner; NULL when there is no owner (empty owner is stored as NULL). |
| `C_ARCHIVED` | boolean |  |  | Boolean: true = archived (hidden from normal lists, read-only to most operations); false/NULL = active. |
| `C_PERMISSONS` | String | unlimited |  | (Column name is misspelt in the schema; keep it.) Structure permission rules as a JSON object, or NULL when there are no rules and edit-inheritance is off. Keys: "permissions" (array of rules, omitted when empty) and "editInheritance" (true, omitted when false). Each rule is either {"type":"set","subject":<subject>,"level":<level>} or {"type":"apply","structure":<structure id>} (apply the rules of another structure). Subject is {"type":"anyone"}, {"type":"user","name":"<user key>"}, {"type":"group","name":"<group name>"} or {"type":"project.role","project":<project id>,"role":<project role id>}. Level is one of the strings "NONE", "VIEW", "EDIT", "EDIT_GENERATORS", "ADMIN": in this column the automation level is always written as "EDIT_GENERATORS" (legacy name of the 'automate' level) and "EDIT_GENERATORS" is read back as automate. Rules are evaluated in order, later rules override earlier ones. "editInheritance": true means editing the structure additionally requires edit permission on the parent issue ("edit requires parent issue permission"). Example: {"permissions":[{"type":"set","subject":{"type":"group","name":"jira-users"},"level":"VIEW"},{"type":"set","subject":{"type":"project.role","project":10000,"role":10002},"level":"EDIT_GENERATORS"},{"type":"apply","structure":12}],"editInheritance":true}. Unknown keys are ignored on read. |

#### Table `AO_8BAD1B_FOREST`

Current forest (tree of rows) of each structure, one row per structure (primary key = structure id). Created with an empty forest and version 0 when the structure is created (or by restore). Every successful forest update rewrites C_FOREST and advances C_VERSION with an optimistic compare-and-set (update ... where structure id = ? and version = old version); a concurrent writer retries. Deleted with the structure. The incremental changes between versions are journaled in AO_8BAD1B_FOREST_CHANGE.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_STRUCTURE_ID` | int |  | primary key, not null | Structure id (AO_8BAD1B_STRUCTURE.ID), primary key, not auto-generated. |
| `C_FOREST` | String | unlimited | not null | Forest JSON: {"rows":[r1,r2,...],"depths":[d1,d2,...]} - two equal-length arrays in depth-first (pre-order) display order: rows are public row ids (even = AO_8BAD1B_ROW.ID*2), depths are 0-based nesting levels (0 = top level; each depth is at most previous depth + 1; first depth is 0). Keys appear in the order rows, depths. An empty forest is {"rows":[],"depths":[]}. On read, a scalar in place of an array is accepted as a one-element array and null elements as 0. Example: {"rows":[14,16,18,20],"depths":[0,1,1,0]} is row 14 with children 16 and 18, followed by top-level row 20. |
| `C_VERSION` | int |  | not null | Forest version number (int), 0 for a newly created structure. Each update increases it by the number of elementary changes written to AO_8BAD1B_FOREST_CHANGE in that update (so version N means N elementary changes since creation, modulo restore). After a restore the version is set to the value recorded in the backup. |

#### Table `AO_8BAD1B_FOREST_CHANGE`

Journal of elementary forest changes per structure, used by clients and other nodes to update a cached forest incrementally from version V to a later one. One row per elementary change. Rows are inserted in the same operation that bumps AO_8BAD1B_FOREST.C_VERSION: if the forest goes from version v to v+k, k rows are written with versions v+1..v+k, in order. Rows are never updated. Old rows are purged: a scheduled job (job key 'forestChanges.lastCleanTime', default every 12 hours) keeps only the latest 501 changes per structure: it deletes the versions below the highest minus 500, so one more than the limit of 500 remains (both numbers are tunable via dark-feature settings); all rows of a structure are deleted with the structure. A reader needing versions older than the oldest retained change must reload the whole forest.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_ID` | long |  | primary key, not null | Composite bigint key = (structure id << 32) \| version, where version is the forest version produced by this change (the change transforms version-1 into version). E.g. structure 5, version 3 -> 5*4294967296+3 = 21474836483. Explicitly assigned (not auto-increment). All changes of structure s lie in [s<<32, (s+1)<<32). |
| `C_CHANGE` | String | unlimited | not null | The change as a JSON object with a type discriminator "action" first and the remaining properties in alphabetical order. Four kinds: add: {"action":"add","addedForest":<forest>,"after":<row id or 0>,"under":<row id or 0>} - inserts a sub-forest (same {"rows","depths"} format as AO_8BAD1B_FOREST.C_FOREST) as children of 'under' (0 = top level) right after sibling 'after' (0 = as first child). move: {"action":"move","after":<row id or 0>,"movedRows":[row ids],"under":<row id or 0>} - moves the listed rows (with their subtrees) to the given position. remove: {"action":"remove","removedRows":[row ids]} - removes the listed rows with their subtrees. reorder: {"action":"reorder","children":[row ids],"under":<row id or 0>} - sets the order of the children of 'under'. Row ids are public row ids. Example: {"action":"add","addedForest":{"rows":[22],"depths":[0]},"after":16,"under":14}. |

#### Table `AO_8BAD1B_GENERATOR`

Stored configuration of generators (automation rules: inserters, extenders, groupers, sorters, filters) placed in structures. One row per generator instance. Created when a generator row is added to a structure (or by restore with an explicit id), updated when its parameters change, deleted when the generator is removed/cleaned up. Public generator id = C_ID * 2 (even, positive); that public id is the long item id of the generator's row ('...:type-generator') in AO_8BAD1B_ROW.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_ID` | int |  | primary key, auto increment, not null | Auto-increment integer key. Public generator id = C_ID * 2; restore inserts C_ID = public id / 2. |
| `C_MODULE_KEY` | String | 190 | not null | Complete key of the generator module, '<plugin key>:<module key>', max 190 chars. Built-in values include 'com.almworks.jira.structure:inserter-jql', ':agile-board', ':inserter-text', ':inserter-substructure', ':inserter-recent-issues', ':extender-subtasks', ':extender-links', ':extender-agile', ':extender-portfolio-children', ':grouper-field', ':grouper-sprint', ':grouper-agile-epic', ':grouper-text', ':grouper-portfolio-parent', ':grouper-tempo-account', ':grouper-version-name', ':grouper-links', ':sorter-attribute', ':sorter-agile-rank', ':sorter-manual', ':filter-by-field', ':filter-jql', ':filter-text', ':filter-attribute', ':filter-number-attribute', ':filter-sjql', ':filter-item', ':filter-inserter-extender-duplicates', ':filter-sprint' (all prefixed with 'com.almworks.jira.structure'). |
| `C_PARAMETERS` | String | unlimited |  | Generator parameters as a JSON object (map of parameter name to JSON value; nulls omitted); its keys are defined by each generator type. NULL when the parameter map is empty. Example for a JQL inserter: {"jql":"project = ABC","limit":1000}. |
| `C_OWNING_STRUCTURE` | Long |  |  | Id of the structure (AO_8BAD1B_STRUCTURE.ID) the generator belongs to; NULL when not bound to a structure. Used for permission checks and cleanup of generators of deleted structures. |

#### Table `AO_8BAD1B_VIEW`

Saved views (column configurations shown on top of a structure). One row per view. Created by users, by restore (explicit ID) and once at first start when the default views are created (guarded by the property 'createdDefaultViews' in AO_8BAD1B_PROPERTY). Updated in place by read-merge-write of the JSON. Deleted when a view is deleted (its AO_8BAD1B_VIEW_TO_STRUCTURE rows are deleted at the same time). ID is the public view id.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment public view id (positive). |
| `C_DATA` | String | unlimited | not null | View definition as a JSON object (nulls omitted, unknown keys ignored on read). Keys: "name" (string, required), "description" (string), "owner" (permission subject, normally {"type":"user","name":"<user key>"}), "permissions" (array of permission rules, same rule/subject grammar as AO_8BAD1B_STRUCTURE.C_PERMISSONS except that levels are written by their plain names "NONE", "VIEW", "EDIT", "ADMIN"), "specification" (object), and possibly "id" (the view id, written only when the view was created with a known id; ignored on read, the row ID wins). "specification" = {"columns":[<column>...],"columnDisplayMode":1\|2,"rowDisplayMode":11\|12,"pins":[<csid>...]} where columnDisplayMode 1 = auto-fit, 2 = scrollable (default 1); rowDisplayMode 11 = one line, 12 = text wrapping (default 11); "pins" lists the csids of pinned columns. Each column = {"csid":"<column id unique within the view, decimal string>","key":"<column type>","name":"<header, optional>","parameters":{...}} with column type keys such as "main", "field" (parameter "field": Jira field id like "issuekey", "assignee", "timeestimate", optional "aggregate":"sum"), "progress", "icons" (parameter "fields": list of field ids), "formula", etc.; parameters are type-specific. Example: {"name":"Basic View","owner":{"type":"user","name":"JIRAUSER10000"},"permissions":[{"type":"set","subject":{"type":"anyone"},"level":"VIEW"}],"specification":{"columns":[{"csid":"0","key":"field","parameters":{"field":"issuekey"}},{"csid":"1","key":"main","name":"main"}],"columnDisplayMode":1,"rowDisplayMode":11,"pins":[]}}. |

#### Table `AO_8BAD1B_STRUCTURE_TO_VIEW`

Per-structure view settings: which views are associated with a structure, on which pages they appear in the view menu and which is the default. One row per structure that ever had settings, plus the special row with C_STRUCTURE_ID = 0 holding the global default view settings (used for structures without own settings). Created on first save (version 0); each later save rewrites C_VIEW_SETTINGS with an optimistic compare-and-set on C_VERSION and increments it. Clearing the settings stores NULL settings (the row is kept, version still incremented). After each successful save of a structure's settings (not for row 0), the derived index AO_8BAD1B_VIEW_TO_STRUCTURE is rewritten for that structure.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_STRUCTURE_ID` | int |  | primary key, not null | Structure id (AO_8BAD1B_STRUCTURE.ID), or 0 for the global default settings. Primary key, not auto-generated. |
| `C_VIEW_SETTINGS` | String | unlimited |  | JSON object {"views":[<associated view>...]} (nulls omitted; an object without "views" means 'settings not defined' -> fall back to defaults). Each associated view = {"view":<view id>,"menuPages":[<page>...],"defaultPages":[<page>...]} in that key order; "menuPages" omitted means the view appears on all pages; "defaultPages" lists pages where it is the default view. Page values: "structure" (structure board), "issue" (issue page panel), "project" (project page tab), "gadget" (dashboard gadget); legacy values "structure-with-details" (read as structure+project), "component", "version", "navigator", "greenhopper" may appear in old data. Menu pages are restricted to structure/issue/project/gadget, default pages to structure/issue/project. Order of the array is the menu order. Example: {"views":[{"view":3,"defaultPages":["structure","project"]},{"view":7,"menuPages":["structure"]}]}. NULL = settings removed. |
| `C_VERSION` | int |  | not null | Optimistic-lock counter, 0 on insert, +1 on every successful update. Also stamped onto the matching AO_8BAD1B_VIEW_TO_STRUCTURE rows. |

#### Table `AO_8BAD1B_VIEW_TO_STRUCTURE`

Reverse index view -> structures, derived from AO_8BAD1B_STRUCTURE_TO_VIEW, used to find which structures a view is associated with. One row per (structure, associated view) pair of a structure's current settings (only positive view ids). On each successful save of a structure's view settings with new version v, rows (structure, view, v) are inserted for every associated view and then all rows of that structure with C_VERSION < v are deleted. All rows of a view are deleted when the view is deleted. Duplicates are tolerated on read (the structure list is de-duplicated).

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment surrogate key; no meaning. |
| `C_VIEW_ID` | int |  | not null, indexed | View id (AO_8BAD1B_VIEW.ID). |
| `C_STRUCTURE_ID` | int |  | not null, indexed | Structure id (AO_8BAD1B_STRUCTURE.ID) whose settings reference the view. |
| `C_VERSION` | int |  | not null | The AO_8BAD1B_STRUCTURE_TO_VIEW.C_VERSION of the structure's settings at the time the row was written; rows with older versions are stale and purged. |

#### Table `AO_8BAD1B_PROPERTY`

Global key/value store of the plugin (string values). One row per key. Setting an empty or null value deletes the row; otherwise the row is created or its value overwritten. A restore writes every global property found in the backup. Values are plain strings: booleans as 'true'/'false' (anything other than 'true' reads as false), numbers as decimal text, structured values as JSON. Keys written by the plugin: 'createdDefaultViews' (boolean; true once the default views were created at first start, prevents re-creating them); 'generationTimeLimit' (long, seconds; global limit for generator execution time per structure, overridable per structure in structure properties); 'manualAdjustments.enableForNewStructure' (boolean, default false); 'statistics.sendingEnabled' (boolean; consent to send usage statistics, default false); 'welcomeScreen.help' (JSON {"title":"...","content":"<wiki markup>","contactKeys":["<user key>",...]} for the admin-defined help panel; row removed when cleared); 'appSupport.blockedSerials' (space-separated list of license serial numbers); 'appSupport.lastCheckedSerial' (license serial of the plugin last reported to the vendor's app-support check) and 'appSupport.lastCheckedSerial:<product key>' for extension products; 'sjm.<job key>' (epoch milliseconds of the last run of an internal scheduled job; job keys: 'statistics.lastSentTime', 'appSupport.lastCheckTime', 'licenseCheck:<module key>', 'forestChanges.lastCleanTime', 'maintenance.scheduled.job'); 'maintenance.scheduled.enabled' (boolean, default true); 'maintenance.scheduled.time' ('H:M' daily time, e.g. '3:0' or '23:45', default 3:00); 'maintenance.scheduled.crontab.enabled' (boolean, default false); 'maintenance.scheduled.crontab.schedule' (5-field cron expression minute hour day month weekday, default '0 3 * * *'); 'maintenance.scheduled.parameters' and 'maintenance.manual.parameters' (JSON object of string values, keys: backup, backup-saveHistory, removeOldBackups, removeOldBackups-minFilesToKeep (default 5), removeOldBackups-minDaysToKeep (15), cleanupFavorites, cleanupForests, cleanupViews, cleanupSynchronizers, cleanupStructureProperties, removeOldSyncAuditLogRecords, removeOldSyncAuditLogRecords-daysToKeep (30), reindexHistory, cleanupPerspectives, cleanupPerspectives-daysToKeep (30), reindexStructures, removeOldChangeHistory, removeOldChangeHistory-daysToKeep (30), removeOldChangeHistory-changesPerStructureToKeep (1000), removeOldEffectorProcesses, removeOldEffectorProcesses-daysToKeep (30), removeOldEffectorProcesses-waitingPreviewHoursToKeep (24), removeOldProcessStates, cleanupItemTracker; booleans as "true"/"false", numbers as decimal strings, e.g. {"backup":"true","removeOldBackups-minFilesToKeep":"5"}); 'maintenance.scheduled.nextRunTime' (epoch ms of next scheduled run) and 'maintenance.scheduled.nextRunTime.tz' (Java time zone id, e.g. 'Europe/Berlin', in which it was computed); 'maintenance.scheduled.currentProcessId' (id of the running maintenance process, AO_8BAD1B_PROCESS_STATE id); 'maintenance.manual.lastRunTime' (epoch ms); 'maintenance.successful' (boolean outcome of the last run, default true). Legacy key read during restore of old backups: 'view.defaultAssociatedViews_v2' (JSON in the same format as AO_8BAD1B_STRUCTURE_TO_VIEW.C_VIEW_SETTINGS, global default view settings from 2.x).

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_KEY` | String | 190 | primary key, not null | Property key, non-blank, max 190 chars, primary key (see table summary for the keys and their value formats). |
| `C_VALUE` | String | unlimited |  | Property value as text (unlimited). Never empty in practice (empty means the row is deleted); a NULL value reads as absent. |

#### Table `AO_8BAD1B_FOLDER`

Stored folders: named grouping rows that users add to a structure. One row per folder. Created when a folder is added (or by restore with explicit ID), updated on rename, deleted when the folder is deleted (each change is announced as an item change of type '...:type-folder'). ID is the long item id of the folder's rows in AO_8BAD1B_ROW. (Text-only folders created by groupers are not stored here; they use string ids beginning with '/'.)

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment folder id (public, used directly as the '...:type-folder' long item id; no doubling). |
| `C_NAME` | String | 190 | not null | Folder name as shown in the structure, required, max 190 chars. |
| `C_OWNING_STRUCTURE` | Long |  |  | Id of the structure (AO_8BAD1B_STRUCTURE.ID) in which the folder was created and to which it belongs for permission purposes; NULL if not bound to a structure. |

#### Table `AO_8BAD1B_FAVORITES`

Users' favourite structures. One row per (user, structure) pair that is marked favourite; uniqueness is maintained by the application (marking deletes any existing pair rows and inserts one; unmarking deletes them). Rows are removed when the user's personal data is erased (all rows of that user) and by the maintenance option 'cleanupFavorites', which deletes rows whose user no longer exists or whose structure no longer exists. The number of rows per structure is the structure's popularity.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment surrogate key; no meaning. |
| `C_USER_KEY` | String |  | not null, indexed | Jira user key (not user name) of the user, non-empty (default length 255). |
| `C_STRUCTURE_ID` | Long |  | not null, indexed | Structure id (AO_8BAD1B_STRUCTURE.ID) marked as favourite. |

#### Table `AO_8BAD1B_STATISTICS`

One usage-statistics sample. Rows are append-only. Samples are buffered in memory and flushed by a periodic background job (default every 600 s, tunable via dark feature `structure.statisticsManager.pendingJobIntervalSeconds`; skipped while the plugin's database is locked), or written immediately when the browser posts statistics. A named statistic is either a 'total count' statistic (one row per flush with user null and the accumulated count in C_VALUE) or a 'unique user' statistic (one row per distinct user seen in the flush window, C_USERKEY set). No uniqueness constraint. Purge: a daily scheduled job (scheduled-job key `statistics.lastSentTime`, interval 86400000 ms, overridable via dark feature `almworks.statistics.dev.requestInterval`) deletes every row with C_TIMESTAMP older than now minus 40 days (3456000000 ms), then, if the admin opted in, sends an aggregated report off-site (see report notes). When a Jira user key changes (user anonymization), C_USERKEY values equal to the old key are rewritten to the new key. No foreign keys to other plugin tables.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_ID` | long |  | primary key, auto increment, not null | Surrogate primary key, auto-increment 64-bit integer. No meaning. |
| `C_VALUE` | double |  | not null | Double. For a total-count statistic: the sum of increments collected during the flush window (usually an integer count such as 3.0; some sources add fractional or larger amounts). For a unique-user row it repeats the statistic's total if one was set, otherwise 0.0. The report sums C_VALUE over all rows with null user and divides by the number of days covered (average per day). |
| `C_TIMESTAMP` | long |  | not null, indexed | Epoch milliseconds of the sample: the time of the last event recorded into the buffer before the flush, or the client-supplied `timestamp` when the browser posts statistics via REST (so it may come from the client clock). Indexed; used for the 40-day purge and for date-range user counts. |
| `C_STAT` | String | 190 | not null | Statistic name, non-blank free-form dotted identifier, max 190 chars. Families: plain feature names (e.g. `perspectiveAccessCount`, `perspectiveShareCount`, `effectors.start.instance`, `effectors.effects.apply.success`, browser-reported UI action names such as `collapseAll`, `view.addColumn`); `userCount` and `activeUser` (unique-user statistics, recorded together with every browser report; `activeUser` only when the report includes one of a fixed set of interactive actions); `activeUser.<feature>` (unique users of a feature); distribution bins `<prefix>.<bin>` where <bin> is the smallest configured upper bound >= the value, written as a decimal integer, or `inf` if above all bounds (e.g. `effectors.previewSize.100`, `effectors.forestSize.inf`). Readers must accept unknown names. |
| `C_USERKEY` | String | 190 |  | Jira user key (application user key, not user name) for unique-user statistics; null for total-count rows. A user without a key is stored as empty string. Rewritten on user-key change. |

#### Table `AO_8BAD1B_HISTORY_ENTRY`

One committed version step of a structure's stored (manual) forest: the header of a batch of forest changes made by one user or one synchronizer run in one transaction-like batch. Natural key is C_ID which packs (structure id, new forest version). Created whenever a batch of forest edits commits (also recreated verbatim when restoring a backup). Child rows: AO_8BAD1B_HISTORY_CHANGE (C_HID = this C_ID, the actual changes, in C_ID order), AO_8BAD1B_HISTORY_ISSUE and AO_8BAD1B_HISTORY_PROJECT (C_HID = this C_ID, search indexes). Purge: when a structure is deleted all its entries are removed (range [hid(s,0), hid(s+1,0)) in all four history tables); the maintenance task `removeOldChangeHistory` keeps, per structure, entries newer than `removeOldChangeHistory-daysToKeep` days (default 30) but at least the latest `removeOldChangeHistory-changesPerStructureToKeep` entries (default 1000) and deletes the older ones, again across all four tables by C_ID/C_HID range (0 for both settings means delete all history). On user-key change, C_USER_KEY is rewritten.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_ID` | long |  | primary key, not null | Packed history id (not auto-increment): (structureId << 32) \| version, as a signed 64-bit integer, where structureId is AO_8BAD1B_STRUCTURE.ID (1..2^31-1) and version is the structure forest version produced by this entry (the value AO_8BAD1B_FOREST.C_VERSION took after the batch; >= 0). Example: structure 7, version 12 -> 7*4294967296+12 = 30064771084. All history of a structure is the C_ID range [s<<32, (s+1)<<32); ordering by C_ID orders by version. |
| `C_PREV_VERSION` | int |  | not null | Forest version of the structure immediately before this batch (int). Usually the previous entry's version, but versions can be skipped when changes are not recorded (so the gap between entries is meaningful: prev version != previous entry's version means unrecorded changes in between). |
| `C_TIMESTAMP` | long |  | not null, indexed | Epoch milliseconds when the entry was committed. Indexed; used for activity-stream date filters and day-based retention. |
| `C_USER_KEY` | String | 190 | indexed | Jira user key of the user who made the change; null when no user (anonymous/system) — an empty key is normalized to null. Rewritten on user-key change/anonymization. |
| `C_SYNCHRONIZER` | Long |  | indexed | If the change was made by a synchronizer run: the AO_8BAD1B_SYNC_INSTANCE.ID of that installed synchronizer instance (only positive ids are recorded; one-time resyncs without an installed instance leave it null). Null for manual/user changes. The activity filter distinguishes 'any synchronizer' (not null) from 'none' (null). |

#### Table `AO_8BAD1B_HISTORY_CHANGE`

One elementary forest change inside a history entry. Several rows per entry, applied in ascending C_ID order (undo applies them in reverse). Consecutive compatible changes of the same kind are merged before writing (adjacent inserts at the same place, or moves/removals from the same spot become one row with a bigger forest). Created together with its AO_8BAD1B_HISTORY_ENTRY; deleted with it (see that table). Rows refer to structure rows (AO_8BAD1B_ROW.ID values; may also include rows whose ROW record no longer exists).

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_ID` | long |  | primary key, auto increment, not null | Auto-increment surrogate key; defines the order of changes within an entry. |
| `C_HID` | long |  | not null, indexed | AO_8BAD1B_HISTORY_ENTRY.C_ID of the owning entry (packed structure id and version). Indexed. |
| `C_OPERATION` | int |  | not null | Integer operation code: 1 = add (new rows inserted), 2 = copy (rows inserted as copies of existing rows), 3 = move (existing subtrees moved), 4 = remove (subtrees removed). Any other value is invalid and makes the entry unreadable. |
| `C_FOREST` | String | unlimited | not null | JSON forest fragment affected by the change: `{"rows":[<rowId>,...],"depths":[<depth>,...]}` — two equally long arrays in depth-first order, row ids are AO_8BAD1B_ROW.ID values (64-bit), depths are 0-based relative to the fragment (roots have depth 0). For add/copy: the inserted rows; for move: the moved subtrees; for remove: the removed subtrees. Example: `{"rows":[101,102,103],"depths":[0,1,0]}` (101 with child 102, then 103). Never empty string. |
| `C_PATH_FROM` | String | unlimited |  | For move and remove: JSON array of row ids from the top level down to and including the former parent of the moved/removed rows (`[]` when they were at top level). Null for add and copy. Example `[55,60]`. Readers also accept a bare number (treated as one-element list) and treat JSON null elements as 0. |
| `C_AFTER_FROM` | String | unlimited |  | For move and remove: JSON array with the row id of the sibling that preceded the moved/removed rows in their old position, or `[]` if they were first under their parent. Null for add and copy. Example `[61]`. |
| `C_PATH_TO` | String | unlimited |  | For add, copy and move: JSON array of row ids from the top level down to and including the new parent (`[]` = inserted at top level). Null for remove. |
| `C_AFTER_TO` | String | unlimited |  | For add, copy and move: JSON array holding the row id after which the rows were placed, or `[]` if placed first under the parent. Null for remove. |
| `C_DIRECTION` | Integer |  |  | Only for move: 1 if the moved rows ended up later in the flattened forest order than before (moved down), -1 if earlier (moved up). Null when 0/not applicable (add, copy, remove, or no positional change). |
| `C_ORIGINAL_ROWS` | String | unlimited |  | Only for copy: JSON array parallel to C_FOREST.rows giving, for each inserted row, the row id it was copied from, or 0 if the source row was not part of this structure's forest (or was a transient/generated row). Null for other operations. Example `[88,0,90]`. |

#### Table `AO_8BAD1B_HISTORY_ISSUE`

Search index row: Jira issue X was among the rows touched by history entry H (so the activity stream can be filtered by issue). One row per distinct (entry, issue) pair, written right after the entry and its changes, covering issues referenced by any row in any C_FOREST of that entry. Deleted together with the entry (by C_HID range).

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_ID` | long |  | primary key, auto increment, not null | Auto-increment surrogate key. |
| `C_HID` | long |  | not null, indexed | AO_8BAD1B_HISTORY_ENTRY.C_ID (packed structure id << 32 \| version). Indexed. |
| `C_ISSUE_ID` | long |  | not null, indexed | Jira issue id (jiraissue.ID) of an issue item present in the changed forest fragment. Indexed. |

#### Table `AO_8BAD1B_HISTORY_PROJECT`

Search index row: an issue from Jira project P was among the rows touched by history entry H. One row per distinct (entry, project) pair, derived from the projects of the issues indexed in AO_8BAD1B_HISTORY_ISSUE for the same entry at the time of writing (not updated if issues later move). Deleted together with the entry (by C_HID range).

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_ID` | long |  | primary key, auto increment, not null | Auto-increment surrogate key. |
| `C_HID` | long |  | not null, indexed | AO_8BAD1B_HISTORY_ENTRY.C_ID (packed structure id << 32 \| version). Indexed. |
| `C_PROJECT_ID` | long |  | not null, indexed | Jira project id (project.ID) of an issue touched by the entry. Indexed. |

#### Table `AO_8BAD1B_PERSPECTIVE`

A shared 'perspective': a saved snapshot of the structure page state (which structures/views/expansion are shown) that users share via link or e-mail; the link carries the id. Created when a licensed user with structure access shares the current page (REST POST perspective/share). Read anonymously-allowed by id; every successful read updates C_LAST_USED. Purge: maintenance task `cleanupPerspectives` deletes rows whose C_LAST_USED is older than `cleanupPerspectives-daysToKeep` days (default 30). Backup restore replaces the whole table (all rows deleted, then restored with their original ids and C_LAST_USED = restore time). No relations by column.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_ID` | long |  | primary key, not null | Perspective id, not auto-increment: a random integer in [1, 2147483647] (stored as 64-bit) chosen at creation; on a primary-key collision a new random id is tried, up to 10 attempts. Appears in shared URLs, so existing ids must be preserved. |
| `C_LAST_USED` | long |  | not null, indexed | Epoch milliseconds of creation or of the last retrieval by id (or of the restore). Indexed; drives the purge. |
| `C_SPEC` | String | unlimited | not null | Non-empty client-defined JSON text describing the page state, stored verbatim as supplied by the browser. The server only interprets top-level keys `primary` and `secondary` (each an object describing a forest panel, which may contain `viewSpec`, a view specification in the same JSON shape the view REST API uses); on read, view specifications referencing saved columns are re-expanded from AO_8BAD1B_SAVED_COLUMN and the JSON is re-serialized, preserving all other keys. Example: `{"primary":{"structureId":12,"viewSpec":{"columns":[...]}},"secondary":null}`. |

#### Table `AO_8BAD1B_ISSUE_INDEX`

Reverse index 'which structures contain issue X': one row per (issue, structure) pair with the number of rows referencing that issue in the structure's stored forest (AO_8BAD1B_FOREST; generated rows are not counted). Natural key (C_ISSUE_ID, C_STRUCTURE_ID) is logically unique, not enforced: if duplicates are found, all but the first are deleted. Maintained incrementally on every forest change (count adjusted by the delta; row created when absent; row deleted when the count drops to 0). Rows of a structure are deleted when the structure is deleted. Full rebuild (maintenance task `reindexStructures`): all rows deleted, then one row inserted per issue per structure. Used to answer 'structures containing issue' (only rows with count > 0 count).

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment surrogate key. |
| `C_ISSUE_ID` | long |  | not null, indexed | Jira issue id (jiraissue.ID). Indexed. |
| `C_STRUCTURE_ID` | int |  | not null, indexed | AO_8BAD1B_STRUCTURE.ID of the structure (int). Indexed. |
| `C_OCCURRENCES` | int |  | not null | Number (> 0) of rows in the structure's stored forest whose item is this issue (an issue can occur under several parents). |

#### Table `AO_8BAD1B_SYNC_INSTANCE`

One installed synchronizer: a synchronizer module bound to a structure with its parameters and owner. Created when a user installs a synchronizer on a structure (or by backup restore, which keeps the original ID). Updated when owner/parameters are edited or autosync is toggled. Deleted when the synchronizer is uninstalled, when its structure is deleted, when all synchronizers are uninstalled, and by maintenance task `cleanupSynchronizers` for instances whose structure no longer exists. Referenced by AO_8BAD1B_HISTORY_ENTRY.C_SYNCHRONIZER, AO_8BAD1B_SYNC_EVENT.C_SYNC_INSTANCE and AO_8BAD1B_SYNC_AUDIT_RECORD.C_SYNC_INSTANCE (no FK constraints; those rows may outlive the instance). One-time resyncs are not stored here. Note: the synchronizer UI is shown if dark feature `structure.feature.synchronizers.enabled` is on or if at least one row exists in this table.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment synchronizer instance id (kept on restore). Positive. |
| `C_STRUCTURE_ID` | int |  | not null, indexed | AO_8BAD1B_STRUCTURE.ID of the structure being synchronized (int). Indexed. |
| `C_MODULE_KEY` | String | 190 | not null | Complete plugin module key of the synchronizer: `<pluginKey>:<moduleKey>`. Built-in values: `com.almworks.jira.structure:sync-filter` (saved filter/JQL), `com.almworks.jira.structure:sync-links` (issue links), `com.almworks.jira.structure:sync-gh` (Agile epics/rank), `com.almworks.jira.structure:sync-status-rollup` (status rollup), `com.almworks.jira.structure:sync-subtasks` (sub-tasks). Third-party plugins may register other keys; such rows must be preserved even if the module is absent. |
| `C_OWNER` | String | 190 | not null | Jira user key of the user on whose behalf the synchronizer runs (permissions are checked as this user). |
| `C_PARAMETERS` | String | unlimited |  | Synchronizer-specific serialized parameters, null when none (blank is normalized to null). For all built-in synchronizers it is a JSON object: sync-filter: `filterId` (long Jira saved-filter id, 0/absent when JQL used), `jql` (string), `add`, `remove` (booleans), `addRootIssue` (Jira issue id under which found issues are added; 0/absent = top level), `removeOnlyFromUnderAddRootIssue`, `recheckSubtreeWhenParentCanBeRemoved`, `moveFromUnderAnotherRoot` (booleans). sync-links: `linkTypeId` (long, Jira issue link type id), `childIsLinkSource` (bool), `parentFilterId`/`childFilterId` (long), `parentJql`/`childJql` (string), `expandChild`, `expandParent`, `useAllLinks` (bool), `primacy` (`links`\|`structure`\|`none`), `orphanAction` (`remove`\|`moveUp`), `sourceOfTruth` (`jira`\|`structure`). sync-gh: `sourceOfTruth` (`jira`\|`structure`), `viewId` (long Agile board id, 0 if projects used), `projects` (array of Jira project ids), `syncEpics`, `syncRank`, `independentRanking`, `subtasks` (bool), `rankField` (rank custom field identifier string). sync-status-rollup: `applicableToAllProjects` (bool), `applicableProjects` (array of project ids), `applicableToAllTypes` (bool), `applicableTypes` (array of issue type id strings), `resolutionId` (string), `states` (array of `{"statusId":"<id>","allTransitionsAllowed":bool,"allowedTransitions":[{"workflowName":"...","actionId":<int>}]}`). sync-subtasks: `{"types":["<subtaskIssueTypeId>",...]}`. Example: `{"filterId":10100,"add":true,"remove":true,"removeOnlyFromUnderAddRootIssue":true}`. |
| `C_ENABLED` | boolean |  | not null, indexed | Autosync flag: true = runs incrementally on Jira/structure events; false = installed but only runs on explicit resync. Indexed. |

#### Table `AO_8BAD1B_SYNC_EVENT`

Cluster-wide queue of pending synchronizer events, used only on Jira Data Center (on a single server the queue is kept in memory and this table stays empty). Each row is one event: a Jira change relevant to synchronizers, a resync request, or an 'autosync enabled' marker. Rows are appended by any node; the node running synchronizers periodically reads all rows in ascending ID order and then deletes the rows it read (in batches of 100 ids; dark feature `structure.sync.deleteEventsBatchSize`). So rows are short-lived; no retention policy beyond consumption.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment id; defines processing order. |
| `C_TYPE` | int |  | not null | Event type code: 1 = issue updated, 2 = issue link created, 3 = issue link deleted, 4 = epic link changed (Agile), 5 = rank changed (Agile), 6 = issue deleted, 126 = autosync enabled, 127 = resync request. Unknown codes are skipped with a warning. |
| `C_DATA` | String | unlimited | not null | JSON payload by type. Types 1, 4, 5, 6: a bare JSON number, the Jira issue id (e.g. `10234`). Types 2, 3: `{"linkTypeId":<long>,"sourceId":<issueId>,"destinationId":<issueId>}`. Type 126: two-element array `[<syncInstanceId>,<latestHistoryVersion>]` where the second is the latest AO_8BAD1B_HISTORY_ENTRY version of that instance's structure at the time autosync was enabled (>= 0), e.g. `[4,57]`. Type 127: object `{"instanceId":<long, 0 for one-time resync>,"structureId":<long>,"moduleKey":"<complete module key>","ownerKey":"<user key>","parameters":"<C_PARAMETERS string, empty if none>","processId":<AO_8BAD1B_PROCESS_STATE.ID or 0>,"autosyncEnabled":<bool>,"scheduledResync":<bool>}`. Never blank. |
| `C_TIMESTAMP` | long |  | not null | Epoch milliseconds when the event was recorded. |
| `C_SYNC_INSTANCE` | Long |  |  | AO_8BAD1B_SYNC_INSTANCE.ID of the synchronizer whose run caused this Jira change (so it can ignore its own changes), or null if the change was not made by a synchronizer. |

#### Table `AO_8BAD1B_SYNC_AUDIT_RECORD`

Synchronizer audit log. Records are grouped: a group header row (C_GROUP_ID = 0) describes one synchronizer action/run, followed by zero or more action rows (C_GROUP_ID = header's ID) listing the individual Jira-side changes the run made. Written in bulk by a background job every 30 s (dark feature `structure.sync.audit.pendingRecordsWriteInterval`; 0 disables auditing); groups with no actions are skipped unless dark feature `structure.sync.audit.writingEmptyGroups` is on (install/uninstall/enable events always have no actions, so they are written only in that case). Action rows are also the input for 'undo' of a synchronizer's changes, so their JSON must stay readable. Purge: maintenance task `removeOldSyncAuditLogRecords` deletes rows with C_TIMESTAMP older than `removeOldSyncAuditLogRecords-daysToKeep` days (default 30). Readers return at most 10000 rows per query (dark feature `structure.sync.audit.queryLimit`).

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment id. For header rows also the group id. |
| `C_SYNC_INSTANCE` | long |  | not null, indexed | AO_8BAD1B_SYNC_INSTANCE.ID the record belongs to; 0 for records not tied to an installed instance (global uninstall-all, one-time resync, undo). Set on both header and action rows. Indexed. |
| `C_SYNC_MODULE_KEY` | String | 190 |  | Complete synchronizer module key (e.g. `com.almworks.jira.structure:sync-links`) on header rows; null on action rows and when unknown (empty is stored as null). |
| `C_STRUCTURE_ID` | long |  |  | AO_8BAD1B_STRUCTURE.ID on header rows (0 when not structure-specific, e.g. uninstall-all or undo); null on action rows. |
| `C_TIMESTAMP` | long |  | not null, indexed | Epoch milliseconds when the group was recorded; header and its actions share the same value. Indexed. |
| `C_GROUP_ID` | int |  | not null | 0 for a group header row; otherwise the ID of the header row this action belongs to. |
| `C_DATA` | String | unlimited |  | JSON object. Header rows: description with key `action` = `install` \| `installOffline` \| `uninstall` \| `uninstallAll` \| `uninstallAllForStructure` \| `setAutosyncEnabled` \| `enableAfterResync` \| `edit` \| `sync` \| `resync` \| `undo`; management actions add `loggedInUserKey` (user key, may be empty) and (except uninstallAll*/undo) `parameters`: the synchronizer parameters as a JSON object (`{}` if none), except for `installOffline` and `uninstall`, where it is the stored parameter text as a JSON string; `installOffline` adds `autosyncEnabled` (bool), `setAutosyncEnabled` adds `enabled` (bool), `edit` (an update of the synchronizer's owner or parameters) adds `changedOwner` (bool), `changedParameters` (bool) and `ownerKey` (the owner's user key after the change); `sync`/`resync` headers add `ownerKey`, `parameters`, run-result keys (e.g. `result`: `success`\|`failure`, `reason`, `exception` = `{message?, class, stackTrace, cause?}`), and for `sync` also `jiraEvents` (array of `{"timestamp":ms,"syncInstanceId":long,"type":"<change type name>","issues":[{"key":"ABC-1","id":10000}]}`) and `structureEvents` (array of `{"timestamp":ms,"syncInstanceId":long,"version":int}`). Action rows: synchronizer-specific objects, each with `type` and issue descriptors `{"key":"ABC-1","id":10000}`: links: `type` `createLink`\|`removeLink` with `linkTypeId`, `source`, `destination`; Agile epics: `type` `changeEpic`\|`removeFromEpic` with `issue`, `epic`, `oldEpic`, `epicLink` (link type id); Agile rank: `type` `updateRank` with `issue`, `newAfter` or `newBefore`, optional `oldBefore`/`oldAfter`, `rankField`; status rollup: `issue`, `oldStatus`, `newStatus` (`{"name","id"}`), `action` (`{"name","id"}` workflow transition). Any action may carry failure keys `result`=`failure`, `reason`, `exception`; failed actions are skipped by undo. Null allowed. |

#### Table `AO_8BAD1B_ORDERING`

Persisted manual order of sibling items for a 'manual sorting' automation (a sorter generator inserted into a structure that lets users drag rows to reorder generated content). One row per (sorter, parent path): the ordered list of items under that parent. Created/updated when a user reorders rows under such a sorter; deleted when the stored list becomes empty. Logically unique by C_KEY (not enforced; extra rows with the same key are deleted on update, first one wins on read). Not deleted when the sorter is removed (rows can be orphaned). Relation: C_SORTER_ID = AO_8BAD1B_GENERATOR.C_ID of the sorter; item tokens refer to AO_8BAD1B_ITEM_TYPE ids.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment surrogate key. |
| `C_SORTER_ID` | long |  | not null | AO_8BAD1B_GENERATOR.C_ID of the manual-sorter automation (long). |
| `C_KEY` | String | 190 | not null, indexed | `<sorterId>.<path>`. <path> is `root` for top-level siblings, otherwise the comma-joined item tokens of all ancestors from the top of the forest down to the immediate parent of the ordered rows; when the ordered rows are group rows created by a grouper the path gets suffix `.gr`. Item identity token grammar (shared with other tables): a Jira issue is written as its decimal issue id alone (e.g. `10234`); any other item is `<typeId>/<longId>` (e.g. `3/57`) or, for items with a string id, `<typeId>//<urlEncodedStringId>` (e.g. `5//my%20item`), where <typeId> is the integer ID of the item type's row in AO_8BAD1B_ITEM_TYPE (created on demand) and the string id is percent-encoded like a URI component. Examples: `42.root`, `42.10001,3/7`, `42.10001.gr`. Readers fall back from a `.gr` key by dropping trailing group ancestors and finally to the same path without `.gr`. Indexed. |
| `C_ORDERING` | String | unlimited | not null | Comma-separated item tokens (same grammar as in C_KEY) in the desired order, e.g. `10005,10003,3/12`; the single character `-` denotes an empty list. Items not listed are placed after the listed ones in their natural order; automation items are excluded. |

#### Table `AO_8BAD1B_PROCESS_STATE`

State of one long-running background process (e.g. maintenance run, backup/restore, effector application, resync) shown with a progress bar in the UI. Created PENDING when the process starts; updated with status, progress and display parameters as it runs; a cancel request sets C_CANCELLED. Deleted explicitly when the owner finishes with it, and by maintenance task `removeOldProcessStates`, which deletes rows whose C_TIMESTAMP is older than 30 days except those referenced by AO_8BAD1B_EFFECTOR_PROCESS.C_PROCESS_HANDLE_ID. The process id (this ID) is referenced from AO_8BAD1B_EFFECTOR_PROCESS.C_PROCESS_HANDLE_ID, resync requests (`processId` in AO_8BAD1B_SYNC_EVENT data) and the plugin's own property recording the currently running maintenance process.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Auto-increment process id (exposed to the UI/REST as the process handle id). |
| `C_TIMESTAMP` | long |  | not null | Epoch milliseconds of creation and, after that, of the last status change (progress updates do not touch it). |
| `C_STATUS` | int |  | not null | Status code: 0 = pending, 1 = running, 2 = finished. Any other value reads as finished. |
| `C_PARAMETERS` | String | unlimited |  | Display parameters as JSON or null: `{"name":<i18n text>,"buttons":[{"caption":<i18n text>,"url":"<relative or absolute url>"},...]}` where <i18n text> is `{"i18nKey":"<message key>","arguments":[...]}` (arguments are strings or numbers). Example: `{"name":{"i18nKey":"my.process.name","arguments":["7"]},"buttons":[{"caption":{"i18nKey":"my.button","arguments":[]},"url":"/some/page"}]}`. Unknown keys are ignored when reading. |
| `C_MANAGING_USER` | String | 190 |  | Jira user key of the user who started/manages the process; null if none (empty normalized to null). |
| `C_ACTIVITY` | String | unlimited |  | Current activity description as an i18n text JSON `{"i18nKey":"...","arguments":[...]}`, or null before the first progress report. |
| `C_PERCENT_COMPLETE` | Integer |  |  | Progress 0..100; -1 (set at creation) or null means unknown/indeterminate. |
| `C_CANCELLED` | Boolean |  |  | True once cancellation was requested; created false. Null reads as false. |

#### Table `AO_8BAD1B_STRUCTURE_PROPERTY`

Per-structure key/value property store (string values). One row per (structure, key); primary key is the composite string. Setting a blank/null value deletes the row. All rows of a structure are deleted when the structure is deleted; maintenance task `cleanupStructureProperties` deletes rows whose structure no longer exists. Copied when a structure is copied and included in backups. The store is exposed to other plugins via the public StructurePropertyService API, so arbitrary keys may exist and must be preserved. Known keys written by the plugin: `showDescription` (`true`/`false`: show the structure description on the structure page); `quick-transforms` (JSON array of quick transformation items for the structure toolbar, each `{"key":"<transform type key, or 'group'>","quick":{"id":"<unique id>","name":"...","color":"..."},"module":"<generator module key>","params":{...}}`, a group item having `"key":"group"` and `"transforms":[<items>]` instead of module/params; ids unique across the whole tree; default `[]`); `manualAdjustments.enable` (`true`/`false`: manual adjustments of generated content allowed in this structure); `generationTimeLimit` (decimal seconds, per-structure limit on forest generation time, overriding the global property of the same name; absent/0 = use global); `lastPolledMillis` (decimal epoch milliseconds of the last time the structure was opened/polled, written at most once per 2 hours per structure per node; shown as 'last used' in structure management).

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_COMPOSITE_KEY` | String | 190 | primary key, not null | `<structureId>:<key>`, e.g. `12:showDescription`. <structureId> is AO_8BAD1B_STRUCTURE.ID in decimal (>= 0); <key> is at most 170 chars. Primary key. |
| `C_VALUE` | String | unlimited |  | The property value as a string (format depends on key, see summary). Non-blank in practice; null treated as absent. |
| `C_STRUCTURE_ID` | Long |  | not null, indexed | AO_8BAD1B_STRUCTURE.ID, redundant with the key prefix; used for per-structure listing and deletion. Indexed. |

#### Table `AO_8BAD1B_S_ITEM_PROPERTY`

Per-structure, per-item key/value properties: values attached to an item (issue or other item) within a specific structure. The main use is structure notes: text notes shown in note columns. One row per (structure, item, property name); primary key is the composite string. Setting a blank value deletes the row. All rows of a structure are deleted when the structure is deleted (scan-and-delete by parsed key). Copied with structure copy, included in backup/restore and migration (where note property names are remapped to new note ids). Property names written by the plugin: `notes` (the default note) and `dc_note_<n>` where <n> is AO_8BAD1B_NOTE.ID (an additional named note); other names may be written via API and must be preserved.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_COMPOSITE_KEY` | String | 190 | primary key, not null | Pipe-separated: for items with a numeric id `<structureId>\|<typeId>\|<longItemId>\|<propertyName>`; for items with a string id `<structureId>\|<typeId>\|\|<stringItemId>\|<propertyName>` (empty field marks a string id; the string id is stored raw, not encoded, and may not contain `\|`). <structureId> is AO_8BAD1B_STRUCTURE.ID (> 0); <typeId> is the integer ID of the item type in AO_8BAD1B_ITEM_TYPE (for issues the row with C_KEY `com.almworks.jira.structure:type-issue`), <longItemId> for issues is the Jira issue id; <propertyName> is non-blank, at most 160 chars. Examples: `12\|1\|10234\|notes`, `12\|4\|\|abc\|dc_note_3`. Rows whose key cannot be parsed are ignored. |
| `C_VALUE` | String | unlimited | not null | Property value string, never blank (blank means delete). For notes: the note text exactly as entered by the user (multi-line plain text). |

#### Table `AO_8BAD1B_GENERIC_ITEM`

One row is one stored generic item: a user-created item that is not a Jira entity and is shown in structures. Two generic item types exist: memos (item type key `com.almworks.jira.structure:type-memo`) and planning tasks (`com.almworks.jira.structure:type-planning-task`); the type is told by C_TYPE_ID. The item identity used everywhere else (forests, rows, item properties) is (type key, ID), so ID is the item's numeric id and must be preserved. Rows are created when a user creates an item (auto-increment ID) and are also created with an explicit ID when a backup is restored (the ID from the backup is reused). Updated when the item is edited, or when the item is attached to a structure (C_OWNING_STRUCTURE set from null to that structure). If an already-owned item is placed into a different structure (e.g. when copying a structure), a NEW row is created as a copy owned by the target structure; the original is left alone. Deleted (hard delete by ID) when a user deletes the item; deletion does not remove its history rows (AO_8BAD1B_GENERIC_ITEM_HISTORY) and nothing deletes items when their owning structure is deleted. Each create and each user-visible update also appends a row to AO_8BAD1B_GENERIC_ITEM_HISTORY. Relations: C_TYPE_ID -> AO_8BAD1B_ITEM_TYPE.ID; C_OWNING_STRUCTURE -> AO_8BAD1B_STRUCTURE.ID; AO_8BAD1B_GENERIC_ITEM_HISTORY.C_LONG_ID + C_TYPE_ID -> this ID + C_TYPE_ID. A lookup by item identity must check that the row's type id matches the identity's type; a mismatch is treated as not found.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Item id (auto-increment integer, primary key). This is the numeric id in the item identity, e.g. memo 42 is (com.almworks.jira.structure:type-memo, 42). Explicit values are inserted on backup restore. |
| `C_NAME` | String | 190 | not null | Item display name, required. For a memo it is the memo text title; for a planning task it is the task summary (the `summary` field is stored here, not in the parameters). Plain text, up to 190 characters. |
| `C_OWNING_STRUCTURE` | Long |  |  | Id of the structure (AO_8BAD1B_STRUCTURE.ID) that owns the item, or null when the item is not owned by any structure. When non-null, the item is visible only to users who can view that structure; when null, it is visible to everyone who can see the referencing row. |
| `C_DESCRIPTION` | String | unlimited |  | Optional item description (the `description` field), unlimited text; for planning tasks it is Jira wiki-markup text as typed by the user. Null when absent. |
| `C_PARAMETERS` | String | unlimited |  | Item parameters as a JSON object (compact, null members omitted), or null when there are no parameters (an empty map is stored as null, never `{}`). Keys: `fields` (object, see below) for both types; memos additionally may have `color` (the colour value exactly as sent by the client, stored opaquely and returned as-is; also exposed as the memo attribute `color`) and `iconClass` (CSS class name string of the chosen icon). Unknown keys are preserved. Field-value map: the JSON object under key `fields` maps a Jira field id to a SERIALIZED STRING value (never a nested JSON value; the string itself may contain JSON). Field ids are Jira system field ids (`assignee`, `reporter`, `duedate`, `timeoriginalestimate`, `timeestimate`, `timespent`, `environment`, `priority`, `issuetype`, `project`, `labels`, `versions`, `fixVersions`, `components`) or custom field ids `customfield_<n>`; `summary` and `description` are never stored here (they live in the name/description columns). Value encodings by field kind: single-line and multi-line text: the raw text; single user (`assignee`, `reporter`, user picker): Jira user key, e.g. `JIRAUSER10100`; multi user: JSON array of user keys as strings, e.g. `["JIRAUSER10100","admin"]`; single group: group name; multi group: JSON array of group names; single select option: option id in decimal, e.g. `10200`; multi select: JSON array of option ids as strings, e.g. `["10200","10201"]`; date (`duedate`, date picker): ISO local date `yyyy-MM-dd`, e.g. `2026-10-28`; date-time picker: epoch milliseconds in decimal; durations (`timeoriginalestimate`, `timeestimate`, `timespent`): number of milliseconds in decimal, e.g. `7200000` for 2h; number field: a JSON number, e.g. `3.5` or `2.0`; project: project id written as a JSON floating number, e.g. `10000.0`; single version picker: version id in decimal; multi version (`versions`, `fixVersions`, multi version picker): JSON array of version ids as floating numbers, e.g. `[10001.0,10002.0]`; `components`: JSON array of component ids as strings, e.g. `["10100"]`; `labels` and label fields: JSON array of strings, e.g. `["backend","q4"]`; sprint field: the sprint id as a JSON string literal including the quotes, e.g. `"12"`; `issuetype` and `priority`: Jira constant id in decimal, e.g. `10001`. Null values are dropped from the map, and the `fields` key is removed when the map becomes empty. When neither estimate was set before and only one of `timeoriginalestimate`/`timeestimate` is now given, the other is filled with the same value. Example memo: `{"color":"blue","fields":{"assignee":"JIRAUSER10100","duedate":"2026-11-30"}}`. Example planning task: `{"fields":{"project":"10000.0","issuetype":"10001","timeoriginalestimate":"28800000","timeestimate":"28800000"}}`. |
| `C_TYPE_ID` | int |  | not null, indexed | Item type of this generic item, as AO_8BAD1B_ITEM_TYPE.ID of the type key (`com.almworks.jira.structure:type-memo` or `com.almworks.jira.structure:type-planning-task`; any item type registered as generic could appear). Integer, indexed. |

#### Table `AO_8BAD1B_ATOMIC_FLAG`

One row is one named cluster-wide flag holding a short string, updated with compare-and-set semantics (UPDATE ... WHERE C_KEY = ? AND C_VALUE = old, or C_VALUE IS NULL when the expected old value is null; success means exactly one row changed). Used on Jira Data Center to elect the single cluster node that performs a background duty. Known keys: `com.almworks.jira.structure.workNode.effector` (node that applies queued effector processes) and `com.almworks.jira.structure.workNode.autosync` (node that runs automatic synchronizers); the key grammar is `com.almworks.jira.structure.workNode.<duty>`. A row is inserted the first time a node tries to take the duty (insert races are resolved by the primary-key violation, the loser re-reads). The value is set to the taking node's id when the current holder is null or is not among the live cluster nodes; it is reset to null when the holding node shuts the duty down cleanly. Rows are never deleted. Not used on single-node (Server) installs.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_KEY` | String | 190 | primary key, not null | Flag name (primary key, up to 190 characters), e.g. `com.almworks.jira.structure.workNode.autosync`. |
| `C_VALUE` | String | 190 |  | Current holder: the Jira cluster node id (as reported by Jira's cluster info, e.g. `node1`) of the node that owns the duty, or null when nobody owns it. Empty strings are normalised to null before writing. |

#### Table `AO_8BAD1B_MANUAL_ADJUSTMENTS`

One row per structure that has manual adjustments: the list of manual changes a user made to the generated (automation-produced) part of a structure's forest (adding items under generated rows, moving generated rows). Natural key = C_STRUCTURE_ID. Written with optimistic concurrency: the row is read, modified, and written back with UPDATE ... WHERE C_STRUCTURE_ID = ? AND C_VERSION = old version (up to 10 retries); the first write inserts with the new version (an insert conflict counts as a lost race). The total number of adjustments per structure is capped (default 2000; the change is rejected above it). The row is deleted when the structure is deleted or when a user clears all adjustments of the structure. Relations: C_STRUCTURE_ID -> AO_8BAD1B_STRUCTURE.ID; row ids inside the data refer to AO_8BAD1B_ROW.ID; item ids use AO_8BAD1B_ITEM_TYPE ids.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `C_STRUCTURE_ID` | int |  | primary key, not null | Structure id (AO_8BAD1B_STRUCTURE.ID), primary key (not auto-increment). |
| `C_VERSION` | int |  | not null | Change counter used for optimistic locking and as the id source of new adjustments. Starts at 0 meaning 'no row'; each applied change increments it by one, so the first stored version is >= 1. A newly added adjustment gets the new version number as its `id`. |
| `C_DATA` | String | unlimited |  | JSON array of adjustment objects (compact, null members omitted), or null/empty when there are none (an empty list is stored as null; a row with empty data is treated as no adjustments). Each object: `id` (int, the adjustment id, unique within the structure) and either an add form `{"id":..,"added":[rowSpec,..],"under":R,"after":R,"before":R}` or a move form `{"id":..,"moved":R,"under":R,"after":R,"before":R}`; a `removed` key is accepted on read but never written; unknown keys are ignored. `added` is a forest fragment, a list of strings `<rowId>:<depth>:<itemId>:<semantics>` in depth-first order (depth 0 = top of the fragment), where rowId is a row id (AO_8BAD1B_ROW.ID), itemId uses the compact item-id grammar below and semantics is the row's semantics code (long). R (a row identity) is one of: the number 0 (= the root / nothing, e.g. 'at top' or 'no after'), the number -1 (= missing/unknown row), a positive number (a plain row id), or a JSON array that is a path of row specs from the top, each spec being either a number (a row id) or a string `<itemId>:<semantics>` optionally followed by the letter `p` (`p` marks a persistent, non-generated row). Compact item-id grammar used here (shared with other columns of the plugin): an issue is written as its bare Jira issue id in decimal (e.g. `10234`); any other item is `<typeId>/<longId>` for items with a numeric id (e.g. `7/42`) or `<typeId>//<stringId>` for items with a string id (e.g. `5//jsmith`), where <typeId> is AO_8BAD1B_ITEM_TYPE.ID of the item type key (the registry assigns a new id on first use). Parsing regex: `(\d+)(?:/(?:(\d+)\|/(.+)))?`; a lone number is always an issue. Example: `[{"id":3,"added":["901:0:10234:0","902:1:7/42:0"],"under":["12/5:0p","10500:0"],"after":0,"before":-1},{"id":4,"moved":["12/5:0p","10777:0"],"under":["12/5:0p"],"after":0,"before":0}]`. Unparseable data is logged and treated as empty. |

#### Table `AO_8BAD1B_EFFECTOR_INSTANCE`

One row is one configured effector instance: an effector (a module that computes changes to Jira data from a structure) together with its configuration, as inserted into a structure. Its row in a forest is the item (com.almworks.jira.structure:type-effector, ID). Created when a user adds an effector to a structure; updated when its configuration is edited; deleted (by ID) when explicitly deleted through the API. Not deleted automatically when the owning structure is deleted. On backup restore, rows are recreated with their original ID (module key and parameters only; the owning structure is left null on restore). Relations: C_OWNING_STRUCTURE -> AO_8BAD1B_STRUCTURE.ID; effector process parameters (AO_8BAD1B_EFFECTOR_PROCESS.C_PARAMETERS, key `effectorInstances`) embed copies of instances by id.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Effector instance id (auto-increment; explicit on restore); the numeric id of the effector item. |
| `C_MODULE_KEY` | String | 190 | not null | Complete plugin module key of the effector type, `<pluginKey>:<moduleKey>`. Bundled values: `com.almworks.jira.structure:effector-attribute-to-field`, `com.almworks.jira.structure:effector-status-rollup`, `com.almworks.jira.structure:effector-delay`, `com.almworks.jira.structure:effector-conversion`; third-party effectors use their own plugin key. |
| `C_PARAMETERS` | String | unlimited |  | Effector configuration as a JSON object whose keys are defined by the effector type (compact, null members omitted), or null when empty (an empty map is stored as null). |
| `C_OWNING_STRUCTURE` | Long |  |  | Structure (AO_8BAD1B_STRUCTURE.ID) the instance belongs to, or null if it is not attached to a structure. |

#### Table `AO_8BAD1B_EFFECTOR_PROCESS`

One row is one effector process: a run that first calculates a preview of effects (proposed changes to Jira issues/items) and, once confirmed, applies them. Three kinds, told apart by C_PARAMETERS: a run of the effector instances in a structure, a one-off run of an effector module over a forest spec, and an undo run that reverts selected effect records of an earlier process. Created by the user starting a run (status PENDING); all later state changes are conditional updates that check the current status (statement succeeds only if the row is still in the expected status). Lifecycle: PENDING -> CALCULATING (C_START_TIME set) -> CALCULATED (preview + C_FINISH_TIME set) or CALCULATION_FAILED (from PENDING/CALCULATING) or CALCULATION_STOPPED; CALCULATED (or directly after calculation when no confirmation is required) -> QUEUED (C_QUEUED set; preview kept) -> IN_PROGRESS (picked by the single applying node in order of C_QUEUED, null first; C_START_TIME reset to now and C_FINISH_TIME cleared) -> COMPLETED / COMPLETED_WITH_ERRORS (C_FINISH_TIME set, C_EFFECTOR_PREVIEW cleared to null) or APPLY_STOPPED (cancel). Undo runs are created PENDING with the preview filled directly and immediately moved to QUEUED. At startup a node marks its own PENDING/CALCULATING rows (matching C_NODE_ID, or null node id on single-node) as CALCULATION_STOPPED; the applying job, on its first run after start, turns IN_PROGRESS and QUEUED into APPLY_INTERRUPTED, and on later runs returns IN_PROGRESS rows to QUEUED; an APPLY_INTERRUPTED process can be resumed (-> QUEUED, C_ACKNOWLEDGED reset to false). The user acknowledges a finished process (COMPLETED, COMPLETED_WITH_ERRORS, APPLY_INTERRUPTED, APPLY_STOPPED) which sets C_ACKNOWLEDGED; unacknowledged processes of a user are listed as 'running' for that user, newest C_CREATED first. Purge: a maintenance task (key `removeOldEffectorProcesses`) deletes processes in COMPLETED, COMPLETED_WITH_ERRORS, APPLY_INTERRUPTED or APPLY_STOPPED whose C_FINISH_TIME is older than N days (default 30, setting `removeOldEffectorProcesses-daysToKeep`) together with their AO_8BAD1B_EFFECTOR_RECORD rows, and processes in PENDING, CALCULATING, CALCULATED, CALCULATION_STOPPED or CALCULATION_FAILED whose C_CREATED is older than M hours (default 24, setting `removeOldEffectorProcesses-waitingPreviewHoursToKeep`); a user may also delete a CALCULATED/CALCULATION_STOPPED/CALCULATION_FAILED process. Each delete also deletes the linked process handle row (AO_8BAD1B_PROCESS_STATE). User anonymisation rewrites C_USER_KEY from the old key to the new one. Relations: C_PROCESS_HANDLE_ID -> AO_8BAD1B_PROCESS_STATE.ID; AO_8BAD1B_EFFECTOR_RECORD.C_PROCESS_ID -> ID; parameters refer to AO_8BAD1B_STRUCTURE.ID, AO_8BAD1B_EFFECTOR_INSTANCE.ID and to other processes.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Process id (auto-increment integer). |
| `C_PARAMETERS` | String | unlimited |  | Run parameters as a JSON object (compact, null members omitted, unknown keys ignored on read). Keys: `structureId` (long, structure the run works on; present for instance runs, copied into undo runs); `effectorInstances` (array of effector instance snapshots, each `{"id":<instance id>,"moduleKey":"<complete module key>","owningStructure":<structure id, omitted if null>,"parameters":{..effector config..}}`, instance runs only); `oneOffEffectorModuleKey` (string, complete effector module key, one-off runs); `oneOffParams` (object, effector configuration for a one-off run); `oneOffForestSpec` (object, the forest the one-off run covers, in the REST forest-spec format of com.almworks.jira.structure.api.rest.RestForestSpec: keys `structureId`, `version`, `sQuery` {`query`,`type`}, `type`, `transforms` [{`module`,`key`,`params`}], `title`; copied into undo runs); `revertedProcessId` (long, the process being undone; undo runs only). Example: `{"structureId":128,"effectorInstances":[{"id":7,"moduleKey":"com.almworks.jira.structure:effector-status-rollup","owningStructure":128,"parameters":{"x":1}}]}`. |
| `C_EFFECTOR_PREVIEW` | String | unlimited |  | Calculated preview as a JSON object `{"previewEffects":[effect,..],"errors":[text,..]}` (either key may be absent), or null (before calculation, and after the process completes or is stopped, the preview is cleared). An effect is `{"moduleKey":"<complete effect-provider module key>","parameters":{..}}`, e.g. `{"moduleKey":"com.almworks.jira.structure:assignee-effect-provider","parameters":{"issue":10234,"assignee":"JIRAUSER10100"}}`; effect-provider keys are `com.almworks.jira.structure:<key>` with key one of the bundled providers (assignee-, priority-, description-, environment-, resolution-, summary-, due-date-, reporter-, status-, cascade-custom-field-, project-picker-custom-field-, script-runner-single-issue-picker-, single-select-custom-field-, portfolio-team-custom-field-, single-user-custom-field-, single-group-custom-field-, single-version-custom-field-, text-custom-field-, number-custom-field-, date-custom-field-, date-time-custom-field-, labels-, multi-versions-custom-field-, affects-versions-, fix-versions-, components-, multi-select-custom-field-, multi-user-custom-field-, multi-group-custom-field-, multi-labels-custom-field-, insight-object-custom-field-, warning-, delay-, original-estimate-, remaining-estimate-, sprint-, add-comment-, delete-comment-, memo-field-, conversion- each followed by `effect-provider`) or third-party ones; parameter keys are provider-specific (common ones: `issue` issue id, `customField` field id, `value`, `from`, `to`, `add`/`remove` lists, `conflicts`, `memo` item id string with `field` and `value` for memo fields; the public type com.almworks.jira.structure.api.effect.CoreEffects documents the core ones). A text in `errors` is `{"i18nKey":"<message key>","arguments":[..]}`. |
| `C_STATUS` | String | 190 | not null | Process status, the enum constant name as text, one of: `PENDING` (created, preview not yet calculated), `CALCULATING` (preview calculation running), `CALCULATED` (preview ready, waiting for user confirmation), `CALCULATION_FAILED` (preview failed; errors are in C_EFFECTOR_PREVIEW), `CALCULATION_STOPPED` (preview calculation cancelled by the user or abandoned because the node restarted), `QUEUED` (confirmed, waiting to be applied), `IN_PROGRESS` (effects being applied), `COMPLETED` (all effects applied), `COMPLETED_WITH_ERRORS` (applied, some effects failed), `APPLY_INTERRUPTED` (application stopped by a restart and not resumed), `APPLY_STOPPED` (application cancelled by the user). |
| `C_USER_KEY` | String | 190 |  | Jira user key of the user who started the process (rewritten on user anonymisation). |
| `C_PROCESS_HANDLE_ID` | long |  |  | Id of the process handle row in AO_8BAD1B_PROCESS_STATE (progress tracking of this process); that row is deleted with the process. |
| `C_START_TIME` | Long |  |  | Epoch ms when calculation started (set on PENDING -> CALCULATING) and overwritten with the time application started (QUEUED -> IN_PROGRESS); null before. |
| `C_FINISH_TIME` | Long |  |  | Epoch ms when the latest phase ended (calculation finished/failed/stopped, or application completed/stopped/aborted by restart cleanup); set to null when a queued process is picked for applying. Used for purging finished processes. |
| `C_QUEUED` | Long |  |  | Epoch ms when the process was put into the applying queue (status QUEUED); the queue is served in ascending order of this value (rows with null first). Null if never queued. |
| `C_CREATED` | long |  |  | Epoch ms when the process row was created. Used to list newest first and to purge stale previews. |
| `C_NODE_ID` | String | 190 |  | Jira cluster node id of the node that created the process (used to abandon its calculations when that node restarts); null on a non-clustered (single-node) install. |
| `C_ACKNOWLEDGED` | boolean |  |  | False on creation (and on resume); set true when the user acknowledges a finished process (only allowed in COMPLETED, COMPLETED_WITH_ERRORS, APPLY_INTERRUPTED, APPLY_STOPPED). |

#### Table `AO_8BAD1B_EFFECTOR_RECORD`

One row is the outcome of applying one effect of an effector process (one entry of the process preview): a message, an error flag, the effect that would undo it, and the items it touched. Rows are appended while a process is IN_PROGRESS, one per effect attempted; never updated. Deleted together with the process by the effector-process purge (see AO_8BAD1B_EFFECTOR_PROCESS). Undo runs read the records of the reverted process and use their C_UNDO_EFFECT values (optionally only selected C_PREVIEW_INDEX values) as their preview. Relations: C_PROCESS_ID -> AO_8BAD1B_EFFECTOR_PROCESS.ID.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Record id (auto-increment integer). |
| `C_PROCESS_ID` | long |  | indexed | Id of the effector process (AO_8BAD1B_EFFECTOR_PROCESS.ID) this record belongs to. Indexed. |
| `C_EFFECT_MESSAGE` | String | unlimited | not null | Human-readable result message as JSON. Plain form: `{"i18nKey":"<message key>","arguments":[..]}`. Form with user references: `{"i18nKey":..,"arguments":[..],"argumentsWithUserKeys":[..]}`, where `arguments` holds the arguments resolved to display text at write time and `argumentsWithUserKeys` holds the same arguments as strings in which each user is written as `${<user key>}` (e.g. `"${JIRAUSER10100}"`); readers re-resolve each `${...}` to the user's current display name (or an 'unknown user' text) when the key `argumentsWithUserKeys` is present. |
| `C_ERROR` | boolean |  |  | True if applying this effect failed (the message then describes the error), false if it succeeded. |
| `C_UNDO_EFFECT` | String | unlimited |  | The effect that reverts this one, as JSON `{"moduleKey":"<complete effect-provider module key>","parameters":{..}}` (same effect format as in the process preview); an empty string (or null) when no undo is possible. |
| `C_AFFECTED_ITEMS` | String | unlimited |  | Items changed by the effect, as a JSON array of strings in the compact item-id grammar, or null when none. Compact item-id grammar used here (shared with other columns of the plugin): an issue is written as its bare Jira issue id in decimal (e.g. `10234`); any other item is `<typeId>/<longId>` for items with a numeric id (e.g. `7/42`) or `<typeId>//<stringId>` for items with a string id (e.g. `5//jsmith`), where <typeId> is AO_8BAD1B_ITEM_TYPE.ID of the item type key (the registry assigns a new id on first use). Parsing regex: `(\d+)(?:/(?:(\d+)\|/(.+)))?`; a lone number is always an issue. Example: `["10234","9/42"]`. |
| `C_TIMESTAMP` | long |  |  | Epoch ms when the effect was applied. |
| `C_PREVIEW_INDEX` | int |  |  | Zero-based index of the effect within the process preview's `previewEffects` array that this record is the outcome of. |

#### Table `AO_8BAD1B_MIGRATION_CONFIG`

One row is one named cloud-migration configuration: which structures (and which optional add-on data) to send when Atlassian's Jira Cloud Migration Assistant runs an app-data migration whose migration plan has the same name. Natural key = C_NAME (unique). Created/edited/deleted by an administrator on the migration configurations admin page (each save sets C_EDITED_AT/C_EDITED_BY and saves status DRAFT or READY, with C_RUN_AT reset to null). During a cloud migration the plugin looks up the row whose C_NAME equals the migration plan name; if found and its status is not runnable (DRAFT or RUNNING) the app data migration is skipped; otherwise status goes READY -> RUNNING -> DONE or FAILED, and C_RUN_AT is set when it ends (other columns are kept). If no row matches, all structures are migrated. Relations: C_STRUCTURE_IDS lists AO_8BAD1B_STRUCTURE.ID values.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Configuration id (auto-increment integer). |
| `C_NAME` | String | 190 | not null, unique | Configuration name, unique; must match the Jira Cloud Migration Assistant migration plan name to be used. Up to 190 characters. |
| `C_STATUS` | String | 190 | not null | Status as text, one of `DRAFT` (saved but not published; not runnable), `READY` (published, runnable), `RUNNING` (a migration is in progress; not runnable), `DONE` (last run succeeded; runnable again), `FAILED` (last run failed; runnable again). |
| `C_STRUCTURE_IDS` | String | unlimited | not null | Structures to migrate, as a JSON array of structure ids (numbers), e.g. `[12,57,130]`; `[]` (or an empty string) means none selected, which the migration treats as 'migrate all structures'. Never null (empty string written instead of null). A single bare number is also accepted on read. |
| `C_EXTENSION_KEYS` | String | unlimited |  | Optional add-on data to include, as a JSON array of Jira app (plugin) keys of apps that contribute structure backup data, e.g. `["com.almworks.structure.gantt"]`; null when the set is empty. |
| `C_RUN_AT` | Long |  |  | Epoch ms when the last migration using this configuration finished (DONE or FAILED); null when it has not run since the last save or is running. |
| `C_EDITED_AT` | long |  | not null | Epoch ms of the last create/edit by an administrator. |
| `C_EDITED_BY` | String | 190 | not null | Jira user key of the administrator who last created/edited the configuration. |

#### Table `AO_8BAD1B_SAVED_COLUMN`

One row is one saved (reusable) column definition from the column library: either a global column (C_OWNER null, shared with all users) or a personal column of one user (C_OWNER = user key). Created by users or admins, updated in place, deleted by id (permission checks are done by the caller against the owner); a personal column can be turned into a global one (owner set to null). On backup restore rows are recreated with their original ID. Views refer to a saved column through a column parameter `savedColumn` whose value is `[modified/]<sourceId>/<columnId>`, where sourceId `stored` means this table and columnId is this ID (e.g. `stored/15`, or `modified/stored/15` when the view changed the column after inserting it); `bundled/<n>` refers to built-in columns not stored here. When a view is loaded, an unmodified reference is replaced by this row's type and parameters; a reference to a missing row removes the column.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Saved column id (auto-increment; explicit on restore). Referenced as `stored/<ID>`. |
| `C_NAME` | String | 190 | not null | Column name shown in the library, required, up to 190 characters. |
| `C_DESCRIPTION` | String | unlimited |  | Optional description text, or null. |
| `C_TYPE` | String |  | not null | Column type key, i.e. the `key` of a view column specification that this saved column produces (the same key strings used for columns in view specifications, e.g. `field`, `formula`). Required. Note: declared without an explicit length, so the database column is the default Active Objects string length (255). |
| `C_OWNER` | String | 190 |  | Jira user key of the owner for a personal column; null for a global column. |
| `C_PARAMETERS` | String | unlimited | not null | Column parameters as a JSON object (the `params` of a view column specification of type C_TYPE), required; an empty parameter set is stored as `{}`. Example for type `formula`: `{"formula":"due_date - created"}` (further keys depend on the column type). Other column keys seen in view specifications include `main`, `icons`, `handle`, `progress`. |

#### Table `AO_8BAD1B_NOTE`

One row is one note: a named, permission-controlled container of per-item note texts (the texts themselves are stored as item properties, not here; this row is the note's header). The note's external id is `dc_note_<ID>` (e.g. `dc_note_17`), which is also the item-property name under which the note's text is stored for each item. A synthetic default note with id `notes` and permission scheme `defaultNote` exists without any row. Created by users (structure-scoped notes require edit permission on the structure); renamed (not allowed when archived); archived (C_ARCHIVED set true; there is no un-archive and no delete in normal operation). On backup restore rows are recreated with their original ID. Relations: the permission scheme may reference AO_8BAD1B_STRUCTURE.ID.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Note number (auto-increment; explicit on restore). External note id is the string `dc_note_` + ID. |
| `C_NAME` | String | 190 | not null | Note name, trimmed, non-blank, at most 190 characters. |
| `C_PERMISSION_SCHEME` | String |  |  | Permission scheme spec (text; declared without explicit length, so default 255 chars). Grammar, tried in order: (1) a JSON object `{"structure":<structure id>}` meaning the note inherits the permissions of that structure (view/edit/admin as on the structure), e.g. `{"structure":128}` (this is what notes created for a structure get); (2) one of the lowercase words `none`, `view`, `edit`, `admin` meaning everyone has that level (levels are ordered none < view < edit < admin); (3) `defaultNote` meaning view-only for everyone (editing denied). Any other value is invalid. |
| `C_CREATED` | long |  |  | Creation time, epoch ms (restore keeps the original value). |
| `C_ARCHIVED` | boolean |  |  | True when the note is archived (read-only, hidden from active lists); false or null means active. |

#### Table `AO_8BAD1B_GENERIC_ITEM_HISTORY`

One row is one change record of a generic item (append-only audit trail used for memo/planning-task history display and for history-based attributes such as created, updated, creator). A row is written each time a generic item is created (C_CREATE true, no old values), restored from backup, or updated by a user (old and new snapshot). Attaching an unowned item to a structure does NOT write a record. Rows are never updated. They are deleted only for given items when a backup is restored or migrated (all history rows of the restored items are removed and replaced by the history from the backup); deleting the item itself keeps its history. Each row's ID is also the numeric id of an item of type `com.almworks.jira.structure:type-memo-change-history-group` (that identity is how a single change record is addressed). Relations: (C_TYPE_ID, C_LONG_ID) -> AO_8BAD1B_GENERIC_ITEM (C_TYPE_ID, ID); C_TYPE_ID -> AO_8BAD1B_ITEM_TYPE.ID. Readers order records by C_TIMESTAMP.

| column | Java type | length | constraints | meaning and stored format |
|---|---|---|---|---|
| `ID` | int |  | primary key, auto increment, not null | Record id (auto-increment integer); doubles as the long id of the item (com.almworks.jira.structure:type-memo-change-history-group, ID). |
| `C_LONG_ID` | long |  | not null, indexed | Numeric id of the generic item that changed (AO_8BAD1B_GENERIC_ITEM.ID). Stored as a 64-bit integer. |
| `C_TYPE_ID` | int |  | not null, indexed | Item type of the changed item (AO_8BAD1B_ITEM_TYPE.ID of e.g. `com.almworks.jira.structure:type-memo`). |
| `C_OLD_NAME` | String | 190 |  | Item name before the change; null on a create record. A blank or null old name is how readers tell that there is no old snapshot (old description/parameters are then ignored). |
| `C_OLD_DESCRIPTION` | String | unlimited |  | Item description before the change, or null (null also for creates). |
| `C_OLD_PARAMETERS` | String | unlimited |  | Item parameters before the change, in the same JSON format as AO_8BAD1B_GENERIC_ITEM.C_PARAMETERS (empty -> null). Null on creates. |
| `C_NEW_NAME` | String | 190 | not null | Item name after the change (required). |
| `C_NEW_DESCRIPTION` | String | unlimited |  | Item description after the change, or null. |
| `C_NEW_PARAMETERS` | String | unlimited |  | Item parameters after the change, same JSON format as AO_8BAD1B_GENERIC_ITEM.C_PARAMETERS; null when empty. |
| `C_AUTHOR` | String | unlimited |  | Jira user key of the user who made the change (the acting user at the time), or null when there was no authenticated user (e.g. system or anonymous context). |
| `C_TIMESTAMP` | long |  | not null, indexed | Time of the change, epoch milliseconds (server clock). Indexed; readers sort by it. |
| `C_CREATE` | boolean |  | not null | True when the record is the creation of the item (including creation by backup restore), false for an update. |
<!-- END generated: ao -->

## 1.6 Other persisted names

Jira and other plugins store these strings in their own data. Changing one breaks existing instances.

**Workflow condition and validator.** A workflow that uses `structure-workflow-condition` or
`structure-workflow-validator` stores, in Jira's workflow XML, the class name
`com.almworks.jira.structure.workflow.StructureWorkflowChecker` (argument `class.name`). The replacement must
have a class with exactly that name, implementing both Jira's condition and validator interfaces. Their
arguments are stored as strings:
| argument | value |
|---|---|
| `runAsLead` | `true`: evaluate as the project lead; `false`: as the user below |
| `runAsUserName`, `runAsUserKey` | only when `runAsLead` is `false`: the user's name and Jira user key |
| `structureType` | `default` (the default structure), `manual` (the structure in `structureId`), or the older `containing`, read as `default` |
| `structureId` | only when `structureType` is `manual`: a structure id |
| `queryString` | the S-JQL query the issue must match |
| `queryDesc` | validator only: the reason shown when the transition is blocked |
| `allowUnstructured` | `true`: an issue not in the structure passes; anything else blocks it |

**JQL function.** Saved filters store `issue in structure(...)`; the function name `structure` is kept
(module `jql-structure`).

**Custom field.** Jira stores custom fields by their type and searcher keys:
`com.almworks.jira.structure:index-monitor-cf-type` and
`com.almworks.jira.structure:index-monitor-cf-searcher`.

**Dashboard gadgets.** Dashboards store a gadget by its spec URI,
`rest/gadgets/1.0/g/com.almworks.jira.structure:<module key>/<location>` (module key and `location` from
`inventory.json`), and the user's settings as user preferences by name:
- `structure-gadget`: `structureId`, `viewId`, `filterId`, `customTitle`, `numRows` (default `10`),
  `isConfigured` (default `false`), `allowChanges` (default `true`), `useCanvasSettings` (default `false`),
  `canvas-viewId`, `canvas-numRows`, `filterType`, `filterQuery`;
- `cfd-gadget`: `scopeStructureId`, `trainingStructureId`, `trainingPeriod` (default `-1`),
  `estimationIssueTypes`, `scopeIssueTypes`, `teamAttributeSpec`, `targetDate`,
  `whenAppearedAttributeSpec`, `whenWorkStartedAttributeSpec`, `whenCompletedAttributeSpec`,
  `ignoreThreshold`, `adjustments`, `customTitle`, `isConfigured` (default `false`).

All preferences are hidden (the gadget sets them itself). Their meaning is in the gadgets' claims.

<!-- BEGIN generated: persisted -->
#### Active Objects module and schema identity

- Plugin key `com.almworks.jira.structure`. The Active Objects module has key `ao` and namespace `com.almworks.jira.structure`. Active Objects derives the table prefix from the namespace: the last 6 hex digits of the MD5 of the namespace, upper-cased, give `AO_8BAD1B_`. The replacement must declare the same namespace, or it will not see the existing tables.
- Every entity carries an explicit table name, so table names do not depend on entity interface names. Column names are the ones in the table notes above, including the misspelt `C_PERMISSONS`.
- No Active Objects upgrade tasks are declared, so the plugin writes no Active Objects model version marker. Schema changes rely on Active Objects' automatic additive migration (new tables and columns are created at start-up).
- One SAL plugin upgrade task is declared with build number 1, and it does nothing. SAL records the highest applied build number in global plugin settings under `com.almworks.jira.structure:build` (decimal string, so `1` on an existing install). If the JVM system property `structure.upgrade.reset` is true, the plugin removes that key at start-up. A replacement that adds upgrade tasks must number them above 1.
- There is no separate data-version marker. Old data is recognised by its contents (legacy values in view settings, and the backup `version` attribute).

#### Plugin's own property table

All global plugin properties live in `AO_8BAD1B_PROPERTY`. Its keys and value formats are listed in that table's notes. Highlights:
- Maintenance settings use the `maintenance.` keys.
- Internal scheduled-job last-run times use `sjm.<job key>`, in epoch ms.
- Other keys: `createdDefaultViews`, `generationTimeLimit`, `manualAdjustments.enableForNewStructure`, `statistics.sendingEnabled`, `welcomeScreen.help`, and the `appSupport.` keys.

Per-structure properties live in `AO_8BAD1B_STRUCTURE_PROPERTY`, and per-item properties in `AO_8BAD1B_S_ITEM_PROPERTY`. Both are described in their table notes.

#### Jira application properties (global, via Jira's application properties store)

Long values are split into chunks of at most 250 characters:
- The first chunk is stored under the key itself, and the rest under `<key>.1`, `<key>.2`, ….
- A reader concatenates chunks until it finds a missing or empty one.
- A writer clears leftover higher-numbered chunks by setting them to null.

Keys marked *chunked* below use this scheme. All values are strings.

| key | value |
|---|---|
| `com.almworks.jira.structure.config.enabledForAllProjects` | `true`/`false`; absent means true. Whether the plugin is enabled for every project. |
| `com.almworks.jira.structure.config.enabledProjects` | *chunked*. Comma-separated Jira project ids, e.g. `10000,10101`. On read, project keys are also accepted (case-insensitive), but a list mixes neither form. Empty means none. |
| `com.almworks.jira.structure.config.enabledForAnyone` / `...config.enabledSubjects` | "use the app" permission. The first key is `true`/`false` (absent = true); the second is *chunked* permission subjects. |
| `com.almworks.jira.structure.config.createForAnyone` / `...config.creatorSubjects` | same pair, for "create structure" |
| `com.almworks.jira.structure.config.synchronizationForAnyone` / `...config.synchronizationSubjects` | same pair, for "synchronization" |
| `com.almworks.jira.structure.config.automationForAnyone` / `...config.automationSubjects` | same pair, for "automation" |
| `com.almworks.jira.structure.config.permission.<key>.anyone` / `com.almworks.jira.structure.config.permission.<key>.subjects` | same pair for the other app permissions. `<key>` is one of `configureGenerators`, `configureEffectors`, `executeEffectors`, `executeEffectorsOnQueries`, `manageGlobalSavedColumns` (keys of com.almworks.jira.structure.api.permissions.CoreAppPermissions). |
| `com.almworks.jira.structure.config.defaultStructure` | decimal structure id of the global default structure; `0` or absent means none |
| `com.almworks.jira.structure.config.defaultStructurePP` | *chunked*. Per-project default structures as comma-separated `<projectId>=<structureId>` pairs, e.g. `10000=12,10101=7`. On read, a project key is accepted in place of the id. Pairs with non-positive ids are ignored. |
| `com.almworks.jira.structure.config.issuePage.autoSwitch` | system default auto-switch strategy for the issue page: `off`, `withIssue` or `default`. Absent means `withIssue`. |
| `com.almworks.jira.structure.config.projectPage.autoSwitch` | same codes, for the project page; absent means `off` |
| `com.almworks.jira.structure.config.issuePage.autoCollapse` | `true`/`false`, absent = true |
| `com.almworks.jira.structure.config.issuePage.keepWhileNavigating` | `true`/`false`, absent = true |
| `com.almworks.jira.structure.config.attributeSensitivity` | *chunked*. JSON `{"sensitivityMode":<int>,"nonSensitiveAttributes":[{"id":"...","format":"...","params":{...}},...]}`. Mode codes are 0 standard, 1 strict and 2 permissive. Each attribute uses the REST attribute-spec shape (keys `id`, `format`, `params`). Absent or unparsable means standard mode with no exceptions. |
| `com.almworks.structure.license` | *chunked*. Text of a vendor (non-Marketplace) license; empty means none. |
| `com.almworks.structure.license.starttime` | epoch ms, decimal. When the developer-mode evaluation license started (only on dev instances). |
| `com.almworks.jira.structure.system.refreshedOnStart` | `true`/`false`. Records whether the plugin has already been re-wired once after a watched dependency changed (Jira Software rank API, Service Management API). |

The permission-subject list is comma-separated, and each subject uses the public encoding of com.almworks.jira.structure.api.permissions.PermissionSubject:
- `anyone`
- `user:<userKey>`
- `group:<groupName>`
- `role:<projectId>:<roleId>`

Example: `group:jira-software-users,role:10000:10002,user:JIRAUSER10100`.

**Dark features.** These are tuning switches. The plugin reads application properties (falling back to JVM system properties) whose keys start with `com.almworks.`, `almworks.`, `structure.` or `testy.`. Its admin dark-features page writes them as plain strings. A backup carries them, and a restore deletes those not in the backup (see the backup section). The following never count as dark features:
- keys matching `com.almworks.structure[.<x>].license[.…]`;
- `com.almworks.atlas-yourkit…`;
- keys under `com.almworks.jira.structure.config.`;
- keys ending in `:build`.

Two dark-feature keys hold user-facing settings:
- `structure.board.issueLinkAction`: instance default of the board link action (`showDetails`, `openIssuePage` or `doNothing`). Absent means `showDetails`.
- `structure.feature.synchronizers.enabled`: shows the synchronizer UI.

Some dark-feature keys are prefixed with a fully qualified internal class name and suffixed `.changesCleanInterval`, `.changePersistedLimit`, `.forestUpdateAttempts`, `.changeCacheLimit` or `.forestSizeLimit`. They are tuning only and are not part of the stored-data contract.

#### Jira user properties and preferences

- **User property set:**
  - `com.almworks.jira.structure.config.issuePage.autoSwitch` and `com.almworks.jira.structure.config.projectPage.autoSwitch` hold `off`, `withIssue` or `default`.
  - `com.almworks.jira.structure.config.issuePage.autoCollapse` and `com.almworks.jira.structure.config.issuePage.keepWhileNavigating` hold `true`/`false`.
  - These are per-user overrides of the system values above, and absent means "inherit". Resetting a user's settings removes all four.
  - `com.almworks.jira.structure.statistics.offerRejected` is a boolean property, set to true once the user (an admin) dismisses the usage-statistics offer.
- **User extended preferences:** `structure.board.issueLinkAction` holds `showDetails`, `openIssuePage` or `doNothing`.

#### Plugin settings (SAL global plugin settings)

Only `com.almworks.jira.structure:build` (see above). The plugin keeps all its other state in the stores listed here.

#### Cluster locks (Jira cluster lock service; matter only for mixed nodes during an upgrade)

- `com.almworks.jira.structure.backup`: one backup or restore at a time.
- `com.almworks.jira.structure.maintenance`: one maintenance run at a time.
- `com.almworks.jira.structure.indexMonitorManager`: creating the index-monitor custom field.
- **Lockers from the shared library:** named `com.almworks.structure..<locker name>.<id>`, with the double dot. Lockers in use:
  - `AOLock`: structure-level database lock, id = structure id.
  - `sjm`: internal scheduled-job runs, id = job key.
  - `ViewManagerInit`: id `createDefaultViews`.
  - `ievent-signature-lock`: item-event node signatures, id `0`.

#### Scheduled jobs

The plugin registers no jobs with Jira's scheduler. It runs internal periodic jobs and records each job's last run time in `AO_8BAD1B_PROPERTY` under `sjm.<job key>`, in epoch ms. Job keys:
- `statistics.lastSentTime`
- `appSupport.lastCheckTime`
- `licenseCheck:<module key>`
- `forestChanges.lastCleanTime`
- `maintenance.scheduled.job`

The maintenance schedule itself is in the `maintenance.scheduled.*` properties.

#### Caches visible to Jira

The shared caches are named `com.almworks.structure.<name>`, for example `forest`, `favorites`, `properties`, `structure-properties`, `structure-item-properties`, `view`, `allViews`, `allStructures` and `structureConfiguration.global`. They hold only derived data and need not be compatible.

#### Jira entities the plugin creates or references

- **Custom field type** `com.almworks.jira.structure:index-monitor-cf-type` and **searcher** `com.almworks.jira.structure:index-monitor-cf-searcher`:
  - At start-up the plugin makes sure there is exactly one global custom field of this type, named `Structure Index Monitor`, with description "System custom field, required for correct functioning of Structure add-on. Does not store any data."
  - It locks that field as a managed configuration item. A non-global instance is deleted and re-created.
  - The field stores no values and adds nothing to the issue index; its indexer only observes reindexing.
  - Existing installs have this field in Jira's custom-field table, keyed by the type key above.
- **JQL function** `structure` (list function). Saved filters, board filters and gadget configs persist JQL such as `issue in structure("My structure", "child of X")`, so the function name and argument grammar are stored contract.
- **Workflow condition and validator** (modules `com.almworks.jira.structure:structure-workflow-condition` and `com.almworks.jira.structure:structure-workflow-validator`):
  - Jira stores them inside workflow XML descriptors as `type="class"` entries whose `class.name` argument is the plugin's checker class, `com.almworks.jira.structure.workflow.StructureWorkflowChecker`. Both modules share that one class. Existing workflows will reference it by that exact name.
  - Further string args:
    - `runAsLead`: `true`/`false`.
    - `runAsUserName` and `runAsUserKey`: present when `runAsLead` is false.
    - `structureType`: `default` (the project's default structure) or `manual`. The legacy value `containing` is read as `default`.
    - `structureId`: decimal, present when `structureType` is `manual`.
    - `queryString`: S-JQL.
    - `queryDesc`: validator only, the message shown when the issue is blocked.
    - `allowUnstructured`: `true`/`false`.
- **Gadgets** `com.almworks.jira.structure:structure-gadget` and `com.almworks.jira.structure:cfd-gadget`. Jira's dashboard tables persist their spec URIs and string user preferences:
  - Structure gadget: `structureId`, `viewId`, `filterId`, `customTitle`, `numRows` (default `10`), `isConfigured` (default `false`), `allowChanges` (default `true`), `useCanvasSettings` (default `false`), `canvas-viewId`, `canvas-numRows`, `filterType`, `filterQuery`, `adjustments`.
  - Cumulative-flow gadget: `scopeStructureId`, `trainingStructureId`, `trainingPeriod` (default `-1`), `estimationIssueTypes`, `scopeIssueTypes`, `teamAttributeSpec`, `targetDate`, `whenAppearedAttributeSpec`, `whenWorkStartedAttributeSpec`, `whenCompletedAttributeSpec`, `ignoreThreshold`, `customTitle`, `isConfigured` (default `false`).
  - The browser script defines the value contents. Ids are decimal strings, and attribute specs are JSON.

#### Lucene / files

- The plugin adds no Lucene fields and writes no index files of its own. Its issue index is the table `AO_8BAD1B_ISSUE_INDEX`.
- The only files it writes under the Jira home are backups in `<jira-home>/export` (see below).
- It reads restore and migration files from `<jira-home>/import`.

#### Backup files: location, naming, container

- The plugin's backup is one UTF-8 XML document (XML declaration `<?xml version="1.0" encoding="UTF-8"?>`, two-space indentation, no namespaces). It is either written as a bare `.xml` file or wrapped in a `.zip` that holds exactly **one** entry.
- Zip entry name: when the plugin writes a backup file, the entry is named after the file, with `.zip` swapped for `.xml`. So `my-backup.zip` holds `my-backup.xml`, and a name without `.zip` gets `.xml` appended. When it writes the backup into a stream or into a shared zip, as cloud migration does, the entry is named `backup.xml`.
- If the requested file name has no dot, `.zip` is appended when zipping and `.xml` otherwise. Missing parent directories are created. A partially written file is deleted if writing fails.
- Manual backup from the admin UI always zips. The target must resolve inside Jira's **export directory** (`<jira-home>/export`, the directory Jira reports as its export dir). Paths that escape it are refused, and overwriting an existing file needs confirmation.
- Scheduled maintenance backup (maintenance task key `backup`, option `backup-saveHistory`, default true) writes `<jira-home>/export/structure-YYYYMMDD-HHmm.zip`, using server local time and US locale. If that name exists it tries `-1` … `-9` before the extension, for example `structure-20261028-0300-2.zip`, and gives up after `-9`. History is included unless the option is false.
- Old-backup cleanup (maintenance task key `removeOldBackups`, options `removeOldBackups-minFilesToKeep`, default 5, and `removeOldBackups-minDaysToKeep`, default 15) deletes files in the export dir whose names fully match `^structure-\d{8}-\d{4}(-\d)?\.zip$`. A file qualifies only if the date-time parsed from its name is older than the minimum days. It deletes no more than (count − minFilesToKeep) files, oldest first by base name, retrying each deletion up to 5 times, 1 s apart. Other files in the export dir are never touched.
- Restore and the "migrate from backup" import read only from Jira's **import directory** (`<jira-home>/import`). A relative name resolves against it, and anything outside it is refused. File type is detected as follows:
  - a name ending in `.xml` is read as plain XML;
  - a name ending in `.zip` must be a zip with exactly one entry ("too many files" is an error);
  - any other name is tried as a zip first and then as plain XML.

#### Backup XML: overall layout (format version written: `5.0`)

The root is `<structure-backup version="5.0">`. Child sections appear in the order shown below. Sections switched off for a run are omitted entirely. Optional child elements are omitted when the value is null or empty: the writer never emits an empty text element, except for the marker elements noted below. Unknown elements are skipped by the reader at every level. Booleans are `true`/`false`. Numbers are decimal. Ids are the database ids from the AO tables, so a restore preserves them.

1. `meta`: `<date>` holds the backup time as `yyyy-MM-dd HH:mm:ss` in server local time. `<by>` holds the Jira user key of the user who ran the backup, or `system`. Restore ignores this section.
2. `properties` (only when application configuration is included): one `<property name="KEY">VALUE</property>` per row of `AO_8BAD1B_PROPERTY` (C_KEY → `name`, C_VALUE → text). The single key `maintenance.scheduled.nextRunTime` is excluded. On restore every property is written back with set semantics, overwriting the same key. That table is not wiped by restore.
3. `structures`: one `<structure id="N">` per structure, ascending by id. Children, in order:
   - `name`;
   - `description`;
   - `owner`: the owner encoded as `user:<userKey>`;
   - `owner2`: `<user><key>K</key><name>USERNAME</name></user>`, which carries the user name too so the owner can be remapped on another instance;
   - `permissions`: zero or more `<rule>ENCODED</rule>`, in the same rule encoding as the structure permissions column (see below);
   - `permissions2`: the same rules in structured form (see below);
   - `requireEditOnParent` (`true`, present only when set);
   - `archived` (`true`, present only when set);
   - `forest version="V"`: the latest forest version number, with the row tree nested inside (see "Row elements");
   - `manualAdjustments` (optional; see below).
4. `histories` (only when history is included): one `<history structure="SID">` per structure whose forest version is > 0, holding `<entry>` elements in version order (see "History").
5. `structureFields` (present only if some backed-up generic item uses custom fields): one or more `<fieldInfo type="FIELD-TYPE-KEY">`, each holding
   - `<field id="FIELD-ID" name="FIELD NAME">` with an optional `<properties>` child (the field type's own serialized properties string);
   - `<value><serializedValue>S</serializedValue><resolutionValue>R</resolutionValue></value>`, one per distinct value used. S is the value exactly as stored inside the generic item's parameters JSON. R is the human-readable option name it stands for (for option-based field types: the option's display name). R is used to re-resolve S on a different instance.
6. `synchronizers`: one `<synchronizer id="SYNC-ID" structureId="SID">` per sync instance whose owner still exists. Children:
   - `moduleKey`;
   - `ownerKey`: user key;
   - `ownerName`: user name;
   - `autosyncEnabled`: `true`/`false`;
   - `parameters`: the C_PARAMETERS string of `AO_8BAD1B_SYNC_INSTANCE`, verbatim.

   The reader also accepts the legacy names `key` for moduleKey, `user` for ownerKey and `params` for parameters.
7. `favorites` (optional section): `<user name="USERKEY">` containing `<structure id="SID"/>` per favourite. The `name` attribute carries the user **key**, except in format `0.4`, where it is a user name.
8. `savedColumns` (optional section): `<column id="N" sourceId="SOURCE" type="TYPE">` with children `name`, `description`, `additionalData` (a JSON object, source-specific extra data) and `params` (a JSON object of column parameters). A column without type or name is ignored on restore.
9. `notes`: `<note id="N" permissionScheme="SPEC">` (both attributes mandatory) with children `name`, `created` (epoch ms) and `archived` (`true`, present only when set). This maps onto `AO_8BAD1B_NOTE`.
10. `views`: `<view id="N" system="true|false">`. `system` is true when the view has no owner, meaning a built-in or default view. Children:
    - `name`;
    - `description`;
    - `owner`, `owner2`, `permissions`, `permissions2`, each as for structures;
    - `spec`: the view specification as JSON, the same JSON as the view's stored data. When saved columns are not included, the saved-column reference is stripped from each column's parameters.
11. `viewAssociations`: `<structure id="SID">TEXT</structure>`, where TEXT is the raw C_VIEW_SETTINGS string of `AO_8BAD1B_STRUCTURE_TO_VIEW` for that structure. Id `0` is the global default view settings.
12. `perspectives` (optional section): `<perspective id="N">SPEC</perspective>`, where SPEC is the raw C_SPEC of `AO_8BAD1B_PERSPECTIVE`. Only valid perspectives are written.
13. `structureProperties`: `<property structureId="SID" key="KEY">VALUE</property>`, one per non-null per-structure property (`AO_8BAD1B_STRUCTURE_PROPERTY`).
14. `structureItemProperties`: `<structure id="SID">` → `<property name="PROPNAME">` → one item element per item, whose text is the property value (`AO_8BAD1B_S_ITEM_PROPERTY`). The item element uses the item tag table below with an `id` attribute when the item type has a tag and a numeric id. Otherwise it is `<item itemId="ITEM-ID-STRING">`.
15. `configuration` (only with application configuration):
    - `<enabledForProjects><all>true|false</all><projects><project id="PID"><key>K</key><name>N</name></project>…</projects></enabledForProjects>`. `projects` appears only when projects were picked.
    - Then one `<permission name="APPKEY">` per application permission, in this order: `use`, `createStructure`, `synchronization`, `automation`, `configureGenerators`, `configureEffectors`, `executeEffectors`, `executeEffectorsOnQueries`, `manageGlobalSavedColumns`. Each holds `<anyone>true|false</anyone>` and optionally `<subjects>` containing subject elements (see below).
16. `attributeSettings` (only with application configuration): `<sensitivityMode>` holds 0 = standard, 1 = strict or 2 = permissive. `<nonSensitiveAttributes>` holds one `<spec>` per attribute, each a JSON object with keys `id` (string), `format` (string) and `params` (object), for example `{"id":"customfield","format":"text","params":{"fieldId":10010}}`.
17. `darkFeatures` (only with application configuration): `<property key="K">V</property>` for each Jira application property (or JVM system property) whose key starts with `com.almworks.`, `almworks.`, `structure.` or `testy.` and whose value is non-empty. License keys are excluded (`com.almworks.structure[.x].license[.…]`), as are `com.almworks.atlas-yourkit…`, `com.almworks.jira.structure.config.…` and keys ending in `:build`. On restore, matching application properties that are absent from the backup are **cleared**, and those present are set.
18. `gadgets` (written only by the cloud-migration export; restore skips it): `<gadget id dashboardId [dashboardOwnerKey] moduleKey column row [color] [gadgetUri]>` with `<userPref name="N">V</userPref>` children, sorted by name.
19. `extensions`: `<extension key="APP-PLUGIN-KEY" version="PLUGIN-VERSION">` wrapping whatever XML that extension's backup provider writes, which is opaque to the core. On restore the block goes to the provider registered for the same key, and it is skipped if there is none.
20. `genericItemHistory` (optional section): `<historyRecord itemLongId="N" itemTypeId="TYPE-KEY" isCreate="true|false" timestamp="EPOCH-MS" [author="USERKEY"] [structure="SID"]>` with optional children `oldName`, `oldDescription`, `oldParams` (JSON), `newName`, `newDescription` and `newParams` (JSON). This maps onto `AO_8BAD1B_GENERIC_ITEM_HISTORY`. Only records for generic items present in the backed-up forests are written.

On reading, top-level sections may come in any order, but dependent sections must come after `structures`. These are histories, synchronizers, favorites, structure fields, item properties and generic item history. Synchronizers, histories and generic-item history are dropped for any structure that was not successfully read. Writers should keep the order above.

#### Row elements (forests, adjustments, history lists)

A forest is written as nested elements. A row's children are the elements nested inside it, and depth equals nesting level. The tag gives the item type:

| tag | item type key |
|---|---|
| `issue` | `com.almworks.jira.structure:type-issue` |
| `folder` | `com.almworks.jira.structure:type-folder` |
| `generator` | `com.almworks.jira.structure:type-generator` |
| `effector` | `com.almworks.jira.structure:type-effector` |
| `project` | `com.almworks.jira.structure:type-project` |
| `component` | `com.almworks.jira.structure:type-project-component` |
| `version` | `com.almworks.jira.structure:type-version` |
| `item` | any other type |

Attributes:
- `rowId`: the row id from `AO_8BAD1B_ROW`, written only when > 0.
- `semantics`: written only when non-zero.
- `id`: the numeric item id, on typed tags.
- `itemId`: the item id string, on `item`. It is `<typeKey>/<longId>` for numeric ids and `<typeKey>//<stringId>` for string ids. A bare number means an issue id.

Descriptive child elements, which come before nested child rows, are used to re-resolve or recreate items on restore:
- issue: `key`, `summary`;
- project: `key`, `name`;
- component/version: `name`, `projectId`, `projectKey`, `projectName`;
- generator/effector: `moduleKey`, `parameters` (JSON object, omitted when empty);
- folder: `name`;
- generic items (`item` with `itemId`): `name`, `description`, `parameters` (JSON);
- other items: `description`, `url`.

A row whose data is missing is written as `<item rowId="N"/>`. On read, a row element without a positive `rowId` gets a temporary negative id, and its item is ignored. So forest rows must carry `rowId`, except inside adjustment and item-path contexts.

Restore re-creates rows with their original row ids and the original ids of generators, effectors, folders and generic items. It recreates generators and effectors from `moduleKey`+`parameters`, folders from `name`, and generic items from `name`/`description`/`parameters` (an `item` element with a `name` child counts as a generic item). It keeps issue ids that still exist. Unresolvable items are kept with their original id, and the restore reports them.

Example:
```xml
<forest version="12">
  <issue rowId="101" id="10200"><key>DEMO-1</key><summary>Epic</summary>
    <issue rowId="102" id="10201"><key>DEMO-2</key><summary>Task</summary></issue>
  </issue>
  <generator rowId="103" id="7"><moduleKey>EXAMPLE-MODULE-KEY</moduleKey><parameters>{"jql":"project = DEMO"}</parameters></generator>
  <item rowId="104" itemId="com.almworks.jira.structure:type-memo/3"><name>Note</name></item>
</forest>
```

#### Manual adjustments

`<manualAdjustments>` holds a list of `<adjustment type="add|move">` elements:
- `add` contains `<added>` (a forest fragment of row elements) followed by `<under>`, `<after>` and `<before>`.
- `move` contains `<moved>`, `<under>`, `<after>` and `<before>`.

Each of the position elements (`moved`, `under`, `after`, `before`) contains exactly one of the following:
- `<zero/>`;
- `<missing/>`;
- `<rowId>ROW-ELEMENT</rowId>`;
- `<itemPath>`: a sequence of `<rowId>ROW-ELEMENT</rowId>` and/or `<itemId [persistent="true"]>ROW-ELEMENT</itemId>`. In `itemId` the row element carries item id and semantics but no rowId.

All four position elements (three for `add`, plus `added`) are required, or the adjustment is dropped.

#### History

`<entry version="V" prevVersion="P">` (V ≥ 1) has these children:
- `timestamp`: an XML Schema dateTime with offset, for example `2026-10-28T14:07:09.123+01:00`; required;
- `userkey`: optional;
- `synchronizer`: sync instance id, optional;
- one or more `<change>` elements.

Each `<change>` has these children:
- `operation`: `add`, `copy`, `move` or `remove`;
- `<forest>`: the affected rows as row elements; required;
- `<parentPath type="source|destination">` and `<precedingSibling type="source|destination">`: flat row lists, where `source` is the from-position and `destination` the to-position. They are omitted when empty, and the reader treats a missing one as empty where the operation needs it;
- `direction`: −1 or 1, omitted when 0;
- `<originalRows>`: a flat list.

**Compatibility quirk:** the writer emits `direction`, but the reader only recognises `moveDirection`, clamped to −1..1. So a restored history always gets direction 0. A compatible reader should accept both names.

History entries restore with their original versions. After history is read, each structure's forest version is set to the version from `forest version`.

#### Permission encodings used in backups

- Rule strings (`<rule>` and the structure/view permission columns):
  - `set:<level>:<subject>`, where level is a number: 0 none, 10 view, 20 edit, 25 edit-generators/automate, 30 admin. Reading also accepts a level name in place of the number.
  - `apply:<structureId>`.
  - Subjects: `anyone`, `user:<userKey>`, `group:<groupName>`, `role:<projectId>:<roleId>` (projectId 0 means any project).
  - Example: `set:20:group:jira-developers`.
  - In format `0.4`, `user:` carries a user name instead of a key.
- `permissions2` holds `<setLevel level="N">SUBJECT</setLevel>` or `<applyStructure structureId="SID"/>`. SUBJECT elements are:
  - `<anyone/>`;
  - `<user><key/><name/></user>`;
  - `<group><name/></group>`;
  - `<projectRole>` with an optional `<project id="PID"><key/><name/></project>` and a `<role id="RID"><name/></role>`.

  Restore prefers these structured forms when they are present, and uses names to remap users, groups, projects and roles on another instance.

#### What a full restore does to stored data

1. Restore takes the database lock. Before reading, it drops and recreates every plugin table **except** these: `AO_8BAD1B_BOOTSTRAP`, `AO_8BAD1B_ATOMIC_FLAG`, `AO_8BAD1B_NODE_SIGNS_V2`, `AO_8BAD1B_ITEM_EVENTS_V2`, `AO_8BAD1B_ITEM_TYPE`, `AO_8BAD1B_PROPERTY`, `AO_8BAD1B_PROCESS_STATE`, `AO_8BAD1B_STATISTICS`.

   This means all structures, forests, rows, history, views, sync instances, favourites, saved columns, notes, effector processes and records, migration configs, orderings, issue index and so on are emptied. They are then refilled from the file with the **original primary keys**. Ids are inserted explicitly for these tables: structures, rows, generators, effectors, folders, generic items, views, saved columns, notes and sync instances.
2. Caches on all cluster nodes are cleared before and after.
3. Data not present in a backup is lost on restore:
   - the issue index (not verified whether the plugin rebuilds it afterwards);
   - forest change log;
   - events;
   - statistics;
   - process states;
   - effector processes and records;
   - migration configurations;
   - orderings;
   - manual-adjustment rows outside forests.

#### Accepted input versions

- Current reader: root `structure-backup` with `version` = `3.0`, `3.3` or `5.0`.
- If that reader rejects the file, a legacy reader is tried for versions `0.4` and `2.3`. In those versions forests contain only `<issue id>` rows with `key`/`summary` children, history entries use `username`, and rows get fresh ids. Restoring synchronizers from such files is refused with a message.
- A root named `structure` is rejected as "too old".
- Any other version is rejected.
- In format `0.4`, user references (owners, rules, favourites) are user **names** and are converted to user keys.

#### Migrate-from-backup (import into a live instance)

This reads the same file format from the import directory but does not wipe tables. Selected structures, with their views, columns, notes and the rest, are created alongside existing data where ids may change; items are re-resolved by key or name (behaviour detail not fully traced). Afterwards the old → new perspective id mapping is reported.

#### Cloud migration export (data sent off-instance)

On an Atlassian cloud-migration (app data transfer) request, the plugin streams a zip through the Jira cloud-migration app-data API in chunks labelled `structure_backup_0`, `structure_backup_1`, …. Then it uploads `structure_backup_table_of_contents`, containing `{"count":N,"sequence":["structure_backup_0",…]}`.

The zip contains:
- `backup.xml`: format above, with no history, generic-item history, application configuration or perspectives, restricted to the structures (and the views they use) chosen in the migration configuration, plus the `gadgets` section when dashboard gadgets are included;
- `meta.json`: `{"configs":[{"name":…,"status":…,"structures":[ids]}],"selectedConfig":NAME|null}`.

The `extensions` providers receive the option `includeDashboardGadgets` (boolean).

#### Other files

- The plugin writes no other files under the Jira home. No caches, indexes or logs of its own go there; it logs through Jira's logging.
- Excel and printable exports, and the S-JQL troubleshooting zip (single entry `S-JQL_Troubleshooting.log`), are streamed to the browser and are not persisted.
<!-- END generated: persisted -->

**Module keys inside the plugin's own data.** Stored rows refer to some modules by complete key, such as
item types, generators, effectors and synchronizers (section 1.5). So module keys are data too.

## 1.7 Front-end extension points

Other apps add parts to the plugin's pages through these names, so they are kept even though no module of the
original uses them itself:
- web-resource contexts `structure.widget` (the structure widget on any page: board, gadget, issue panel) and
  `structure.printable` (the printable page);
- the web-item location `structure.export.menu` (the board's export menu);
- every web-resource's module key, context and dependency (`inventory.json`), and every web section and
  location the plugin declares.

The browser-side programming interface that extension apps call is specified with the web-resources' claims.

## 1.8 Out of scope: contacting the vendor

The original contacts its vendor and the Atlassian Marketplace over the network. The replacement never does
(product owner decision, 2026-10-28): it opens no connection to the vendor, the Marketplace or any other
server of its own accord.
- **Licence reports.** `app-support-client` and `app-support-connector` keep their module keys and send
  nothing. With no reports, no serial number is ever blocked.
- **Usage statistics.** `statistics-manager` collects, stores and purges statistics locally, and keeps the
  administrator's opt-in offer and the stored setting, but never uploads.
- **Update check.** `plugin-update-checker` never contacts the Marketplace; it always reports that no update
  is known.
- **About popup.** `GET /rest/structure/2.0/info-popup` reports every "update available" flag, for the
  plugin and for each companion app, as `false`, and never asks the Marketplace.

REST endpoints and pages that would show the result of such a call show the "nothing sent / nothing known"
state.

# Part 2. The public Java API

Part 2 is in `API.md`, because of its size. It lists every package and type of the public Java API, and the
two contract types outside it (`com.almworks.jira.structure.generic.GenericItemHistoryManager` and its record
type), with every public and protected member as a Java declaration and its meaning.
