import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useJournal } from '../state/JournalStore';
import { MediaImage } from './MediaImage';
import { MediaViewer } from './MediaViewer';
import { KeeperSummariesTab } from './KeeperSummariesTab';
import type { SummarySubjectType } from '../logic/summaryEngine';
import {
  clearPromptLog,
  estimateQueueRun,
  getPromptLog,
  insightEngine,
  resolveRole,
  useInsightEngine,
  type PromptLogEntry,
} from '../logic/insightEngine';
import { getApiKey } from '../logic/keys';
import {
  Ban,
  Check,
  CheckSquare,
  Eye,
  FileText,
  Lock,
  Pause,
  Play,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';

type IndexFilterStatus =
  | 'ALL'
  | 'NOT_INDEXED'
  | 'DESCRIBED'
  | 'FAILED'
  | 'BLOCKED'
  | 'EDITED'
  | 'EXCLUDED';

interface FilterMemory {
  status: IndexFilterStatus;
  source: 'ALL' | 'DEVICE' | 'XBOX';
  gameId: string;
  dateFrom: string;
  dateTo: string;
}

const DEFAULT_FILTER: FilterMemory = {
  status: 'ALL',
  source: 'ALL',
  gameId: 'ALL',
  dateFrom: '',
  dateTo: '',
};

let lastSessionFilter: FilterMemory = { ...DEFAULT_FILTER };

interface ConfirmRunState {
  title: string;
  shas: string[];
  forceReindex: boolean;
  allowSelectionShortcut?: boolean;
}

export function KeeperIndexView({
  initialSubtab = 'pictures',
  onOpenSummaries,
}: {
  initialSubtab?: 'pictures' | 'summaries';
  onOpenSummaries?: (subjectFilter?: string) => void;
}) {
  const { db, updateDb, navigate, requestAiConsent, pushToast, playSound } = useJournal();
  const engine = useInsightEngine();
  const [subtab, setSubtab] = useState<'pictures' | 'summaries'>(initialSubtab);
  const [summaryTypeFilter, setSummaryTypeFilter] = useState<'ALL' | SummarySubjectType>('ALL');

  const [filter, setFilter] = useState<FilterMemory>(() => {
    try {
      const saved = sessionStorage.getItem('gg_index_filter_v1');
      if (saved) return { ...DEFAULT_FILTER, ...JSON.parse(saved) };
    } catch {
      /* ignore */
    }
    return lastSessionFilter;
  });

  useEffect(() => {
    lastSessionFilter = filter;
    try {
      sessionStorage.setItem('gg_index_filter_v1', JSON.stringify(filter));
    } catch {
      /* ignore */
    }
  }, [filter]);

  const [selectMode, setSelectMode] = useState(false);
  const [selectedShas, setSelectedShas] = useState<string[]>([]);
  const [confirmRun, setConfirmRun] = useState<ConfirmRunState | null>(null);
  const [viewerSha, setViewerSha] = useState<string | null>(null);
  const [showLogModal, setShowLogModal] = useState(false);
  const [promptLog, setPromptLog] = useState<PromptLogEntry[]>([]);
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const gameMap = useMemo(() => new Map(db.games.map((g) => [g.id, g])), [db.games]);
  const legGameMap = useMemo(() => new Map(db.legs.map((l) => [l.id, l.gameId])), [db.legs]);

  const activeDescribeBySha = useMemo(() => {
    const map = new Map<string, (typeof db.insights)[number]>();
    for (const ins of db.insights) {
      if (ins.subjectType !== 'MEDIA' || ins.kind !== 'DESCRIBE' || ins.stale || ins.pendingSuggestion) continue;
      const prev = map.get(ins.subjectId);
      if (!prev || ins.userEdited || ins.createdAt >= prev.createdAt) {
        map.set(ins.subjectId, ins);
      }
    }
    return map;
  }, [db.insights]);

  const queuedIds = useMemo(
    () => insightEngine.getQueuedIds(),
    [engine.queued, engine.active, engine.done, engine.failed, engine.blocked]
  );

  const gameBySha = useMemo(() => {
    const map = new Map<string, { gameId?: string; gameName: string }>();
    for (const ml of db.mediaLinks) {
      if (ml.deletedAt || map.has(ml.mediaSha)) continue;
      if (ml.ownerType === 'GAME') {
        const g = gameMap.get(ml.ownerId);
        if (g) map.set(ml.mediaSha, { gameId: g.id, gameName: g.name });
      } else if (ml.ownerType === 'LEG') {
        const gid = legGameMap.get(ml.ownerId);
        const g = gid ? gameMap.get(gid) : undefined;
        if (g) map.set(ml.mediaSha, { gameId: g.id, gameName: g.name });
      }
    }
    for (const g of db.games) {
      for (const sha of [g.coverMediaSha, g.heroMediaSha, g.iconMediaSha]) {
        if (sha && !map.has(sha)) map.set(sha, { gameId: g.id, gameName: g.name });
      }
    }
    return map;
  }, [db.mediaLinks, db.games, gameMap, legGameMap]);

  // Coverage stats (excluded pictures are never counted)
  const coverage = useMemo(() => {
    let eligible = 0;
    let described = 0;
    let excluded = 0;
    let failedCount = 0;
    for (const m of db.media) {
      if (m.aiIndex === 'EXCLUDED') {
        excluded++;
        continue;
      }
      eligible++;
      const ins = activeDescribeBySha.get(m.sha256);
      if (ins) {
        const st = ins.status ?? 'DONE';
        if (st === 'DONE') described++;
        else if (st === 'FAILED') failedCount++;
      }
    }
    const pct = eligible > 0 ? Math.round((described / eligible) * 100) : 0;
    return { eligible, described, excluded, failedCount, pct };
  }, [db.media, activeDescribeBySha]);

  // Text subject summary stats line (live from db.insights)
  const textCoverage = useMemo(() => {
    const activeEntries = db.entries.filter((e) => !e.deletedAt);
    const activeLegs = db.legs.filter((l) => !l.deletedAt);
    const activeTours = db.tours.filter((t) => !t.deletedAt);
    const activeGames = db.games.filter((g) => !g.deletedAt);
    const doneSet = (st: string) =>
      new Set(
        db.insights
          .filter((i) => i.subjectType === st && i.kind === 'SUMMARY' && !i.stale && (i.status ?? 'DONE') === 'DONE')
          .map((i) => i.subjectId)
      );
    const pct = (done: number, total: number) => (total === 0 ? '—' : `${Math.round((done / total) * 100)}%`);
    const entryDone = doneSet('ENTRY').size;
    const legDone = doneSet('LEG').size;
    const tourDone = doneSet('TOUR').size;
    const gameDone = doneSet('GAME').size;
    const hasYear = doneSet('YEAR').size > 0;
    const hasLifetime = doneSet('LIFETIME').size > 0;
    return {
      notes: pct(Math.min(entryDone, activeEntries.length), activeEntries.length),
      legs: pct(Math.min(legDone, activeLegs.length), activeLegs.length),
      tours: pct(Math.min(tourDone, activeTours.length), activeTours.length),
      games: pct(Math.min(gameDone, activeGames.length), activeGames.length),
      year: hasYear ? '✓' : '—',
      lifetime: hasLifetime ? '✓' : '—',
    };
  }, [db.entries, db.legs, db.tours, db.games, db.insights]);

  const enrichedMedia = useMemo(() => {
    return [...db.media]
      .sort((a, b) => (b.takenAt ?? b.createdAt) - (a.takenAt ?? a.createdAt))
      .map((item) => {
        const ins = activeDescribeBySha.get(item.sha256);
        const linkMeta = gameBySha.get(item.sha256);
        const gameName = item.xbox?.titleName || linkMeta?.gameName || 'Unlinked';
        const gameId = linkMeta?.gameId;
        const ts = item.takenAt ?? item.xbox?.capturedAt ?? item.createdAt;
        const dateIso = new Date(ts).toISOString().slice(0, 10);
        const isExcluded = item.aiIndex === 'EXCLUDED';
        const isQueued = queuedIds.has(item.sha256);

        let badge: { label: string; cls: string } = { label: 'Not indexed', cls: 'bg-black/75 text-white/80' };
        if (isExcluded) badge = { label: 'Excluded', cls: 'bg-zinc-800/90 text-zinc-300' };
        else if (isQueued) badge = { label: 'Queued', cls: 'bg-amber-600/90 text-white' };
        else if (ins?.userEdited) badge = { label: 'Edited', cls: 'bg-sky-700/90 text-white' };
        else if (ins?.status === 'FAILED') badge = { label: 'Failed', cls: 'bg-red-700/90 text-white' };
        else if (ins?.status === 'BLOCKED') badge = { label: 'Blocked', cls: 'bg-orange-700/90 text-white' };
        else if (ins && (ins.status ?? 'DONE') === 'DONE') badge = { label: 'Described', cls: 'bg-emerald-700/90 text-white' };

        return { item, ins, gameId, gameName, dateIso, isExcluded, isQueued, badge };
      });
  }, [db.media, activeDescribeBySha, gameBySha, queuedIds]);

  const filteredMedia = useMemo(() => {
    return enrichedMedia.filter((row) => {
      if (filter.status === 'EXCLUDED') {
        if (!row.isExcluded) return false;
      } else {
        if (row.isExcluded) return false;
        if (filter.status === 'NOT_INDEXED' && row.ins) return false;
        if (filter.status === 'DESCRIBED' && (!row.ins || (row.ins.status ?? 'DONE') !== 'DONE')) return false;
        if (filter.status === 'FAILED' && row.ins?.status !== 'FAILED') return false;
        if (filter.status === 'BLOCKED' && row.ins?.status !== 'BLOCKED') return false;
        if (filter.status === 'EDITED' && !row.ins?.userEdited) return false;
      }
      if (filter.source === 'XBOX' && row.item.source !== 'XBOX') return false;
      if (filter.source === 'DEVICE' && row.item.source === 'XBOX') return false;
      if (filter.gameId !== 'ALL' && row.gameId !== filter.gameId) return false;
      if (filter.dateFrom && row.dateIso < filter.dateFrom) return false;
      if (filter.dateTo && row.dateIso > filter.dateTo) return false;
      return true;
    });
  }, [enrichedMedia, filter]);

  const resolvedVision = resolveRole(db.settings, 'vision');
  const needsRemoteConsent =
    db.settings.aiSendImages && resolvedVision.profile?.capabilities?.vision !== false;
  const missingConnection = needsRemoteConsent && !resolvedVision.profile;
  const missingKey =
    needsRemoteConsent &&
    resolvedVision.profile &&
    resolvedVision.profile.authStyle !== 'none' &&
    !getApiKey(resolvedVision.profile.id);
  const missingConsent = needsRemoteConsent && !db.settings.aiConsentAt;

  const openEstimateConfirm = (opts: ConfirmRunState) => {
    if (opts.shas.length === 0) {
      pushToast({ title: 'No matching pictures to queue' });
      return;
    }
    setConfirmRun(opts);
  };

  const executeConfirmRun = async () => {
    if (!confirmRun) return;
    const ok = await requestAiConsent('index these pictures', false);
    if (!ok) {
      setConfirmRun(null);
      return;
    }
    insightEngine.enqueueMedia(confirmRun.shas, {
      priority: 100,
      forceReindex: confirmRun.forceReindex,
    });
    pushToast({
      title: `Queued ${confirmRun.shas.length} picture(s)`,
      subtitle: confirmRun.forceReindex ? 'Re-describing with priority' : 'Indexing in background while app stays open',
    });
    setConfirmRun(null);
    setSelectedShas([]);
    setSelectMode(false);
    playSound('save');
  };

  const toggleSelectSha = (sha: string) => {
    setSelectedShas((prev) =>
      prev.includes(sha) ? prev.filter((s) => s !== sha) : [...prev, sha]
    );
  };

  const setExclusionForShas = (shas: string[], exclude: boolean) => {
    const set = new Set(shas);
    updateDb((prev) => ({
      ...prev,
      media: prev.media.map((m) =>
        set.has(m.sha256) ? { ...m, aiIndex: exclude ? 'EXCLUDED' : undefined } : m
      ),
    }), exclude ? 'ExcludePictures' : 'IncludePictures');
    pushToast({
      title: exclude ? `Excluded ${shas.length} picture(s)` : `Included ${shas.length} picture(s)`,
    });
    setSelectedShas([]);
    setSelectMode(false);
  };

  const openPromptLog = async () => {
    setPromptLog(await getPromptLog());
    setShowLogModal(true);
  };

  const etaRemainingText = useMemo(() => {
    if (!engine.avgMsPerItem || engine.queued === 0) return null;
    const secs = Math.max(1, Math.round((engine.queued * engine.avgMsPerItem) / 1000));
    if (secs < 60) return `${secs}s left`;
    return `~${Math.round(secs / 60)}m left`;
  }, [engine.avgMsPerItem, engine.queued]);

  const confirmEstimate = confirmRun
    ? estimateQueueRun(confirmRun.shas.length, db.settings.aiMaxImagesPerRequest, engine.avgMsPerItem)
    : null;

  return (
    <div className="space-y-4">
      {/* Index Subtabs: Pictures | Summaries */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex rounded-xl p-1 bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]">
          <button
            type="button"
            onClick={() => setSubtab('pictures')}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold ${
              subtab === 'pictures' ? 'bg-[var(--gg-accent)] text-white' : 'text-[var(--gg-text-secondary)]'
            }`}
          >
            Pictures ({coverage.described}/{coverage.eligible})
          </button>
          <button
            type="button"
            onClick={() => setSubtab('summaries')}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold ${
              subtab === 'summaries' ? 'bg-[var(--gg-accent)] text-white' : 'text-[var(--gg-text-secondary)]'
            }`}
          >
            Summaries
          </button>
        </div>

        {/* Compact text summaries coverage row */}
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--gg-text-secondary)]">
          {(
            [
              ['Notes', textCoverage.notes, 'ENTRY'],
              ['Legs', textCoverage.legs, 'LEG'],
              ['Tours', textCoverage.tours, 'TOUR'],
              ['Games', textCoverage.games, 'GAME'],
              ['Year', textCoverage.year, 'YEAR'],
              ['Lifetime', textCoverage.lifetime, 'LIFETIME'],
            ] as const
          ).map(([label, val, subj], idx) => (
            <React.Fragment key={label}>
              {idx > 0 && <span className="opacity-40">·</span>}
              <button
                type="button"
                onClick={() => {
                  setSummaryTypeFilter(subj);
                  setSubtab('summaries');
                  onOpenSummaries?.(subj);
                }}
                className="hover:text-[var(--gg-text-primary)] hover:underline tabular-nums"
              >
                {label} {val}
              </button>
            </React.Fragment>
          ))}
        </div>
      </div>

      {subtab === 'summaries' ? (
        <KeeperSummariesTab
          subjectTypeFilter={summaryTypeFilter}
          onChangeSubjectTypeFilter={setSummaryTypeFilter}
          onOpenLog={openPromptLog}
        />
      ) : (
      <>
      {/* Header: Coverage & Engine Status */}
      <div className="p-4 rounded-2xl bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-sm font-semibold text-[var(--gg-text-primary)] tabular-nums">
              Pictures {coverage.described} / {coverage.eligible} described
            </div>
            {coverage.excluded > 0 && (
              <button
                type="button"
                onClick={() => setFilter((f) => ({ ...f, status: f.status === 'EXCLUDED' ? 'ALL' : 'EXCLUDED' }))}
                className="text-[11px] text-[var(--gg-text-tertiary)] hover:underline"
              >
                {coverage.excluded} excluded
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                const shas = filteredMedia
                  .filter((r) => !r.isExcluded && !r.ins)
                  .map((r) => r.item.sha256);
                openEstimateConfirm({
                  title: 'Index not-yet-described pictures',
                  shas,
                  forceReindex: false,
                  allowSelectionShortcut: true,
                });
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-[var(--gg-accent)] text-white"
            >
              <Sparkles size={13} />
              <span>Index now</span>
            </button>
            {coverage.failedCount > 0 && (
              <button
                type="button"
                onClick={() => {
                  const shas = enrichedMedia
                    .filter((r) => !r.isExcluded && (r.ins?.status === 'FAILED'))
                    .map((r) => r.item.sha256);
                  openEstimateConfirm({ title: 'Retry failed pictures', shas, forceReindex: true });
                }}
                className="px-3 py-1.5 rounded-xl text-xs font-semibold bg-red-900/50 text-red-100"
              >
                Retry failed ({coverage.failedCount})
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                const shas = filteredMedia
                  .filter((r) => !r.isExcluded && !r.ins?.userEdited)
                  .map((r) => r.item.sha256);
                openEstimateConfirm({
                  title: 'Re-describe pictures (skips edited)',
                  shas,
                  forceReindex: true,
                });
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs bg-[var(--gg-surface-control)]"
            >
              <RefreshCw size={13} />
              <span>Re-describe all</span>
            </button>
          </div>
        </div>

        <div className="h-2 rounded-full bg-white/10 overflow-hidden">
          <div
            className="h-full bg-[var(--gg-accent)] transition-all"
            style={{ width: `${coverage.pct}%` }}
          />
        </div>

        {/* Live Engine Status */}
        {(engine.queued > 0 || engine.active > 0 || engine.paused) && (
          <div className="p-3 rounded-xl bg-black/30 border border-[var(--gg-divider)] flex flex-wrap items-center justify-between gap-2 text-xs">
            <div className="space-y-0.5">
              <div className="font-semibold flex items-center gap-2">
                <span>
                  {engine.paused
                    ? `Paused: ${engine.pauseReason || 'Waiting'}`
                    : engine.rateLimited
                      ? 'Rate limited, retrying…'
                      : engine.running
                        ? `Indexing${engine.currentLabel ? `: ${engine.currentLabel}` : '…'}`
                        : 'Queue idle'}
                </span>
                <span className="text-[11px] text-[var(--gg-text-secondary)] tabular-nums">
                  {engine.queued} queued · {engine.active} active
                  {engine.avgMsPerItem ? ` · ${(engine.avgMsPerItem / 1000).toFixed(1)}s/pic` : ''}
                  {etaRemainingText ? ` · ${etaRemainingText}` : ''}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {engine.paused ? (
                <button
                  type="button"
                  onClick={() => insightEngine.resume()}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-xl bg-[var(--gg-accent)] text-white font-semibold"
                >
                  <Play size={12} /> Resume
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => insightEngine.pause('Paused by you')}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-xl bg-[var(--gg-surface-control)]"
                >
                  <Pause size={12} /> Pause
                </button>
              )}
              <button
                type="button"
                onClick={() => insightEngine.cancelAll()}
                className="px-2.5 py-1 rounded-xl bg-white/10"
              >
                Cancel queue
              </button>
            </div>
          </div>
        )}

        {/* Setup / Consent Fix Card */}
        {(missingConnection || missingKey || missingConsent) && (
          <div className="p-3 rounded-xl bg-[var(--gg-accent-wash)] border border-[var(--gg-focus-ring)] flex flex-wrap items-center justify-between gap-2 text-xs">
            <div className="flex items-center gap-2">
              <ShieldAlert size={16} className="text-[var(--gg-focus-ring)] shrink-0" />
              <span>
                {missingConnection
                  ? 'Add an AI connection to describe pictures automatically.'
                  : missingKey
                    ? `Add your API key for ${resolvedVision.profile?.name} in Settings.`
                    : 'Confirm sending small copies of pictures to your AI provider before indexing.'}
              </span>
            </div>
            <div className="flex gap-2">
              {(missingConnection || missingKey) && (
                <button
                  type="button"
                  onClick={() => navigate({ page: 'settings', category: 'keeper' })}
                  className="px-3 py-1.5 rounded-xl bg-[var(--gg-accent)] text-white font-semibold"
                >
                  Add a connection
                </button>
              )}
              {!missingConnection && !missingKey && missingConsent && (
                <button
                  type="button"
                  onClick={() => void requestAiConsent('describe your pictures', false)}
                  className="px-3 py-1.5 rounded-xl bg-[var(--gg-accent)] text-white font-semibold"
                >
                  Confirm sending pictures
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Filters & Selection Toggle */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {(
            [
              ['ALL', 'All'],
              ['NOT_INDEXED', 'Not indexed'],
              ['DESCRIBED', 'Described'],
              ['FAILED', 'Failed'],
              ['BLOCKED', 'Blocked'],
              ['EDITED', 'Edited by me'],
              ['EXCLUDED', 'Excluded'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setFilter((f) => ({ ...f, status: id }))}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold ${
                filter.status === id
                  ? 'bg-[var(--gg-accent)] text-white'
                  : 'bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)]'
              }`}
            >
              {label}
            </button>
          ))}

          <button
            type="button"
            onClick={() => {
              setSelectMode((v) => !v);
              if (selectMode) setSelectedShas([]);
            }}
            className={`ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold ${
              selectMode ? 'bg-[var(--gg-accent)] text-white' : 'bg-[var(--gg-surface-control)]'
            }`}
          >
            <CheckSquare size={13} />
            <span>{selectMode ? 'Done selecting' : 'Select'}</span>
          </button>

          {db.settings.aiLogPrompts && (
            <button
              type="button"
              onClick={openPromptLog}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs bg-[var(--gg-surface-control)]"
            >
              <FileText size={13} />
              <span>View log</span>
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select
            value={filter.source}
            onChange={(e) => setFilter((f) => ({ ...f, source: e.target.value as FilterMemory['source'] }))}
            aria-label="Filter by picture source"
            className="px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
          >
            <option value="ALL">All sources</option>
            <option value="DEVICE">Device</option>
            <option value="XBOX">Xbox</option>
          </select>

          <select
            value={filter.gameId}
            onChange={(e) => setFilter((f) => ({ ...f, gameId: e.target.value }))}
            aria-label="Filter by game"
            className="px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
          >
            <option value="ALL">All games</option>
            {db.games.filter((g) => !g.deletedAt).map((g) => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </select>

          <input
            type="date"
            value={filter.dateFrom}
            onChange={(e) => setFilter((f) => ({ ...f, dateFrom: e.target.value }))}
            aria-label="From date"
            className="px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
          />
          <input
            type="date"
            value={filter.dateTo}
            onChange={(e) => setFilter((f) => ({ ...f, dateTo: e.target.value }))}
            aria-label="To date"
            className="px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
          />
        </div>
      </div>

      {/* Picture Grid (Landscape 16:9 rounded tiles with content-visibility: auto) */}
      {filteredMedia.length === 0 ? (
        <div className="p-8 rounded-2xl bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] text-center text-xs text-[var(--gg-text-secondary)]">
          No pictures match these filters.
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
          {filteredMedia.map(({ item, ins, gameName, badge }) => {
            const isSelected = selectedShas.includes(item.sha256);
            return (
              <div
                key={item.sha256}
                style={{ contentVisibility: 'auto', containIntrinsicSize: '260px 160px' }}
                className={`group relative rounded-[var(--gg-r-tile)] overflow-hidden border bg-black xbox-ring ${
                  isSelected ? 'border-2 border-[var(--gg-focus-ring)]' : 'border-white/10'
                }`}
              >
                <button
                  type="button"
                  onClick={() => {
                    if (selectMode) toggleSelectSha(item.sha256);
                    else setViewerSha(item.sha256);
                  }}
                  onPointerDown={() => {
                    if (longPressTimer.current) clearTimeout(longPressTimer.current);
                    longPressTimer.current = setTimeout(() => {
                      setSelectMode(true);
                      setSelectedShas((prev) => (prev.includes(item.sha256) ? prev : [...prev, item.sha256]));
                    }, 450);
                  }}
                  onPointerUp={() => {
                    if (longPressTimer.current) clearTimeout(longPressTimer.current);
                  }}
                  onPointerLeave={() => {
                    if (longPressTimer.current) clearTimeout(longPressTimer.current);
                  }}
                  className="block w-full aspect-video text-left"
                >
                  <MediaImage
                    sha={item.sha256}
                    kind="thumb"
                    alt={ins?.text || item.origName}
                    className="w-full h-full object-cover"
                  />
                  <div className="absolute inset-x-0 bottom-0 p-2 bg-gradient-to-t from-black/90 via-black/45 to-transparent flex items-end justify-between gap-2">
                    <span className="text-[11px] font-medium text-[var(--gg-text-primary)] truncate">{gameName}</span>
                    <span className={`px-1.5 py-0.5 rounded-lg text-[10px] font-semibold shrink-0 inline-flex items-center gap-1 ${badge.cls}`}>
                      {ins?.userEdited && <Lock size={9} />}
                      {badge.label}
                    </span>
                  </div>
                </button>

                <button
                  type="button"
                  aria-label={isSelected ? `Deselect ${item.origName}` : `Select ${item.origName}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectMode(true);
                    toggleSelectSha(item.sha256);
                  }}
                  className={`absolute top-2 left-2 w-6 h-6 rounded-lg flex items-center justify-center border text-xs ${
                    isSelected
                      ? 'bg-[var(--gg-accent)] border-white text-white'
                      : 'bg-black/60 border-white/40 text-transparent hover:text-white/70'
                  }`}
                >
                  <Check size={13} />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Selection Sticky Action Bar */}
      {(selectMode || selectedShas.length > 0) && (
        <div className="sticky bottom-20 z-30 p-3 rounded-2xl bg-[var(--gg-bg-panel)] border border-[var(--gg-focus-ring)] shadow-xl flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="font-semibold tabular-nums">{selectedShas.length} selected</span>
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => setSelectedShas(filteredMedia.map((r) => r.item.sha256))}
              className="px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)]"
            >
              Select all (shown)
            </button>
            <button
              type="button"
              onClick={() =>
                setSelectedShas(
                  filteredMedia.filter((r) => !r.isExcluded && !r.ins).map((r) => r.item.sha256)
                )
              }
              className="px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)]"
            >
              Select all not indexed
            </button>
            <button
              type="button"
              onClick={() => {
                setSelectedShas([]);
                setSelectMode(false);
              }}
              className="px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)]"
            >
              Select none
            </button>
            {selectedShas.length > 0 && (
              <>
                <button
                  type="button"
                  onClick={() => {
                    const eligible = selectedShas.filter((sha) => {
                      const m = db.media.find((x) => x.sha256 === sha);
                      const ins = activeDescribeBySha.get(sha);
                      return m?.aiIndex !== 'EXCLUDED' && (!ins || (ins.status ?? 'DONE') !== 'DONE');
                    });
                    openEstimateConfirm({
                      title: `Index selected (${eligible.length})`,
                      shas: eligible,
                      forceReindex: false,
                    });
                  }}
                  className="px-3 py-1.5 rounded-xl bg-[var(--gg-accent)] text-white font-semibold"
                >
                  Index selected ({selectedShas.length})
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const eligible = selectedShas.filter((sha) => {
                      const m = db.media.find((x) => x.sha256 === sha);
                      return m?.aiIndex !== 'EXCLUDED';
                    });
                    openEstimateConfirm({
                      title: `Re-describe selected (${eligible.length})`,
                      shas: eligible,
                      forceReindex: true,
                    });
                  }}
                  className="px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)]"
                >
                  Re-describe selected
                </button>
                <button
                  type="button"
                  onClick={() => setExclusionForShas(selectedShas, true)}
                  className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-white/10"
                >
                  <Ban size={12} /> Don&apos;t index selected
                </button>
                <button
                  type="button"
                  onClick={() => setExclusionForShas(selectedShas, false)}
                  className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-white/10"
                >
                  <Eye size={12} /> Include selected
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Estimate & Confirm Modal */}
      {confirmRun && confirmEstimate && (
        <div className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4" onClick={() => setConfirmRun(null)}>
          <div
            className="w-full max-w-md rounded-2xl bg-[var(--gg-bg-panel)] border border-[var(--gg-divider)] p-5 space-y-4 text-xs"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-base font-semibold text-[var(--gg-text-primary)]">{confirmRun.title}</div>
            <p className="text-sm text-[var(--gg-text-secondary)]">
              {confirmEstimate.items} {confirmEstimate.items === 1 ? 'picture' : 'pictures'}, about{' '}
              {confirmEstimate.requests} {confirmEstimate.requests === 1 ? 'request' : 'requests'},{' '}
              {confirmEstimate.minutesText}.
            </p>
            <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
              {confirmRun.allowSelectionShortcut ? (
                <button
                  type="button"
                  onClick={() => {
                    setConfirmRun(null);
                    setSelectMode(true);
                  }}
                  className="underline text-[var(--gg-focus-ring)]"
                >
                  Select which ones
                </button>
              ) : (
                <span />
              )}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setConfirmRun(null)}
                  className="px-3.5 py-2 rounded-xl bg-white/10"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={executeConfirmRun}
                  className="px-4 py-2 rounded-xl bg-[var(--gg-accent)] text-white font-semibold"
                >
                  Confirm &amp; start
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      </>
      )}

      {/* Prompt Log Modal */}
      {showLogModal && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4" onClick={() => setShowLogModal(false)}>
          <div
            className="w-full max-w-2xl max-h-[82vh] flex flex-col rounded-2xl bg-[var(--gg-bg-panel)] border border-[var(--gg-divider)] p-5 space-y-3 text-xs"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold">Local Prompt Log ({promptLog.length})</div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={async () => {
                    await clearPromptLog();
                    setPromptLog([]);
                    pushToast({ title: 'Prompt log cleared' });
                  }}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl bg-red-900/50 text-red-100"
                >
                  <Trash2 size={12} /> Clear log
                </button>
                <button
                  type="button"
                  onClick={() => setShowLogModal(false)}
                  aria-label="Close prompt log"
                  className="p-1.5 rounded-xl bg-white/10"
                >
                  <X size={16} />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto space-y-2">
              {promptLog.length === 0 ? (
                <p className="text-[var(--gg-text-secondary)]">No logged AI calls yet.</p>
              ) : (
                promptLog.map((entry) => (
                  <div key={entry.id} className="p-3 rounded-xl bg-black/35 border border-[var(--gg-divider)] space-y-1">
                    <div className="flex justify-between font-mono text-[10px] text-[var(--gg-focus-ring)]">
                      <span>{entry.subjectLabel} ({entry.shaPrefix})</span>
                      <span>{entry.model} · {entry.ms}ms · {new Date(entry.time).toLocaleTimeString()}</span>
                    </div>
                    <div className="text-[11px] text-[var(--gg-text-secondary)] whitespace-pre-wrap">{entry.userText}</div>
                    <pre className="text-[10px] font-mono bg-black/40 p-2 rounded-lg overflow-x-auto">{entry.replyText}</pre>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Shared Media Viewer */}
      {viewerSha && (
        <MediaViewer
          shas={filteredMedia.map((r) => r.item.sha256)}
          initialSha={viewerSha}
          onClose={() => setViewerSha(null)}
        />
      )}
    </div>
  );
}
