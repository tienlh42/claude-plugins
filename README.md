# claude-plugins

Personal Claude Code plugin marketplace (Le Hai Tien).

## Install

```bash
claude plugin marketplace add https://github.com/tienlh42/claude-plugins
claude plugin install generate-permissions@lehaitien-plugins
claude plugin install api-permission@lehaitien-plugins
```

## Plugins

### generate-permissions

Scans a Django backend repo to enumerate its endpoints (`method` +
`api_pattern`), then drafts a permission CSV (feature, group, description,
slugs...) for human review before importing it through whatever CSV/Excel
import mechanism the target system already has. It never writes to a
database directly.

Use it when a Django repo has new endpoints that need permissions assigned,
or to audit an existing permission list without typing every row by hand.

See [plugins/generate-permissions/skills/generate-permissions/SKILL.md](plugins/generate-permissions/skills/generate-permissions/SKILL.md)
for the full workflow, options, and known limitations.

### api-permission

Looks up one or more `service-api` endpoints by URL (`/hubspot/student/detail/126`,
`/hubspot/student/detail/pk`) or view class (`SyncStudentDebts`) and reports
which view handles it, whether `RoleAccess` gates it, the matching
`authentication_permission` row in the DB, and which roles can currently get
through. Then proposes a CSV permission row that follows how the importer and
`RoleAccess` actually behave. It never writes to the database.

Specific to `service-api`: `lookup.py` runs inside the `crm-api` container's
Django shell.

```
/api-permission SyncStudentDebts /hubspot/student/export-xlsx
```

See [plugins/api-permission/skills/api-permission/SKILL.md](plugins/api-permission/skills/api-permission/SKILL.md).

## Structure

```
.claude-plugin/marketplace.json          # marketplace manifest, lists plugins below
plugins/
  generate-permissions/
    .claude-plugin/plugin.json           # plugin manifest
    skills/generate-permissions/
      SKILL.md
      scripts/
        scan_django_permissions.py
        diff_against_csv.py
        merge_into_existing_csv.py
  api-permission/
    .claude-plugin/plugin.json
    skills/api-permission/
      SKILL.md
      lookup.py
```

Each plugin under `plugins/` is self-contained and can be added on its own
via `claude --plugin-dir <path>` for local testing.

## License

MIT
