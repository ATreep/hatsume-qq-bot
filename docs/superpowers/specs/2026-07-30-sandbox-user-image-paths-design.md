# Sandbox User Image Paths Design

## Goal

Make ordinary QQ images available to Hatsume's persistent Kali sandbox and
represent them in the normalized human message as deterministic absolute paths.
The chat model will no longer receive inline base64 image content blocks. It can
inspect a saved image through `view_image` or operate on it with sandbox tools.

## Scope

- Save images attached to an ordinary current message.
- Resolve images contained in the message being replied to.
- Preserve each image's original position in the normalized message or reply
  text.
- Leave merged-forward image handling unchanged: nested forward messages keep
  their QQ temporary URLs.
- Do not add persistence outside the existing Docker container and do not add a
  cleanup policy.

## Normalized Representation

The sandbox directory is fixed at `/tmp/hatsume-user-images`. Each filename is:

```text
<message-id>-<one-based-image-order>.<detected-extension>
```

Image order counts only image segments within that QQ message. The current
message uses `event.message_id`; a replied-to message uses
`event.reply.message_id`.

The normalized JSON stores a successfully resolved image inline as Markdown:

```markdown
![图片](/tmp/hatsume-user-images/123456-1.png)
```

This replacement occurs at the original image segment position in both the
top-level `content` string and `reply_to.content`. `get_human_message()` returns
only the normalized JSON text content block. It does not append `image_url` or
`img_url` blocks.

## Components

### Message parsing

`handlers/dialogue.py` continues to own OneBot segment interpretation. For each
ordinary image, it downloads the source URL, enforces the existing 9 MiB and
36-million-pixel limits, detects the actual format with Pillow, normalizes the
extension (for example JPEG to `.jpg`), and delegates storage to the sandbox
helper.

For reply images, the handler first searches for
`<replied-message-id>-<order>.*`. If a matching file exists, it reuses the path.
If no file exists, it downloads and stores the image from the temporary URL in
the reply segment. This repairs replies to messages received before process
startup or before a sandbox reset.

### Sandbox storage

`infra.py` owns the sandbox boundary. A focused asynchronous API will:

- ensure the persistent container is running;
- create `/tmp/hatsume-user-images` when needed;
- find an existing deterministic image path;
- copy validated bytes from a short-lived host temporary file with `docker cp`;
- participate in the existing subprocess reference-count and delayed-stop
  lifecycle; and
- remove the host temporary file in all outcomes.

Message IDs and order numbers are converted to integers, and extensions come
only from validated Pillow format names. No user-controlled string is
interpolated into a sandbox command or destination path.

### Role prompt

`prompts.py` will explain that Markdown targets under
`/tmp/hatsume-user-images` are files inside the Kali sandbox. To inspect an
image, the model must call `view_image` with the `file://` form of the absolute
path, such as `file:///tmp/hatsume-user-images/123456-1.png`. Shell and media
tools may use the corresponding sandbox path according to their existing
contracts. The prompt continues to prohibit exposing sandbox paths to users.

### Architecture documentation

`docs/arch.md` will describe the new image flow, deterministic naming, reply
lookup and recovery, merged-forward exception, and removal of direct multimodal
content blocks.

## Error Handling

Download failures, HTTP errors, limit violations, unsupported or unreadable
formats, sandbox startup errors, directory creation failures, lookup failures,
and copy failures are logged with the existing diagnostic style. They do not
discard the surrounding text message. The affected image remains represented
by its original temporary URL using the existing temporary-link Markdown form.

A reply lookup failure proceeds to recovery from the reply segment's temporary
URL. If recovery also fails, the reply keeps that temporary URL.

The application does not delete files from `/tmp/hatsume-user-images` on
conversation finish, `/clear`, delayed container stop, or process shutdown. The
Kali environment or `/resetsandbox` may remove them as part of the existing
container lifecycle.

## Concurrency and Ordering

Each path is derived from a QQ message ID and the one-based position of the
image, so different messages do not collide. Reprocessing the same message may
replace the same deterministic destination with identical source content.
Current-message and replied-to image counters are independent.

Image resolution remains sequential within a message, preserving segment order
and matching the existing synchronous download behavior. This change does not
introduce additional conversation state or a background task manager.

## Testing

Focused tests will cover:

- actual-format extension detection and JPEG normalization;
- deterministic one-based filenames for multiple current-message images;
- inline local Markdown paths and absence of `image_url`/`img_url` blocks;
- reply lookup by the replied message ID and image order;
- reply recovery when the sandbox file is missing;
- temporary-URL fallback after download, validation, lookup, or copy failure;
- preservation of temporary URLs in merged-forward content; and
- sandbox helper success, missing-file lookup, subprocess failure, timeout,
  reference-count release, and host temporary-file cleanup.

All tests mock network, Pillow inputs where appropriate, and Docker subprocesses.
They remain offline and do not require a live QQ connection or container.

After focused tests, the repository-required Ruff, Pyright, and complete pytest
commands must pass without collection errors, resource warnings, or ignored type
errors.
