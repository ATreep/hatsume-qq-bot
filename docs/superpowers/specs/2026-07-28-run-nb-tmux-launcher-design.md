# Run NB Tmux Launcher Design

## Goal

Start the Hatsume NoneBot service in a detached tmux session so `run_nb.sh`
can return immediately while the service continues running.

## Session Contract

The launcher uses the fixed session name `nb-hatsume`. If that exact session
already exists, the launcher terminates it before creating a replacement.
Other tmux sessions remain untouched.

The replacement session starts in the repository directory and runs:

```text
ENVIRONMENT=prod nb run
```

After successful startup, the launcher prints this command and exits:

```text
tmux attach-session -t nb-hatsume
```

## Error Handling

The absence of an existing `nb-hatsume` session is expected and does not fail
the launcher. A failure to terminate an existing session or create the new
detached session causes `run_nb.sh` to exit with a non-zero status. The attach
command is printed only after tmux reports successful session creation.

## Verification

Run `bash -n run_nb.sh` for syntax validation. Use a temporary stub `tmux`
executable to verify the absent-session and replacement-session call order,
the detached launch command, printed attach command, and exit statuses without
starting the real service or disturbing existing tmux sessions.
