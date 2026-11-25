import React, { useMemo, useState } from 'react';
import { useJournal } from '../state/JournalStore';
import { BUNDLED_MILESTONES, GENRE_MAP } from '../data/bundledModules';
import { PlayerAvatar } from '../components/PlayerAvatar';
import { collectJournalRegistries } from '../logic/registries';
import type { MilestoneDef } from '../types/journal';
import { Award, BookOpen, Eye, EyeOff, Flame, HelpCircle, Lock, Sparkles, X } from 'lucide-react';
import { XboxProfileCard } from '../components/XboxProfileCard';

function computeActiveDayStreak(dates: string[]): number {
  const unique = Array.from(new Set(dates.filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)))).sort().reverse();
  if (unique.length === 0) return 0;

  const today = new Date();
  const toKey = (dt: Date) => dt.toISOString().slice(0, 10);
  const todayStr = toKey(today);
  const yest = new Date(today.getTime() - 86400_000);
  const yestStr = toKey(yest);

  if (unique[0] !== todayStr && unique[0] !== yestStr) {
    return 0;
  }

  let streak = 0;
  let cursor = new Date(`${unique[0]}T00:00:00Z`);
  const dateSet = new Set(unique);
  while (dateSet.has(toKey(cursor))) {
    streak++;
    cursor = new Date(cursor.getTime() - 86400_000);
  }
  return streak;
}

export function ProfilePage() {
  const { db, ledger, activeProfile, navigate, updateSettings } = useJournal();
  const [selectedBadge, setSelectedBadge] = useState<MilestoneDef | null>(null);

  const activeGames = useMemo(() => db.games.filter((g) => !g.deletedAt), [db.games]);
  const activeLegs = useMemo(() => db.legs.filter((l) => !l.deletedAt), [db.legs]);
  const activeTours = useMemo(() => db.tours.filter((t) => !t.deletedAt), [db.tours]);
  const registries = useMemo(() => collectJournalRegistries(db), [db]);

  const awardById = useMemo(() => {
    const m = new Map<string, { awardedAt: number; reason?: string }>();
    for (const aw of db.milestoneAwards) {
      m.set(aw.milestoneId, { awardedAt: aw.awardedAt, reason: aw.contextNote });
    }
    return m;
  }, [db.milestoneAwards]);

  const recentAwards = useMemo(
    () => [...db.milestoneAwards].sort((a, b) => b.awardedAt - a.awardedAt).slice(0, 5),
    [db.milestoneAwards]
  );

  const streakDays = useMemo(() => {
    const legDays = activeLegs.map((l) => l.flownOn || new Date(l.createdAt).toISOString().slice(0, 10));
    const entryDays = db.entries.filter((e) => !e.deletedAt).map((e) => new Date(e.createdAt).toISOString().slice(0, 10));
    return computeActiveDayStreak([...legDays, ...entryDays]);
  }, [activeLegs, db.entries]);

  const favorites = useMemo(() => {
    const topAircraft = registries.aircraft[0]?.canonical;
    const topSim = registries.sims[0]?.canonical;
    const topGame = [...activeGames].sort(
      (a, b) => (ledger.perGameHours[b.id] ?? 0) - (ledger.perGameHours[a.id] ?? 0)
    )[0];

    const genreHours = new Map<string, number>();
    for (const g of activeGames) {
      const h = ledger.perGameHours[g.id] ?? 0.5;
      if (g.packId === 'flight') {
        genreHours.set('Flight Sim', (genreHours.get('Flight Sim') ?? 0) + h);
      } else {
        for (const gid of g.genreIds) {
          const label = GENRE_MAP[gid]?.label || gid;
          genreHours.set(label, (genreHours.get(label) ?? 0) + h);
        }
      }
    }
    const topGenre = Array.from(genreHours.entries()).sort((a, b) => b[1] - a[1])[0]?.[0];

    return { topAircraft, topSim, topGame, topGenre };
  }, [registries, activeGames, ledger.perGameHours]);

  const dossierPreview = useMemo(() => {
    const pinned = db.dossier.facts.filter((f) => !f.retired && f.pinned).slice(0, 4);
    if (pinned.length > 0) return pinned.map((f) => f.text);
    const active = db.dossier.facts.filter((f) => !f.retired).slice(0, 4);
    if (active.length > 0) return active.map((f) => f.text);
    return [];
  }, [db.dossier.facts]);

  const hasFlight = activeGames.some((g) => g.packId === 'flight');
  const hideScore = Boolean(db.settings.hideJournalScore);

  const selectedAward = selectedBadge ? awardById.get(selectedBadge.id) : undefined;

  return (
    <div className="space-y-6 pb-28">
      {/* Header Banner */}
      <section className="p-6 rounded-[var(--gg-r-panel)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <PlayerAvatar url={activeProfile.avatarUrl} tag={activeProfile.playerTag} size={72} />
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-light text-[var(--gg-text-primary)] tracking-tight">
                {activeProfile.playerTag}
              </h1>
              <span
                className={`px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider rounded-[var(--gg-r-badge)] ${
                  activeProfile.isXboxLinked
                    ? 'bg-[#107C10] text-white'
                    : 'bg-[#EBEBEB] text-[#101010]'
                }`}
              >
                {activeProfile.tier}
              </span>
              {hasFlight && ledger.aviationRank && (
                <span className="px-2.5 py-0.5 text-xs font-semibold rounded-[var(--gg-r-badge)] bg-[var(--gg-accent-wash)] text-[var(--gg-focus-ring)] border border-[var(--gg-divider)]">
                  {ledger.aviationRank}
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--gg-text-secondary)]">
              {activeProfile.isXboxLinked && typeof activeProfile.gamerscore === 'number' && (
                <span className="inline-flex items-center gap-1 font-semibold text-[var(--gg-text-primary)] tabular-nums">
                  <span
                    className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-[#107C10] text-white text-[9px] font-black"
                    title="Xbox Gamerscore"
                  >
                    G
                  </span>
                  <span>{activeProfile.gamerscore.toLocaleString()} Gamerscore</span>
                </span>
              )}
              {!hideScore && (
                <span className="font-semibold text-[var(--gg-text-primary)] tabular-nums">
                  Journal Score: {ledger.journalScore.toLocaleString()} JS
                </span>
              )}
              <span className="inline-flex items-center gap-1">
                <Flame size={13} className="text-amber-400" />
                <span>{streakDays} day streak</span>
              </span>
              <span>
                {db.milestoneAwards.length} / {BUNDLED_MILESTONES.length} badges unlocked
              </span>
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={() => updateSettings({ hideJournalScore: !hideScore })}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-[var(--gg-r-control)] bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-xs font-medium self-start sm:self-center"
        >
          {hideScore ? <Eye size={14} /> : <EyeOff size={14} />}
          <span>{hideScore ? 'Show Journal Score' : 'Hide Journal Score'}</span>
        </button>
      </section>

      {/* Xbox Profile Activity */}
      <section className="space-y-2.5">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
            Xbox Live Activity
          </h2>
          {activeProfile.isXboxLinked && (
            <span className="text-xs text-[var(--gg-text-secondary)] tabular-nums">
              {activeProfile.playerTag} · {activeProfile.tier}
            </span>
          )}
        </div>
        <XboxProfileCard showRecent={true} />
      </section>

      {/* Totals */}
      <section className="space-y-2.5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
          Totals
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
          {[
            ...(activeProfile.isXboxLinked && typeof activeProfile.gamerscore === 'number'
              ? [{ label: 'Gamerscore', val: `G ${activeProfile.gamerscore.toLocaleString()}` }]
              : []),
            { label: 'Hours', val: activeProfile.hoursFormatted },
            { label: 'Legs / Sessions', val: activeLegs.length },
            { label: 'Tours / Campaigns', val: activeTours.length },
            { label: 'Places / Airports', val: ledger.distinctAirports },
            { label: 'Aircraft & Vehicles', val: registries.aircraft.length + registries.vehiclesByGame.reduce((a, g) => a + g.entries.length, 0) },
            { label: 'Sims', val: registries.sims.length },
            { label: 'Games', val: activeProfile.gamesCount },
          ].map((stat) => (
            <div
              key={stat.label}
              className="p-3.5 rounded-[var(--gg-r-tile)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)]"
            >
              <div className="text-xl font-semibold text-[var(--gg-text-primary)] tabular-nums">
                {stat.val}
              </div>
              <div className="text-[11px] text-[var(--gg-text-secondary)] mt-0.5">{stat.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Favourites & Keeper's Read on You */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className="p-5 rounded-[var(--gg-r-panel)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
            Derived Favourites
          </h2>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="p-3 rounded-[var(--gg-r-control)] bg-white/5">
              <div className="text-[var(--gg-text-secondary)]">Top game</div>
              <div className="font-semibold text-[var(--gg-text-primary)] mt-0.5 truncate">
                {favorites.topGame?.name || '—'}
              </div>
            </div>
            <div className="p-3 rounded-[var(--gg-r-control)] bg-white/5">
              <div className="text-[var(--gg-text-secondary)]">Top genre</div>
              <div className="font-semibold text-[var(--gg-text-primary)] mt-0.5 truncate">
                {favorites.topGenre || '—'}
              </div>
            </div>
            <div className="p-3 rounded-[var(--gg-r-control)] bg-white/5">
              <div className="text-[var(--gg-text-secondary)]">Most-used aircraft</div>
              <div className="font-semibold text-[var(--gg-text-primary)] mt-0.5 truncate">
                {favorites.topAircraft || '—'}
              </div>
            </div>
            <div className="p-3 rounded-[var(--gg-r-control)] bg-white/5">
              <div className="text-[var(--gg-text-secondary)]">Primary simulator</div>
              <div className="font-semibold text-[var(--gg-text-primary)] mt-0.5 truncate">
                {favorites.topSim || '—'}
              </div>
            </div>
          </div>
        </section>

        <section className="p-5 rounded-[var(--gg-r-panel)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)] flex items-center gap-1.5">
              <Sparkles size={13} className="text-[var(--gg-focus-ring)]" />
              <span>Keeper&apos;s read on you</span>
            </h2>
            <button
              type="button"
              onClick={() => navigate({ page: 'keeper', view: 'dossier' })}
              className="inline-flex items-center gap-1 text-xs text-[var(--gg-focus-ring)] hover:underline"
            >
              <BookOpen size={12} />
              <span>Open Dossier (v{db.dossier.version})</span>
            </button>
          </div>
          {dossierPreview.length > 0 ? (
            <ul className="space-y-1.5 text-xs text-[var(--gg-text-broadcast)]">
              {dossierPreview.map((line, i) => (
                <li key={i} className="p-2 rounded-[var(--gg-r-badge)] bg-white/5">
                  {line}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-[var(--gg-text-secondary)]">
              As you log entries and chat with the Keeper, durable facts and preferences gather in your Player Dossier.
            </p>
          )}
        </section>
      </div>

      {/* 5 Most Recent Badges */}
      {recentAwards.length > 0 && (
        <section className="space-y-2.5">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
            Recent Badges
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
            {recentAwards.map((aw) => {
              const def = BUNDLED_MILESTONES.find((m) => m.id === aw.milestoneId);
              if (!def) return null;
              return (
                <button
                  key={aw.milestoneId}
                  type="button"
                  onClick={() => setSelectedBadge(def)}
                  className="text-left p-3.5 rounded-[var(--gg-r-tile)] bg-[var(--gg-accent-wash)] border border-[var(--gg-focus-ring)]/60 hover:border-[var(--gg-focus-ring)] transition-colors"
                >
                  <div className="flex items-center justify-between gap-2">
                    <Award size={16} className="text-[var(--gg-focus-ring)]" />
                    <span className="text-[11px] font-mono text-[var(--gg-focus-ring)] font-semibold">
                      +{def.points}
                    </span>
                  </div>
                  <div className="text-sm font-semibold text-[var(--gg-text-primary)] mt-1.5 truncate">
                    {def.title}
                  </div>
                  <div className="text-[11px] text-[var(--gg-text-secondary)] mt-0.5">
                    {new Date(aw.awardedAt).toLocaleDateString()}
                  </div>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {/* Full Badges Grid */}
      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
          All Badges ({db.milestoneAwards.length} / {BUNDLED_MILESTONES.length})
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {BUNDLED_MILESTONES.map((def) => {
            const award = awardById.get(def.id);
            const unlocked = Boolean(award);
            const masked = Boolean(def.hidden && !unlocked);
            return (
              <button
                key={def.id}
                type="button"
                onClick={() => setSelectedBadge(def)}
                className={`text-left p-4 rounded-[var(--gg-r-tile)] border transition-all ${
                  unlocked
                    ? 'bg-[var(--gg-bg-raised)] border-[var(--gg-focus-ring)]/70 hover:border-[var(--gg-focus-ring)]'
                    : 'bg-transparent border-dashed border-[var(--gg-divider)] opacity-75 hover:opacity-100'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold">
                    {masked ? (
                      <HelpCircle size={15} className="text-[var(--gg-text-secondary)]" />
                    ) : unlocked ? (
                      <Award size={15} className="text-[var(--gg-focus-ring)]" />
                    ) : (
                      <Lock size={14} className="text-[var(--gg-text-secondary)]" />
                    )}
                    <span className="text-[var(--gg-text-primary)]">
                      {masked ? 'Hidden badge' : def.title}
                    </span>
                  </span>
                  <span className="text-[11px] font-mono text-[var(--gg-text-secondary)]">
                    +{def.points}
                  </span>
                </div>
                <p className="text-xs text-[var(--gg-text-secondary)] mt-1.5 line-clamp-2">
                  {masked ? 'Unlock this secret milestone to reveal its details.' : def.desc}
                </p>
                {award && (
                  <div className="text-[10px] text-[var(--gg-focus-ring)] mt-2">
                    Unlocked {new Date(award.awardedAt).toLocaleDateString()}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </section>

      {selectedBadge && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm"
          onClick={() => setSelectedBadge(null)}
          role="dialog"
          aria-modal="true"
          aria-label="Badge details"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-[var(--gg-r-panel)] border border-[var(--gg-divider)] p-5 space-y-3"
            style={{ backgroundColor: 'var(--gg-bg-panel)' }}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-[var(--gg-text-primary)]">
                {selectedBadge.hidden && !selectedAward ? 'Hidden badge' : selectedBadge.title}
              </h3>
              <button
                type="button"
                onClick={() => setSelectedBadge(null)}
                aria-label="Close badge details"
                className="p-1.5 rounded-[var(--gg-r-control)] bg-white/10"
              >
                <X size={15} />
              </button>
            </div>
            <p className="text-xs text-[var(--gg-text-broadcast)]">
              {selectedBadge.hidden && !selectedAward
                ? 'This secret badge stays hidden until unlocked during your adventures.'
                : selectedBadge.desc}
            </p>
            <div className="text-xs text-[var(--gg-text-secondary)] space-y-1 pt-2 border-t border-[var(--gg-divider)]">
              <div>Reward: +{selectedBadge.points} JS</div>
              {selectedAward ? (
                <div className="text-[var(--gg-focus-ring)]">
                  Unlocked on {new Date(selectedAward.awardedAt).toLocaleString()}
                  {selectedAward.reason ? ` · ${selectedAward.reason}` : ''}
                </div>
              ) : (
                <div>Status: Locked — keep logging sessions, routes, and notes to unlock.</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
