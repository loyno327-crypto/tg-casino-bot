# Supabase setup for tg-casino-bot

## 1. Create a Supabase project
1. Open the Supabase dashboard.
2. Create a new project.
3. Wait until the database becomes available.

## 2. Create the `users` table
1. Open **SQL Editor** in Supabase.
2. Copy and run the SQL from `supabase/users_schema.sql`.

This bot stores user stats in the remote `public.users` table:
- `telegram_id`
- `name`
- `player_code`
- `balance`
- `wins_games`
- `losses_games`
- `wins_battles`
- `losses_battles`
- `created_at`

## 3. Get API credentials
In Supabase Dashboard -> **Project Settings** -> **Data API** / **API** copy:
- `Project URL` -> set as `SUPABASE_URL`
- `service_role` secret key -> set as `SUPABASE_KEY`

Use `service_role` on the backend only. Never expose it in the frontend.

## 4. Add environment variables to the bot
Set these variables in your hosting platform:
- `SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co`
- `SUPABASE_KEY=YOUR_SERVICE_ROLE_KEY`

Optional:
- `SUPABASE_USERS_TABLE=users`

## 5. Keep local SQLite for non-user data
This bot now uses:
- Supabase for persistent user stats.
- Local SQLite for sessions, inventory, case history, and battles.

So in Supabase you do **not** need to upload files like `bot.db`.
You only need to create the remote `users` table using the SQL file.

## 6. Deploy
After setting env vars and redeploying:
1. Start the bot.
2. Run `/start` from Telegram.
3. Check the `users` table in Supabase Table Editor.
4. You should see the user's row created there.

## 7. How to verify persistence
1. Open the bot and change balance/stats.
2. Restart/redeploy the app.
3. Run `/start` again.
4. The same `telegram_id` row should still exist in Supabase and stats should remain unchanged.

## 8. Troubleshooting
### Stats still reset
Check:
- `SUPABASE_URL` is correct.
- `SUPABASE_KEY` is the backend `service_role` key.
- The SQL from `supabase/users_schema.sql` was executed successfully.
- The app logs show `USER STORE: supabase`.

### Row is not created
Check the app logs for Supabase errors and verify the backend can reach the internet.

### Old local users are not visible
Old users in SQLite are not automatically copied into Supabase.
If needed, they can be migrated separately with a one-off script.
