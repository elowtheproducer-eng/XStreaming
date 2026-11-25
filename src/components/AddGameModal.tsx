import React, { useEffect, useMemo, useState } from 'react';
import { BUNDLED_GENRES, GENRE_MAP } from '../data/bundledModules';
import { useJournal, type AddGameXboxSeed } from '../state/JournalStore';
import type { FocalCrop, GameStatus } from '../types/journal';
import { GlyphIcon } from './Glyphs';
import { CropEditor } from './CropEditor';
import { AddImageSheet, type ImportedImage } from './AddImageSheet';
import { XboxArtPickerModal } from './XboxArtPickerModal';
import { useMediaUrl } from '../logic/media';
import { formatIngestToast, ingestFiles } from '../logic/mediaIngest';
import { importSingleXboxArtChoice } from '../logic/xbox/gameArt';
import { normaliseGameTitle } from '../logic/xbox/titlehub';
import { Check, Image as ImageIcon, X } from 'lucide-react';

export function AddGameModal({
  initialXboxSeed,
  onClose,
  onCreated,
}: {
  initialXboxSeed?: AddGameXboxSeed | null;
  onClose: () => void;
  onCreated: (gameId: string) => void;
}) {
  const { db, addGame, addMediaItems, playSound, navigate, pushToast } = useJournal();

  const [step, setStep] = useState<'details' | 'genres'>('details');
  const [name, setName] = useState(() => initialXboxSeed?.name ?? '');
  const [platform, setPlatform] = useState(() => initialXboxSeed?.platform ?? 'Xbox Series X|S');
  const [xboxTitleId, setXboxTitleId] = useState<string | undefined>(() => initialXboxSeed?.xboxTitleId);
  const [packId, setPackId] = useState<'general' | 'flight'>(() =>
    initialXboxSeed?.name && normaliseGameTitle(initialXboxSeed.name).includes('flight simulator')
      ? 'flight'
      : 'general'
  );
  const [status, setStatus] = useState<GameStatus>('PLAYING');
  const [selectedGenres, setSelectedGenres] = useState<string[]>([]);
  const [genreSearch, setGenreSearch] = useState('');
  const [previewGenreId, setPreviewGenreId] = useState<string | null>(null);

  const [coverSha, setCoverSha] = useState<string | undefined>();
  const [heroSha, setHeroSha] = useState<string | undefined>();
  const [pullingXboxArt, setPullingXboxArt] = useState(false);
  const [xboxPickerOpen, setXboxPickerOpen] = useState(false);
  const [focal, setFocal] = useState<FocalCrop | undefined>();
  const [showCrop, setShowCrop] = useState(false);
  const coverUrl = useMediaUrl(coverSha, 'full');
  const heroUrl = useMediaUrl(heroSha, 'full');

  useEffect(() => {
    if (!initialXboxSeed || (!initialXboxSeed.coverUrl && !initialXboxSeed.wallpaperUrl)) return;
    let live = true;
    setPullingXboxArt(true);
    void importSingleXboxArtChoice({
      gameName: initialXboxSeed.name,
      coverUrl: initialXboxSeed.coverUrl,
      wallpaperUrl: initialXboxSeed.wallpaperUrl,
      existingMedia: db.media,
    })
      .then((res) => {
        if (!live) return;
        if (res.mediaEntries.length > 0) addMediaItems(res.mediaEntries, { skipAutoIndex: true });
        if (res.coverSha) setCoverSha(res.coverSha);
        if (res.heroSha) setHeroSha(res.heroSha);
      })
      .catch(() => undefined)
      .finally(() => {
        if (live) setPullingXboxArt(false);
      });
    return () => {
      live = false;
    };
  }, [initialXboxSeed]);

  const filteredGenres = useMemo(() => {
    const q = genreSearch.trim().toLowerCase();
    if (!q) return BUNDLED_GENRES;
    return BUNDLED_GENRES.filter(
      (g) => g.label.toLowerCase().includes(q) || g.id.includes(q)
    );
  }, [genreSearch]);

  const previewGenre = previewGenreId ? GENRE_MAP[previewGenreId] : null;

  const handleCoverUpload = async (images: ImportedImage[]) => {
    const file = images[0]?.file;
    if (!file) return;
    let stats = { added: 0, reused: 0, failed: 0 };
    const items = await ingestFiles([file], {
      maxDim: 2560,
      source: 'PICKER',
      existingMedia: db.media,
      onStats: (s) => { stats = s; },
    });
    if (items[0]) {
      addMediaItems([{ item: items[0] }]);
      setCoverSha(items[0].sha256);
      setShowCrop(true);
    }
    pushToast(formatIngestToast(stats.added, stats.reused, stats.failed));
  };

  const toggleGenre = (id: string) => {
    playSound('focus_move');
    setPreviewGenreId(id);
    setSelectedGenres((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 3) return [...prev.slice(1), id];
      return [...prev, id];
    });
  };

  const handleCreate = () => {
    if (!name.trim()) return;
    const created = addGame({
      name: name.trim(),
      platform,
      packId,
      genreIds: packId === 'flight' ? [] : selectedGenres,
      status,
      xboxTitleId,
      coverMediaSha: coverSha,
      heroMediaSha: heroSha,
      focal,
    });
    playSound('select');
    onCreated(created.id);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-label="Add game to Library"
    >
      <div
        className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-[var(--gg-r-panel)] border border-[var(--gg-divider)] p-6 space-y-5 shadow-2xl"
        style={{ backgroundColor: 'var(--gg-bg-raised)' }}
      >
        <div className="flex items-center justify-between border-b border-[var(--gg-divider)] pb-3">
          <div>
            <h2 className="text-xl font-semibold text-[var(--gg-text-primary)]">
              {step === 'details' ? 'Add Game to Library' : 'What kind of game is it?'}
            </h2>
            <p className="text-xs text-[var(--gg-text-secondary)]">
              {step === 'details'
                ? 'Choose a pack, status, and optional cover art or Xbox wallpaper.'
                : 'Pick up to 3 genres. Genres only add fields, tools, and templates — nothing is ever removed.'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close Add Game dialog"
            className="p-2 rounded-[var(--gg-r-control)] hover:bg-white/10 text-[var(--gg-text-secondary)]"
          >
            <X size={18} />
          </button>
        </div>

        {step === 'details' && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="block space-y-1.5">
                <span className="text-xs font-semibold text-[var(--gg-text-secondary)]">Game title</span>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., Trackmania, Baldur's Gate 3, Halo Infinite"
                  autoFocus
                  className="w-full px-3 py-2.5 rounded-[var(--gg-r-control)] text-sm bg-[var(--gg-surface-control)] text-[var(--gg-text-primary)] border border-[var(--gg-divider)]"
                />
              </label>

              <label className="block space-y-1.5">
                <span className="text-xs font-semibold text-[var(--gg-text-secondary)]">Platform</span>
                <select
                  value={platform}
                  onChange={(e) => setPlatform(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-[var(--gg-r-control)] text-sm bg-[var(--gg-surface-control)] text-[var(--gg-text-primary)] border border-[var(--gg-divider)]"
                >
                  {['Xbox Series X|S', 'Xbox 360', 'PC', 'PlayStation 5', 'Switch', 'Cloud', 'Mobile', 'Other'].map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <span className="text-xs font-semibold text-[var(--gg-text-secondary)]">Journal Pack</span>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { id: 'general' as const, title: 'General Pack', desc: 'Sessions, campaigns, goals, genres' },
                    { id: 'flight' as const, title: 'Flight Pack', desc: 'Legs, tours, SimBrief, Atlas' },
                  ].map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setPackId(p.id)}
                      className={`text-left p-3 rounded-[var(--gg-r-tile)] border transition-colors ${
                        packId === p.id
                          ? 'border-[var(--gg-focus-ring)] bg-[var(--gg-accent-wash)]'
                          : 'border-[var(--gg-divider)] bg-[var(--gg-surface-control)]'
                      }`}
                    >
                      <div className="text-sm font-semibold text-[var(--gg-text-primary)]">{p.title}</div>
                      <div className="text-[11px] text-[var(--gg-text-secondary)] mt-0.5">{p.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5">
                <span className="text-xs font-semibold text-[var(--gg-text-secondary)]">Library status</span>
                <div className="grid grid-cols-3 gap-1.5">
                  {(['PLAYING', 'BACKLOG', 'ON_HOLD', 'COMPLETED', 'WISHLIST', 'DROPPED'] as GameStatus[]).map((st) => (
                    <button
                      key={st}
                      type="button"
                      onClick={() => setStatus(st)}
                      className={`px-2 py-2 rounded-[var(--gg-r-control)] text-xs font-medium transition-colors ${
                        status === st
                          ? 'bg-[var(--gg-accent)] text-white'
                          : 'bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)] hover:text-[var(--gg-text-primary)]'
                      }`}
                    >
                      {st === 'BACKLOG' ? 'Play later' : st.replace('_', ' ')}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Cover & Wallpaper */}
            <div className="space-y-3 pt-2 border-t border-[var(--gg-divider)]">
              <div className="flex flex-wrap items-center gap-3">
                <AddImageSheet
                  label={coverSha ? 'Change cover art' : 'Add cover art'}
                  onFiles={handleCoverUpload}
                  onXbox={() => setXboxPickerOpen(true)}
                />
                <button
                  type="button"
                  onClick={() => setXboxPickerOpen(true)}
                  className="inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-sm font-medium bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] hover:border-[var(--gg-focus-ring)] xbox-ring"
                >
                  <ImageIcon size={15} />
                  <span>Pull from Xbox</span>
                </button>
                {coverUrl && (
                  <button
                    type="button"
                    onClick={() => setShowCrop(true)}
                    className="text-xs font-semibold text-[var(--gg-focus-ring)] hover:underline"
                  >
                    Adjust 2:3 / 1:1 focal crop
                  </button>
                )}
                {pullingXboxArt && (
                  <span className="text-xs text-[var(--gg-text-secondary)]">
                    Downloading Xbox cover &amp; wallpaper…
                  </span>
                )}
              </div>

              {(coverUrl || heroUrl) && (
                <div className="flex flex-wrap items-center gap-4">
                  {coverUrl && (
                    <div className="flex items-center gap-2">
                      <img
                        src={coverUrl}
                        alt="Cover art preview"
                        className="w-12 aspect-[2/3] rounded-[var(--gg-r-badge)] object-cover border border-white/10"
                      />
                      <span className="text-[11px] text-[var(--gg-text-secondary)]">Cover set</span>
                    </div>
                  )}
                  {heroUrl && (
                    <div className="flex items-center gap-2">
                      <img
                        src={heroUrl}
                        alt="Wallpaper preview"
                        className="w-24 aspect-video rounded-[var(--gg-r-badge)] object-cover border border-white/10"
                      />
                      <span className="text-[11px] text-[var(--gg-text-secondary)]">Wallpaper set</span>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-3">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-[var(--gg-r-control)] text-sm bg-[var(--gg-surface-control)]"
              >
                Cancel
              </button>
              {packId === 'general' ? (
                <button
                  type="button"
                  disabled={!name.trim()}
                  onClick={() => setStep('genres')}
                  className="px-5 py-2 rounded-[var(--gg-r-control)] text-sm font-semibold bg-[var(--gg-accent)] text-white disabled:opacity-40"
                >
                  Next: Pick Genres →
                </button>
              ) : (
                <button
                  type="button"
                  disabled={!name.trim()}
                  onClick={handleCreate}
                  className="px-5 py-2 rounded-[var(--gg-r-control)] text-sm font-semibold bg-[var(--gg-accent)] text-white disabled:opacity-40"
                >
                  Create Flight Game
                </button>
              )}
            </div>
          </div>
        )}

        {step === 'genres' && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <input
                type="text"
                value={genreSearch}
                onChange={(e) => setGenreSearch(e.target.value)}
                placeholder="Filter 17 genres..."
                className="flex-1 min-w-[200px] px-3 py-2 rounded-[var(--gg-r-control)] text-sm bg-[var(--gg-surface-control)] text-[var(--gg-text-primary)] border border-[var(--gg-divider)]"
              />
              <div className="text-xs text-[var(--gg-text-secondary)]">
                Selected: <strong className="text-[var(--gg-text-primary)]">{selectedGenres.length}/3</strong>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2.5 max-h-[38vh] overflow-y-auto pr-1">
              {filteredGenres.map((g) => {
                const selected = selectedGenres.includes(g.id);
                const toolsCount = Object.values(g.features).filter(Boolean).length;
                return (
                  <button
                    key={g.id}
                    type="button"
                    onClick={() => toggleGenre(g.id)}
                    aria-label={`${g.label}, adds ${g.fields.length} fields and ${toolsCount} tools`}
                    className={`relative text-left p-3 rounded-[var(--gg-r-tile)] border transition-all xbox-ring ${
                      selected
                        ? 'border-2 border-[var(--gg-focus-ring)] bg-[var(--gg-accent-wash)]'
                        : 'border-[var(--gg-divider)] bg-[var(--gg-surface-control)] hover:bg-white/10'
                    }`}
                  >
                    {selected && (
                      <span className="absolute top-2 right-2 w-5 h-5 rounded-full bg-[var(--gg-accent)] text-white flex items-center justify-center">
                        <Check size={12} />
                      </span>
                    )}
                    <GlyphIcon name={g.glyph} size={20} className="text-[var(--gg-focus-ring)] mb-2" />
                    <div className="text-sm font-semibold text-[var(--gg-text-primary)] leading-tight">
                      {g.label}
                    </div>
                    <div className="text-[11px] text-[var(--gg-text-secondary)] mt-1">
                      +{g.fields.length} fields · +{toolsCount} tools
                    </div>
                  </button>
                );
              })}
            </div>

            {/* "This adds..." preview plate (§22.17.2) */}
            {previewGenre && (
              <div className="p-3.5 rounded-[var(--gg-r-tile)] bg-black/30 border border-[var(--gg-divider)] space-y-1.5">
                <div className="text-xs font-semibold text-[var(--gg-focus-ring)]">
                  This adds ({previewGenre.label}):
                </div>
                <div className="text-xs text-[var(--gg-text-broadcast)]">
                  <strong>Fields:</strong> {previewGenre.fields.map((f) => f.label).join(', ')}
                </div>
                {previewGenre.stats && previewGenre.stats.length > 0 && (
                  <div className="text-xs text-[var(--gg-text-secondary)]">
                    <strong>Stats &amp; Tools:</strong>{' '}
                    {previewGenre.stats.map((s) => s.label).join(', ')}
                    {previewGenre.records?.length ? ` · Records (${previewGenre.records[0].label})` : ''}
                    {previewGenre.collections?.length ? ` · Collection (${previewGenre.collections[0].name})` : ''}
                  </div>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[var(--gg-divider)]">
              <button
                type="button"
                onClick={() => setStep('details')}
                className="px-4 py-2 rounded-[var(--gg-r-control)] text-sm bg-[var(--gg-surface-control)]"
              >
                ← Back
              </button>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setSelectedGenres([]);
                    handleCreate();
                  }}
                  className="px-4 py-2 rounded-[var(--gg-r-control)] text-sm bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)]"
                >
                  Skip (Custom)
                </button>
                <button
                  type="button"
                  onClick={handleCreate}
                  className="px-5 py-2 rounded-[var(--gg-r-control)] text-sm font-semibold bg-[var(--gg-accent)] text-white"
                >
                  Create Game
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {showCrop && coverUrl && (
        <CropEditor
          imageDataUrl={coverUrl}
          initialFocal={focal}
          onCancel={() => setShowCrop(false)}
          onSave={(f) => {
            setFocal(f);
            setShowCrop(false);
          }}
        />
      )}

      {xboxPickerOpen && (
        <XboxArtPickerModal
          gameName={name}
          xboxTitleId={xboxTitleId}
          initialCoverPreviewUrl={coverUrl ?? undefined}
          initialWallpaperPreviewUrl={heroUrl ?? undefined}
          onApplyUrls={async ({ coverUrl: chosenCover, wallpaperUrl: chosenHero, title }) => {
            const imported = await importSingleXboxArtChoice({
              gameName: name.trim() || title?.name || 'Xbox game',
              coverUrl: chosenCover,
              wallpaperUrl: chosenHero,
              existingMedia: db.media,
            });
            if (imported.mediaEntries.length > 0) {
              addMediaItems(imported.mediaEntries, { skipAutoIndex: true });
            }
            if (imported.coverSha) setCoverSha(imported.coverSha);
            if (imported.heroSha) setHeroSha(imported.heroSha);
            if (title?.titleId) setXboxTitleId(title.titleId);
            if (!name.trim() && title?.name) {
              setName(title.name);
              if (normaliseGameTitle(title.name).includes('flight simulator')) {
                setPackId('flight');
              }
            }
            pushToast({ title: 'Xbox artwork ready' });
          }}
          onClose={() => setXboxPickerOpen(false)}
        />
      )}
    </div>
  );
}
