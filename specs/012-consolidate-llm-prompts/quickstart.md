# Quickstart: Verify Prompt Consolidation

**Date**: 2026-06-14
**Feature**: [spec.md](./spec.md)

## Verification Steps

1. **All prompts centralized**:
   ```bash
   grep -E "(^[A-Z_].*_PROMPT|^def build_.*_prompt)" hatsume/plugins/hatsume-plugin/prompts.py | wc -l
   ```
   Expected: finds all prompt definitions

2. **Syntax valid**:
   ```bash
   python -c "from hatsume.plugins.hatsume_plugin.prompts import *"
   ```

3. **Tests pass**:
   ```bash
   python -m pytest tests/ -xvs
   ```

4. **Lint clean**:
   ```bash
   ruff check hatsume/plugins/hatsume-plugin/
   ```

## Rollback

If issues arise, `git revert` the commits on branch `012-consolidate-llm-prompts`. All changes are isolated to 8 files with no database migrations or config changes.
