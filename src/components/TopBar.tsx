import React, { useEffect, useState } from 'react';
import { useJournal } from '../state/JournalStore';
import { GlyphIcon, GreenGuideMark } from './Glyphs';
import { PlayerAvatar } from './PlayerAvatar';
import { ArrowLeft } from 'lucide-react';
import { APP_VERSION } from '../version';

export function TopBar() {
  const {
    db,
    ledger,
    activeProfile,
    route,
    canGoBack,
    navigate,
    goBack,
    setGuideOpen,
    playSound,
  } = useJournal();

  const [clockText, setClockText] = useState(() =>
    new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  );

  useEffect(() => {
    const t = setInterval(() => {
      setClockText(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    }, 15_000);
    return () => clearInterval(t);
  }, []);

  const hasUnreadWhatsNew = db.settings.whatsNewLastSeenVersion !== APP_VERSION;
  const unreadInboxCount = (db.inbox ?? []).filter((i) => i.status === 'UNREAD').length;
  const profileRight = db.settings.profilePlacement === 'right';

  const navItems: Array<{ id: 'home' | 'library' | 'keeper' | 'search' | 'settings'; label: string; glyph: string; dot?: boolean }> = [
    { id: 'home', label: 'Home', glyph: 'home' },
    { id: 'library', label: 'Library', glyph: 'library' },
    { id: 'keeper', label: 'Keeper', glyph: 'keeper' },
    { id: 'search', label: 'Search', glyph: 'search' },
    { id: 'settings', label: 'Settings', glyph: 'settings', dot: hasUnreadWhatsNew },
  ];

  const ProfileCluster = (
    <button
      type="button"
      onClick={() => {
        playSound('guide_open');
        setGuideOpen(true);
      }}
      className="relative flex items-center gap-3 text-left rounded-[var(--gg-r-control)] px-2 py-1.5 hover:bg-white/10 transition-colors xbox-ring-subtle shrink-0"
      aria-label={`Open Guide for ${activeProfile.playerTag}${unreadInboxCount > 0 ? ` (${unreadInboxCount} unread in Inbox)` : ''}`}
    >
      <div className="relative">
        <PlayerAvatar url={activeProfile.avatarUrl} tag={activeProfile.playerTag} size={38} />
        {unreadInboxCount > 0 && (
          <span
            className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-[var(--gg-accent)] text-white text-[10px] font-bold flex items-center justify-center border border-[var(--gg-bg-base)]"
            title={`${unreadInboxCount} unread in Inbox`}
          >
            {unreadInboxCount}
          </span>
        )}
      </div>
      <div className="leading-tight min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[var(--gg-text-primary)] truncate max-w-[130px]">
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
        <div className="flex items-center gap-1.5 text-xs text-[var(--gg-text-secondary)] tabular-nums mt-0.5">
          {activeProfile.isXboxLinked && typeof activeProfile.gamerscore === 'number' ? (
            <>
              <span
                className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-[#107C10] text-white text-[9px] font-black"
                title="Xbox Gamerscore"
              >
                G
              </span>
              <span className="font-medium text-[var(--gg-text-primary)]">
                {activeProfile.gamerscore.toLocaleString()}
              </span>
              <span aria-hidden="true">·</span>
              <span>{activeProfile.hoursFormatted}</span>
            </>
          ) : (
            <>
              {!db.settings.hideJournalScore && (
                <>
                  <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-[var(--gg-text-primary)] text-[var(--gg-bg-base)] text-[9px] font-bold">
                    J
                  </span>
                  <span>{ledger.journalScore.toLocaleString()}</span>
                  <span aria-hidden="true">·</span>
                </>
              )}
              <span>{ledger.globalHours}h</span>
            </>
          )}
        </div>
      </div>
    </button>
  );

  const NavStrip = (
    <nav className="flex items-center gap-1 sm:gap-2 overflow-x-auto no-scrollbar" aria-label="Primary navigation">
      {navItems.map((item) => {
        const active = route.page === item.id;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() =>
              navigate(
                item.id === 'home'
                  ? { page: 'home' }
                  : item.id === 'library'
                    ? { page: 'library' }
                    : item.id === 'keeper'
                      ? { page: 'keeper' }
                      : item.id === 'search'
                        ? { page: 'search' }
                        : { page: 'settings' }
              )
            }
            aria-label={item.label}
            aria-current={active ? 'page' : undefined}
            className={`relative flex items-center gap-2 px-3 py-2 rounded-[var(--gg-r-control)] text-sm font-medium whitespace-nowrap shrink-0 transition-all duration-150 xbox-ring-subtle ${
              active
                ? 'bg-[var(--gg-accent)] text-white'
                : 'bg-[var(--gg-surface-control)] text-[var(--gg-text-broadcast)] hover:bg-white/15'
            }`}
          >
            <GlyphIcon name={item.glyph} size={16} />
            <span className="hidden md:inline">{item.label}</span>
            {item.dot && (
              <span
                className="w-2 h-2 rounded-full bg-[#9BF00B] shrink-0"
                title="What's new unread"
              />
            )}
          </button>
        );
      })}
    </nav>
  );

  const RightStatus = (
    <div className="flex items-center gap-3 text-xs text-[var(--gg-text-secondary)] shrink-0">
      <div className="hidden sm:flex items-center gap-1.5" title="Green Guide offline-first">
        <GreenGuideMark size={18} className="text-[var(--gg-text-primary)]" />
        <span className="font-semibold text-[var(--gg-text-primary)] tracking-tight whitespace-nowrap">
          Green Guide
        </span>
      </div>
      <span className="tabular-nums text-sm font-medium text-[var(--gg-text-primary)] whitespace-nowrap">
        {clockText}
      </span>
    </div>
  );

  return (
    <header
      className="sticky top-0 z-30 w-full pb-3 bg-gradient-to-b from-[var(--gg-bg-base)]/85 via-[var(--gg-bg-base)]/40 to-transparent backdrop-blur-[2px]"
      style={{
        paddingTop: 'calc(var(--gg-inset-top) + 8px)',
        paddingLeft: 'calc(var(--gg-inset-left) + 16px)',
        paddingRight: 'calc(var(--gg-inset-right) + 16px)',
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {canGoBack && route.page !== 'home' && (
            <button
              type="button"
              onClick={goBack}
              aria-label="Go back"
              className="flex items-center justify-center w-9 h-9 rounded-[var(--gg-r-control)] bg-[var(--gg-surface-control)] text-[var(--gg-text-primary)] hover:bg-white/20 transition-colors xbox-ring-subtle shrink-0"
            >
              <ArrowLeft size={18} />
            </button>
          )}
          {!profileRight ? ProfileCluster : RightStatus}
        </div>

        <div className="order-3 sm:order-2 w-full sm:w-auto flex justify-center">
          {NavStrip}
        </div>

        <div className="order-2 sm:order-3 flex items-center gap-2">
          {!profileRight ? RightStatus : ProfileCluster}
        </div>
      </div>
    </header>
  );
}
