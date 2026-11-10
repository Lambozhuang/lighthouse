-- Lighthouse schema. Runs on self-hosted Supabase (auth schema, anon/authenticated/service_role roles
-- already exist) and, for tests, on plain pgvector Postgres after tests/sql/supabase_stub.sql.

create extension if not exists vector;

-- Internal schema: migration bookkeeping and LangGraph checkpoints. PostgREST only exposes `public`,
-- so nothing here is reachable with the anon key.
create schema if not exists lighthouse;
revoke all on schema lighthouse from public;

create type public.inbox_kind as enum ('text', 'url');
create type public.inbox_status as enum ('pending', 'processing', 'done', 'failed');
create type public.chunk_kind as enum ('distilled', 'source');

-- A note is the distilled, structured form of one dropped item. `body` keeps the cleaned source
-- text for the human reader; the chat agent only ever reads the distilled fields.
create table public.notes (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null default auth.uid() references auth.users (id) on delete cascade,
    title         text not null,
    summary       text not null,
    key_points    text[] not null default '{}',
    tags          text[] not null default '{}',
    source_url    text,
    source_title  text,
    body          text not null,
    created_at    timestamptz not null default now()
);
create index notes_user_created_idx on public.notes (user_id, created_at desc);
create index notes_tags_idx on public.notes using gin (tags);

-- Everything dropped in lands here first. The worker claims rows with FOR UPDATE SKIP LOCKED,
-- so this table doubles as the job queue.
create table public.inbox_items (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
    kind        public.inbox_kind not null,
    content     text not null,                -- the pasted text, or the URL
    status      public.inbox_status not null default 'pending',
    error       text,
    attempts    int not null default 0,
    note_id     uuid references public.notes (id) on delete set null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index inbox_items_user_created_idx on public.inbox_items (user_id, created_at desc);
create index inbox_items_pending_idx on public.inbox_items (created_at) where status = 'pending';

-- Retrieval units. 'distilled' chunks hold title + summary + key points; 'source' chunks hold
-- pieces of the cleaned source text. Both are searched; both map back to a note.
create table public.note_chunks (
    id           bigint generated always as identity primary key,
    note_id      uuid not null references public.notes (id) on delete cascade,
    user_id      uuid not null references auth.users (id) on delete cascade,
    kind         public.chunk_kind not null,
    chunk_index  int not null,
    content      text not null,
    embedding    vector(1536) not null,       -- openai/text-embedding-3-small
    fts          tsvector generated always as (to_tsvector('simple', content)) stored,
    unique (note_id, kind, chunk_index)
);
create index note_chunks_embedding_idx on public.note_chunks using hnsw (embedding vector_cosine_ops);
create index note_chunks_fts_idx on public.note_chunks using gin (fts);
create index note_chunks_user_idx on public.note_chunks (user_id);

-- One row per conversation. The messages themselves live in LangGraph checkpoints
-- (schema `lighthouse`), keyed by this id.
create table public.threads (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
    title       text not null default 'New chat',
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index threads_user_updated_idx on public.threads (user_id, updated_at desc);

-- Row level security: a signed-in user sees and changes only their own rows. The API runs every
-- user request as role `authenticated` with the JWT claims set, so these policies are what
-- actually enforces isolation. The worker connects as the table owner and bypasses them.
alter table public.notes enable row level security;
alter table public.inbox_items enable row level security;
alter table public.note_chunks enable row level security;
alter table public.threads enable row level security;

create policy notes_owner on public.notes
    for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy inbox_items_owner on public.inbox_items
    for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy note_chunks_owner on public.note_chunks
    for select to authenticated using (user_id = (select auth.uid()));
create policy threads_owner on public.threads
    for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

grant usage on schema public to authenticated;
grant select, insert, update, delete on public.notes, public.inbox_items, public.threads to authenticated;
grant select on public.note_chunks to authenticated;
revoke all on public.notes, public.inbox_items, public.note_chunks, public.threads from anon;

-- Hybrid search: vector similarity and full-text search each produce a ranked list; the two are
-- merged with reciprocal rank fusion (score = sum of 1 / (60 + rank)). SECURITY INVOKER, so RLS
-- limits the search to the caller's own chunks.
create function public.match_note_chunks(
    query_embedding vector(1536),
    query_text text,
    match_count int default 8
)
returns table (chunk_id bigint, note_id uuid, kind public.chunk_kind, content text, score double precision)
language sql stable security invoker
set search_path = public
as $$
    with semantic as (
        select c.id, row_number() over (order by c.embedding <=> query_embedding) as rank
        from public.note_chunks c
        order by c.embedding <=> query_embedding
        limit 40
    ),
    keyword as (
        select c.id, row_number() over (order by ts_rank_cd(c.fts, q) desc) as rank
        from public.note_chunks c, websearch_to_tsquery('simple', query_text) q
        where c.fts @@ q
        order by ts_rank_cd(c.fts, q) desc
        limit 40
    ),
    fused as (
        select coalesce(s.id, k.id) as id,
               coalesce(1.0 / (60 + s.rank), 0) + coalesce(1.0 / (60 + k.rank), 0) as score
        from semantic s
        full outer join keyword k on k.id = s.id
    )
    select c.id, c.note_id, c.kind, c.content, f.score::double precision
    from fused f
    join public.note_chunks c on c.id = f.id
    order by f.score desc
    limit match_count
$$;
revoke all on function public.match_note_chunks(vector, text, int) from public, anon;
grant execute on function public.match_note_chunks(vector, text, int) to authenticated;
