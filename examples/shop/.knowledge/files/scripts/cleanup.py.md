---
type: Source File
title: scripts/cleanup.py
description: Module defining 1 public function (run).
resource: https://github.com/venkat2912/Rizhome/blob/HEAD/scripts/cleanup.py
tags: [python, 'subsystem:unlinked-scripts', 'security:shell-exec']
timestamp: '2026-10-03T17:13:18+00:00'
language: python
content_hash: sha256:4e7f76e9a7dcf77a
subsystem: unlinked-scripts
parser: ast
loc: 3
fan_in: 0
fan_out: 0
centrality: 0.02326
---

# Summary

Module defining 1 public function (run).

# Subsystem

Part of [Unlinked files in scripts](/subsystems/unlinked-scripts.md).

# Symbols

- `def run()` (L3)

# Functions

- `run` (L3-L4)

# Depends on

None.

# Used by

None.

# External dependencies

`os`

# Security notes

- L4 · **high** · shell-exec: `os.system()` runs a shell command
