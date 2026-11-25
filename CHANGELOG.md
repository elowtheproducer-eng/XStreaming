# Changelog

## [2.4.1] — 2026-11-25
### Added
- **Real Xbox profile everywhere:** gamertag, gamerpic, gamerscore, games played and time played from your linked account now drive the top bar, Guide, Profile, Settings and Keeper. Stats refresh in the background on launch when they are older than 30 minutes, and the stored player tag follows your gamertag.
- **Xbox settings restored:** Settings → Xbox Live & Profile now has Link Xbox account, Sign in with a code, the Azure Client ID field, match-games-automatically, prefer box art, and capture import quality. Manual stat entry is tucked away and only offered when no account is linked.
### Fixed
- Text and form fields that turned white-on-white in Day mode (Settings, onboarding, keyboard cheatsheet, art picker and more).
- A linked Xbox account no longer shows the journal rank (for example VETERAN) as its tier badge; a gamerpic that fails to load falls back to the generated avatar.
- Opening Settings with an unknown category no longer shows an empty panel.

## [2.4.0] — 2026-11-25
### Added
- **Picture & note indexing:** Automatic Keeper picture descriptions on import, manual selection for older pictures, metadata-only mode, EXIF location stripping, and visual search by objects, aircraft, scenery, weather, and mood.
- **Multi-level summaries:** Factual summaries plus *Keeper's take* across notes, legs/sessions, tours/campaigns, games, years, and lifetime stats.
- **Keeper upgrades:** Per-task model role matrix (chat, vision, summaries), full-journal search lookup tools, token usage & cost tracking, and versioned Dossier history with restore.
- **New journal features:** Cross-app tags, Inbox & Android Share-in capture, *On this day* memories, *Year in Review*, full Profile page, Atlas photo pins, heatmap & timeline filter, folder capture import, similar-picture finder, Markdown vault zip export, voice dictation, App Lock, settings presets, Android launcher shortcuts, and background-only notification channels.
- **Safety:** Safe Mode & Boot Trace watchdog (auto Safe Mode after 3 consecutive failed launches), exportable crash logs, scheduled automatic backups, recovery points, and GitHub update checker.
- **Xbox profile:** Gamerscore, games played, time played, and recently played titles on Home (*Xbox profile* rail), the Xbox page, and Guide profile tab (cached on-device, cleared on sign-out).
- **Wallpaper:** New **Settings → Wallpaper** page (style, device/library picture, top banner or full screen, dim/blur/colour, scroll motion, reset) with shortcuts from Appearance, Guide profile tab, and Library → Captures.
- **Rounded design tokens & landscape tiles:** Introduced `--gg-r-tile` (`18px`), `--gg-r-panel` (`22px`), `--gg-r-control` (`12px`), and `--gg-r-badge` (`8px`) across the entire app, updated Home *Jump back in* and *Recently logged* to 16:9 landscape, *Milestones* to 2:1 landscape, wide utility/hub/index/capture cards to landscape, kept square game/utility tiles comfortably sized with snap-scrolling `.rail-fade` edges, and added a lint guard banning `rounded-[2px]` / `rounded-[4px]`.
- **Stable Dev signing key:** Added deterministic Dev signing key bootstrapping and certificate verification (`signing/dev.keystore.b64`, `signing/dev.cert.sha256`, `signing/README.md`) so `Green Guide Dev` builds install cleanly over earlier Dev builds.
- **Settings coverage & Documentation:** Added UI for screen mode, curved-screen edge padding, reduce motion, hint bar toggle, haptics, developer options, app permissions check, pre-update safety snapshot restore, expanded `README.md`, and added `docs/spec/ADDENDUM_V2_4.md`.
### Changed
- **Xbox import rewrite:** Added background prefetch on tick, parallel downloads and off-thread single-decode image processing, zero-reencode JPEG storage, batched IndexedDB writes, no duplicate base64 copy in journal JSON, live speed/ETA progress bar with cancel, and Select all / Clear.
- **Media loading:** Library images load from the IndexedDB blob store (`useMediaUrlMap`) instead of storing base64 copies in journal records.
### Fixed
- Library → Captures image loading for blob-only captures and lightbox viewer integration, plus What's New unread badge clearing upon viewing.

## [Unreleased]

## [2.3.1]
### Added
- On-device AI provider layer and Connections editor (spec §11.2); free-text model chip in Keeper.
- Capacitor Android packaging, `build.py`, GitHub Actions workflow, signing guide.
- Selawik font bundled locally (§7.3).
### Changed
- SimBrief fetched directly from the device (no proxy server).
- Journal persistence moved from localStorage to IndexedDB; save failures now show a toast; flush on background.
- Spec moved to `docs/spec/`; launcher icon/splash are XML vectors.
### Fixed
- `npm install` failure (esbuild pin vs Vite 8); settings now merge with defaults for older saved data.
### Removed
- Express/Gemini server (`server.ts`), `@google/genai`, Google Fonts links.
