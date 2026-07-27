# Random ACG Filename Suffix Design

## Goal

Prevent repeated sandbox filenames when `random_acg_photo` is called more than
once during the same second by appending a random six-digit number.

## Scope

Only the sandbox destination filename created by `random_acg_photo` changes.
The macOS Photos export filename used by the poke handler remains unchanged.

## Filename Contract

The sandbox path uses this format:

```text
/tmp/apple_photo_export_yymmdd_hhmmss_######.<extension>
```

The suffix is an integer from `0` through `999999`, formatted with leading
zeroes to exactly six digits. The source file extension is preserved; files
without an extension continue to use `.jpg`.

## Implementation

Generate the suffix in `random_acg_photo` with the module's existing `random`
dependency, then include it after the timestamp and before the extension. Keep
the Photos export, container startup, Docker copy, and error paths unchanged.

## Verification

Add a focused deterministic test that fixes the generated random number and
asserts the returned sandbox path and the destination passed to `docker cp`.
Run the focused ACG photo tests, followed by the repository's required lint,
type, and full test checks.
