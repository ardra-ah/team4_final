# Neon Database Setup

The project uses Neon (hosted Postgres) instead of Docker Postgres.

## 1. Create the local settings file

1. In the project folder, copy `.env.example` to `.env`.
2. Replace the placeholder with your Neon connection string after `DATABASE_URL=`.
3. Keep `.env` out of version control and out of chat.

## 2. Create the tables

1. Open the Neon console and select your project and the `neondb` database.
2. Open the SQL Editor.
3. Paste the contents of `data/db/schema.sql` and run it.

## 3. Load the seed data (run once)

1. In the SQL Editor, paste the contents of `data/db/seed.sql` and run it.
2. Running it a second time will fail with duplicate-key errors. To reset, run `TRUNCATE claims_history, providers, policy_master;` first, then seed again.

## 4. Security

The connection string was shared in chat during setup. Rotate the Neon password (Neon console, Roles, Reset password), then update `.env` with the new string.
