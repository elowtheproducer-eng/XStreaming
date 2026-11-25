import React, { useEffect, useMemo, useState } from 'react';
import { Check, Image as ImageIcon, RefreshCw, Search, Sparkles, X } from 'lucide-react';
import { useJournal } from '../state/JournalStore';
import { getCachedXboxProfile } from '../logic/xbox/profile';
import { session } from '../logic/xbox/session';
import {
  fetchTitleHistory,
  fetchTitlesByIds,
  findMatchingXboxTitle,
  type TitleArtInfo,
  type TitleArtVariant,
} from '../logic/xbox/titlehub';
import { mergeXboxTitleCatalog } from '../logic/xbox/gameArt';

function getVariantsForTitle(title: TitleArtInfo | null): TitleArtVariant[] {
  if (!title) return [];
  if (title.variants && title.variants.length > 0) return title.variants;
  const out: TitleArtVariant[] = [];
  const seen = new Set<string>();
  const add = (type: string, label: string, url: string | undefined, role: 'cover' | 'wallpaper' | 'other') => {
    const clean = url?.trim();
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    out.push({ type, label, url: clean, role });
  };
  add('BoxArt', 'Cover Art', title.coverUrl, 'cover');
  add('Hero', 'Wallpaper', title.wallpaperUrl, 'wallpaper');
  add('DisplayImage', 'Display Art', title.artUrl, 'other');
  return out;
}

export function XboxArtPickerModal({
  gameName,
  xboxTitleId,
  initialCatalog,
  initialCoverPreviewUrl,
  initialWallpaperPreviewUrl,
  onApplyUrls,
  onClose,
}: {
  gameName: string;
  xboxTitleId?: string;
  initialCatalog?: TitleArtInfo[];
  initialCoverPreviewUrl?: string;
  initialWallpaperPreviewUrl?: string;
  onApplyUrls: (choice: {
    coverUrl?: string;
    wallpaperUrl?: string;
    title?: TitleArtInfo;
  }) => Promise<void>;
  onClose: () => void;
}) {
  const { navigate, pushToast } = useJournal();
  const [catalog, setCatalog] = useState<TitleArtInfo[]>(() => initialCatalog ?? []);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedTitleId, setSelectedTitleId] = useState<string>(xboxTitleId || '');
  const [coverUrl, setCoverUrl] = useState<string | undefined>();
  const [wallpaperUrl, setWallpaperUrl] = useState<string | undefined>();
  const [error, setError] = useState('');

  const selectTitleDefaults = (title: TitleArtInfo | null) => {
    if (!title) return;
    setSelectedTitleId(title.titleId);
    setCoverUrl(title.coverUrl || title.artUrl);
    setWallpaperUrl(title.wallpaperUrl || title.artUrl || title.coverUrl);
  };

  useEffect(() => {
    let live = true;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const [cached, status] = await Promise.all([
          getCachedXboxProfile(),
          session.getSessionStatus().catch(() => ({ signedIn: false as const, xuid: undefined })),
        ]);
        if (!live) return;
        setSignedIn(status.signedIn);

        let merged = mergeXboxTitleCatalog(cached?.titles, initialCatalog);
        setCatalog(merged);

        const cachedMatch = findMatchingXboxTitle(
          { id: '', name: gameName, xboxTitleId },
          merged
        );
        if (cachedMatch) {
          selectTitleDefaults(cachedMatch);
        } else if (merged[0]) {
          selectTitleDefaults(merged[0]);
        }

        // If signed in and match missing or lacks full variants, query Xbox TitleHub directly
        const needsLive =
          status.signedIn &&
          status.xuid &&
          (!cachedMatch || !cachedMatch.variants || cachedMatch.variants.length === 0);
        if (needsLive && status.xuid) {
          const history = await fetchTitleHistory(status.xuid);
          if (!live) return;
          merged = mergeXboxTitleCatalog(merged, history);
          if (xboxTitleId && xboxTitleId !== '0' && !merged.some((t) => t.titleId === xboxTitleId)) {
            const batch = await fetchTitlesByIds(status.xuid, [xboxTitleId]);
            merged = mergeXboxTitleCatalog(merged, batch);
          }
          if (!live) return;
          setCatalog(merged);
          const freshMatch = findMatchingXboxTitle(
            { id: '', name: gameName, xboxTitleId },
            merged
          );
          if (freshMatch) selectTitleDefaults(freshMatch);
          else if (merged[0] && !cachedMatch) selectTitleDefaults(merged[0]);
        }
      } catch (e: any) {
        if (live) setError(e?.message || 'Could not load Xbox artwork catalog.');
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => {
      live = false;
    };
  }, [gameName, xboxTitleId]);

  const handleRefreshFromXbox = async () => {
    setLoading(true);
    setError('');
    try {
      const status = await session.getSessionStatus();
      setSignedIn(status.signedIn);
      if (!status.signedIn || !status.xuid) {
        setError('Link your Xbox account in Settings → Xbox first.');
        return;
      }
      const history = await fetchTitleHistory(status.xuid);
      let merged = mergeXboxTitleCatalog(catalog, history);
      if (xboxTitleId && xboxTitleId !== '0' && !history.has(xboxTitleId)) {
        const batch = await fetchTitlesByIds(status.xuid, [xboxTitleId]);
        merged = mergeXboxTitleCatalog(merged, batch);
      }
      setCatalog(merged);
      const matched =
        merged.find((t) => t.titleId === selectedTitleId) ??
        findMatchingXboxTitle({ id: '', name: gameName, xboxTitleId }, merged) ??
        merged[0] ??
        null;
      selectTitleDefaults(matched);
    } catch (e: any) {
      setError(e?.message || 'Could not reach Xbox TitleHub.');
    } finally {
      setLoading(false);
    }
  };

  const filteredCatalog = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return catalog;
    return catalog.filter((t) => t.name.toLowerCase().includes(q) || t.titleId.includes(q));
  }, [catalog, query]);

  const selectedTitle = useMemo(
    () => catalog.find((t) => t.titleId === selectedTitleId) ?? null,
    [catalog, selectedTitleId]
  );

  const variants = useMemo(() => getVariantsForTitle(selectedTitle), [selectedTitle]);

  const handleApply = async () => {
    if (!coverUrl && !wallpaperUrl) return;
    setSaving(true);
    setError('');
    try {
      await onApplyUrls({
        coverUrl,
        wallpaperUrl,
        title: selectedTitle ?? undefined,
      });
      onClose();
    } catch (e: any) {
      const msg = e?.message || 'Could not download selected Xbox artwork.';
      setError(msg);
      pushToast({ title: 'Xbox art import failed', subtitle: msg, kind: 'error' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[75] flex items-center justify-center p-4 bg-black/75 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-label={`Xbox artwork for ${gameName || 'game'}`}
      onClick={() => !saving && onClose()}
    >
      <div
        className="w-full max-w-4xl max-h-[90vh] flex flex-col rounded-[var(--gg-r-panel)] border border-[var(--gg-divider)] bg-[var(--gg-bg-raised)] shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-b border-[var(--gg-divider)]">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-[var(--gg-text-primary)] truncate">
              Xbox Cover & Wallpaper{gameName ? ` · ${gameName}` : ''}
            </h2>
            <p className="text-xs text-[var(--gg-text-secondary)]">
              Pick official cover art and a widescreen hero wallpaper saved offline to your journal.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {signedIn && (
              <button
                type="button"
                onClick={() => void handleRefreshFromXbox()}
                disabled={loading || saving}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--gg-r-control)] text-xs font-medium bg-[var(--gg-surface-control)] hover:bg-white/10 disabled:opacity-50 xbox-ring"
              >
                <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                <span>Refresh Xbox</span>
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              aria-label="Close Xbox artwork picker"
              className="p-2 rounded-[var(--gg-r-control)] hover:bg-white/10 text-[var(--gg-text-secondary)]"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {error && (
            <div className="p-3 rounded-[var(--gg-r-control)] bg-red-500/15 border border-red-500/40 text-xs text-red-200">
              {error}
            </div>
          )}

          {catalog.length === 0 && !loading ? (
            <div className="p-8 rounded-[var(--gg-r-tile)] border border-[var(--gg-divider)] bg-[var(--gg-surface-control)]/50 text-center space-y-3">
              <ImageIcon size={28} className="mx-auto text-[var(--gg-text-tertiary)]" />
              <div className="text-sm font-medium text-[var(--gg-text-primary)]">
                No Xbox title catalog loaded yet
              </div>
              <p className="text-xs text-[var(--gg-text-secondary)] max-w-md mx-auto">
                Link your Xbox account and refresh your Xbox Profile in the Android app so Green Guide can load official covers and hero wallpapers for your games.
              </p>
              <div className="flex justify-center gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    navigate({ page: 'settings', category: 'xbox' });
                  }}
                  className="px-4 py-2 rounded-[var(--gg-r-control)] text-xs font-semibold bg-[var(--gg-accent)] text-white"
                >
                  Open Xbox Settings
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 rounded-[var(--gg-r-control)] text-xs bg-[var(--gg-surface-control)]"
                >
                  Close
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* Title switcher / search */}
              <div className="space-y-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
                    Xbox Title ({filteredCatalog.length})
                  </span>
                  <div className="relative w-full sm:w-64">
                    <Search
                      size={13}
                      className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--gg-text-tertiary)]"
                    />
                    <input
                      type="search"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Filter Xbox games…"
                      aria-label="Filter Xbox games"
                      className="w-full pl-8 pr-3 py-1.5 rounded-[var(--gg-r-control)] text-xs bg-[var(--gg-surface-control)] text-[var(--gg-text-primary)] border border-[var(--gg-divider)]"
                    />
                  </div>
                </div>

                <div className="flex gap-2 overflow-x-auto rail-scroll pb-1">
                  {filteredCatalog.slice(0, 40).map((t) => {
                    const active = t.titleId === selectedTitleId;
                    const thumb = t.coverUrl || t.wallpaperUrl || t.artUrl;
                    return (
                      <button
                        key={t.titleId}
                        type="button"
                        onClick={() => selectTitleDefaults(t)}
                        className={`shrink-0 flex items-center gap-2.5 pl-1.5 pr-3 py-1.5 rounded-[var(--gg-r-control)] border text-left transition-colors xbox-ring ${
                          active
                            ? 'border-[var(--gg-focus-ring)] bg-[var(--gg-accent-wash)] text-[var(--gg-text-primary)]'
                            : 'border-[var(--gg-divider)] bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)] hover:text-[var(--gg-text-primary)]'
                        }`}
                      >
                        <div className="w-8 h-8 rounded-[var(--gg-r-badge)] overflow-hidden bg-black/30 shrink-0">
                          {thumb && (
                            <img src={thumb} alt="" className="w-full h-full object-cover" />
                          )}
                        </div>
                        <span className="text-xs font-medium max-w-[160px] truncate">{t.name}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Selected preview */}
              {selectedTitle && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-3.5 rounded-[var(--gg-r-tile)] bg-[var(--gg-bg-base)]/60 border border-[var(--gg-divider)]">
                  <div className="flex items-center gap-3">
                    <div className="w-16 aspect-[2/3] rounded-[var(--gg-r-badge)] overflow-hidden bg-[var(--gg-surface-control)] border border-white/10 shrink-0">
                      {(coverUrl || initialCoverPreviewUrl) ? (
                        <img
                          src={coverUrl || initialCoverPreviewUrl}
                          alt="Selected cover preview"
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-[10px] text-[var(--gg-text-tertiary)]">
                          None
                        </div>
                      )}
                    </div>
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="text-xs font-semibold text-[var(--gg-text-primary)]">
                        Selected Cover
                      </div>
                      <div className="text-[11px] text-[var(--gg-text-secondary)]">
                        {coverUrl ? 'Xbox art selected for library cover' : 'Keep existing cover'}
                      </div>
                      {coverUrl && (
                        <button
                          type="button"
                          onClick={() => setCoverUrl(undefined)}
                          className="text-[11px] text-[var(--gg-text-tertiary)] underline hover:text-[var(--gg-text-primary)]"
                        >
                          Skip cover
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <div className="w-28 aspect-video rounded-[var(--gg-r-badge)] overflow-hidden bg-[var(--gg-surface-control)] border border-white/10 shrink-0">
                      {(wallpaperUrl || initialWallpaperPreviewUrl) ? (
                        <img
                          src={wallpaperUrl || initialWallpaperPreviewUrl}
                          alt="Selected wallpaper preview"
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-[10px] text-[var(--gg-text-tertiary)]">
                          None
                        </div>
                      )}
                    </div>
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="text-xs font-semibold text-[var(--gg-text-primary)]">
                        Selected Wallpaper
                      </div>
                      <div className="text-[11px] text-[var(--gg-text-secondary)]">
                        {wallpaperUrl ? 'Used on Home tiles & backdrop' : 'Keep existing wallpaper'}
                      </div>
                      {wallpaperUrl && (
                        <button
                          type="button"
                          onClick={() => setWallpaperUrl(undefined)}
                          className="text-[11px] text-[var(--gg-text-tertiary)] underline hover:text-[var(--gg-text-primary)]"
                        >
                          Skip wallpaper
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Variants Grid */}
              {loading && variants.length === 0 ? (
                <div className="py-8 text-center text-xs text-[var(--gg-text-secondary)]">
                  Loading artwork variants from Xbox…
                </div>
              ) : selectedTitle ? (
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-xs font-semibold text-[var(--gg-text-secondary)]">
                      Available Artwork Variants for {selectedTitle.name} ({variants.length})
                    </div>
                    <button
                      type="button"
                      onClick={() => selectTitleDefaults(selectedTitle)}
                      className="inline-flex items-center gap-1 text-xs text-[var(--gg-focus-ring)] hover:underline"
                    >
                      <Sparkles size={12} />
                      <span>Use Xbox recommended</span>
                    </button>
                  </div>

                  {variants.length === 0 ? (
                    <div className="p-6 rounded-[var(--gg-r-tile)] bg-[var(--gg-surface-control)]/40 text-xs text-[var(--gg-text-secondary)] text-center">
                      Xbox did not return image variants for this title yet. Try refreshing from Xbox.
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                      {variants.map((v, idx) => {
                        const isCover = coverUrl === v.url;
                        const isWallpaper = wallpaperUrl === v.url;
                        return (
                          <div
                            key={`${v.type}-${idx}`}
                            className={`rounded-[var(--gg-r-tile)] border overflow-hidden bg-[var(--gg-bg-base)]/60 flex flex-col ${
                              isCover || isWallpaper
                                ? 'border-[var(--gg-focus-ring)]'
                                : 'border-[var(--gg-divider)]'
                            }`}
                          >
                            <div className="aspect-video bg-black/40 relative overflow-hidden">
                              <img
                                src={v.url}
                                alt={`${selectedTitle.name} ${v.label}`}
                                loading="lazy"
                                className="w-full h-full object-contain"
                              />
                              <span className="absolute top-2 left-2 px-2 py-0.5 rounded-[var(--gg-r-badge)] text-[10px] font-semibold bg-black/75 text-white border border-white/10">
                                {v.label}
                              </span>
                            </div>
                            <div className="p-2.5 flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => setCoverUrl(isCover ? undefined : v.url)}
                                className={`flex-1 inline-flex items-center justify-center gap-1 px-2.5 py-1.5 rounded-[var(--gg-r-control)] text-xs font-medium transition-colors ${
                                  isCover
                                    ? 'bg-[var(--gg-accent)] text-white'
                                    : 'bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)] hover:text-[var(--gg-text-primary)]'
                                }`}
                              >
                                {isCover && <Check size={12} />}
                                <span>Cover</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => setWallpaperUrl(isWallpaper ? undefined : v.url)}
                                className={`flex-1 inline-flex items-center justify-center gap-1 px-2.5 py-1.5 rounded-[var(--gg-r-control)] text-xs font-medium transition-colors ${
                                  isWallpaper
                                    ? 'bg-[var(--gg-accent)] text-white'
                                    : 'bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)] hover:text-[var(--gg-text-primary)]'
                                }`}
                              >
                                {isWallpaper && <Check size={12} />}
                                <span>Wallpaper</span>
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ) : null}
            </>
          )}
        </div>

        {/* Footer */}
        {catalog.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 border-t border-[var(--gg-divider)] bg-[var(--gg-bg-base)]/40">
            <div className="text-xs text-[var(--gg-text-secondary)]">
              {coverUrl || wallpaperUrl
                ? 'Selected artwork downloads offline as local library media.'
                : 'Select Cover, Wallpaper, or both above.'}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={saving}
                className="px-4 py-2 rounded-[var(--gg-r-control)] text-xs bg-[var(--gg-surface-control)]"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={saving || (!coverUrl && !wallpaperUrl)}
                onClick={() => void handleApply()}
                className="px-5 py-2 rounded-[var(--gg-r-control)] text-xs font-semibold bg-[var(--gg-accent)] text-white disabled:opacity-45"
              >
                {saving ? 'Downloading artwork…' : 'Apply selected art'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
