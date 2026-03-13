# Legends GM-Tools Bridge (Foundry Module Base)

This is a base FoundryVTT module scaffold focused on handshake connectivity with the GMTools app.

## Features in this base
- Module settings for:
  - GMTools base URL
  - optional API token
  - optional Foundry asset base URL override for image mirroring
  - sync setting tag (used to bucket imports into setting-specific folders)
  - auto-handshake on startup
- Handshake request to:
  - `POST /plugins/foundryvtt/handshake`
- Health check helper for:
  - `GET /plugins/foundryvtt/health`
- Keybinding:
  - `Ctrl+Shift+H` to run handshake
- Actor sheet header button:
  - `GMTools` sends current actor directly to GMTools (`/plugins/foundryvtt/import/actor`)
- Item sheet header button:
  - `GMTools` sends current item directly to GMTools (`/plugins/foundryvtt/import/item`)
- Actor Directory bulk sync button:
  - `GMTools Sync` opens a dialog to sync all PCs, all NPC/creature actors, or both

## Sync folder behavior
- Foundry imports are saved under:
  - `storage/foundryvtt/<setting>/<type>/...`
- `<setting>` comes from module setting `Sync Setting Tag`.
- If `Sync Setting Tag` is empty, module falls back to `Legacy Default Setting Tag`.
- When possible, synced Foundry images are mirrored into GMTools local image storage so records keep portraits even if Foundry is offline later.
- If Foundry is accessed via `localhost`, set `Foundry Asset Base URL Override` to a reachable host such as `https://foundry.olterman.eu`.

## Server requirements
The GMTools app should run with the `foundryVTT` plugin enabled and expose:
- `/plugins/foundryvtt/health`
- `/plugins/foundryvtt/handshake`

Optional environment variables on app side:
- `LOL_FOUNDRYVTT_API_TOKEN`
- `LOL_FOUNDRYVTT_ALLOWED_ORIGINS`

## Next steps
- Add scene sync endpoints and a scene transfer UI.
- Add journal entry sync into GMTools lore records.
- Add conflict handling and round-trip update tools.
