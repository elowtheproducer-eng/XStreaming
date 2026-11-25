import React, { useMemo, useState } from 'react';
import { useJournal } from '../state/JournalStore';
import { searchAirports } from '../logic/planParser';
import { formatMsToTime } from '../logic/genreResolver';
import { buildPictureSearchIndex, searchPictures } from '../logic/pictureSearch';
import { listSummarySubjects } from '../logic/summaryEngine';
import { ownerMatchesTagFilter } from '../logic/tags';
import { resolveAlias } from '../logic/registries';
import { MediaImage } from '../components/MediaImage';
import { MediaViewer } from '../components/MediaViewer';
import { Search as SearchIcon } from 'lucide-react';

export function SearchPage({ initialQuery = '' }: { initialQuery?: string }) {
  const { db, navigate } = useJournal();
  const [query, setQuery] = useState(initialQuery);
  const [viewerSha, setViewerSha] = useState<string | null>(null);

  const parsed = useMemo(() => {
    const tokens = query.trim().split(/\s+/).filter(Boolean);
    const filters: Record<string, string> = {};
    const terms: string[] = [];

    for (const tok of tokens) {
      const m = /^([a-zA-Z]+):(.*)$/.exec(tok);
      if (m) filters[m[1].toLowerCase()] = m[2].toLowerCase();
      else terms.push(tok.toLowerCase());
    }
    return { filters, terms };
  }, [query]);

  const games = useMemo(() => {
    return db.games.filter((g) => {
      if (g.deletedAt) return false;
      if (parsed.filters.status && g.status.toLowerCase() !== parsed.filters.status) return false;
      if (parsed.filters.genre && !g.genreIds.includes(parsed.filters.genre)) return false;
      if (parsed.filters.game && !g.name.toLowerCase().includes(parsed.filters.game)) return false;
      if (parsed.filters.tag && !ownerMatchesTagFilter(db, 'GAME', g.id, parsed.filters.tag)) return false;
      return parsed.terms.every(
        (t) =>
          g.name.toLowerCase().includes(t) ||
          g.genreIds.some((gid) => gid.includes(t)) ||
          (g.platform ?? '').toLowerCase().includes(t)
      );
    });
  }, [db, parsed]);

  const legs = useMemo(() => {
    const aircraftAliases = db.settings.aircraftAliases;
    const simAliases = db.settings.simAliases;
    return db.legs.filter((l) => {
      if (l.deletedAt) return false;
      if (parsed.filters.status && l.status.toLowerCase() !== parsed.filters.status) return false;
      if (parsed.filters.from && !(l.originIcao ?? '').toLowerCase().includes(parsed.filters.from)) {
        return false;
      }
      if (parsed.filters.to && !(l.destIcao ?? '').toLowerCase().includes(parsed.filters.to)) {
        return false;
      }
      if (parsed.filters.tag && !ownerMatchesTagFilter(db, 'LEG', l.id, parsed.filters.tag)) {
        return false;
      }
      if (parsed.filters.game) {
        const g = db.games.find((gm) => gm.id === l.gameId);
        if (!g || !g.name.toLowerCase().includes(parsed.filters.game)) return false;
      }
      const canonicalAc = resolveAlias(l.aircraftName, aircraftAliases).toLowerCase();
      const canonicalSim = resolveAlias(l.simName, simAliases).toLowerCase();
      return parsed.terms.every((t) => {
        const termAc = resolveAlias(t, aircraftAliases).toLowerCase();
        const termSim = resolveAlias(t, simAliases).toLowerCase();
        return (
          (l.title ?? '').toLowerCase().includes(t) ||
          (l.originIcao ?? '').toLowerCase().includes(t) ||
          (l.destIcao ?? '').toLowerCase().includes(t) ||
          (l.aircraftName ?? '').toLowerCase().includes(t) ||
          (canonicalAc && (canonicalAc.includes(t) || (termAc && canonicalAc.includes(termAc)))) ||
          (canonicalSim && (canonicalSim.includes(t) || (termSim && canonicalSim.includes(termSim)))) ||
          (l.summary ?? '').toLowerCase().includes(t)
        );
      });
    });
  }, [db, parsed]);

  const tours = useMemo(() => {
    return db.tours.filter((t) => {
      if (t.deletedAt) return false;
      if (parsed.filters.status && t.status.toLowerCase() !== parsed.filters.status) return false;
      if (parsed.filters.tag && !ownerMatchesTagFilter(db, 'TOUR', t.id, parsed.filters.tag)) return false;
      if (parsed.filters.game) {
        const g = db.games.find((gm) => gm.id === t.gameId);
        if (!g || !g.name.toLowerCase().includes(parsed.filters.game)) return false;
      }
      return parsed.terms.every(
        (term) =>
          t.name.toLowerCase().includes(term) ||
          (t.description ?? '').toLowerCase().includes(term)
      );
    });
  }, [db, parsed]);

  const records = useMemo(() => {
    return db.records.filter((r) =>
      parsed.terms.every((t) => r.subject.toLowerCase().includes(t))
    );
  }, [db.records, parsed.terms]);

  const notes = useMemo(() => {
    return db.entries.filter((e) => {
      if (e.deletedAt) return false;
      if (parsed.filters.tag && !ownerMatchesTagFilter(db, 'ENTRY', e.id, parsed.filters.tag)) return false;
      return parsed.terms.every(
        (t) =>
          e.body.toLowerCase().includes(t) || (e.title ?? '').toLowerCase().includes(t)
      );
    });
  }, [db, parsed]);

  const airports = useMemo(
    () => (parsed.terms.length > 0 ? searchAirports(parsed.terms[0], 6) : []),
    [parsed.terms]
  );

  const pictureIndex = useMemo(() => buildPictureSearchIndex(db), [db]);
  const pictureResults = useMemo(
    () => (query.trim() ? searchPictures(pictureIndex, query, { limit: 24 }) : []),
    [pictureIndex, query]
  );

  const summaryRows = useMemo(() => listSummarySubjects(db), [db]);
  const summaryResults = useMemo(() => {
    if (!query.trim()) return [];
    const tagFilter = parsed.filters.tag;
    const gameFilter = parsed.filters.game;
    return summaryRows.filter((row) => {
      const ins = row.insight;
      const take = row.keepersTake;
      if (!ins?.text && !take?.text) return false;
      if (gameFilter) {
        const g = row.gameId ? db.games.find((gm) => gm.id === row.gameId) : undefined;
        if (!g || !g.name.toLowerCase().includes(gameFilter)) return false;
      }
      const tags = [...(ins?.tags ?? []), ...(take?.tags ?? [])];
      const matchesOwnerTag =
        row.subjectType !== 'YEAR' && row.subjectType !== 'LIFETIME'
          ? ownerMatchesTagFilter(db, row.subjectType as any, row.subjectId, tagFilter)
          : false;
      if (tagFilter && !tags.some((t) => t.toLowerCase().includes(tagFilter)) && !matchesOwnerTag) return false;
      const ent = ins?.entities;
      const entFlat = ent
        ? [
            ...(ent.places ?? []),
            ...(ent.vehicles ?? []),
            ...(ent.people ?? []),
            ...(ent.feelings ?? []),
            ...(ent.events ?? []),
            ...(ent.preferences ?? []),
          ]
        : [];
      const hay = [
        row.label,
        row.subtitle,
        ins?.text ?? '',
        take?.text ?? '',
        ...tags,
        ...entFlat,
      ]
        .join(' ')
        .toLowerCase();
      return parsed.terms.every((t) => hay.includes(t));
    });
  }, [summaryRows, query, parsed, db.games]);

  return (
    <div className="space-y-6 pb-24">
      <div className="space-y-2">
        <h1 className="text-2xl font-light text-[var(--gg-text-primary)] tracking-tight">
          Search Journal
        </h1>
        <div className="relative">
          <SearchIcon
            size={18}
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--gg-text-secondary)]"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
            placeholder="Search games, flights, notes, tracks, ICAO... Try tokens: game:forza status:paused genre:racing from:egll"
            className="w-full pl-11 pr-4 py-3 rounded-[var(--gg-r-control)] text-sm bg-[var(--gg-bg-raised)] border border-[var(--gg-focus-ring)]/60 text-[var(--gg-text-primary)]"
          />
        </div>
        <div className="flex flex-wrap gap-1.5 text-[11px]">
          {['genre:racing', 'status:paused', 'from:egll', 'tag:sunset', 'source:xbox', 'text:'].map((hint) => (
            <button
              key={hint}
              type="button"
              onClick={() => setQuery(hint)}
              className="px-2.5 py-1 rounded-[var(--gg-r-control)] bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)] hover:text-[var(--gg-text-primary)] font-mono"
            >
              {hint}
            </button>
          ))}
        </div>
      </div>

      {pictureResults.length > 0 && (
        <section className="space-y-2.5">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
            Pictures ({pictureResults.length})
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {pictureResults.map(({ entry, matchedTerms, snippet }) => {
              const highlightTerms = matchedTerms.filter((t) => t.length >= 2);
              const escaped = highlightTerms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
              const parts = escaped.length > 0
                ? snippet.split(new RegExp(`(${escaped.join('|')})`, 'gi'))
                : [snippet];
              return (
                <button
                  key={entry.item.sha256}
                  type="button"
                  onClick={() => setViewerSha(entry.item.sha256)}
                  className="p-2.5 rounded-[var(--gg-r-tile)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] hover:border-[var(--gg-focus-ring)] xbox-ring text-left flex gap-3 items-center"
                >
                  <div className="w-28 aspect-video rounded-[var(--gg-r-control)] overflow-hidden bg-black shrink-0">
                    <MediaImage sha={entry.item.sha256} kind="thumb" alt={entry.item.origName} className="w-full h-full object-cover" />
                  </div>
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="text-xs font-semibold text-[var(--gg-text-primary)] truncate">
                      {entry.gameName || entry.item.origName}
                    </div>
                    <div className="text-[11px] text-[var(--gg-text-secondary)] line-clamp-2">
                      {parts.map((part, i) => {
                        const isMatch = highlightTerms.some((t) => part.toLowerCase() === t.toLowerCase());
                        return isMatch ? (
                          <mark key={i} className="bg-[var(--gg-accent)]/40 text-white px-0.5 rounded-[var(--gg-r-badge)]">
                            {part}
                          </mark>
                        ) : (
                          <React.Fragment key={i}>{part}</React.Fragment>
                        );
                      })}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {summaryResults.length > 0 && (
        <section className="space-y-2.5">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
            Summaries &amp; Entities ({summaryResults.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {summaryResults.slice(0, 12).map((row) => (
              <button
                key={row.key}
                type="button"
                onClick={() => {
                  if (row.subjectType === 'LEG') navigate({ page: 'leg', legId: row.subjectId });
                  else if (row.subjectType === 'TOUR') navigate({ page: 'tour', tourId: row.subjectId });
                  else if (row.subjectType === 'GAME') navigate({ page: 'game', gameId: row.subjectId });
                  else navigate({ page: 'keeper', view: 'index', indexSubtab: 'summaries' });
                }}
                className="p-3 rounded-[var(--gg-r-tile)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] hover:border-[var(--gg-focus-ring)] xbox-ring text-left space-y-1"
              >
                <div className="text-xs font-semibold text-[var(--gg-text-primary)]">{row.label}</div>
                <div className="text-[11px] text-[var(--gg-focus-ring)]">{row.subtitle}</div>
                <div className="text-xs text-[var(--gg-text-secondary)] line-clamp-2">
                  {row.insight?.text || row.keepersTake?.text}
                </div>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <section className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
            Games ({games.length})
          </h2>
          {games.map((g) => (
            <button
              key={g.id}
              type="button"
              onClick={() => navigate({ page: 'game', gameId: g.id })}
              className="w-full p-3 rounded-[var(--gg-r-tile)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] hover:border-[var(--gg-focus-ring)] text-left"
            >
              <div className="text-sm font-semibold">{g.name}</div>
              <div className="text-xs text-[var(--gg-text-secondary)]">
                {g.platform} · {g.status} · {g.genreIds.join(', ') || g.packId}
              </div>
            </button>
          ))}
        </section>

        <section className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
            Legs &amp; Sessions ({legs.length})
          </h2>
          {legs.slice(0, 8).map((l) => (
            <button
              key={l.id}
              type="button"
              onClick={() => navigate({ page: 'leg', legId: l.id })}
              className="w-full p-3 rounded-[var(--gg-r-tile)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] hover:border-[var(--gg-focus-ring)] text-left"
            >
              <div className="text-sm font-semibold">
                {l.title || `${l.originIcao ?? ''} → ${l.destIcao ?? ''}`}
              </div>
              <div className="text-xs text-[var(--gg-text-secondary)] truncate">
                {l.flownOn} · {l.status} · {l.summary}
              </div>
            </button>
          ))}
        </section>

        {records.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
              Records ({records.length})
            </h2>
            {records.map((r) => {
              const def = db.recordDefs.find((d) => d.id === r.defId);
              return (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => navigate({ page: 'game', gameId: r.gameId, tab: 'records' })}
                  className="w-full p-3 rounded-[var(--gg-r-tile)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] text-left flex justify-between"
                >
                  <span className="text-sm font-semibold">{r.subject}</span>
                  <span className="font-mono text-xs text-[#9BF00B]">
                    {def?.kind === 'TIME' ? formatMsToTime(r.valueNum) : r.valueNum}
                  </span>
                </button>
              );
            })}
          </section>
        )}

        {tours.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
              Tours &amp; Campaigns ({tours.length})
            </h2>
            {tours.slice(0, 6).map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => navigate({ page: 'tour', tourId: t.id })}
                className="w-full p-3 rounded-[var(--gg-r-control)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] hover:border-[var(--gg-focus-ring)] text-left"
              >
                <div className="text-sm font-semibold">{t.name}</div>
                <div className="text-xs text-[var(--gg-text-secondary)]">{t.status.replace('_', ' ')}</div>
              </button>
            ))}
          </section>
        )}

        {notes.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
              Notes ({notes.length})
            </h2>
            {notes.slice(0, 6).map((n) => (
              <div key={n.id} className="p-3 rounded-[var(--gg-r-tile)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)]">
                {n.title && <div className="text-xs font-semibold">{n.title}</div>}
                <div className="text-xs text-[var(--gg-text-secondary)] line-clamp-2">{n.body}</div>
              </div>
            ))}
          </section>
        )}

        {airports.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--gg-text-secondary)]">
              Airports ({airports.length})
            </h2>
            {airports.map((ap) => (
              <button
                key={ap.icao}
                type="button"
                onClick={() => navigate({ page: 'atlas' })}
                className="w-full p-3 rounded-[var(--gg-r-tile)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] text-left text-xs"
              >
                <strong className="font-mono text-[var(--gg-focus-ring)]">{ap.icao}</strong> · {ap.name} ({ap.city}, {ap.country})
              </button>
            ))}
          </section>
        )}
      </div>

      {viewerSha && (
        <MediaViewer
          shas={pictureResults.map((r) => r.entry.item.sha256)}
          initialSha={viewerSha}
          onClose={() => setViewerSha(null)}
        />
      )}
    </div>
  );
}
