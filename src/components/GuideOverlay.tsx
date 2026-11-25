import React, { useEffect, useMemo, useState } from 'react';
import { useJournal } from '../state/JournalStore';
import { BUNDLED_MILESTONES } from '../data/bundledModules';
import { GlyphIcon, GreenGuideMark } from './Glyphs';
import { PlayerAvatar } from './PlayerAvatar';
import { X, Sun, Moon, Volume2, VolumeX, PlusCircle } from 'lucide-react';
import { APP_VERSION } from '../version';
import { XboxProfileCard } from './XboxProfileCard';
import { DictationButton } from './DictationButton';

export function GuideOverlay() {
  const {
    db,
    ledger,
    activeProfile,
    isNight,
    route,
    guideOpen,
    setGuideOpen,
    navigate,
    updateSettings,
    createLegOrSession,
    playSound,
    pushToast,
    quickNoteSignal,
  } = useJournal();

  const [tab, setTab] = useState<'home' | 'library' | 'keeper' | 'captures' | 'profile'>('home');
  const [quickNoteOpen, setQuickNoteOpen] = useState(false);
  const [quickNoteText, setQuickNoteText] = useState('');

  useEffect(() => {
    if (quickNoteSignal > 0) {
      setQuickNoteOpen(true);
    }
  }, [quickNoteSignal]);

  const unreadInbox = (db.inbox ?? []).filter((i) => i.status === 'UNREAD').length;
  const hasUnreadWhatsNew = db.settings.whatsNewLastSeenVersion !== APP_VERSION;

  const tabItems = useMemo(() => {
    const base: Array<{ id: typeof tab; label: string; glyph: string }> = [
      { id: 'home', label: 'Home', glyph: 'home' },
      { id: 'library', label: 'Library', glyph: 'library' },
      { id: 'keeper', label: 'Keeper', glyph: 'keeper' },
      { id: 'captures', label: 'Captures', glyph: 'atlas' },
      { id: 'profile', label: 'Profile', glyph: 'trophy' },
    ];
    const order = db.settings.guideTabOrder;
    if (!order || order.length === 0) return base;
    return [...base].sort((a, b) => {
      const ia = order.indexOf(a.id);
      const ib = order.indexOf(b.id);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
  }, [db.settings.guideTabOrder]);

  if (!guideOpen) return null;

  const sideRight = db.settings.guideSide === 'right';
  const activeGames = db.games.filter((g) => !g.deletedAt);
  const recentAwards = [...db.milestoneAwards]
    .sort((a, b) => b.awardedAt - a.awardedAt)
    .slice(0, 5);

  const toggleDayNight = () => {
    const next = isNight ? 'DAY' : 'NIGHT';
    updateSettings({ themeMode: next });
    playSound('toggle_on');
  };

  const toggleMute = () => {
    const nextVol = db.settings.soundMaster > 0 ? 0 : 70;
    updateSettings({ soundMaster: nextVol });
  };

  const handleQuickNoteSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!quickNoteText.trim()) return;
    const game = activeGames[0];
    if (!game) return;
    const sess = createLegOrSession({
      gameId: game.id,
      title: quickNoteText.trim().slice(0, 42),
      summary: quickNoteText.trim(),
      status: 'IN_PROGRESS',
    });
    setQuickNoteText('');
    setQuickNoteOpen(false);
    setGuideOpen(false);
    pushToast({ title: `Quick entry added to ${game.name}` });
    navigate({ page: 'leg', legId: sess.id });
  };

  return (
    <div
      className="fixed inset-0 z-40 flex"
      role="dialog"
      aria-modal="true"
      aria-label="Xbox Guide Overlay"
    >
      {/* Dimmed blur backdrop */}
      <div
        className="fixed inset-0 bg-black/55 backdrop-blur-md transition-opacity"
        onClick={() => {
          playSound('guide_close');
          setGuideOpen(false);
        }}
      />

      <aside
        className={`relative z-10 w-[min(90vw,372px)] h-full flex flex-col justify-between p-4 shadow-2xl border-[var(--gg-divider)] ${
          sideRight ? 'ml-auto rounded-l-[var(--gg-r-panel)] border-l' : 'mr-auto rounded-r-[var(--gg-r-panel)] border-r'
        }`}
        style={{
          backgroundColor: 'var(--gg-bg-panel)',
          backgroundImage: `linear-gradient(180deg, var(--gg-accent-wash) 0%, transparent 45%)`,
          backdropFilter: 'blur(28px)',
        }}
      >
        {/* Top Tab Strip */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <GreenGuideMark size={20} className="text-[var(--gg-text-primary)]" />
              <span className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
                Guide
              </span>
            </div>
            <button
              type="button"
              onClick={() => {
                playSound('guide_close');
                setGuideOpen(false);
              }}
              aria-label="Close Guide"
              className="w-8 h-8 rounded flex items-center justify-center text-[var(--gg-text-secondary)] hover:bg-white/10 hover:text-[var(--gg-text-primary)]"
            >
              <X size={16} />
            </button>
          </div>

          <div className="grid grid-cols-5 gap-1 p-1 rounded bg-black/25 mb-4">
            {tabItems.map((t) => {
              const active = tab === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => {
                    playSound('focus_move');
                    setTab(t.id);
                  }}
                  aria-label={t.label}
                  className={`flex flex-col items-center justify-center py-2 rounded text-[11px] transition-colors ${
                    active
                      ? 'bg-[var(--gg-accent)] text-white font-semibold'
                      : 'text-[var(--gg-text-secondary)] hover:bg-white/10'
                  }`}
                >
                  <GlyphIcon name={t.glyph} size={17} />
                </button>
              );
            })}
          </div>

          {/* Guide Body */}
          {tab === 'home' && (
            <div className="space-y-1.5">
              {[
                { label: 'Home', active: route.page === 'home', action: () => navigate({ page: 'home' }) },
                { label: 'My library', active: route.page === 'library', action: () => navigate({ page: 'library' }) },
                {
                  label: unreadInbox > 0 ? `Inbox (${unreadInbox} unread)` : 'Inbox',
                  active: route.page === 'inbox',
                  badge: unreadInbox > 0 ? unreadInbox : undefined,
                  action: () => navigate({ page: 'inbox' }),
                },
                { label: 'MSFS 2024 · Flight Pack', active: route.page === 'game' && route.gameId === 'game_msfs2024', action: () => navigate({ page: 'game', gameId: 'game_msfs2024' }) },
                { label: 'Atlas (Offline World Map)', active: route.page === 'atlas', action: () => navigate({ page: 'atlas' }) },
                { label: 'Keeper AI Librarian', active: route.page === 'keeper', action: () => navigate({ page: 'keeper' }) },
                { label: 'Recap', active: route.page === 'recap', action: () => navigate({ page: 'recap' }) },
                { label: 'Settings', active: route.page === 'settings', action: () => navigate({ page: 'settings' }) },
              ].map((row) => (
                <button
                  key={row.label}
                  type="button"
                  onClick={row.action}
                  className={`w-full text-left px-3.5 py-3 rounded-[var(--gg-r-control)] text-sm font-medium transition-all flex items-center justify-between ${
                    row.active
                      ? 'border-2 border-[var(--gg-focus-ring)] bg-[var(--gg-surface-focus)] text-[var(--gg-text-primary)]'
                      : 'border border-transparent hover:bg-[var(--gg-surface-focus)] text-[var(--gg-text-broadcast)]'
                  }`}
                >
                  <span>{row.label}</span>
                  {'badge' in row && row.badge ? (
                    <span className="px-2 py-0.5 rounded-[var(--gg-r-badge)] text-[10px] font-bold bg-[var(--gg-accent)] text-white">
                      {row.badge}
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
          )}

          {tab === 'library' && (
            <div className="space-y-1.5 max-h-[60vh] overflow-y-auto pr-1">
              <div className="text-xs text-[var(--gg-text-secondary)] px-1 mb-2">
                Jump directly into a game hub
              </div>
              {activeGames.map((g) => (
                <button
                  key={g.id}
                  type="button"
                  onClick={() => navigate({ page: 'game', gameId: g.id })}
                  className="w-full text-left px-3 py-2.5 rounded-[var(--gg-r-control)] hover:bg-[var(--gg-surface-focus)] flex items-center justify-between"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-[var(--gg-text-primary)] truncate">
                      {g.name}
                    </div>
                    <div className="text-xs text-[var(--gg-text-secondary)]">
                      {g.platform} · {g.status}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}

          {tab === 'keeper' && (
            <div className="space-y-2">
              <p className="text-xs text-[var(--gg-text-secondary)] px-1">
                Keeper scopes &amp; memory files
              </p>
              <button
                type="button"
                onClick={() => navigate({ page: 'keeper', view: 'chat' })}
                className="w-full text-left px-3.5 py-3 rounded-[var(--gg-r-control)] bg-[var(--gg-accent)] text-white text-sm font-semibold"
              >
                Open Keeper Chat
              </button>
              <button
                type="button"
                onClick={() => navigate({ page: 'keeper', view: 'dossier' })}
                className="w-full text-left px-3.5 py-2.5 rounded-[var(--gg-r-control)] hover:bg-[var(--gg-surface-focus)] text-sm"
              >
                Player Dossier (v{db.dossier.version})
              </button>
              <button
                type="button"
                onClick={() => navigate({ page: 'keeper', view: 'chronicle' })}
                className="w-full text-left px-3.5 py-2.5 rounded-[var(--gg-r-control)] hover:bg-[var(--gg-surface-focus)] text-sm"
              >
                Chronicle Archive ({db.chronicleFiles.length} file{db.chronicleFiles.length === 1 ? '' : 's'})
              </button>
              <button
                type="button"
                onClick={() => navigate({ page: 'keeper', view: 'persona' })}
                className="w-full text-left px-3.5 py-2.5 rounded-[var(--gg-r-control)] hover:bg-[var(--gg-surface-focus)] text-sm"
              >
                Swap Persona
              </button>
            </div>
          )}

          {tab === 'captures' && (
            <div className="space-y-2">
              <div className="text-xs text-[var(--gg-text-secondary)] px-1">
                Captures &amp; quick tools
              </div>
              <button
                type="button"
                onClick={() => navigate({ page: 'library', tab: 'captures' })}
                className="w-full text-left px-3.5 py-3 rounded-[var(--gg-r-control)] hover:bg-[var(--gg-surface-focus)] text-sm"
              >
                Browse all captures ({db.media.length})
              </button>
              <button
                type="button"
                onClick={() => navigate({ page: 'atlas' })}
                className="w-full text-left px-3.5 py-3 rounded-[var(--gg-r-control)] hover:bg-[var(--gg-surface-focus)] text-sm"
              >
                Open Offline Flight Atlas
              </button>
              <button
                type="button"
                onClick={() => navigate({ page: 'recap' })}
                className="w-full text-left px-3.5 py-3 rounded-[var(--gg-r-control)] hover:bg-[var(--gg-surface-focus)] text-sm"
              >
                Create Year in Games Recap
              </button>
            </div>
          )}

          {tab === 'profile' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-2 p-3 rounded-[var(--gg-r-control)] bg-white/5">
                <div className="flex items-center gap-3 min-w-0">
                  <PlayerAvatar url={activeProfile.avatarUrl} tag={activeProfile.playerTag} size={48} />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-[var(--gg-text-primary)] truncate">
                        {activeProfile.playerTag}
                      </span>
                      <span
                        className={`px-1.5 py-0.5 text-[10px] font-bold tracking-wider uppercase rounded-[var(--gg-r-badge)] shrink-0 ${
                          activeProfile.isXboxLinked
                            ? 'bg-[#107C10] text-white'
                            : 'bg-[#EBEBEB] text-[#101010]'
                        }`}
                      >
                        {activeProfile.tier}
                      </span>
                    </div>
                    <div className="text-xs text-[var(--gg-text-secondary)] tabular-nums flex flex-wrap items-center gap-1.5 mt-0.5">
                      {activeProfile.isXboxLinked && typeof activeProfile.gamerscore === 'number' ? (
                        <>
                          <span
                            className="inline-flex items-center justify-center w-3 h-3 rounded-full bg-[#107C10] text-white text-[8px] font-bold"
                            title="Xbox Gamerscore"
                          >
                            G
                          </span>
                          <span>{activeProfile.gamerscore.toLocaleString()}</span>
                          <span aria-hidden="true">·</span>
                          <span>{activeProfile.hoursFormatted}</span>
                          {!db.settings.hideJournalScore && (
                            <>
                              <span aria-hidden="true">·</span>
                              <span>{ledger.journalScore.toLocaleString()} JS</span>
                            </>
                          )}
                        </>
                      ) : (
                        <>
                          {!db.settings.hideJournalScore ? `${ledger.journalScore.toLocaleString()} JS · ` : ''}
                          {`${ledger.globalHours}h total`}
                        </>
                      )}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => navigate({ page: 'profile' })}
                  className="px-2.5 py-1.5 rounded-[var(--gg-r-control)] bg-[var(--gg-accent)] text-white text-xs font-semibold shrink-0"
                >
                  Full profile
                </button>
              </div>

              <XboxProfileCard showRecent={false} />

              <div>
                <div className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)] mb-2">
                  Recent Milestones (5)
                </div>
                <div className="space-y-1.5">
                  {recentAwards.map((aw) => {
                    const def = BUNDLED_MILESTONES.find((m) => m.id === aw.milestoneId);
                    if (!def) return null;
                    return (
                      <div key={aw.milestoneId} className="flex items-center justify-between px-2.5 py-2 rounded bg-white/5 text-xs">
                        <div className="min-w-0">
                          <div className="font-semibold text-[var(--gg-text-primary)] truncate">{def.title}</div>
                          <div className="text-[var(--gg-text-tertiary)] truncate">{def.desc}</div>
                        </div>
                        <span className="font-mono text-[var(--gg-focus-ring)] font-semibold shrink-0 ml-2">
                          +{def.points}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="space-y-1 pt-1 border-t border-[var(--gg-divider)]">
                <button
                  type="button"
                  onClick={() => {
                    setGuideOpen(false);
                    navigate({ page: 'settings', category: 'wallpaper' });
                  }}
                  className="w-full text-left px-3 py-2 rounded-[var(--gg-r-control)] text-sm hover:bg-white/10"
                >
                  Change wallpaper
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setGuideOpen(false);
                    navigate({ page: 'settings', category: 'whatsnew' });
                  }}
                  className="w-full text-left px-3 py-2 rounded-[var(--gg-r-control)] text-sm hover:bg-white/10 flex items-center justify-between"
                >
                  <span>What&apos;s New ({APP_VERSION})</span>
                  {hasUnreadWhatsNew && (
                    <span
                      className="w-2 h-2 rounded-full bg-[#9BF00B] shrink-0"
                      title="What's new unread"
                    />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setGuideOpen(false);
                    navigate({ page: 'settings', category: 'backup' });
                  }}
                  className="w-full text-left px-3 py-2 rounded-[var(--gg-r-control)] text-sm hover:bg-white/10"
                >
                  Data &amp; Backup
                </button>
              </div>
            </div>
          )}

          {quickNoteOpen && (
            <form onSubmit={handleQuickNoteSubmit} className="mt-4 p-3 rounded-[var(--gg-r-control)] bg-black/35 border border-[var(--gg-divider)] space-y-2">
              <label className="block text-xs font-semibold text-[var(--gg-text-primary)]">
                Quick log into {activeGames[0]?.name}
              </label>
              <input
                type="text"
                value={quickNoteText}
                onChange={(e) => setQuickNoteText(e.target.value)}
                placeholder="What just happened?"
                className="w-full px-2.5 py-2 rounded-[var(--gg-r-control)] text-sm bg-[var(--gg-surface-control)] text-[var(--gg-text-primary)] border border-[var(--gg-divider)]"
              />
              <div className="flex items-center justify-between gap-2">
                <DictationButton
                  compact
                  onDictated={(spoken) =>
                    setQuickNoteText((prev) => (prev ? `${prev} ${spoken}` : spoken))
                  }
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setQuickNoteOpen(false)}
                    className="px-2.5 py-1 text-xs rounded-[var(--gg-r-control)] bg-white/10"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-2.5 py-1 text-xs rounded-[var(--gg-r-control)] bg-[var(--gg-accent)] text-white font-semibold"
                  >
                    Log
                  </button>
                </div>
              </div>
            </form>
          )}
        </div>

        {/* Bottom Glyph Row */}
        <div className="pt-3 border-t border-[var(--gg-divider)] flex items-center justify-between gap-1">
          <button
            type="button"
            onClick={() => setQuickNoteOpen((v) => !v)}
            aria-label="Quick note"
            title="Quick note"
            className="p-2.5 rounded hover:bg-white/10 text-[var(--gg-text-broadcast)]"
          >
            <PlusCircle size={18} />
          </button>
          <button
            type="button"
            onClick={() => navigate({ page: 'atlas' })}
            aria-label="Open Atlas"
            title="Atlas Map"
            className="p-2.5 rounded hover:bg-white/10 text-[var(--gg-text-broadcast)]"
          >
            <GlyphIcon name="atlas" size={18} />
          </button>
          <button
            type="button"
            onClick={() => navigate({ page: 'search' })}
            aria-label="Global Search"
            title="Search"
            className="p-2.5 rounded hover:bg-white/10 text-[var(--gg-text-broadcast)]"
          >
            <GlyphIcon name="search" size={18} />
          </button>
          <button
            type="button"
            onClick={toggleMute}
            aria-label={db.settings.soundMaster > 0 ? 'Mute UI sounds' : 'Unmute UI sounds'}
            title="Sound volume toggle"
            className="p-2.5 rounded hover:bg-white/10 text-[var(--gg-text-broadcast)]"
          >
            {db.settings.soundMaster > 0 ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>
          <button
            type="button"
            onClick={toggleDayNight}
            aria-label={isNight ? 'Switch to Day theme' : 'Switch to Night theme'}
            title="Toggle Day/Night"
            className="p-2.5 rounded hover:bg-white/10 text-[var(--gg-text-broadcast)]"
          >
            {isNight ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
      </aside>
    </div>
  );
}
