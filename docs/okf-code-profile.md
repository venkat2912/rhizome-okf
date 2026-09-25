# OKF Code Profile (okf-code/0.1)

This document defines conventions for representing a **source-code repository** as an
[Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
(OKF v0.1) bundle. OKF requires only a `type` field on every concept and leaves the content
model to producers; this profile fixes the content model for code so that bundles produced by
different scanners can be consumed by the same agents without translation.

A conforming bundle declares `profile: okf-code/0.1` in the frontmatter of its root `index.md`.

## 1. Layout

```
.knowledge/                     bundle root (committed next to the code it describes)
├── index.md                    type: Index    – orientation, subsystem list, hotspots
├── log.md                      type: Log      – chronological history of knowledge updates
├── subsystems/
│   ├── index.md                type: Index    – all level-1 subsystems
│   ├── <slug>.md               type: Subsystem
│   └── <slug>/
│       ├── index.md            type: Index    – components of <slug>
│       └── <child>.md          type: Component
├── files/
│   ├── index.md                type: Index    – one per directory, mirrors the repo tree
│   └── <repo path>.md          type: Source File (e.g. files/src/app/auth.py.md)
├── requirements/               optional
│   ├── index.md                type: Index
│   └── <slug>.md               type: Requirement
└── .rhizome/state.json         producer state (hashes, cached summaries); not a concept
```

**Identity rule.** A source file's concept path is derived from its repository path
(`/files/<path>.md`) and never from its community. Communities change as code evolves;
file identities must not.

## 2. Concept types

| type | One per | Required profile fields (in addition to OKF `type`) |
|---|---|---|
| `Source File` | source file | `title` (repo path), `description`, `resource`, `tags`, `timestamp`, `language`, `content_hash`, `subsystem` |
| `Subsystem` | level-1 community | `title`, `description`, `tags`, `timestamp`, `level`, `size`, `hub`, `grouping`, `cohesion`, `connected` |
| `Component` | level-2 community | as Subsystem, plus `parent` |
| `Requirement` | requirement document | `title`, `description`, `resource`, `tags`, `timestamp` |
| `Index` | directory | `title`, `description`, `timestamp` |
| `Log` | bundle | `title`, `description`, `timestamp` |

Optional `Source File` fields: `component`, `loc`, `fan_in`, `fan_out`, `centrality`.

### Field semantics

- `resource` – URL of the real artefact. Use a branch-stable form (`…/blob/HEAD/<path>`) rather
  than a commit SHA, so that committing the bundle together with the code does not make it stale.
- `content_hash` – `sha256:<16 hex>` of the file bytes. This, not git history, is the freshness
  anchor: a concept is stale iff its `content_hash` differs from the file on disk.
- `timestamp` – when the concept's *content* last changed (not when the scanner last ran).
  Unchanged concepts keep their timestamp across scans, keeping diffs minimal.
- `tags` – must include `python` (or the language), `subsystem:<slug>`; may include `test`,
  `area:<name>` and `security:<rule>` (one per non-informational finding).
- `grouping` – `leiden` for communities found by community detection, or
  `directory (no internal imports)` for files with no internal dependency edges.
- `cohesion` – internal edge weight / (internal + boundary edge weight), in [0, 1].
- `connected` – `true` iff the community's induced import subgraph is connected. Producers
  using the Leiden algorithm iterated to a stable partition guarantee this.

## 3. Body sections (typed links)

Markdown links are untyped. The profile types them by the **section heading** they appear
under. Consumers must interpret links by section:

| Concept type | Section | Link meaning |
|---|---|---|
| Source File | `# Subsystem` | member-of (Subsystem, then Component) |
| Source File | `# Depends on` | this file imports the target; line lists imported names |
| Source File | `# Used by` | the target imports this file |
| Source File | `# Requirements` | a requirement this file implements |
| Subsystem / Component | `# Members` | member files, ordered by centrality (most central first) |
| Subsystem | `# Components` | child components |
| Component | `# Parent` | parent subsystem |
| Subsystem / Component | `# Depends on subsystems` / `# Depends on sibling components` | aggregated import edges |
| Subsystem / Component | `# Used by subsystems` / `# Used by sibling components` | aggregated reverse edges |
| Requirement | `# Implemented by` | code files matched to the requirement |

Other sections (`# Summary`, `# Symbols`, `# External dependencies`, `# Security notes`,
`# Text`) are informational. `Depends on` / `Used by` must be symmetric across the bundle.

## 4. Co-evolution protocol

1. A change that edits source files **must** update the affected concepts in the same commit
   or pull request (`rhizome scan`).
2. CI runs `rhizome check`; it fails when any concept would change on re-scan.
3. Every scan that changes the bundle appends an entry to `log.md` listing added, modified,
   removed and re-grouped files and new or dissolved communities.
4. Human reviewers review the knowledge diff together with the code diff.
