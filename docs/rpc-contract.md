# aria2 JSON-RPC contract

`aria2-tui` treats the running aria2 process as the source of truth. It stores no
download state of its own.

## Transport

- Endpoint: `http://127.0.0.1:6800/jsonrpc`
- Protocol: JSON-RPC 2.0 over HTTP
- Optional authentication: prepend `token:<secret>` to every `params` array
- Timeout: 5 seconds

## Methods used

| Method | Params | Purpose |
| --- | --- | --- |
| `aria2.getVersion` | none | Verify connectivity and display the aria2 version |
| `aria2.getGlobalOption` | none | Read the default download directory |
| `aria2.tellActive` | `[keys]` | Fetch active downloads |
| `aria2.tellWaiting` | `[0, 100, keys]` | Fetch queued and paused downloads |
| `aria2.tellStopped` | `[0, 100, keys]` | Fetch completed, failed, and removed history |
| `aria2.addUri` | `[[uri], options]` | Add a URL or magnet link |
| `aria2.pause` | `[gid]` | Pause an active or queued task |
| `aria2.unpause` | `[gid]` | Resume a paused task |
| `aria2.remove` | `[gid]` | Remove an unfinished task |
| `aria2.removeDownloadResult` | `[gid]` | Remove a stopped task from history |

## Download fields

The list requests only the fields it renders:

`gid`, `status`, `totalLength`, `completedLength`, `downloadSpeed`,
`uploadSpeed`, `connections`, `numPieces`, `pieceLength`, `errorMessage`,
`files`, `bittorrent`, and `dir`.

Successful responses must contain `result`. RPC failures contain `error.code`,
`error.message`, and optionally `error.data`. HTTP, transport, and malformed JSON
failures are surfaced in the UI and trigger reconnect attempts on the next poll.

## Safety behavior

- The RPC secret is never rendered in the UI.
- URL query strings and fragments are hidden in task details so signed download
  URLs and access tokens are not exposed on screen.
- Removing a task does not delete files already written to disk.
