# API

Base URL in development: `http://localhost:8080`. Interactive docs: `/docs`. Models: [`src/lighthouse/schemas.py`](../src/lighthouse/schemas.py).

Every endpoint except `/api/health` needs `Authorization: Bearer <access token>`, where the token
is the Supabase Auth session's `access_token`. Missing or invalid token: `401`. Errors are
`{"detail": "..."}`. Ids are UUIDs, timestamps are ISO 8601 UTC.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/health` | | `{"status": "ok"}` |
| POST | `/api/drop` | `{"content": string}` | `202` `InboxItem` |
| GET | `/api/inbox?limit=50` | | `InboxItem[]`, newest first; `content` is cut to the first 500 characters |
| POST | `/api/inbox/{id}/retry` | | `202` `InboxItem` (only for `failed` items, else `409`) |
| GET | `/api/notes?q=&tag=&limit=50&offset=0` | | `NoteSummary[]`, newest first |
| GET | `/api/notes/{id}` | | `Note` |
| DELETE | `/api/notes/{id}` | | `204` |
| GET | `/api/threads` | | `Thread[]`, most recently updated first |
| GET | `/api/threads/{id}/messages` | | `ChatMessage[]`, oldest first |
| DELETE | `/api/threads/{id}` | | `204` |
| POST | `/api/chat` | `{"message": string, "thread_id"?: uuid}` | `text/event-stream`, see below |

```ts
type InboxItem = {
  id: string; kind: "text" | "url"; content: string;       // the pasted text, or the URL
  status: "pending" | "processing" | "done" | "failed";
  error: string | null;                                    // human-readable reason when failed
  note_id: string | null;                                  // set when done
  created_at: string; updated_at: string;
};
type NoteSummary = { id: string; title: string; summary: string; tags: string[]; source_url: string | null; created_at: string };
type Note = NoteSummary & { key_points: string[]; source_title: string | null; body: string };
type Thread = { id: string; title: string; created_at: string; updated_at: string };
type Source = { id: string; title: string; source_url: string | null };
type ChatMessage = { role: "user" | "assistant"; content: string; sources: Source[] };
```

## Drop

`POST /api/drop` returns immediately; a background worker turns the item into a note. If `content`
is a single `http(s)://` URL (after trimming) the item is a `url` and the page is fetched,
otherwise it is `text`. Poll `GET /api/inbox` to watch `status` move
`pending → processing → done | failed`.

## Chat stream

`POST /api/chat` answers with server-sent events. Each event has an `event:` name and a JSON
`data:` payload. Omit `thread_id` to start a new thread; a `thread_id` that is not the caller's
gives `404` before any event.

| Event | Data | When |
|---|---|---|
| `thread` | `{"thread_id": uuid, "title": string}` | First event, always. |
| `tool` | `{"name": "search_notes", "input": {"query": string}}` or `{"name": "get_note", "input": {"note_id": string}}` | Each time the agent calls a tool. |
| `token` | `{"text": string}` | A piece of the answer. Concatenate in order. |
| `sources` | `{"sources": Source[]}` | Once, after the last token: notes retrieved in this turn, plus notes from earlier turns that this answer cites. |
| `error` | `{"message": string}` | Something failed; the stream ends after this. |
| `done` | `{}` | Last event of a successful turn. |

The answer cites notes inline as `[note:xxxxxxxx]`, the first 8 hex characters of the note id.
Match with `/\[note:([0-9a-f]{8})\]/g` and resolve against the turn's `sources` (and
`ChatMessage.sources` when loading history).
