**Stage 0: onboarding, and an inventory of the plugin**

We are replacing a Jira Data Center plugin that we no longer have the source for. Its jar is in
`vendor/`. Over the coming stages you will work out exactly what it does, write that down as a
behavioural specification, and then build a clean-room replacement: a Jira plugin, built from this repository, that can be installed
in place of the original. Read
`README.md`, `CLAUDE.md` (project rules, binding) and `ENVIRONMENT.md` first. `ENVIRONMENT.md` lists
the decompilers and other tools you have.

This stage is only about understanding the plugin's structure. Do not start the rewrite yet.

## 0.1 Decompile

Decompile the jar into `.decompiled/` (git-ignored; never commit decompiled code). Use whichever of the
tools in `ENVIRONMENT.md` give you the most readable output. You can use more than one.

## 0.2 Inventory

Write two files.

`analysis/INVENTORY.md`, for people: what the plugin is for, its modules (from
`atlassian-plugin.xml`), the main classes and how they fit together, external Jira APIs it depends on,
and anything you could not work out.

`analysis/inventory.json`, for tools, in exactly this shape:

```json
{
  "plugin": {"key": "...", "name": "...", "version": "..."},
  "modules": [
    {"key": "<the module's key in atlassian-plugin.xml>",
     "type": "<its element name, e.g. workflow-validator, rest, customfield-type, servlet>",
     "class": "<fully qualified implementing class, or null>",
     "purpose": "<one or two sentences>",
     "evidence": ["com.example.Foo", "com.example.Foo#validate"]}
  ],
  "classes": [
    {"name": "com.example.Foo", "role": "<one sentence>", "module_keys": ["..."]}
  ]
}
```

Every module in `atlassian-plugin.xml` must appear. Evidence entries are fully qualified class names,
optionally with `#methodName`, exactly as they appear in the jar (inner classes as `Outer$Inner`).

Commit both files.
