# Skin catalog data

This folder stores a local skin catalog database that is meant to become the source
of truth for the bot in a future refactor.

## Files
- `skin_catalog_seed.json` — seed catalog used to build the initial SQLite DB.
- `skin_catalog.db` — generated SQLite database with the skin catalog.
- `../scripts/build_skin_catalog.py` — rebuilds the DB from the seed JSON.
- `../scripts/sync_csmoney_wiki.py` — crawler for `wiki.cs.money` pages that can
  update `source_url` and `image_url` fields when network access to the site is
  available from the runtime environment.
