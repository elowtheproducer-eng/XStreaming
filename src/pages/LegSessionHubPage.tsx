import { useMediaUrlMap } from '../logic/media';
import React, { useEffect, useMemo, useState } from 'react';
import { useJournal } from '../state/JournalStore';
import { GENRE_MAP } from '../data/bundledModules';
import { resolveGameConfig } from '../logic/genreResolver';
import { formatPlayTime } from '../logic/ledger';
import {
  buildPlanSnapshotFromCandidate,
  parseAnyFlightPlanText,
} from '../logic/planParser';
import { composeRecapDoc } from '../logic/recapEngine';
import { AddImageSheet } from '../components/AddImageSheet';
import { MediaViewer } from '../components/MediaViewer';
import { SummaryCard } from '../components/SummaryCard';
import { TagChips } from '../components/TagChips';
import { DictationButton } from '../components/DictationButton';
import { findMatchingPlanConflict, type PlanConflictMatch } from '../logic/mediaDuplicates';
import {
  computeStintMinutes,
  startLegSessionStint,
  stopLegSessionStint,
} from '../logic/legSessions';
import { formatIngestToast, ingestFiles } from '../logic/mediaIngest';
import type { EntryRevision, LegStatus, PlanFacetType } from '../types/journal';
import {
  Check,
  Clock,
  Copy,
  History,
  Map as MapIcon,
  Pause,
  Play,
  Plus,
  Sparkles,
  Square,
  Trash2,
  Upload,
  X,
} from 'lucide-react';

const WEATHER_MOODS = ['Clear CAVOK', 'Scattered clouds', 'Crosswind', 'Overcast IFR', 'Stormy', 'Night', 'Golden hour'];
const LANDING_FEELS = ['Butter', 'Firm', 'Floating', 'Go-around', 'Crosswind crab', 'Unlogged'];

export function LegSessionHubPage({
  legId,
  initialTab = 'details',
}: {
  legId: string;
  initialTab?: string;
}) {
  const {
    db,
    navigate,
    updateLeg,
    softDeleteLeg,
    updateDb,
    setFieldValue,
    addMediaItems,
    addPlanSnapshot,
    addRecap,
    playSound,
    pushToast,
  } = useJournal();

  const leg = db.legs.find((l) => l.id === legId);
  const game = leg ? db.games.find((g) => g.id === leg.gameId) : undefined;
  const resolved = useMemo(
    () => (game ? resolveGameConfig(game, GENRE_MAP) : null),
    [game]
  );

  const [tab, setTab] = useState(initialTab);
  const [timerRunning, setTimerRunning] = useState(leg?.status === 'IN_PROGRESS');
  const [sessionSecs, setSessionSecs] = useState(0);
  const [liveCaptureText, setLiveCaptureText] = useState('');

  // Note composer + revision drawer
  const [noteTitle, setNoteTitle] = useState('');
  const [noteBody, setNoteBody] = useState('');
  const [editingEntryId, setEditingEntryId] = useState<string | null>(null);
  const [showRevisionsFor, setShowRevisionsFor] = useState<string | null>(null);

  // Custom field creator
  const [newFieldLabel, setNewFieldLabel] = useState('');
  const [newFieldType, setNewFieldType] = useState<'TEXT' | 'NUMBER' | 'CHECK'>('TEXT');

  // Media viewer
  const [viewerSha, setViewerSha] = useState<string | null>(null);
  const [captureProg, setCaptureProg] = useState<{ done: number; total: number } | null>(null);

  // Plan re-paste inside leg
  const [quickRouteInput, setQuickRouteInput] = useState('');
  const [pendingPlanConflict, setPendingPlanConflict] = useState<{
    conflict: PlanConflictMatch;
    routeText: string;
  } | null>(null);

  useEffect(() => {
    if (!timerRunning) return;
    const t = setInterval(() => setSessionSecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [timerRunning]);

  const mediaMap = useMediaUrlMap(db.media);

  if (!leg || !game || !resolved) {
    return (
      <div className="p-8 text-center space-y-3">
        <p className="text-sm text-[var(--gg-text-secondary)]">Entry not found.</p>
        <button
          type="button"
          onClick={() => navigate({ page: 'library' })}
          className="px-4 py-2 rounded bg-[var(--gg-accent)] text-white text-sm"
        >
          Back to Library
        </button>
      </div>
    );
  }

  const isFlight = game.packId === 'flight';
  const { config } = resolved;

  const legEntries = db.entries
    .filter((e) => e.ownerType === 'LEG' && e.ownerId === leg.id && !e.deletedAt)
    .sort((a, b) => b.updatedAt - a.updatedAt);

  const legMediaLinks = db.mediaLinks.filter(
    (ml) => ml.ownerType === 'LEG' && ml.ownerId === leg.id && !ml.deletedAt
  );

  const legPlans = db.plans.filter((p) => p.legId === leg.id);
  const fieldDefs = db.fieldDefs.filter(
    (fd) => fd.gameId === game.id && fd.ownerKind === 'SESSION' && !fd.hidden
  );

  const getFieldVal = (key: string) =>
    db.fieldValues.find(
      (fv) => fv.ownerType === 'SESSION' && fv.ownerId === leg.id && fv.key === key
    )?.value ?? '';

  const legStints = useMemo(
    () =>
      (db.legSessions ?? [])
        .filter((s) => s.legId === leg.id)
        .sort((a, b) => b.startedAt - a.startedAt),
    [db.legSessions, leg.id]
  );

  const commitTimerMinutes = (nextStatus?: LegStatus) => {
    const now = Date.now();
    const addedMins = Math.floor(sessionSecs / 60);
    let extraFromStint = addedMins;
    updateDb((prev) => {
      const stopped = stopLegSessionStint(prev.legSessions ?? [], leg.id, now);
      extraFromStint = Math.max(addedMins, stopped.closedMinutes);
      return {
        ...prev,
        legSessions: stopped.sessions,
        legs: prev.legs.map((l) =>
          l.id === leg.id
            ? {
                ...l,
                ...(nextStatus ? { status: nextStatus } : {}),
                ...(nextStatus === 'COMPLETED' ? { endedAt: now } : {}),
                blockMinutes: (l.blockMinutes ?? 0) + extraFromStint,
                updatedAt: now,
              }
            : l
        ),
      };
    }, 'SessionStintStop');
    setSessionSecs(0);
    setTimerRunning(false);
    playSound('save');
  };

  const handleQuickLiveNote = (e: React.FormEvent) => {
    e.preventDefault();
    if (!liveCaptureText.trim()) return;
    const now = Date.now();
    const entryId = `entry_${now}`;
    updateDb((prev) => ({
      ...prev,
      entries: [
        {
          id: entryId,
          ownerType: 'LEG',
          ownerId: leg.id,
          kind: 'MOMENT',
          title: 'Live moment',
          body: liveCaptureText.trim(),
          sortKey: now,
          momentAt: now,
          createdAt: now,
          updatedAt: now,
          rev: 1,
        },
        ...prev.entries,
      ],
    }), 'LiveMoment');
    setLiveCaptureText('');
    pushToast({ title: 'Moment captured' });
  };

  const handleSaveNote = (e: React.FormEvent) => {
    e.preventDefault();
    if (!noteBody.trim()) return;
    const now = Date.now();

    if (editingEntryId) {
      updateDb((prev) => {
        const current = prev.entries.find((x) => x.id === editingEntryId);
        const revCount = prev.entryRevisions.filter((r) => r.entryId === editingEntryId).length;
        const snapshot: EntryRevision | null = current
          ? {
              id: `rev_${now}_${Math.random().toString(36).slice(2, 5)}`,
              entryId: current.id,
              revNo: revCount + 1,
              title: current.title,
              body: current.body,
              savedAt: now,
              reason: 'MANUAL',
              authorKind: 'USER',
            }
          : null;
        return {
          ...prev,
          entries: prev.entries.map((x) =>
            x.id === editingEntryId
              ? { ...x, title: noteTitle.trim() || undefined, body: noteBody.trim(), updatedAt: now, rev: x.rev + 1 }
              : x
          ),
          entryRevisions: snapshot ? [snapshot, ...prev.entryRevisions] : prev.entryRevisions,
        };
      }, 'NoteRevision');
      setEditingEntryId(null);
    } else {
      const entryId = `entry_${now}`;
      updateDb((prev) => ({
        ...prev,
        entries: [
          {
            id: entryId,
            ownerType: 'LEG',
            ownerId: leg.id,
            kind: 'NOTE',
            title: noteTitle.trim() || undefined,
            body: noteBody.trim(),
            sortKey: now,
            createdAt: now,
            updatedAt: now,
            rev: 1,
          },
          ...prev.entries,
        ],
      }), 'NoteCreate');
    }
    setNoteTitle('');
    setNoteBody('');
    playSound('save');
    pushToast({ title: 'Note saved with revision history' });
  };

  const handleRestoreRevision = (rev: EntryRevision) => {
    const now = Date.now();
    updateDb((prev) => ({
      ...prev,
      entries: prev.entries.map((x) =>
        x.id === rev.entryId
          ? { ...x, title: rev.title, body: rev.body, updatedAt: now, rev: x.rev + 1 }
          : x
      ),
      entryRevisions: [
        {
          id: `rev_${now}`,
          entryId: rev.entryId,
          revNo: prev.entryRevisions.filter((r) => r.entryId === rev.entryId).length + 1,
          title: rev.title,
          body: rev.body,
          savedAt: now,
          reason: 'RESTORE',
          authorKind: 'USER',
        },
        ...prev.entryRevisions,
      ],
    }), 'NoteRestore');
    setShowRevisionsFor(null);
    pushToast({ title: `Restored revision #${rev.revNo}` });
  };


  return (
    <div className="space-y-6 pb-24">
      {/* Header */}
      <section className="p-5 rounded-[var(--gg-r-panel)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <button
              type="button"
              onClick={() => navigate({ page: 'game', gameId: game.id })}
              className="text-xs font-semibold text-[var(--gg-focus-ring)] hover:underline"
            >
              ← {game.name}
            </button>
            <h1 className="text-2xl font-light text-[var(--gg-text-primary)] tracking-tight">
              {leg.title || `${leg.originIcao ?? ''} → ${leg.destIcao ?? ''}`}
            </h1>
            <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--gg-text-secondary)] tabular-nums">
              <span>{leg.flownOn}</span>
              <span>·</span>
              <span>Logged: {formatPlayTime(leg.blockMinutes)}</span>
              {leg.distanceNm ? (
                <>
                  <span>·</span>
                  <span>{leg.distanceNm} nm</span>
                </>
              ) : null}
            </div>
            <div className="pt-1.5">
              <TagChips ownerType="LEG" ownerId={leg.id} compact />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Play Timer control */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-[var(--gg-r-control)] bg-black/35 border border-[var(--gg-divider)] text-xs font-mono tabular-nums">
              <Clock size={14} className="text-[var(--gg-focus-ring)]" />
              <span>
                {String(Math.floor(sessionSecs / 60)).padStart(2, '0')}:
                {String(sessionSecs % 60).padStart(2, '0')}
              </span>
              {timerRunning ? (
                <button
                  type="button"
                  onClick={() => commitTimerMinutes('PAUSED')}
                  aria-label="Pause timer"
                  className="p-1 rounded bg-white/10 hover:bg-white/20"
                >
                  <Pause size={12} />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    const now = Date.now();
                    updateDb((prev) => ({
                      ...prev,
                      legSessions: startLegSessionStint(prev.legSessions ?? [], leg.id, now),
                      legs: prev.legs.map((l) =>
                        l.id === leg.id
                          ? { ...l, status: 'IN_PROGRESS', startedAt: l.startedAt ?? now, updatedAt: now }
                          : l
                      ),
                    }), 'SessionStintStart');
                    setTimerRunning(true);
                  }}
                  aria-label="Start timer"
                  className="p-1 rounded bg-[var(--gg-accent)] text-white"
                >
                  <Play size={12} />
                </button>
              )}
            </div>

            <select
              value={leg.status}
              onChange={(e) => {
                const st = e.target.value as LegStatus;
                updateLeg(leg.id, { status: st });
                if (st !== 'IN_PROGRESS') setTimerRunning(false);
              }}
              aria-label="Entry status"
              className="px-3 py-1.5 rounded-[var(--gg-r-control)] text-xs font-semibold bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
            >
              <option value="DRAFT">Draft</option>
              <option value="PLANNED">Planned</option>
              <option value="IN_PROGRESS">In progress</option>
              <option value="PAUSED">Paused</option>
              <option value="COMPLETED">Completed</option>
              <option value="ABANDONED">Abandoned</option>
            </select>

            {leg.status !== 'COMPLETED' && (
              <button
                type="button"
                onClick={() => {
                  commitTimerMinutes('COMPLETED');
                  pushToast({ title: `${config.terms.session} concluded` });
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--gg-r-control)] text-xs font-semibold bg-[var(--gg-accent)] text-white"
              >
                <Square size={12} />
                <span>{config.terms.concludeAction}</span>
              </button>
            )}

            <button
              type="button"
              onClick={() => {
                softDeleteLeg(leg.id);
                navigate({ page: 'game', gameId: game.id });
              }}
              aria-label="Move entry to Trash"
              className="p-2 rounded bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)] hover:text-red-300"
            >
              <Trash2 size={15} />
            </button>
          </div>
        </div>

        {/* Live Capture Bar when IN_PROGRESS (§22.18) */}
        {(leg.status === 'IN_PROGRESS' || timerRunning) && (
          <form onSubmit={handleQuickLiveNote} className="flex gap-2 pt-2 border-t border-[var(--gg-divider)]">
            <input
              type="text"
              value={liveCaptureText}
              onChange={(e) => setLiveCaptureText(e.target.value)}
              placeholder={`Live capture bar: jot a quick moment during this ${config.terms.session.toLowerCase()}...`}
              className="flex-1 px-3 py-2 rounded-[var(--gg-r-control)] text-sm bg-black/35 border border-[var(--gg-focus-ring)]/50"
            />
            <button type="submit" className="px-4 py-2 rounded-[var(--gg-r-control)] text-xs font-semibold bg-[var(--gg-accent)] text-white">
              Pin Moment
            </button>
          </form>
        )}
      </section>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-[var(--gg-divider)] overflow-x-auto no-scrollbar">
        {[
          { id: 'details', label: isFlight ? 'Flight Diary & Details' : 'Details & Custom Fields' },
          { id: 'notes', label: `Notes (${legEntries.length})` },
          { id: 'captures', label: `Captures (${legMediaLinks.length})` },
          ...(isFlight ? [{ id: 'plans', label: `Plans (${legPlans.length})` }] : []),
          { id: 'recap', label: 'Recap & Keeper' },
        ].map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-3.5 py-2 text-sm font-medium border-b-2 whitespace-nowrap ${
              tab === t.id
                ? 'border-[var(--gg-focus-ring)] text-[var(--gg-text-primary)]'
                : 'border-transparent text-[var(--gg-text-secondary)]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* TAB: DETAILS & FIELDS */}
      {tab === 'details' && (
        <div className="space-y-5">
          <SummaryCard
            subjectType="LEG"
            subjectId={leg.id}
            title={`${config.terms.session} Summary`}
            showKeepersTake
          />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div className="p-4 rounded-[var(--gg-r-control)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-3">
            <h2 className="text-sm font-semibold">Core Logbook</h2>
            <label className="block space-y-1 text-xs">
              <span className="text-[var(--gg-text-secondary)]">Title</span>
              <input
                type="text"
                value={leg.title ?? ''}
                onChange={(e) => updateLeg(leg.id, { title: e.target.value })}
                className="w-full px-3 py-2 rounded text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
              />
            </label>

            {isFlight && (
              <div className="grid grid-cols-3 gap-2">
                <label className="block space-y-1 text-xs">
                  <span className="text-[var(--gg-text-secondary)]">Origin ICAO</span>
                  <input
                    type="text"
                    value={leg.originIcao ?? ''}
                    onChange={(e) => updateLeg(leg.id, { originIcao: e.target.value.toUpperCase() })}
                    className="w-full px-2.5 py-2 rounded text-sm font-mono bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
                  />
                </label>
                <label className="block space-y-1 text-xs">
                  <span className="text-[var(--gg-text-secondary)]">Dest ICAO</span>
                  <input
                    type="text"
                    value={leg.destIcao ?? ''}
                    onChange={(e) => updateLeg(leg.id, { destIcao: e.target.value.toUpperCase() })}
                    className="w-full px-2.5 py-2 rounded text-sm font-mono bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
                  />
                </label>
                <label className="block space-y-1 text-xs">
                  <span className="text-[var(--gg-text-secondary)]">Aircraft</span>
                  <input
                    type="text"
                    value={leg.aircraftName ?? ''}
                    onChange={(e) => updateLeg(leg.id, { aircraftName: e.target.value })}
                    className="w-full px-2.5 py-2 rounded text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
                  />
                </label>
              </div>
            )}

            <div className="grid grid-cols-2 gap-2">
              <label className="block space-y-1 text-xs">
                <span className="text-[var(--gg-text-secondary)]">Date</span>
                <input
                  type="date"
                  value={leg.flownOn}
                  onChange={(e) => updateLeg(leg.id, { flownOn: e.target.value })}
                  className="w-full px-2.5 py-2 rounded text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
                />
              </label>
              <label className="block space-y-1 text-xs">
                <span className="text-[var(--gg-text-secondary)]">Duration (minutes)</span>
                <input
                  type="number"
                  min={0}
                  value={leg.blockMinutes ?? 0}
                  onChange={(e) => updateLeg(leg.id, { blockMinutes: Math.max(0, Number(e.target.value)) })}
                  className="w-full px-2.5 py-2 rounded text-sm tabular-nums bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
                />
              </label>
            </div>

            <label className="block space-y-1 text-xs">
              <span className="text-[var(--gg-text-secondary)]">Summary</span>
              <textarea
                rows={3}
                value={leg.summary ?? ''}
                onChange={(e) => updateLeg(leg.id, { summary: e.target.value })}
                className="w-full px-3 py-2 rounded text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
              />
            </label>
          </div>

          {/* Right Pane: Flight Diary OR General + Genre Custom Fields */}
          {isFlight ? (
            <div className="p-4 rounded-[var(--gg-r-control)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">Flight Diary</h2>
                <button
                  type="button"
                  onClick={() => navigate({ page: 'atlas', focusLegId: leg.id })}
                  className="inline-flex items-center gap-1 text-xs text-[var(--gg-focus-ring)] hover:underline"
                >
                  <MapIcon size={13} />
                  <span>View route on Atlas</span>
                </button>
              </div>

              <div className="space-y-1.5">
                <span className="text-xs text-[var(--gg-text-secondary)]">Weather mood</span>
                <div className="flex flex-wrap gap-1.5">
                  {WEATHER_MOODS.map((m) => {
                    const active = (leg.weatherMood ?? []).includes(m);
                    return (
                      <button
                        key={m}
                        type="button"
                        onClick={() => {
                          const cur = leg.weatherMood ?? [];
                          updateLeg(leg.id, {
                            weatherMood: active ? cur.filter((x) => x !== m) : [...cur, m],
                          });
                        }}
                        className={`px-2.5 py-1 rounded text-xs ${
                          active
                            ? 'bg-[var(--gg-accent)] text-white'
                            : 'bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)]'
                        }`}
                      >
                        {m}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="space-y-1.5">
                <span className="text-xs text-[var(--gg-text-secondary)]">Landing feel</span>
                <div className="flex flex-wrap gap-1.5">
                  {LANDING_FEELS.map((lf) => (
                    <button
                      key={lf}
                      type="button"
                      onClick={() => updateLeg(leg.id, { landingFeel: lf })}
                      className={`px-2.5 py-1 rounded text-xs ${
                        leg.landingFeel === lf
                          ? 'bg-[var(--gg-accent)] text-white'
                          : 'bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)]'
                      }`}
                    >
                      {lf}
                    </button>
                  ))}
                </div>
              </div>

              <label className="block space-y-1 text-xs">
                <span className="text-[var(--gg-text-secondary)]">
                  Fuel diary note (recorded text only — no fuel planning maths)
                </span>
                <textarea
                  rows={2}
                  value={leg.fuelNote ?? ''}
                  onChange={(e) => updateLeg(leg.id, { fuelNote: e.target.value })}
                  placeholder="Optional story about fuel or weather holding..."
                  className="w-full px-3 py-2 rounded text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
                />
              </label>
            </div>
          ) : (
            <div className="p-4 rounded-[var(--gg-r-control)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-4">
              <h2 className="text-sm font-semibold">Custom &amp; Genre Fields</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {fieldDefs.map((fd) => {
                  const val = getFieldVal(fd.key);
                  return (
                    <label key={fd.id} className="block space-y-1 text-xs">
                      <span className="text-[var(--gg-text-secondary)]">
                        {fd.label}{' '}
                        {fd.origin === 'GENRE' && fd.genreId && (
                          <span className="text-[10px] text-[var(--gg-focus-ring)]">({fd.genreId})</span>
                        )}
                      </span>
                      {fd.type === 'CHOICE' && fd.choices ? (
                        <select
                          value={String(val)}
                          onChange={(e) => setFieldValue('SESSION', leg.id, fd.key, e.target.value)}
                          className="w-full px-2.5 py-2 rounded text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
                        >
                          <option value="">—</option>
                          {fd.choices.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      ) : fd.type === 'CHECK' ? (
                        <div className="pt-1">
                          <input
                            type="checkbox"
                            checked={Boolean(val)}
                            onChange={(e) => setFieldValue('SESSION', leg.id, fd.key, e.target.checked)}
                          />
                        </div>
                      ) : (
                        <input
                          type={fd.type === 'NUMBER' ? 'number' : 'text'}
                          value={String(val)}
                          onChange={(e) =>
                            setFieldValue(
                              'SESSION',
                              leg.id,
                              fd.key,
                              fd.type === 'NUMBER' && e.target.value !== ''
                                ? Number(e.target.value)
                                : e.target.value
                            )
                          }
                          className="w-full px-2.5 py-2 rounded text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
                        />
                      )}
                    </label>
                  );
                })}
              </div>

              {/* Add user custom field */}
              <div className="pt-3 border-t border-[var(--gg-divider)] flex flex-wrap gap-2">
                <input
                  type="text"
                  value={newFieldLabel}
                  onChange={(e) => setNewFieldLabel(e.target.value)}
                  placeholder="Add custom field..."
                  className="flex-1 min-w-[140px] px-2.5 py-1.5 rounded text-xs bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
                />
                <select
                  value={newFieldType}
                  onChange={(e) => setNewFieldType(e.target.value as 'TEXT' | 'NUMBER' | 'CHECK')}
                  className="px-2 py-1.5 rounded text-xs bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
                >
                  <option value="TEXT">Text</option>
                  <option value="NUMBER">Number</option>
                  <option value="CHECK">Check</option>
                </select>
                <button
                  type="button"
                  onClick={() => {
                    if (!newFieldLabel.trim()) return;
                    const key = `custom_${newFieldLabel.trim().toLowerCase().replace(/[^a-z0-9]/g, '_')}`;
                    updateDb((prev) => ({
                      ...prev,
                      fieldDefs: [
                        ...prev.fieldDefs,
                        {
                          id: `fdef_${Date.now()}`,
                          gameId: game.id,
                          key,
                          label: newFieldLabel.trim(),
                          type: newFieldType,
                          sortKey: fieldDefs.length + 10,
                          ownerKind: 'SESSION',
                          origin: 'USER',
                        },
                      ],
                    }));
                    setNewFieldLabel('');
                    pushToast({ title: 'Custom field added' });
                  }}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded text-xs font-semibold bg-[var(--gg-accent)] text-white"
                >
                  <Plus size={12} />
                  <span>Add field</span>
                </button>
              </div>
            </div>
          )}
          </div>

          {/* Recorded Session Stints (D15) */}
          <div className="p-4 rounded-[var(--gg-r-tile)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-2.5">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">Session stints ({legStints.length})</h2>
              <span className="text-xs text-[var(--gg-text-secondary)] tabular-nums">
                Stint total: {formatPlayTime(computeStintMinutes(db.legSessions ?? [], leg.id))}
              </span>
            </div>
            {legStints.length === 0 ? (
              <p className="text-xs text-[var(--gg-text-secondary)]">
                Press Play on the timer in the header to record individual start and stop stints for this {config.terms.session.toLowerCase()}.
              </p>
            ) : (
              <div className="space-y-1.5">
                {legStints.map((st) => {
                  const mins = st.endedAt
                    ? Math.max(0, Math.round((st.endedAt - st.startedAt) / 60_000))
                    : null;
                  return (
                    <div
                      key={st.id}
                      className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 rounded-[var(--gg-r-control)] bg-black/25 text-xs tabular-nums"
                    >
                      <span>
                        {new Date(st.startedAt).toLocaleString()}
                        {st.endedAt ? ` → ${new Date(st.endedAt).toLocaleTimeString()}` : ' → Active now'}
                      </span>
                      <span className="font-mono text-[var(--gg-focus-ring)]">
                        {mins !== null ? formatPlayTime(mins) : 'Running'}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB: NOTES WITH REVISION HISTORY */}
      {tab === 'notes' && (
        <div className="space-y-4">
          <form onSubmit={handleSaveNote} className="p-4 rounded-[var(--gg-r-control)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-3">
            <div className="flex flex-wrap gap-1.5">
              {config.noteTemplates.map((tpl) => (
                <button
                  key={tpl}
                  type="button"
                  onClick={() => setNoteTitle(tpl)}
                  className="px-2.5 py-1 rounded text-xs bg-[var(--gg-surface-control)] hover:bg-white/15"
                >
                  + {tpl}
                </button>
              ))}
            </div>
            <input
              type="text"
              value={noteTitle}
              onChange={(e) => setNoteTitle(e.target.value)}
              placeholder="Note heading (optional)"
              className="w-full px-3 py-2 rounded text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
            />
            <textarea
              rows={4}
              value={noteBody}
              onChange={(e) => setNoteBody(e.target.value)}
              placeholder="Markdown supported..."
              className="w-full px-3 py-2 rounded text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
            />
            <div className="flex flex-wrap items-center gap-2">
              <button type="submit" className="px-4 py-2 rounded text-xs font-semibold bg-[var(--gg-accent)] text-white">
                {editingEntryId ? 'Save Revision' : 'Add Note'}
              </button>
              <DictationButton
                compact
                onDictated={(text) => setNoteBody((prev) => (prev ? `${prev} ${text}` : text))}
              />
              {editingEntryId && (
                <button
                  type="button"
                  onClick={() => {
                    setEditingEntryId(null);
                    setNoteTitle('');
                    setNoteBody('');
                  }}
                  className="px-3 py-2 rounded text-xs bg-[var(--gg-surface-control)]"
                >
                  Cancel edit
                </button>
              )}
            </div>
          </form>

          <div className="space-y-2.5">
            {legEntries.map((en) => {
              const revs = db.entryRevisions.filter((r) => r.entryId === en.id);
              return (
                <div key={en.id} className="p-4 rounded-[var(--gg-r-control)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-2">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-[10px] font-mono uppercase text-[var(--gg-focus-ring)] mr-2">
                        {en.kind} · rev {en.rev}
                      </span>
                      {en.title && <span className="text-sm font-semibold">{en.title}</span>}
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      <button
                        type="button"
                        onClick={() => {
                          setEditingEntryId(en.id);
                          setNoteTitle(en.title ?? '');
                          setNoteBody(en.body);
                        }}
                        className="text-[var(--gg-focus-ring)] hover:underline"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => setShowRevisionsFor(showRevisionsFor === en.id ? null : en.id)}
                        className="inline-flex items-center gap-1 text-[var(--gg-text-secondary)] hover:text-[var(--gg-text-primary)]"
                      >
                        <History size={12} />
                        <span>History ({revs.length})</span>
                      </button>
                    </div>
                  </div>
                  <p className="text-sm text-[var(--gg-text-broadcast)] whitespace-pre-wrap">{en.body}</p>
                  <TagChips ownerType="ENTRY" ownerId={en.id} compact />

                  {showRevisionsFor === en.id && revs.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-[var(--gg-divider)] space-y-1.5">
                      {revs.map((rv) => (
                        <div key={rv.id} className="flex items-center justify-between text-xs p-2 rounded bg-black/30">
                          <div className="truncate flex-1 mr-3">
                            <strong>rev {rv.revNo}</strong> ({rv.reason}): {rv.body.slice(0, 60)}...
                          </div>
                          <button
                            type="button"
                            onClick={() => handleRestoreRevision(rv)}
                            className="px-2 py-1 rounded bg-[var(--gg-accent)] text-white text-[11px]"
                          >
                            Restore
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* TAB: CAPTURES + NON-DESTRUCTIVE MEDIA VIEWER */}
      {tab === 'captures' && (
        <div className="space-y-4">
          <AddImageSheet
            label={`Add screenshot to this ${config.terms.session.toLowerCase()}`}
            multiple
            onFiles={async (images) => {
              const files = images.map((i) => i.file);
              if (!files.length) return;
              let stats = { added: files.length, reused: 0, failed: 0 };
              if (files.length >= 4) setCaptureProg({ done: 0, total: files.length });
              try {
                const items = await ingestFiles(files, {
                  maxDim: 1920,
                  source: 'PICKER',
                  existingMedia: db.media,
                  onProgress: (done, total) => {
                    if (total >= 4) setCaptureProg({ done, total });
                  },
                  onStats: (s) => {
                    stats = s;
                  },
                });
                if (items.length > 0) {
                  addMediaItems(
                    items.map((item) => ({
                      item,
                      link: { ownerType: 'LEG', ownerId: leg.id, sortKey: Date.now() },
                    }))
                  );
                }
                pushToast(formatIngestToast(stats.added, stats.reused, stats.failed));
              } finally {
                setCaptureProg(null);
              }
            }}
            onXbox={() => navigate({ page: 'xbox', targetOwnerType: 'LEG', targetOwnerId: leg.id })}
          />
          {captureProg && (
            <div className="p-3 rounded-xl bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span>Adding pictures…</span>
                <span className="tabular-nums">{captureProg.done} / {captureProg.total}</span>
              </div>
              <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                <div
                  className="h-full bg-[var(--gg-accent)] transition-all"
                  style={{ width: `${captureProg.total ? Math.round((captureProg.done / captureProg.total) * 100) : 100}%` }}
                />
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {legMediaLinks.map((ml) => {
              const url = mediaMap.get(ml.mediaSha);
              if (!url) return null;
              const ops = ml.editOps ?? {};
              return (
                <button
                  key={ml.id}
                  type="button"
                  onClick={() => setViewerSha(ml.mediaSha)}
                  className="aspect-video rounded-[var(--gg-r-tile)] overflow-hidden border border-white/10 bg-black hover:border-[var(--gg-focus-ring)] xbox-ring"
                >
                  <img
                    src={url}
                    alt={ml.caption || 'Capture'}
                    className="w-full h-full object-cover"
                    style={{
                      transform: `rotate(${ops.rotateDeg ?? 0}deg) scaleX(${ops.flipH ? -1 : 1})`,
                      filter: `brightness(${1 + (ops.brightness ?? 0)}) contrast(${ops.contrast ?? 1}) saturate(${ops.saturation ?? 1})`,
                    }}
                  />
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* TAB: PLANS (Flight Pack) */}
      {tab === 'plans' && isFlight && (
        <div className="space-y-4">
          <div className="flex gap-2">
            <input
              type="text"
              value={quickRouteInput}
              onChange={(e) => setQuickRouteInput(e.target.value)}
              placeholder="Paste route string e.g. EGLL CPT N864 BHD KJFK"
              className="flex-1 px-3 py-2 rounded text-xs font-mono bg-[var(--gg-surface-control)] border border-[var(--gg-divider)]"
            />
            <button
              type="button"
              onClick={() => {
                if (!quickRouteInput.trim()) return;
                const cand = parseAnyFlightPlanText(quickRouteInput);
                const conflict = findMatchingPlanConflict(
                  {
                    originIcao: cand.originIcao,
                    destIcao: cand.destIcao,
                    callsign: cand.callsign,
                    rawKind: cand.rawKind,
                  },
                  db.plans,
                  db.legs,
                  Date.now(),
                  leg.id
                );
                if (conflict) {
                  setPendingPlanConflict({ conflict, routeText: quickRouteInput });
                  return;
                }
                const snap = buildPlanSnapshotFromCandidate(cand, cand.availableFacets, true, {
                  id: `plan_${Date.now()}`,
                  legId: leg.id,
                  source: 'PASTE',
                  isCurrent: true,
                });
                addPlanSnapshot(snap);
                setQuickRouteInput('');
                pushToast({ title: 'Plan attached to leg' });
              }}
              className="px-4 py-2 rounded text-xs font-semibold bg-[var(--gg-accent)] text-white"
            >
              Attach Plan
            </button>
          </div>

          {pendingPlanConflict && (
            <div className="p-3 rounded-[var(--gg-r-control)] bg-amber-950/40 border border-amber-500/40 flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="text-amber-100">{pendingPlanConflict.conflict.reason} Replace it or keep both?</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    const cand = parseAnyFlightPlanText(pendingPlanConflict.routeText);
                    const snap = buildPlanSnapshotFromCandidate(cand, cand.availableFacets, true, {
                      id: pendingPlanConflict.conflict.existingPlan.id,
                      legId: leg.id,
                      source: 'PASTE',
                      isCurrent: true,
                    });
                    updateDb((prev) => ({
                      ...prev,
                      plans: [snap, ...prev.plans.filter((p) => p.id !== pendingPlanConflict.conflict.existingPlan.id)],
                    }), 'PlanReplace');
                    setPendingPlanConflict(null);
                    setQuickRouteInput('');
                    pushToast({ title: 'Replaced flight plan on leg' });
                  }}
                  className="px-3 py-1.5 rounded-[var(--gg-r-control)] bg-[var(--gg-accent)] text-white font-semibold"
                >
                  Replace existing
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const cand = parseAnyFlightPlanText(pendingPlanConflict.routeText);
                    const snap = buildPlanSnapshotFromCandidate(cand, cand.availableFacets, true, {
                      id: `plan_${Date.now()}`,
                      legId: leg.id,
                      source: 'PASTE',
                      isCurrent: true,
                    });
                    addPlanSnapshot(snap);
                    setPendingPlanConflict(null);
                    setQuickRouteInput('');
                    pushToast({ title: 'Kept both plans on leg' });
                  }}
                  className="px-3 py-1.5 rounded-[var(--gg-r-control)] bg-white/15 font-semibold"
                >
                  Keep both
                </button>
                <button
                  type="button"
                  onClick={() => setPendingPlanConflict(null)}
                  className="px-2.5 py-1.5 rounded-[var(--gg-r-control)] bg-white/5"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {legPlans.map((p) => (
            <div key={p.id} className="p-4 rounded-[var(--gg-r-control)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-semibold">
                  {p.label ?? p.rawKind} {p.isCurrent && <span className="text-[10px] text-[#9BF00B] ml-2">CURRENT</span>}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {(['COORDS', 'WAYPOINTS', 'NAVAIDS', 'STRINGS', 'META'] as PlanFacetType[]).map((f) => (
                    <span
                      key={f}
                      className={`px-2 py-0.5 rounded-[var(--gg-r-badge)] text-[10px] font-mono ${
                        p.facetsPresent.includes(f)
                          ? 'bg-[var(--gg-accent)]/25 text-[#9BF00B]'
                          : 'bg-white/5 text-white/30'
                      }`}
                    >
                      {f}
                    </span>
                  ))}
                </div>
              </div>

              {p.strings.map((s) => (
                <div key={s.id} className="flex items-center justify-between gap-2 p-2.5 rounded bg-black/35 font-mono text-xs">
                  <span className="break-all">{s.text}</span>
                  <button
                    type="button"
                    onClick={() => {
                      navigator.clipboard?.writeText(s.text);
                      pushToast({ title: 'Route string copied' });
                    }}
                    aria-label="Copy route string"
                    className="p-1.5 rounded bg-white/10 shrink-0"
                  >
                    <Copy size={12} />
                  </button>
                </div>
              ))}

              {p.points.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {p.points.map((pt) => (
                    <span key={pt.id} className="px-2 py-1 rounded bg-white/5 font-mono text-[11px]">
                      {pt.ident}
                      {pt.altFt ? ` (${Math.round(pt.altFt / 100) ? `FL${Math.round(pt.altFt / 100)}` : pt.altFt})` : ''}
                    </span>
                  ))}
                </div>
              )}

              {p.meta && Object.keys(p.meta).length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                  {Object.entries(p.meta).map(([k, v]) => (
                    <div key={k} className="p-2 rounded bg-white/5">
                      <div className="text-[10px] text-[var(--gg-text-secondary)]">{k}</div>
                      <div className="font-semibold">{v}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* TAB: RECAP & KEEPER */}
      {tab === 'recap' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <button
            type="button"
            onClick={() => {
              const doc = composeRecapDoc(db, {
                scopeType: 'LEG',
                scopeIds: [leg.id],
                gameId: game.id,
              });
              addRecap(doc);
              navigate({ page: 'recap', recapId: doc.id });
            }}
            className="p-5 rounded-[var(--gg-r-control)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] hover:border-[var(--gg-focus-ring)] text-left space-y-1"
          >
            <div className="text-sm font-semibold">Generate Recap for this {config.terms.session}</div>
            <div className="text-xs text-[var(--gg-text-secondary)]">
              Create a reader-ready document with notes, captures, and plan facets.
            </div>
          </button>

          <button
            type="button"
            onClick={() => navigate({ page: 'keeper', gameId: game.id, legId: leg.id })}
            className="p-5 rounded-[var(--gg-r-control)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] hover:border-[var(--gg-focus-ring)] text-left space-y-1"
          >
            <div className="flex items-center gap-1.5 text-sm font-semibold">
              <Sparkles size={15} className="text-[var(--gg-focus-ring)]" />
              <span>Ask Keeper about this {config.terms.session}</span>
            </div>
            <div className="text-xs text-[var(--gg-text-secondary)]">
              Debrief or expand notes grounded in your logged facts.
            </div>
          </button>
        </div>
      )}

      {/* Shared MediaViewer Modal */}
      {viewerSha && (
        <MediaViewer
          shas={Array.from(new Set(legMediaLinks.map((m) => m.mediaSha)))}
          initialSha={viewerSha}
          links={legMediaLinks}
          onClose={() => setViewerSha(null)}
        />
      )}
    </div>
  );
}
