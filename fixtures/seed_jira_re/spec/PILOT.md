# The pilot's scope

This project is a pilot: it covers only part of the specification, listed here. `spec/` describes the whole
plugin, and at about 5 MB it is far too large to read at once. Read this file, then `pilot-claims.jsonl`, and
search the other files for what you need.

- **In scope:** the 86 modules below and their claims, and the 58 API claims at the end, which are
  748 claims in all. They are all in `pilot-claims.jsonl`, copied unchanged from `claims.jsonl`.
- **Still whole:** the skeleton of stage 1. Every module of `inventory.json` is declared and every type of the
  public Java API exists with its exact signatures, in scope or not.
- **Out of scope:** the behaviour of every other module and API type. Where a module in scope needs one of those,
  give it the smallest stub that lets you build and test, and leave that module `not_started` in
  `analysis/rewrite_map.json`. Do not implement it.
- **A claim that depends on something out of scope** is still in scope: test it against a stand-in for that part.

## Modules

| group | module | type | claims |
|---|---|---|---|
| core-model | `clipboard-manager` | component | 7 |
| core-model | `favorite-manager` | component | 11 |
| core-model | `folder-manager` | component | 5 |
| core-model | `forest-service` | component | 19 |
| core-model | `generic-item-field-accessor-manager` | component | 7 |
| core-model | `generic-item-field-config-service` | component | 8 |
| core-model | `generic-item-manager` | component | 14 |
| core-model | `generic-item-service` | component | 11 |
| core-model | `generic-item-type-helper` | component | 6 |
| core-model | `issue-to-planning-task-converter` | component | 4 |
| core-model | `item-identity-mapper` | component | 4 |
| core-model | `item-resolver` | component | 8 |
| core-model | `item-type-registry` | component | 6 |
| core-model | `jira-field-visibility-service` | component | 7 |
| core-model | `memo-manager` | component | 10 |
| core-model | `planning-task-manager` | component | 10 |
| core-model | `structure-field-manager` | component | 6 |
| core-model | `structure-field-type-manager` | component | 12 |
| core-model | `structure-manager` | component | 60 |
| core-model | `structure-row-manager` | component | 9 |
| core-model | `sub-task-issue-cache` | component | 4 |
| core-model | `transient-row-manager` | component | 9 |
| core-model | `type-attachment` | structure-item-type | 4 |
| core-model | `type-cf-option` | structure-item-type | 4 |
| core-model | `type-change-history-group` | structure-item-type | 7 |
| core-model | `type-change-history-item` | structure-item-type | 10 |
| core-model | `type-comment` | structure-item-type | 4 |
| core-model | `type-effector` | structure-item-type | 8 |
| core-model | `type-folder` | structure-item-type | 8 |
| core-model | `type-generator` | structure-item-type | 7 |
| core-model | `type-group` | structure-item-type | 2 |
| core-model | `type-insight-object` | structure-item-type | 5 |
| core-model | `type-issue` | structure-item-type | 22 |
| core-model | `type-issue-link` | structure-item-type | 4 |
| core-model | `type-issue-link-type` | structure-item-type | 4 |
| core-model | `type-issuetype` | structure-item-type | 4 |
| core-model | `type-label` | structure-item-type | 2 |
| core-model | `type-loop-marker` | structure-item-type | 3 |
| core-model | `type-memo` | structure-item-type | 5 |
| core-model | `type-memo-change-history-group` | structure-item-type | 6 |
| core-model | `type-missing` | structure-item-type | 3 |
| core-model | `type-planning-task` | structure-item-type | 9 |
| core-model | `type-priority` | structure-item-type | 4 |
| core-model | `type-project` | structure-item-type | 4 |
| core-model | `type-project-component` | structure-item-type | 6 |
| core-model | `type-remote-link` | structure-item-type | 5 |
| core-model | `type-resolution` | structure-item-type | 4 |
| core-model | `type-sd-request-type` | structure-item-type | 5 |
| core-model | `type-sprint` | structure-item-type | 4 |
| core-model | `type-status` | structure-item-type | 4 |
| core-model | `type-structure` | structure-item-type | 5 |
| core-model | `type-tempo-account` | structure-item-type | 4 |
| core-model | `type-user` | structure-item-type | 4 |
| core-model | `type-version` | structure-item-type | 6 |
| core-model | `type-version-name` | structure-item-type | 2 |
| core-model | `type-worklog` | structure-item-type | 6 |
| permissions-security | `attribute-sensitivity-manager` | component | 6 |
| permissions-security | `bulk-permission-checker` | component | 4 |
| permissions-security | `forest-permissions-cache` | component | 9 |
| permissions-security | `partitioned-cookie-header-filter` | servlet-filter | 9 |
| permissions-security | `permission-scheme-manager` | component | 8 |
| permissions-security | `permissions-cache` | component | 8 |
| permissions-security | `permissions-calculator` | component | 23 |
| permissions-security | `permissionsEditor` | web-resource | 13 |
| permissions-security | `project-scope-cache` | component | 5 |
| permissions-security | `security-filter` | servlet-filter | 12 |
| permissions-security | `structure-permissions` | web-resource | 9 |
| persistence | `adjustment-store` | component | 8 |
| persistence | `ao` | ao | 4 |
| persistence | `ao-based-statistics-service` | component | 9 |
| persistence | `ao-helper` | component | 9 |
| persistence | `ao-lock` | component | 9 |
| persistence | `effector-process-io` | component | 16 |
| persistence | `history-recorder-io` | component | 6 |
| persistence | `note-manager` | component | 10 |
| persistence | `notes-manager` | component | 9 |
| persistence | `ordering-io` | component | 4 |
| persistence | `persistent-generator-manager` | component | 5 |
| persistence | `persistent-row-manager` | component | 9 |
| persistence | `perspective-io` | component | 6 |
| persistence | `process-io` | component | 8 |
| persistence | `property-service` | component | 6 |
| persistence | `saved-column-io` | component | 8 |
| persistence | `structure-database-provider` | component | 8 |
| persistence | `structure-property-service` | component | 6 |
| licensing-support | `structure-info` | web-resource | 23 |

## API claims

C-0316, C-0420, C-0421, C-0422, C-0423, C-0426, C-0427, C-0428, C-0429, C-0431, C-0432, C-0433, C-0435, C-0436, C-0437, C-0439, C-0440, C-0441, C-0442, C-0443, C-0444, C-0446, C-0452, C-0453, C-0454, C-0455, C-0456, C-0458, C-0459, C-0460, C-0503, C-0504, C-0505, C-0506, C-0507, C-0508, C-0510, C-0511, C-0512, C-0514, C-0515, C-0517, C-0520, C-0669, C-0830, C-0831, C-0832, C-0833, C-0835, C-0836, C-0837, C-0838, C-0839, C-0840, C-0842, C-0843, C-0844, C-0845
