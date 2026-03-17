create extension if not exists pgcrypto;

create table if not exists public.articles (
  id uuid primary key default gen_random_uuid(),
  url text not null,
  url_hash text not null,
  content_hash text not null,
  title text,
  summary_raw text,
  summary_zh text,
  category text,
  importance int,
  source text,
  lang text,
  status text default 'pending',
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists articles_url_hash_uidx on public.articles(url_hash);
create unique index if not exists articles_content_hash_uidx on public.articles(content_hash);
create unique index if not exists articles_url_uidx on public.articles(url);

create index if not exists articles_importance_idx on public.articles(importance desc nulls last);
create index if not exists articles_published_at_idx on public.articles(published_at desc nulls last);
create index if not exists articles_category_idx on public.articles(category);
create index if not exists articles_status_idx on public.articles(status);

create or replace function public.touch_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_articles_touch_updated_at on public.articles;
create trigger trg_articles_touch_updated_at
before update on public.articles
for each row
execute function public.touch_updated_at();
