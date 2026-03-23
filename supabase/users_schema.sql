create table if not exists public.users (
    telegram_id bigint primary key,
    name text,
    player_code text unique,
    balance integer not null default 700,
    wins_games integer not null default 0,
    losses_games integer not null default 0,
    wins_battles integer not null default 0,
    losses_battles integer not null default 0,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists users_player_code_idx on public.users (player_code);
create index if not exists users_name_idx on public.users (name);
