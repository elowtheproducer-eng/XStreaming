import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Capacitor } from '@capacitor/core';
import { Check, Image as ImageIcon, Plus, RefreshCw } from 'lucide-react';
import { useJournal } from '../state/JournalStore';
import { session } from '../logic/xbox/session';
import {
  formatAgo,
  formatMinutes,
  getCachedXboxProfile,
  refreshXboxProfile,
  type XboxProfileSnapshot,
} from '../logic/xbox/profile';
import { findMatchingGame } from '../logic/xbox/titlehub';
import { PlayerAvatar } from './PlayerAvatar';

const STALE_MS = 30 * 60 * 1000;

export function useXboxProfile() {
  const { db, isSafeMode, syncXboxGameArt, xboxProfile } = useJournal();
  const [snap, setSnap] = useState<XboxProfileSnapshot | null>(xboxProfile);
  const [signedIn, setSignedIn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (xboxProfile) setSnap(xboxProfile);
  }, [xboxProfile]);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError('');
    try {
      const fresh = await refreshXboxProfile();
      setSnap(fresh);
      if (!isSafeMode && db.settings.xboxAutoMatch && fresh.titles.length > 0) {
        void syncXboxGameArt({ silent: true, catalogOverride: fresh.titles });
      }
    } catch (e: any) {
      setError(e?.message || 'Could not reach Xbox.');
    } finally {
      setBusy(false);
    }
  }, [isSafeMode, db.settings.xboxAutoMatch, syncXboxGameArt]);

  useEffect(() => {
    let live = true;
    (async () => {
      const [cached, status] = await Promise.all([getCachedXboxProfile(), session.getSessionStatus()]);
      if (!live) return;
      if (cached) setSnap(cached);
      setSignedIn(status.signedIn);
      const stale = !cached || Date.now() - cached.fetchedAt > STALE_MS;
      if (!isSafeMode && status.signedIn && stale && Capacitor.isNativePlatform()) void refresh();
    })();
    return () => {
      live = false;
    };
  }, [refresh, isSafeMode]);

  return { snap, signedIn, busy, error, refresh };
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-lg font-semibold tabular-nums text-[var(--gg-text-primary)] truncate">{value}</div>
      <div className="text-[11px] uppercase tracking-wider text-[var(--gg-text-tertiary)]">{label}</div>
    </div>
  );
}

/** Gamerscore, games played, time played and recently played from the linked Xbox account. */
export function XboxProfileCard({ showRecent = true }: { showRecent?: boolean }) {
  const { db, navigate, openAddGame, syncXboxGameArt } = useJournal();
  const { snap, signedIn, busy, error, refresh } = useXboxProfile();
  const [artSyncBusy, setArtSyncBusy] = useState(false);

  const activeGames = useMemo(() => db.games.filter((g) => !g.deletedAt), [db.games]);

  const handleSyncGameArt = async () => {
    if (artSyncBusy) return;
    setArtSyncBusy(true);
    try {
      await syncXboxGameArt({ silent: false, catalogOverride: snap?.titles });
    } finally {
      setArtSyncBusy(false);
    }
  };

  if (!signedIn && !snap) {
    return (
      <div className="rounded-[var(--gg-r-tile)] border border-[var(--gg-divider)] bg-[var(--gg-bg-raised)] p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-[var(--gg-text-secondary)]">
          Link your Xbox account to see your gamerscore, games played and recent activity here.
        </div>
        <button
          type="button"
          onClick={() => navigate({ page: 'settings', category: 'xbox' })}
          className="rounded-[var(--gg-r-control)] px-4 py-2 bg-[var(--gg-accent)] text-white text-sm xbox-ring"
        >
          Link Xbox
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-[var(--gg-r-tile)] border border-[var(--gg-divider)] bg-[var(--gg-bg-raised)] p-4 space-y-4">
      <div className="flex items-center gap-3">
        <PlayerAvatar url={snap?.avatarUrl} tag={snap?.gamertag || 'Xbox'} size={48} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[var(--gg-text-primary)] truncate">
              {snap?.gamertag ?? 'Xbox'}
            </span>
            {snap?.tier && (
              <span className="px-1.5 py-0.5 text-[10px] font-bold tracking-wider uppercase rounded-[var(--gg-r-badge)] bg-[#107C10] text-white shrink-0">
                {snap.tier}
              </span>
            )}
          </div>
          <div className="text-xs text-[var(--gg-text-secondary)]">
            {busy
              ? 'Updating…'
              : snap
                ? `Updated ${formatAgo(snap.fetchedAt)}`
                : 'Not loaded yet'}
          </div>
        </div>
        {snap && snap.titles.length > 0 && (
          <button
            type="button"
            onClick={() => void handleSyncGameArt()}
            disabled={artSyncBusy}
            aria-label="Sync cover art and wallpapers from Xbox"
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-[var(--gg-r-control)] text-xs font-medium bg-[var(--gg-surface-control)] hover:bg-white/10 disabled:opacity-60 xbox-ring"
          >
            <ImageIcon size={14} />
            <span>{artSyncBusy ? 'Syncing art…' : 'Pull game art'}</span>
          </button>
        )}
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={busy}
          aria-label="Refresh Xbox stats"
          className="p-2 rounded-[var(--gg-r-control)] bg-[var(--gg-surface-control)] disabled:opacity-60 xbox-ring"
        >
          <RefreshCw size={16} className={busy ? 'animate-spin' : ''} />
        </button>
      </div>

      {error && <p className="text-xs text-red-400">{error}</p>}

      {snap && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Gamerscore" value={snap.gamerscore.toLocaleString()} />
            <Stat label="Games played" value={snap.gamesPlayed.toLocaleString()} />
            <Stat label="Time played" value={formatMinutes(snap.totalMinutes)} />
          </div>
          {snap.gamesWithTime < snap.gamesPlayed && (
            <p className="text-[11px] text-[var(--gg-text-tertiary)]">
              Time played covers {snap.gamesWithTime} of {snap.gamesPlayed} games. Xbox only reports it
              for games that track it.
            </p>
          )}

          {showRecent && snap.titles.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
                Recently played
              </div>
              <div className="flex gap-3 overflow-x-auto rail-scroll rail-fade pb-1 pr-5 -mx-1 px-1 snap-x">
                {snap.titles.slice(0, 12).map((t) => {
                  const matchedGame = findMatchingGame(t.titleId, t.name, activeGames);
                  return (
                    <article key={t.titleId} className="w-44 shrink-0 snap-start space-y-1.5">
                      <button
                        type="button"
                        onClick={() => {
                          if (matchedGame) {
                            navigate({ page: 'game', gameId: matchedGame.id });
                          } else {
                            openAddGame({
                              name: t.name,
                              xboxTitleId: t.titleId,
                              platform: 'Xbox Series X|S',
                              coverUrl: t.coverUrl || t.artUrl,
                              wallpaperUrl: t.wallpaperUrl || t.artUrl,
                              variants: t.variants,
                            });
                          }
                        }}
                        aria-label={matchedGame ? `Open ${matchedGame.name} in journal` : `Add ${t.name} to journal`}
                        className="w-full text-left space-y-1 rounded-[var(--gg-r-tile)] xbox-ring"
                      >
                        <div className="aspect-video rounded-[var(--gg-r-tile)] overflow-hidden bg-[var(--gg-surface-control)] relative">
                          {(t.wallpaperUrl || t.artUrl || t.coverUrl) && (
                            <img
                              src={t.wallpaperUrl || t.artUrl || t.coverUrl}
                              alt=""
                              loading="lazy"
                              className="w-full h-full object-cover"
                            />
                          )}
                          {matchedGame && (
                            <span className="absolute top-1.5 right-1.5 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-[var(--gg-r-badge)] text-[10px] font-semibold bg-black/75 text-[#9BF00B]">
                              <Check size={10} />
                              <span>In journal</span>
                            </span>
                          )}
                        </div>
                        <div className="text-xs font-medium text-[var(--gg-text-primary)] line-clamp-2 leading-tight">
                          {t.name}
                        </div>
                      </button>
                      <div className="text-[11px] text-[var(--gg-text-tertiary)] tabular-nums">
                        {formatAgo(t.lastPlayedAt)}
                        {t.minutesPlayed ? ` · ${formatMinutes(t.minutesPlayed)}` : ''}
                      </div>
                      {t.totalGamerscore ? (
                        <div className="text-[11px] text-[var(--gg-text-secondary)] tabular-nums">
                          G {t.gamerscore ?? 0}/{t.totalGamerscore}
                        </div>
                      ) : null}
                      {!matchedGame && (
                        <button
                          type="button"
                          onClick={() =>
                            openAddGame({
                              name: t.name,
                              xboxTitleId: t.titleId,
                              platform: 'Xbox Series X|S',
                              coverUrl: t.coverUrl || t.artUrl,
                              wallpaperUrl: t.wallpaperUrl || t.artUrl,
                              variants: t.variants,
                            })
                          }
                          aria-label={`Add ${t.name} with Xbox art`}
                          className="w-full inline-flex items-center justify-center gap-1 px-2 py-1 rounded-[var(--gg-r-control)] text-[11px] font-medium bg-[var(--gg-surface-control)] hover:bg-white/10 text-[var(--gg-text-primary)] xbox-ring"
                        >
                          <Plus size={11} />
                          <span>Add to journal</span>
                        </button>
                      )}
                    </article>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
