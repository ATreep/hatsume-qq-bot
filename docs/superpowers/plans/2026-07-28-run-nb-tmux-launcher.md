# Run NB Tmux Launcher Implementation Plan

**Goal:** Run the NoneBot service in a replaceable detached tmux session named
`nb-hatsume`, print the attach command, and return immediately.

## Task 1: Update the launcher

**File:** `run_nb.sh`

- Define the fixed tmux session name.
- Check for that exact session and terminate it when present.
- Start `ENVIRONMENT=prod nb run` in a detached replacement session rooted at
  the repository directory.
- Print `tmux attach-session -t nb-hatsume` only after successful creation.
- Preserve non-zero exits for directory, termination, and creation failures.

## Task 2: Verify behavior

- Run `bash -n run_nb.sh`.
- Exercise absent-session, existing-session, kill-failure, and creation-failure
  paths with a temporary stub `tmux` executable.
- Confirm the final worktree contains only the intended files.
