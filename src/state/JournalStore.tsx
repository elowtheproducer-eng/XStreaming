import { readPersistedJson, setPreMigrationBackup, writePersistedJson } from '../logic/persist';
import { applyScreenMode } from '../logic/screen';
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type {
  AppLogEntry,
  AppSettings,
  ChronicleEntry,
  Game,
  Goal,
  Insight,
  JournalDatabase,
  KeeperMessage,
  Leg,
  Loadout,
  MediaItem,
  MediaLink,
  PlanSnapshot,
  RecapDoc,
  RecordEntry,
  Tour,
  NotificationChannelPrefs,
} from '../types/journal';
import { createInitialDatabase, createSampleFreeDatabase, DEFAULT_SETTINGS, SEEDED_MSFS_GAME } from '../data/seedData';
import { BUNDLED_MILESTONES, BUNDLED_MODULES, GENRE_MAP } from '../data/bundledModules';
import { AIRPORT_COUNTRY_MAP } from '../data/airports';
import { computeLedger, evaluateMilestones, type LedgerSnapshot } from '../logic/ledger';
import { resolveGameConfig, syncFieldDefsForGame } from '../logic/genreResolver';
import { appendChronicleEntry, applyDossierPatches, type DossierPatchOp } from '../logic/chronicle';
import { deriveAccentPalette, isNightAtTime, type DerivedThemeColors } from '../logic/theme';
import { soundEngine, type SoundEventId } from '../logic/soundEngine';
import { applyDescribeResultToInsights, insightEngine, resolveRole } from '../logic/insightEngine';
import {
  enqueueSummaryWithAncestors,
  runSummaryTextJob,
  summaryScheduler,
  type SummarySubjectType,
} from '../logic/summaryEngine';
import { Capacitor } from '@capacitor/core';
import { App as CapacitorApp } from '@capacitor/app';
import {
  runDossierConsolidation,
  shouldRunNightlyConsolidation,
} from '../logic/dossierConsolidation';
import { normalizeLegSessions } from '../logic/legSessions';
import { shouldLockOnResume } from '../logic/appLock';
import {
  evaluateIndexingQueueTransition,
  markTourReminderSent,
  maybeDispatchNotification,
  pickDuePausedTourReminder,
  type IndexingQueueTrackerState,
} from '../logic/notifications';
import { buildInboxItemsFromSharePayload, consumePendingShareFromNative } from '../logic/shareInbox';
import type { NotificationChannelId } from '../types/journal';
import {
  isSafeModeActive,
  getSafeModeReason,
  recordBootStage,
  type SafeModeReason,
} from '../logic/crashLog';
import { checkPeriodicUpdate } from '../logic/updateChecker';
import { APP_VERSION } from '../version';
import type { TitleArtInfo, TitleArtVariant } from '../logic/xbox/titlehub';
import {
  applyXboxArtUpdatesToGames,
  importSingleXboxArtChoice,
  resolveXboxTitleCatalog,
  syncXboxArtForGames,
} from '../logic/xbox/gameArt';
import { session as xboxSession } from '../logic/xbox/session';
import {
  getCachedXboxProfile,
  saveCachedXboxProfile,
  clearCachedXboxProfile,
  refreshXboxProfile,
  getEffectivePlayerProfile,
  type XboxProfileSnapshot,
  type EffectivePlayerProfile,
} from '../logic/xbox/profile';

export { isSafeModeActive };

export interface AddGameXboxSeed {
  name: string;
  xboxTitleId?: string;
  platform?: string;
  coverUrl?: string;
  wallpaperUrl?: string;
  variants?: TitleArtVariant[];
}

export type PageRoute =
  | { page: 'home' }
  | { page: 'library'; tab?: 'games' | 'sessions' | 'campaigns' | 'captures' | 'shelves' | 'play_later' }
  | { page: 'xbox'; signInMode?: 'browser' | 'code'; syncNow?: boolean; targetOwnerType?: 'GAME' | 'LEG'; targetOwnerId?: string }
  | { page: 'game'; gameId: string; tab?: string }
  | { page: 'leg'; legId: string; tab?: string }
  | { page: 'tour'; tourId: string; tab?: string }
  | { page: 'atlas'; gameId?: string; focusLegId?: string }
  | {
      page: 'keeper';
      gameId?: string;
      legId?: string;
      view?: 'chat' | 'dossier' | 'chronicle' | 'index' | 'persona' | 'usage';
      indexSubtab?: 'pictures' | 'summaries';
    }
  | { page: 'recap'; recapId?: string }
  | { page: 'inbox' }
  | { page: 'profile' }
  | { page: 'search'; initialQuery?: string }
  | { page: 'settings'; category?: string };

export interface FocusTarget {
  kind: 'game' | 'leg' | 'tour' | 'suggestion' | 'milestone' | 'shelf' | 'utility' | 'none';
  id?: string;
  gameId?: string;
  title?: string;
  subtitle?: string;
  heroMediaSha?: string;
  coverMediaSha?: string;
  accentHex?: string;
  packId?: string;
}

export interface ToastItem {
  id: string;
  title: string;
  subtitle?: string;
  kind?: 'info' | 'milestone' | 'error';
  points?: number;
  undoFn?: () => void;
}

interface JournalContextValue {
  db: JournalDatabase;
  ledger: LedgerSnapshot;
  isNight: boolean;
  palette: DerivedThemeColors;
  route: PageRoute;
  canGoBack: boolean;
  guideOpen: boolean;
  immersive: boolean;
  focusedItem: FocusTarget;
  toasts: ToastItem[];
  lastSavedTick: number;
  navigate: (next: PageRoute) => void;
  goBack: () => void;
  setGuideOpen: (open: boolean) => void;
  setImmersive: (imm: boolean) => void;
  setFocusedItem: (item: FocusTarget) => void;
  playSound: (ev: SoundEventId) => void;
  pushToast: (t: Omit<ToastItem, 'id'>) => void;
  dismissToast: (id: string) => void;
  updateDb: (mutator: (prev: JournalDatabase) => JournalDatabase, logTag?: string) => void;
  updateSettings: (patch: Partial<AppSettings>) => void;
  saveNow: () => void;
  addGame: (input: {
    name: string;
    platform?: string;
    packId: string;
    genreIds: string[];
    status: Game['status'];
    xboxTitleId?: string;
    coverMediaSha?: string;
    iconMediaSha?: string;
    heroMediaSha?: string;
    focal?: Game['focal'];
  }) => Game;
  setGameStatus: (gameId: string, status: Game['status'], withUndo?: boolean) => void;
  resetToSampleFree: () => void;
  loadPreviewSample: () => void;
  createLegOrSession: (input: Partial<Leg> & { gameId: string }) => Leg;
  updateLeg: (legId: string, patch: Partial<Leg>) => void;
  softDeleteLeg: (legId: string) => void;
  softDeleteGame: (gameId: string) => void;
  restoreFromTrash: (kind: 'game' | 'leg' | 'tour', id: string) => void;
  addMediaItem: (
    item: MediaItem,
    link?: Omit<MediaLink, 'id' | 'createdAt' | 'mediaSha'>,
    opts?: { skipAutoIndex?: boolean }
  ) => void;
  /** Adds many media items (and links) in a single state update. */
  replaceDatabase: (next: JournalDatabase) => void;
  addMediaItems: (
    entries: Array<{ item: MediaItem; link?: Omit<MediaLink, 'id' | 'createdAt' | 'mediaSha'> }>,
    opts?: { skipAutoIndex?: boolean }
  ) => void;
  upsertInsights: (insights: Insight[]) => void;
  requestAiConsent: (actionLabel?: string, onDeclineDisableAutoIndex?: boolean, requiresRemoteText?: boolean) => Promise<boolean>;
  setFieldValue: (ownerType: 'SESSION' | 'GAME' | 'CAMPAIGN', ownerId: string, key: string, value: string | number | boolean | null) => void;
  addGoal: (input: Omit<Goal, 'id' | 'createdAt' | 'updatedAt'>) => void;
  toggleGoalDone: (goalId: string) => void;
  addLoadout: (input: Omit<Loadout, 'id' | 'createdAt' | 'updatedAt'>) => void;
  addRecordEntry: (input: Omit<RecordEntry, 'id' | 'createdAt'>) => void;
  addPlanSnapshot: (plan: PlanSnapshot) => void;
  addRecap: (recap: RecapDoc) => void;
  appendKeeperTurn: (convoId: string, userMsg: KeeperMessage, keeperMsg: KeeperMessage, patches?: DossierPatchOp[]) => void;
  recordChronicleEvent: (convoId: string, text: string) => void;
  addLog: (entry: Omit<AppLogEntry, 'id' | 'ts'>) => void;
  isForeground: boolean;
  isSafeMode: boolean;
  safeModeReason: SafeModeReason | null;
  appLocked: boolean;
  unlockApp: () => void;
  quickNoteSignal: number;
  triggerQuickNote: () => void;
  notifyChannel: (channelId: NotificationChannelId, title: string, body: string) => void;
  addGameOpen: boolean;
  addGameSeed: AddGameXboxSeed | null;
  openAddGame: (seed?: AddGameXboxSeed) => void;
  closeAddGame: () => void;
  syncXboxGameArt: (opts?: {
    force?: boolean;
    gameIds?: string[];
    silent?: boolean;
    catalogOverride?: TitleArtInfo[];
  }) => Promise<{ updated: number; covers: number; wallpapers: number; failed: number }>;
  applyXboxGameArt: (
    gameId: string,
    opts: { coverUrl?: string; wallpaperUrl?: string; xboxTitleId?: string }
  ) => Promise<{ coverSha?: string; heroSha?: string }>;
  xboxProfile: XboxProfileSnapshot | null;
  activeProfile: EffectivePlayerProfile;
  setXboxProfile: (snapshot: XboxProfileSnapshot | null) => Promise<void>;
  refreshXboxProfileState: () => Promise<XboxProfileSnapshot | null>;
}

const JournalContext = createContext<JournalContextValue | null>(null);

export function normalizeLoadedDatabase(parsed: Partial<JournalDatabase>): JournalDatabase {
  const base = createInitialDatabase();
  const hasMsfs = (parsed.games ?? []).some((g) => g.id === SEEDED_MSFS_GAME.id);
  const mergedModules = BUNDLED_MODULES.map((bm) => {
    const userMod = parsed.modules?.find((m) => m.id === bm.id && m.type === bm.type);
    return userMod ?? bm;
  });
  const extraUserMods = (parsed.modules ?? []).filter(
    (um) => !BUNDLED_MODULES.some((bm) => bm.id === um.id && bm.type === um.type)
  );
  const mergedSettings: AppSettings = {
    ...DEFAULT_SETTINGS,
    ...(parsed.settings ?? {}),
    roleOverrides: { ...(parsed.settings?.roleOverrides ?? {}) },
    notifyChannels: {
      ...DEFAULT_SETTINGS.notifyChannels,
      ...(parsed.settings?.notifyChannels ?? {}),
    } as NotificationChannelPrefs,
    aircraftAliases: { ...(parsed.settings?.aircraftAliases ?? {}) },
    simAliases: { ...(parsed.settings?.simAliases ?? {}) },
    settingsPresets: Array.isArray(parsed.settings?.settingsPresets) ? parsed.settings!.settingsPresets : [],
  };
  if (!mergedSettings.homeRailOrder.includes('xboxProfile')) {
    const order = [...mergedSettings.homeRailOrder];
    order.splice(Math.min(1, order.length), 0, 'xboxProfile');
    mergedSettings.homeRailOrder = order;
  }

  const normalizedLegs = parsed.legs ?? base.legs;

  return {
    ...base,
    ...parsed,
    settings: mergedSettings,
    games: hasMsfs ? (parsed.games ?? []) : [SEEDED_MSFS_GAME, ...(parsed.games ?? [])],
    legs: normalizedLegs,
    legSessions: normalizeLegSessions(normalizedLegs, Array.isArray(parsed.legSessions) ? parsed.legSessions : []),
    inbox: Array.isArray(parsed.inbox) ? parsed.inbox : [],
    insights: Array.isArray(parsed.insights) ? parsed.insights : [],
    tags: Array.isArray(parsed.tags) ? parsed.tags : [],
    tagLinks: Array.isArray(parsed.tagLinks) ? parsed.tagLinks : [],
    modules: [...mergedModules, ...extraUserMods],
  };
}

function loadPersistedDatabase(): JournalDatabase {
  if (typeof window === 'undefined') return createInitialDatabase();
  const params = new URLSearchParams(window.location.search);
  let loaded: JournalDatabase;
  if (params.get('empty') === '1') {
    loaded = createSampleFreeDatabase();
    recordBootStage('JOURNAL_LOADED');
    recordBootStage('MODULES_LOADED');
    return loaded;
  }
  try {
    const raw = readPersistedJson();
    if (!raw) {
      loaded = createInitialDatabase();
      recordBootStage('JOURNAL_LOADED');
      recordBootStage('MODULES_LOADED');
      return loaded;
    }
    const parsed = JSON.parse(raw) as Partial<JournalDatabase>;
    if (!parsed || !Array.isArray(parsed.games)) {
      loaded = createInitialDatabase();
      recordBootStage('JOURNAL_LOADED');
      recordBootStage('MODULES_LOADED');
      return loaded;
    }
    // Save a recovery point before schema normalisation if schemaVersion is older
    if ((parsed.schemaVersion ?? 1) < 3) {
      void setPreMigrationBackup(raw).catch(() => undefined);
    }
    recordBootStage('JOURNAL_LOADED');
    loaded = normalizeLoadedDatabase(parsed);
    recordBootStage('MODULES_LOADED');
    return loaded;
  } catch {
    loaded = createInitialDatabase();
    recordBootStage('JOURNAL_LOADED');
    recordBootStage('MODULES_LOADED');
    return loaded;
  }
}

export function JournalProvider({ children }: { children: React.ReactNode }) {
  const pushToastRef = useRef<((t: Omit<ToastItem, 'id'>) => void) | null>(null);
  const [db, setDb] = useState<JournalDatabase>(loadPersistedDatabase);
  const [stack, setStack] = useState<PageRoute[]>([{ page: 'home' }]);
  const [guideOpen, setGuideOpen] = useState(false);
  const [immersive, setImmersive] = useState(false);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [lastSavedTick, setLastSavedTick] = useState(Date.now());
  const safeMode = useMemo(() => isSafeModeActive(), []);
  const safeModeReason = useMemo(() => getSafeModeReason(), []);
  const [isForeground, setIsForeground] = useState(() =>
    typeof document === 'undefined' ? true : document.visibilityState !== 'hidden'
  );
  const [appLocked, setAppLocked] = useState(() =>
    Boolean(db.settings.appLockEnabled && !isSafeModeActive())
  );
  const [quickNoteSignal, setQuickNoteSignal] = useState(0);
  const [addGameOpen, setAddGameOpen] = useState(false);
  const [addGameSeed, setAddGameSeed] = useState<AddGameXboxSeed | null>(null);
  const xboxArtSyncInFlightRef = useRef(false);
  const backgroundedAtRef = useRef<number | null>(null);
  const isForegroundRef = useRef(isForeground);
  isForegroundRef.current = isForeground;
  const [focusedItem, setFocusedItem] = useState<FocusTarget>(() => {
    const initialLeg = db.legs[0];
    const initialGame = db.games[0];
    if (initialLeg) {
      const g = db.games.find((x) => x.id === initialLeg.gameId) ?? initialGame;
      return {
        kind: 'leg',
        id: initialLeg.id,
        gameId: g?.id,
        title: initialLeg.title || 'Session',
        subtitle: g?.name ?? 'Green Guide',
        heroMediaSha: g?.heroMediaSha ?? g?.coverMediaSha,
        coverMediaSha: g?.coverMediaSha,
        accentHex: g?.accentHex,
        packId: g?.packId,
      };
    }
    return {
      kind: initialGame ? 'game' : 'none',
      id: initialGame?.id,
      gameId: initialGame?.id,
      title: initialGame?.name ?? 'Green Guide',
      subtitle: initialGame?.platform ?? 'Xbox Series X|S',
      heroMediaSha: initialGame?.heroMediaSha ?? initialGame?.coverMediaSha,
      coverMediaSha: initialGame?.coverMediaSha,
      accentHex: initialGame?.accentHex,
      packId: initialGame?.packId,
    };
  });

  const route = stack[stack.length - 1];

  const ledger = useMemo(
    () => computeLedger(db, BUNDLED_MILESTONES, AIRPORT_COUNTRY_MAP),
    [db]
  );

  const [xboxProfile, setXboxProfileState] = useState<XboxProfileSnapshot | null>(null);

  useEffect(() => {
    let live = true;
    void getCachedXboxProfile().then((cached) => {
      if (live) setXboxProfileState(cached);
    });
    const handleUpdate = (e: any) => {
      setXboxProfileState(e.detail ?? null);
    };
    window.addEventListener('xbox-profile-updated', handleUpdate);
    return () => {
      live = false;
      window.removeEventListener('xbox-profile-updated', handleUpdate);
    };
  }, []);

  const activeGamesCount = useMemo(
    () => db.games.filter((g) => !g.deletedAt).length,
    [db.games]
  );

  const activeProfile = useMemo(
    () => getEffectivePlayerProfile(db.settings, ledger, xboxProfile, activeGamesCount),
    [db.settings, ledger, xboxProfile, activeGamesCount]
  );

  const setXboxProfile = useCallback(async (snapshot: XboxProfileSnapshot | null) => {
    if (snapshot) {
      await saveCachedXboxProfile(snapshot);
      setXboxProfileState(snapshot);
    } else {
      await clearCachedXboxProfile();
      setXboxProfileState(null);
    }
  }, []);

  const refreshXboxProfileState = useCallback(async () => {
    try {
      const fresh = await refreshXboxProfile();
      setXboxProfileState(fresh);
      return fresh;
    } catch {
      const cached = await getCachedXboxProfile();
      setXboxProfileState(cached);
      return cached;
    }
  }, []);

  // Day/Night clock evaluation (§14.3)
  const [nowTick, setNowTick] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNowTick(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  const isNight = useMemo(() => {
    const mode = db.settings.themeMode;
    if (mode === 'NIGHT') return true;
    if (mode === 'DAY') return false;
    if (mode === 'SYSTEM') {
      return typeof window !== 'undefined'
        ? !window.matchMedia('(prefers-color-scheme: light)').matches
        : true;
    }
    const mins = nowTick.getHours() * 60 + nowTick.getMinutes();
    return isNightAtTime(mins, db.settings.dayStart, db.settings.nightStart);
  }, [db.settings.themeMode, db.settings.dayStart, db.settings.nightStart, nowTick]);

  const effectiveAccentHex = useMemo(() => {
    if (db.settings.uiGameAccent && focusedItem.accentHex) {
      return focusedItem.accentHex;
    }
    return db.settings.accentHex || '#107C10';
  }, [db.settings.uiGameAccent, db.settings.accentHex, focusedItem.accentHex]);

  const palette = useMemo(
    () => deriveAccentPalette(effectiveAccentHex, isNight),
    [effectiveAccentHex, isNight]
  );

  // Apply CSS custom properties cleanly
  useEffect(() => {
    const root = document.documentElement;
    if (isNight) {
      root.classList.remove('light-theme');
    } else {
      root.classList.add('light-theme');
    }
    root.style.setProperty('--gg-accent', palette.accentBase);
    root.style.setProperty('--gg-accent-hover', palette.accentHover);
    root.style.setProperty('--gg-accent-pressed', palette.accentPressed);
    root.style.setProperty('--gg-accent-deep', palette.accentDeep);
    root.style.setProperty('--gg-focus-ring', palette.focusRing);
    root.style.setProperty('--gg-accent-wash', palette.accentWash);
    root.style.fontSize = `${Math.round((db.settings.textScale / 100) * 16)}px`;
  }, [isNight, palette, db.settings.textScale]);

  // Screen mode (status / navigation bars), curved-edge inset, reduce-motion flag.
  useEffect(() => {
    void applyScreenMode(db.settings.screenMode);
  }, [db.settings.screenMode]);
  useEffect(() => {
    const root = document.documentElement;
    const px = `${Math.max(0, db.settings.curvedEdgeInset || 0)}px`;
    root.style.setProperty('--safe-area-inset-left', px);
    root.style.setProperty('--safe-area-inset-right', px);
    root.classList.toggle('gg-reduce-motion', Boolean(db.settings.reduceMotion));
    root.classList.toggle('gg-high-contrast', Boolean(db.settings.highContrast));
    root.classList.toggle('gg-focus-bold', Boolean(db.settings.focusRingBold));
  }, [db.settings.curvedEdgeInset, db.settings.reduceMotion, db.settings.highContrast, db.settings.focusRingBold]);

  // Debounced autosave (L1)
  useEffect(() => {
    const timer = setTimeout(() => {
      void writePersistedJson(JSON.stringify(db)).then((ok) => {
        if (ok) {
          setLastSavedTick(Date.now());
        } else {
          // §0.4: never pre-empt; if the OS refuses a write, show an error toast.
          pushToastRef.current?.({ title: 'Could not save journal', subtitle: 'The device refused the write.', kind: 'error' });
        }
      });
    }, 300);
    return () => clearTimeout(timer);
  }, [db]);

  // Flush immediately when the app is backgrounded (§4.3 / §8.6: onPause/onStop).
  const dbRef = useRef(db);
  dbRef.current = db;
  useEffect(() => {
    insightEngine.setSafeMode(safeMode);
  }, [safeMode]);

  useEffect(() => {
    const handleVisibilityOrState = (visible: boolean) => {
      setIsForeground(visible);
      isForegroundRef.current = visible;
      if (!visible) {
        const nowTs = Date.now();
        backgroundedAtRef.current = nowTs;
        void writePersistedJson(JSON.stringify(dbRef.current));
        const store = typeof window !== 'undefined' ? window.localStorage : null;
        const dueTour = pickDuePausedTourReminder(
          dbRef.current.tours,
          dbRef.current.settings,
          nowTs,
          store,
          safeMode
        );
        if (dueTour) {
          void maybeDispatchNotification({
            channelId: 'tourReminder',
            title: `Paused tour: ${dueTour.name}`,
            body: 'Resume when you are ready to log the next leg.',
            settings: dbRef.current.settings,
            isForeground: false,
            isSafeMode: safeMode,
          }).then((sent) => {
            if (sent) markTourReminderSent(dueTour.id, nowTs, store);
          });
        }
        if (!safeMode) {
          void checkPeriodicUpdate(
            dbRef.current.settings,
            APP_VERSION,
            undefined,
            { isForeground: false }
          ).then((info) => {
            if (info) {
              setDb((prev) => ({
                ...prev,
                lastSavedAt: Date.now(),
                settings: { ...prev.settings, lastUpdateCheckAt: Date.now() },
              }));
            }
          });
        }
      } else {
        if (
          shouldLockOnResume(
            backgroundedAtRef.current,
            Date.now(),
            dbRef.current.settings.appLockTimeoutMin ?? 0,
            Boolean(dbRef.current.settings.appLockEnabled),
            safeMode
          )
        ) {
          setAppLocked(true);
        }
        backgroundedAtRef.current = null;
      }
    };

    const onVis = () => handleVisibilityOrState(document.visibilityState !== 'hidden');
    const flush = () => handleVisibilityOrState(false);
    document.addEventListener('visibilitychange', onVis);
    window.addEventListener('pagehide', flush);

    let subPromise: Promise<{ remove: () => Promise<void> }> | undefined;
    if (Capacitor.isNativePlatform()) {
      subPromise = CapacitorApp.addListener('appStateChange', ({ isActive }) => {
        handleVisibilityOrState(isActive);
      });
    }
    return () => {
      document.removeEventListener('visibilitychange', onVis);
      window.removeEventListener('pagehide', flush);
      void subPromise?.then((s) => s.remove()).catch(() => undefined);
    };
  }, [safeMode]);

  const pushToast = useCallback((t: Omit<ToastItem, 'id'>) => {
    const id = `toast_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    setToasts((prev) => [...prev.slice(-2), { ...t, id }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((x) => x.id !== id));
    }, 6000);
  }, []);
  pushToastRef.current = pushToast;

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((x) => x.id !== id));
  }, []);

  const playSound = useCallback(
    (ev: SoundEventId) => {
      soundEngine.play(ev, db.settings);
      if (db.settings.hapticsEnabled) {
        const pattern: Partial<Record<SoundEventId, number>> = { select: 8, save: 14, milestone: 30, error: 40, toggle_on: 8 };
        const ms = pattern[ev];
        if (ms) {
          try {
            navigator.vibrate?.(ms);
          } catch {
            /* ignore */
          }
        }
      }
    },
    [db.settings]
  );

  // Auto-evaluate milestones when ledger changes
  useEffect(() => {
    const newlyEarned = evaluateMilestones(db, ledger, BUNDLED_MILESTONES);
    if (newlyEarned.length > 0) {
      setDb((prev) => ({
        ...prev,
        milestoneAwards: [...prev.milestoneAwards, ...newlyEarned],
      }));
      const firstDef = BUNDLED_MILESTONES.find((m) => m.id === newlyEarned[0].milestoneId);
      if (firstDef) {
        playSound('milestone');
        pushToast({
          title: `Milestone unlocked: ${firstDef.title}`,
          subtitle: firstDef.desc,
          kind: 'milestone',
          points: firstDef.points,
        });
      }
    }
  }, [ledger, db, playSound, pushToast]);

  const navigate = useCallback(
    (next: PageRoute) => {
      playSound('select');
      setGuideOpen(false);
      setStack((prev) => {
        if (next.page === 'home') return [{ page: 'home' }];
        const top = prev[prev.length - 1];
        if (JSON.stringify(top) === JSON.stringify(next)) return prev;
        return [...prev, next];
      });
    },
    [playSound]
  );

  const goBack = useCallback(() => {
    if (immersive) {
      setImmersive(false);
      return;
    }
    if (guideOpen) {
      playSound('guide_close');
      setGuideOpen(false);
      return;
    }
    if (stack.length > 1) {
      playSound('back');
      setStack((prev) => prev.slice(0, -1));
    }
  }, [immersive, guideOpen, stack.length, playSound]);

  const pendingSummaryTriggersRef = useRef<
    Array<{
      subjectType: SummarySubjectType;
      subjectId: string;
      delayMs: number;
      includeKeepersTake?: boolean;
      includeAncestors?: boolean;
      priority: number;
    }>
  >([]);

  const updateDb = useCallback(
    (mutator: (prev: JournalDatabase) => JournalDatabase, logTag?: string) => {
      setDb((prev) => {
        const next = mutator(prev);
        const now = Date.now();
        if (
          logTag === 'NoteCreate' ||
          logTag === 'NoteRevision' ||
          logTag === 'NoteRestore' ||
          logTag === 'LiveMoment' ||
          logTag === 'GameNoteAdd'
        ) {
          const prevMap = new Map(prev.entries.map((e) => [e.id, e]));
          for (const e of next.entries) {
            const old = prevMap.get(e.id);
            if (!old || old.updatedAt !== e.updatedAt || old.rev !== e.rev) {
              pendingSummaryTriggersRef.current.push({
                subjectType: 'ENTRY',
                subjectId: e.id,
                delayMs: 60_000,
                includeAncestors: true,
                priority: 45,
              });
              break;
            }
          }
        } else if (logTag === 'TourCreate' || logTag === 'TourEdit') {
          const prevMap = new Map(prev.tours.map((t) => [t.id, t]));
          for (const t of next.tours) {
            const old = prevMap.get(t.id);
            if (
              !old ||
              old.updatedAt !== t.updatedAt ||
              old.status !== t.status ||
              old.description !== t.description ||
              old.name !== t.name
            ) {
              pendingSummaryTriggersRef.current.push({
                subjectType: 'TOUR',
                subjectId: t.id,
                delayMs: 0,
                includeKeepersTake: true,
                includeAncestors: true,
                priority: 100,
              });
              break;
            }
          }
        }
        const logs = logTag
          ? [
              {
                id: `log_${now}_${Math.random().toString(36).slice(2, 5)}`,
                ts: now,
                channel: 'app' as const,
                level: 'INFO' as const,
                tag: logTag,
                message: `Updated state (${logTag})`,
              },
              ...next.logs.slice(0, 120),
            ]
          : next.logs;
        return { ...next, lastSavedAt: now, logs };
      });
    },
    []
  );

  const updateSettings = useCallback(
    (patch: Partial<AppSettings>) => {
      updateDb((prev) => ({
        ...prev,
        settings: { ...prev.settings, ...patch },
      }));
    },
    [updateDb]
  );

  // Keep the stored player tag in step with the linked Xbox gamertag so summaries,
  // the dossier and Keeper all use the real name.
  useEffect(() => {
    const tag = xboxProfile?.gamertag?.trim();
    if (tag && xboxProfile?.xuid !== 'manual_xbox' && tag !== db.settings.playerTag) {
      updateSettings({ playerTag: tag });
    }
  }, [xboxProfile?.gamertag, xboxProfile?.xuid, db.settings.playerTag, updateSettings]);

  // Refresh Xbox stats in the background on launch when they are stale.
  useEffect(() => {
    if (safeMode || !Capacitor.isNativePlatform()) return;
    let live = true;
    void (async () => {
      try {
        const [cached, status] = await Promise.all([getCachedXboxProfile(), xboxSession.getSessionStatus()]);
        if (!live || !status.signedIn) return;
        if (!cached || Date.now() - cached.fetchedAt > 30 * 60 * 1000) {
          const fresh = await refreshXboxProfile();
          if (live) setXboxProfileState(fresh);
        }
      } catch {
        /* offline or token expired: keep cached stats */
      }
    })();
    return () => {
      live = false;
    };
  }, [safeMode]);

  const saveNow = useCallback(() => {
    const next = { ...db, lastSavedAt: Date.now() };
    void writePersistedJson(JSON.stringify(next)).then((ok) => {
      if (ok) {
        setDb(next);
        setLastSavedTick(Date.now());
        playSound('save');
        pushToast({ title: 'Journal saved', subtitle: 'All records written to local store.' });
      } else {
        pushToast({ title: 'Save failed', kind: 'error' });
      }
    });
  }, [db, playSound, pushToast]);

  const addGame = useCallback(
    (input: {
      name: string;
      platform?: string;
      packId: string;
      genreIds: string[];
      status: Game['status'];
      xboxTitleId?: string;
      coverMediaSha?: string;
      iconMediaSha?: string;
      heroMediaSha?: string;
      focal?: Game['focal'];
    }): Game => {
      const now = Date.now();
      const id = `game_${now}_${Math.random().toString(36).slice(2, 6)}`;
      const game: Game = {
        id,
        name: input.name.trim(),
        sortName: input.name.trim().replace(/^The\s+/i, ''),
        packId: input.packId,
        genreIds: input.packId === 'flight' ? [] : input.genreIds.slice(0, 3),
        platform: input.platform?.trim() || 'Xbox Series X|S',
        status: input.status,
        xboxTitleId: input.xboxTitleId,
        coverMediaSha: input.coverMediaSha,
        iconMediaSha: input.iconMediaSha,
        heroMediaSha: input.heroMediaSha,
        focal: input.focal,
        lastPlayedAt: now,
        totalPlayMinutes: 0,
        createdAt: now,
        updatedAt: now,
        rev: 1,
        extras: {},
      };

      const resolved = resolveGameConfig(game, GENRE_MAP);
      const newFieldDefs = syncFieldDefsForGame(game.id, [], resolved.fieldBlueprints);
      const newRecordDefs = resolved.recordDefs.map((rd, idx) => ({
        id: `rdef_${game.id}_${rd.key}_${idx}`,
        gameId: game.id,
        key: rd.key,
        label: rd.label,
        kind: rd.kind,
        better: rd.better,
        subjectLabel: rd.subjectLabel,
      }));
      const newCollections = resolved.collectionSeeds.map((cs, idx) => ({
        id: `col_${game.id}_${idx}`,
        gameId: game.id,
        name: cs.name,
        kind: cs.kind,
        total: cs.total,
        createdAt: now,
      }));

      updateDb((prev) => ({
        ...prev,
        games: [game, ...prev.games],
        fieldDefs: [...prev.fieldDefs, ...newFieldDefs],
        recordDefs: [...prev.recordDefs, ...newRecordDefs],
        collections: [...prev.collections, ...newCollections],
      }), 'GameAdd');

      return game;
    },
    [updateDb]
  );

  const setGameStatus = useCallback(
    (gameId: string, nextStatus: Game['status'], withUndo = true) => {
      const target = db.games.find((g) => g.id === gameId);
      if (!target || target.status === nextStatus) return;
      const prevStatus = target.status;
      const now = Date.now();
      updateDb(
        (prev) => ({
          ...prev,
          games: prev.games.map((g) =>
            g.id === gameId ? { ...g, status: nextStatus, updatedAt: now } : g
          ),
        }),
        'GameStatus'
      );
      playSound('toggle_on');
      if (withUndo) {
        const label =
          nextStatus === 'BACKLOG'
            ? 'Play later'
            : nextStatus.replace('_', ' ').toLowerCase();
        pushToast({
          title: `${target.name} → ${label}`,
          subtitle: 'Status updated',
          undoFn: () => {
            updateDb((prev) => ({
              ...prev,
              games: prev.games.map((g) =>
                g.id === gameId ? { ...g, status: prevStatus, updatedAt: Date.now() } : g
              ),
            }));
          },
        });
      }
    },
    [db.games, updateDb, playSound, pushToast]
  );

  const resetToSampleFree = useCallback(() => {
    const clean = createSampleFreeDatabase();
    setDb(clean);
    setFocusedItem({
      kind: 'game',
      id: clean.games[0]?.id,
      gameId: clean.games[0]?.id,
      title: clean.games[0]?.name,
      subtitle: clean.games[0]?.platform,
      accentHex: clean.games[0]?.accentHex,
      packId: clean.games[0]?.packId,
    });
    pushToast({
      title: 'Journal reset',
      subtitle: 'Clean journal ready for your games.',
    });
  }, [pushToast]);

  const loadPreviewSample = useCallback(() => {
    const sample = createInitialDatabase();
    setDb(sample);
    const firstLeg = sample.legs[0];
    const firstGame = sample.games[0];
    setFocusedItem({
      kind: 'leg',
      id: firstLeg?.id,
      gameId: firstGame?.id,
      title: firstLeg?.title,
      subtitle: firstGame?.name,
      accentHex: firstGame?.accentHex,
      packId: firstGame?.packId,
    });
    pushToast({
      title: 'Sample data loaded',
      subtitle: 'For visual reference.',
    });
  }, [pushToast]);

  const createLegOrSession = useCallback(
    (input: Partial<Leg> & { gameId: string }): Leg => {
      const now = Date.now();
      const id = `leg_${now}_${Math.random().toString(36).slice(2, 6)}`;
      const today = new Date().toISOString().slice(0, 10);
      const existingCount = db.legs.filter((l) => l.gameId === input.gameId && !l.deletedAt).length;
      const autoTitle =
        input.originIcao && input.destIcao
          ? `${input.originIcao.toUpperCase()} → ${input.destIcao.toUpperCase()}`
          : input.title?.trim() || `Session ${existingCount + 1} · ${new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}`;

      const leg: Leg = {
        id,
        gameId: input.gameId,
        title: autoTitle,
        originIcao: input.originIcao?.toUpperCase(),
        destIcao: input.destIcao?.toUpperCase(),
        originName: input.originName,
        destName: input.destName,
        altIcao: input.altIcao?.toUpperCase(),
        status: input.status ?? 'IN_PROGRESS',
        startedAt: input.status === 'IN_PROGRESS' ? now : undefined,
        flownOn: input.flownOn ?? today,
        datePrecision: input.datePrecision ?? 'DAY',
        blockMinutes: input.blockMinutes ?? 0,
        aircraftName: input.aircraftName,
        simName: input.simName,
        callsign: input.callsign,
        loadoutId: input.loadoutId,
        distanceNm: input.distanceNm,
        cruiseAltFt: input.cruiseAltFt,
        summary: input.summary,
        createdAt: now,
        updatedAt: now,
        rev: 1,
        extras: {},
      };

      updateDb((prev) => ({
        ...prev,
        legs: [leg, ...prev.legs],
        games: prev.games.map((g) =>
          g.id === input.gameId ? { ...g, lastPlayedAt: now, updatedAt: now } : g
        ),
      }), 'SessionCreate');

      return leg;
    },
    [db.legs, updateDb]
  );

  const updateLeg = useCallback(
    (legId: string, patch: Partial<Leg>) => {
      const now = Date.now();
      const concluding = patch.status === 'COMPLETED';
      pendingSummaryTriggersRef.current.push({
        subjectType: 'LEG',
        subjectId: legId,
        delayMs: concluding ? 0 : 90_000,
        includeKeepersTake: concluding,
        includeAncestors: true,
        priority: concluding ? 100 : 40,
      });
      updateDb((prev) => {
        const nextLegs = prev.legs.map((l) =>
          l.id === legId ? { ...l, ...patch, updatedAt: now, rev: l.rev + 1 } : l
        );
        const target = nextLegs.find((l) => l.id === legId);
        const nextGames = target
          ? prev.games.map((g) => {
              if (g.id !== target.gameId) return g;
              const sumMins = nextLegs
                .filter((l) => l.gameId === g.id && !l.deletedAt)
                .reduce((acc, l) => acc + (l.blockMinutes ?? 0), 0);
              return {
                ...g,
                totalPlayMinutes: Math.max(g.totalPlayMinutes, sumMins),
                lastPlayedAt: now,
                updatedAt: now,
              };
            })
          : prev.games;
        return { ...prev, legs: nextLegs, games: nextGames };
      });
    },
    [updateDb]
  );

  const softDeleteLeg = useCallback(
    (legId: string) => {
      const now = Date.now();
      updateDb((prev) => ({
        ...prev,
        legs: prev.legs.map((l) => (l.id === legId ? { ...l, deletedAt: now } : l)),
      }), 'SoftDeleteLeg');
      pushToast({
        title: 'Moved to Trash',
        undoFn: () => {
          updateDb((prev) => ({
            ...prev,
            legs: prev.legs.map((l) => (l.id === legId ? { ...l, deletedAt: null } : l)),
          }));
        },
      });
    },
    [updateDb, pushToast]
  );

  const softDeleteGame = useCallback(
    (gameId: string) => {
      const now = Date.now();
      updateDb((prev) => ({
        ...prev,
        games: prev.games.map((g) => (g.id === gameId ? { ...g, deletedAt: now } : g)),
        legs: prev.legs.map((l) => (l.gameId === gameId ? { ...l, deletedAt: now } : l)),
        tours: prev.tours.map((t) => (t.gameId === gameId ? { ...t, deletedAt: now } : t)),
      }), 'SoftDeleteGame');
      pushToast({
        title: 'Game moved to Trash',
        undoFn: () => {
          updateDb((prev) => ({
            ...prev,
            games: prev.games.map((g) => (g.id === gameId ? { ...g, deletedAt: null } : g)),
            legs: prev.legs.map((l) => (l.gameId === gameId ? { ...l, deletedAt: null } : l)),
            tours: prev.tours.map((t) => (t.gameId === gameId ? { ...t, deletedAt: null } : t)),
          }));
        },
      });
    },
    [updateDb, pushToast]
  );

  const restoreFromTrash = useCallback(
    (kind: 'game' | 'leg' | 'tour', id: string) => {
      updateDb((prev) => {
        if (kind === 'game') {
          return {
            ...prev,
            games: prev.games.map((g) => (g.id === id ? { ...g, deletedAt: null } : g)),
            legs: prev.legs.map((l) => (l.gameId === id ? { ...l, deletedAt: null } : l)),
            tours: prev.tours.map((t) => (t.gameId === id ? { ...t, deletedAt: null } : t)),
          };
        }
        if (kind === 'leg') {
          return {
            ...prev,
            legs: prev.legs.map((l) => (l.id === id ? { ...l, deletedAt: null } : l)),
          };
        }
        return {
          ...prev,
          tours: prev.tours.map((t) => (t.id === id ? { ...t, deletedAt: null } : t)),
        };
      }, 'TrashRestore');
      pushToast({ title: 'Restored from Trash' });
    },
    [updateDb, pushToast]
  );

  const replaceDatabase = useCallback((next: JournalDatabase) => setDb({ ...next, lastSavedAt: Date.now() }), []);

  const [consentPrompt, setConsentPrompt] = useState<{
    providerName: string;
    modelName: string;
    actionLabel: string;
    onDeclineDisableAutoIndex: boolean;
    resolve: (ok: boolean) => void;
  } | null>(null);

  const upsertInsights = useCallback(
    (incoming: Insight[]) => {
      if (incoming.length === 0) return;
      updateDb((prev) => {
        let next = prev.insights;
        for (const ins of incoming) {
          if (ins.kind === 'DESCRIBE' || ins.kind === 'SUMMARY') {
            next = applyDescribeResultToInsights(next, ins);
          } else {
            const exists = next.some((x) => x.id === ins.id);
            next = exists ? next.map((x) => (x.id === ins.id ? ins : x)) : [ins, ...next];
          }
        }
        return { ...prev, insights: next };
      });
    },
    [updateDb]
  );

  // Wire InsightEngine + SummaryScheduler to live store & network changes
  useEffect(() => {
    insightEngine.registerStore(() => dbRef.current, upsertInsights, runSummaryTextJob);
    summaryScheduler.setOnFlush((trigger) => {
      if (safeMode) return;
      const current = dbRef.current;
      if (!current.settings.aiAutoSummaries) return;
      enqueueSummaryWithAncestors(current, trigger.subjectType, trigger.subjectId, {
        includeKeepersTake: trigger.includeKeepersTake,
        includeAncestors: trigger.includeAncestors,
        priority: trigger.priority,
      });
    });
    return () => {
      summaryScheduler.clearAll();
    };
  }, [upsertInsights, safeMode]);

  useEffect(() => {
    if (pendingSummaryTriggersRef.current.length === 0) return;
    const batch = pendingSummaryTriggersRef.current.splice(0, pendingSummaryTriggersRef.current.length);
    const enabled = !safeMode && dbRef.current.settings.aiAutoSummaries;
    for (const item of batch) {
      summaryScheduler.schedule(
        {
          subjectType: item.subjectType,
          subjectId: item.subjectId,
          includeKeepersTake: item.includeKeepersTake,
          includeAncestors: item.includeAncestors,
          priority: item.priority,
        },
        item.delayMs,
        enabled
      );
    }
  }, [db, safeMode]);

  useEffect(() => {
    insightEngine.onEnvironmentChanged();
  }, [
    db.settings.aiSendImages,
    db.settings.aiConsentAt,
    db.settings.aiAutoSummaries,
    db.settings.aiMaxConcurrent,
    db.settings.aiMaxImagesPerRequest,
    db.settings.connections,
    db.settings.activeConnectionId,
    db.settings.roleOverrides,
  ]);

  useEffect(() => {
    const onNet = () => insightEngine.onEnvironmentChanged();
    window.addEventListener('online', onNet);
    window.addEventListener('offline', onNet);
    return () => {
      window.removeEventListener('online', onNet);
      window.removeEventListener('offline', onNet);
    };
  }, []);

  // C6: Nightly dossier consolidation check on app open (>20h, online, opted in)
  useEffect(() => {
    if (safeMode) return;
    const current = dbRef.current;
    const isOnline = typeof navigator === 'undefined' ? true : navigator.onLine !== false;
    if (!shouldRunNightlyConsolidation(current.settings, Date.now(), isOnline)) return;

    const timer = setTimeout(() => {
      if (safeMode) return;
      const latest = dbRef.current;
      if (!shouldRunNightlyConsolidation(latest.settings, Date.now(), typeof navigator === 'undefined' ? true : navigator.onLine !== false)) {
        return;
      }
      void runDossierConsolidation(latest)
        .then((proposals) => {
          const now = Date.now();
          setDb((prev) => {
            const nextSettings = { ...prev.settings, lastConsolidationAt: now };
            if (proposals.length === 0 || prev.convos.length === 0) {
              return { ...prev, settings: nextSettings };
            }
            const keeperMsg: KeeperMessage = {
              id: `kmsg_cons_${now}`,
              convoId: prev.convos[0].id,
              seq: prev.convos[0].messages.length + 1,
              role: 'keeper',
              text: `I reviewed your Dossier and prepared ${proposals.length} tidy-up suggestion${proposals.length === 1 ? '' : 's'} for your review.`,
              createdAt: now,
              personaId: prev.settings.keeperPersonaId,
              proposals,
            };
            return {
              ...prev,
              settings: nextSettings,
              convos: prev.convos.map((c, idx) =>
                idx === 0 ? { ...c, lastMsgAt: now, messages: [...c.messages, keeperMsg] } : c
              ),
            };
          });
        })
        .catch(() => undefined);
    }, 3500);

    return () => clearTimeout(timer);
  }, []);

  const requestAiConsent = useCallback(
    (
      actionLabel = 'describe your pictures',
      onDeclineDisableAutoIndex = false,
      requiresRemoteText = false
    ): Promise<boolean> => {
      const s = dbRef.current.settings;
      if (s.aiConsentAt) return Promise.resolve(true);
      if (!requiresRemoteText) {
        if (!s.aiSendImages) return Promise.resolve(true);
        const resolved = resolveRole(s, 'vision');
        if (resolved.profile?.capabilities?.vision === false) return Promise.resolve(true);
        const providerName = resolved.profile?.provider || resolved.profile?.name || 'your AI provider';
        const modelName = resolved.modelOverride || resolved.profile?.model || 'default model';
        return new Promise<boolean>((resolve) => {
          setConsentPrompt({
            providerName,
            modelName,
            actionLabel,
            onDeclineDisableAutoIndex,
            resolve,
          });
        });
      }
      const resolved = resolveRole(s, 'summary');
      const providerName = resolved.profile?.provider || resolved.profile?.name || 'your AI provider';
      const modelName = resolved.modelOverride || resolved.profile?.model || 'default model';
      return new Promise<boolean>((resolve) => {
        setConsentPrompt({
          providerName,
          modelName,
          actionLabel,
          onDeclineDisableAutoIndex,
          resolve,
        });
      });
    },
    []
  );

  const enqueueAutoIndexIfReady = useCallback(
    (items: MediaItem[], skipAutoIndex?: boolean) => {
      if (skipAutoIndex) return;
      const s = dbRef.current.settings;
      if (!s.aiAutoIndex) return;
      const shas = items
        .filter((m) => m.aiIndex !== 'EXCLUDED' && m.source !== 'SEED' && m.source !== 'AI')
        .map((m) => m.sha256);
      if (shas.length === 0) return;

      const resolved = resolveRole(s, 'vision');
      const needsPictureConsent =
        s.aiSendImages &&
        !s.aiConsentAt &&
        resolved.profile &&
        resolved.profile.capabilities?.vision !== false;

      if (needsPictureConsent) {
        void requestAiConsent('automatically describe newly added pictures', true).then((accepted) => {
          if (accepted) {
            insightEngine.enqueueMedia(shas, { priority: 50 });
          }
        });
      } else {
        insightEngine.enqueueMedia(shas, { priority: 50 });
      }
    },
    [requestAiConsent]
  );

  const addMediaItems = useCallback(
    (
      entries: Array<{ item: MediaItem; link?: Omit<MediaLink, 'id' | 'createdAt' | 'mediaSha'> }>,
      opts?: { skipAutoIndex?: boolean }
    ) => {
      if (entries.length === 0) return;
      const now = Date.now();
      updateDb((prev) => {
        const known = new Set(prev.media.map((m) => m.sha256));
        const fresh: MediaItem[] = [];
        for (const e of entries) {
          if (!known.has(e.item.sha256)) {
            known.add(e.item.sha256);
            fresh.push(e.item);
          }
        }
        const links = [...prev.mediaLinks];
        entries.forEach((e, i) => {
          if (!e.link) return;
          const dup = links.some(
            (l) => l.mediaSha === e.item.sha256 && l.ownerType === e.link!.ownerType && l.ownerId === e.link!.ownerId
          );
          if (dup) return;
          links.push({
            ...e.link,
            id: `ml_${now}_${i}_${Math.random().toString(36).slice(2, 6)}`,
            mediaSha: e.item.sha256,
            createdAt: now,
          });
        });
        return { ...prev, media: [...fresh, ...prev.media], mediaLinks: links };
      }, 'MediaIngest');

      for (const e of entries) {
        if (e.link?.ownerType === 'LEG' && e.link.ownerId) {
          pendingSummaryTriggersRef.current.push({
            subjectType: 'LEG',
            subjectId: e.link.ownerId,
            delayMs: 90_000,
            includeAncestors: true,
            priority: 40,
          });
        }
      }

      enqueueAutoIndexIfReady(
        entries.map((e) => e.item),
        opts?.skipAutoIndex
      );
    },
    [updateDb, enqueueAutoIndexIfReady]
  );

  const addMediaItem = useCallback(
    (
      item: MediaItem,
      link?: Omit<MediaLink, 'id' | 'createdAt' | 'mediaSha'>,
      opts?: { skipAutoIndex?: boolean }
    ) => {
      const now = Date.now();
      if (link?.ownerType === 'LEG' && link.ownerId) {
        pendingSummaryTriggersRef.current.push({
          subjectType: 'LEG',
          subjectId: link.ownerId,
          delayMs: 90_000,
          includeAncestors: true,
          priority: 40,
        });
      }
      updateDb((prev) => {
        const exists = prev.media.some((m) => m.sha256 === item.sha256);
        const nextMedia = exists ? prev.media : [item, ...prev.media];
        const nextLinks = link
          ? [
              ...prev.mediaLinks,
              {
                ...link,
                id: `ml_${now}_${Math.random().toString(36).slice(2, 6)}`,
                mediaSha: item.sha256,
                createdAt: now,
              },
            ]
          : prev.mediaLinks;
        return { ...prev, media: nextMedia, mediaLinks: nextLinks };
      }, 'MediaIngest');

      enqueueAutoIndexIfReady([item], opts?.skipAutoIndex);
    },
    [updateDb, enqueueAutoIndexIfReady]
  );

  const setFieldValue = useCallback(
    (ownerType: 'SESSION' | 'GAME' | 'CAMPAIGN', ownerId: string, key: string, value: string | number | boolean | null) => {
      const now = Date.now();
      if (ownerType === 'SESSION' && ownerId) {
        pendingSummaryTriggersRef.current.push({
          subjectType: 'LEG',
          subjectId: ownerId,
          delayMs: 90_000,
          includeAncestors: true,
          priority: 40,
        });
      } else if (ownerType === 'CAMPAIGN' && ownerId) {
        pendingSummaryTriggersRef.current.push({
          subjectType: 'TOUR',
          subjectId: ownerId,
          delayMs: 0,
          includeKeepersTake: true,
          includeAncestors: true,
          priority: 100,
        });
      }
      updateDb((prev) => {
        const idx = prev.fieldValues.findIndex(
          (fv) => fv.ownerType === ownerType && fv.ownerId === ownerId && fv.key === key
        );
        const next = [...prev.fieldValues];
        if (idx >= 0) {
          next[idx] = { ownerType, ownerId, key, value, updatedAt: now };
        } else {
          next.push({ ownerType, ownerId, key, value, updatedAt: now });
        }
        return { ...prev, fieldValues: next };
      });
    },
    [updateDb]
  );

  const addGoal = useCallback(
    (input: Omit<Goal, 'id' | 'createdAt' | 'updatedAt'>) => {
      const now = Date.now();
      const done = input.done || input.state === 'DONE';
      const goal: Goal = {
        ...input,
        id: `goal_${now}_${Math.random().toString(36).slice(2, 6)}`,
        done,
        state: done ? 'DONE' : input.state,
        doneAt: done ? now : undefined,
        createdAt: now,
        updatedAt: now,
      };
      updateDb((prev) => ({ ...prev, goals: [goal, ...prev.goals] }), 'GoalAdd');
    },
    [updateDb]
  );

  const toggleGoalDone = useCallback(
    (goalId: string) => {
      const now = Date.now();
      updateDb((prev) => ({
        ...prev,
        goals: prev.goals.map((g) => {
          if (g.id !== goalId) return g;
          const nextDone = !g.done;
          return {
            ...g,
            done: nextDone,
            state: nextDone ? 'DONE' : 'ACTIVE',
            doneAt: nextDone ? now : undefined,
            updatedAt: now,
          };
        }),
      }));
    },
    [updateDb]
  );

  const addLoadout = useCallback(
    (input: Omit<Loadout, 'id' | 'createdAt' | 'updatedAt'>) => {
      const now = Date.now();
      const lo: Loadout = {
        ...input,
        id: `lo_${now}_${Math.random().toString(36).slice(2, 6)}`,
        createdAt: now,
        updatedAt: now,
      };
      updateDb((prev) => ({ ...prev, loadouts: [lo, ...prev.loadouts] }), 'LoadoutAdd');
    },
    [updateDb]
  );

  const addRecordEntry = useCallback(
    (input: Omit<RecordEntry, 'id' | 'createdAt'>) => {
      const now = Date.now();
      const rec: RecordEntry = {
        ...input,
        id: `rec_${now}_${Math.random().toString(36).slice(2, 6)}`,
        createdAt: now,
      };
      updateDb((prev) => ({ ...prev, records: [rec, ...prev.records] }), 'RecordAdd');
    },
    [updateDb]
  );

  const addPlanSnapshot = useCallback(
    (plan: PlanSnapshot) => {
      if (plan.legId) {
        pendingSummaryTriggersRef.current.push({
          subjectType: 'LEG',
          subjectId: plan.legId,
          delayMs: 0,
          includeKeepersTake: true,
          includeAncestors: true,
          priority: 100,
        });
      }
      updateDb((prev) => ({
        ...prev,
        plans: [
          plan,
          ...prev.plans.map((p) =>
            p.legId && p.legId === plan.legId && plan.isCurrent ? { ...p, isCurrent: false } : p
          ),
        ],
      }), 'PlanImport');
    },
    [updateDb]
  );

  const notifyChannel = useCallback(
    (channelId: NotificationChannelId, title: string, body: string) => {
      void maybeDispatchNotification({
        channelId,
        title,
        body,
        settings: dbRef.current.settings,
        isForeground: isForegroundRef.current,
        isSafeMode: safeMode,
      });
    },
    [safeMode]
  );

  const unlockApp = useCallback(() => {
    setAppLocked(false);
  }, []);

  const triggerQuickNote = useCallback(() => {
    setGuideOpen(true);
    setQuickNoteSignal((n) => n + 1);
  }, []);

  const openAddGame = useCallback((seed?: AddGameXboxSeed) => {
    setAddGameSeed(seed ?? null);
    setAddGameOpen(true);
  }, []);

  const closeAddGame = useCallback(() => {
    setAddGameOpen(false);
    setAddGameSeed(null);
  }, []);

  const syncXboxGameArt = useCallback(
    async (opts?: {
      force?: boolean;
      gameIds?: string[];
      silent?: boolean;
      catalogOverride?: TitleArtInfo[];
    }): Promise<{ updated: number; covers: number; wallpapers: number; failed: number }> => {
      if (xboxArtSyncInFlightRef.current) {
        return { updated: 0, covers: 0, wallpapers: 0, failed: 0 };
      }
      if (safeMode && opts?.silent) {
        return { updated: 0, covers: 0, wallpapers: 0, failed: 0 };
      }
      xboxArtSyncInFlightRef.current = true;
      try {
        const snapshot = dbRef.current;
        const catalog = await resolveXboxTitleCatalog(snapshot.games, opts?.catalogOverride);
        if (catalog.length === 0) {
          if (!opts?.silent) {
            pushToast({
              title: 'No Xbox game catalog loaded yet',
              subtitle: 'Link and refresh your Xbox profile in the Android app first.',
            });
          }
          return { updated: 0, covers: 0, wallpapers: 0, failed: 0 };
        }

        const result = await syncXboxArtForGames({
          games: snapshot.games,
          existingMedia: snapshot.media,
          catalog,
          force: opts?.force,
          gameIds: opts?.gameIds,
        });

        if (result.mediaEntries.length > 0) {
          addMediaItems(result.mediaEntries, { skipAutoIndex: true });
        }

        if (result.patches.length > 0) {
          updateDb(
            (prev) => {
              const applied = applyXboxArtUpdatesToGames(prev.games, result.patches);
              return applied.changed ? { ...prev, games: applied.games } : prev;
            },
            'XboxGameArtSync'
          );
        }

        if (!opts?.silent) {
          if (result.summary.gamesUpdated > 0) {
            const parts: string[] = [];
            if (result.summary.coversAdded > 0) {
              parts.push(`${result.summary.coversAdded} cover${result.summary.coversAdded === 1 ? '' : 's'}`);
            }
            if (result.summary.wallpapersAdded > 0) {
              parts.push(`${result.summary.wallpapersAdded} wallpaper${result.summary.wallpapersAdded === 1 ? '' : 's'}`);
            }
            pushToast({
              title: `Xbox art synced for ${result.summary.gamesUpdated} game${result.summary.gamesUpdated === 1 ? '' : 's'}`,
              subtitle: parts.join(' · ') || 'Title IDs linked',
            });
          } else if (result.summary.failed > 0) {
            pushToast({
              title: 'Could not download Xbox artwork',
              subtitle: 'Check your connection and try again.',
              kind: 'error',
            });
          } else {
            pushToast({
              title: 'All matched games already have art',
              subtitle: 'Open a game hub to swap cover or wallpaper variants.',
            });
          }
        }

        return {
          updated: result.summary.gamesUpdated,
          covers: result.summary.coversAdded,
          wallpapers: result.summary.wallpapersAdded,
          failed: result.summary.failed,
        };
      } finally {
        xboxArtSyncInFlightRef.current = false;
      }
    },
    [safeMode, addMediaItems, updateDb, pushToast]
  );

  const applyXboxGameArt = useCallback(
    async (
      gameId: string,
      opts: { coverUrl?: string; wallpaperUrl?: string; xboxTitleId?: string }
    ): Promise<{ coverSha?: string; heroSha?: string }> => {
      const snapshot = dbRef.current;
      const game = snapshot.games.find((g) => g.id === gameId);
      if (!game) throw new Error('Game not found.');

      const imported = await importSingleXboxArtChoice({
        gameName: game.name,
        coverUrl: opts.coverUrl,
        wallpaperUrl: opts.wallpaperUrl,
        existingMedia: snapshot.media,
      });

      if (imported.mediaEntries.length > 0) {
        addMediaItems(imported.mediaEntries, { skipAutoIndex: true });
      }

      const patch = {
        gameId,
        ...(imported.coverSha ? { coverMediaSha: imported.coverSha } : {}),
        ...(imported.heroSha ? { heroMediaSha: imported.heroSha } : {}),
        ...(opts.xboxTitleId ? { xboxTitleId: opts.xboxTitleId } : {}),
      };

      updateDb(
        (prev) => {
          const applied = applyXboxArtUpdatesToGames(prev.games, [patch]);
          return applied.changed ? { ...prev, games: applied.games } : prev;
        },
        'XboxGameArtChoice'
      );

      setFocusedItem((prevFocus) => {
        if (prevFocus.gameId !== gameId && prevFocus.id !== gameId) return prevFocus;
        return {
          ...prevFocus,
          coverMediaSha: imported.coverSha ?? prevFocus.coverMediaSha,
          heroMediaSha: imported.heroSha ?? imported.coverSha ?? prevFocus.heroMediaSha,
        };
      });

      return { coverSha: imported.coverSha, heroSha: imported.heroSha };
    },
    [addMediaItems, updateDb]
  );

  // Watch indexing queue drain to fire D14 indexing notification once per completed run when backgrounded
  const indexingTrackerRef = useRef<IndexingQueueTrackerState>({
    wasBusy: false,
    startDoneCount: insightEngine.getSnapshot().done,
  });
  useEffect(() => {
    return insightEngine.subscribe(() => {
      const snap = insightEngine.getSnapshot();
      const transition = evaluateIndexingQueueTransition(indexingTrackerRef.current, snap);
      indexingTrackerRef.current = transition.nextState;
      if (transition.notify && transition.processedCount > 0) {
        notifyChannel(
          'indexing',
          'Indexing finished',
          `Indexed ${transition.processedCount} item${transition.processedCount === 1 ? '' : 's'}.`
        );
      }
    });
  }, [notifyChannel]);

  // D3 Share-in inbox consumer & D13 Deep-link / launcher shortcut router
  const handleDeepLinkUrl = useCallback(
    (rawUrl: string) => {
      const lower = rawUrl.toLowerCase();
      if (lower.startsWith('greenguide://settings/')) {
        const cat = rawUrl.slice('greenguide://settings/'.length).replace(/^\/+/, '').split(/[?#]/)[0];
        if (cat) navigate({ page: 'settings', category: cat });
        return;
      }
      if (lower.startsWith('greenguide://shortcut/')) {
        const sc = rawUrl.slice('greenguide://shortcut/'.length).split(/[?#]/)[0].toLowerCase();
        if (sc === 'new-session') {
          const game = dbRef.current.games.find((g) => !g.deletedAt && g.status === 'PLAYING') ?? dbRef.current.games.find((g) => !g.deletedAt);
          if (game) {
            const leg = createLegOrSession({ gameId: game.id, status: 'IN_PROGRESS' });
            navigate({ page: 'leg', legId: leg.id });
          } else {
            navigate({ page: 'library' });
          }
        } else if (sc === 'quick-note') {
          triggerQuickNote();
        } else if (sc === 'keeper') {
          navigate({ page: 'keeper', view: 'chat' });
        } else if (sc === 'resume-tour') {
          const tour =
            dbRef.current.tours.find((t) => !t.deletedAt && (t.status === 'IN_PROGRESS' || t.status === 'PAUSED')) ??
            dbRef.current.tours.find((t) => !t.deletedAt);
          if (tour) navigate({ page: 'tour', tourId: tour.id });
          else navigate({ page: 'library', tab: 'campaigns' });
        } else if (sc === 'inbox') {
          navigate({ page: 'inbox' });
        }
      }
    },
    [navigate, createLegOrSession, triggerQuickNote]
  );

  useEffect(() => {
    const checkPendingShare = async () => {
      const payload = await consumePendingShareFromNative();
      if (!payload) return;
      const items = buildInboxItemsFromSharePayload(payload);
      if (items.length === 0) return;
      updateDb((prev) => ({
        ...prev,
        inbox: [...items, ...(prev.inbox ?? [])],
      }), 'ShareInbox');
      pushToast({
        title: `Saved ${items.length} shared item${items.length === 1 ? '' : 's'} to Inbox`,
        subtitle: 'Open Guide → Inbox to file or convert to note.',
      });
      navigate({ page: 'inbox' });
    };

    void checkPendingShare();

    // Check URL query shortcut (?shortcut=... or ?settings=...)
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const sc = params.get('shortcut');
      const st = params.get('settings');
      if (sc) handleDeepLinkUrl(`greenguide://shortcut/${sc}`);
      else if (st) handleDeepLinkUrl(`greenguide://settings/${st}`);
    }

    if (!Capacitor.isNativePlatform()) return;
    void CapacitorApp.getLaunchUrl()
      .then((res) => {
        if (res?.url) handleDeepLinkUrl(res.url);
      })
      .catch(() => undefined);

    const listener = CapacitorApp.addListener('appUrlOpen', ({ url }) => {
      if (url) handleDeepLinkUrl(url);
      void checkPendingShare();
    });
    const resumeListener = CapacitorApp.addListener('appStateChange', ({ isActive }) => {
      if (isActive) void checkPendingShare();
    });

    return () => {
      void listener.then((l) => l.remove()).catch(() => undefined);
      void resumeListener.then((l) => l.remove()).catch(() => undefined);
    };
  }, [handleDeepLinkUrl, navigate, pushToast, updateDb]);

  const addRecap = useCallback(
    (recap: RecapDoc) => {
      updateDb((prev) => ({ ...prev, recaps: [recap, ...prev.recaps] }), 'RecapCreate');
      notifyChannel('recap', 'Recap ready', `"${recap.title}" is ready to view.`);
    },
    [updateDb, notifyChannel]
  );

  const appendKeeperTurn = useCallback(
    (convoId: string, userMsg: KeeperMessage, keeperMsg: KeeperMessage, patches: DossierPatchOp[] = []) => {
      updateDb((prev) => {
        const exists = prev.convos.some((c) => c.id === convoId);
        const nextConvos = exists
          ? prev.convos.map((c) =>
              c.id === convoId
                ? {
                    ...c,
                    lastMsgAt: keeperMsg.createdAt,
                    messages: [...c.messages, userMsg, keeperMsg],
                  }
                : c
            )
          : [
              {
                id: convoId,
                title: userMsg.text.slice(0, 46) || 'Keeper Session',
                personaId: prev.settings.keeperPersonaId,
                model: prev.settings.keeperModel,
                createdAt: userMsg.createdAt,
                lastMsgAt: keeperMsg.createdAt,
                messages: [userMsg, keeperMsg],
              },
              ...prev.convos,
            ];

        let nextChronicle = appendChronicleEntry(
          prev.chronicleFiles,
          {
            id: userMsg.id,
            convoId,
            seqInConvo: userMsg.seq,
            role: 'Player',
            text: userMsg.text,
            ts: new Date(userMsg.createdAt).toISOString(),
          },
          { maxKb: prev.settings.chronicleMaxKb, maxEntries: prev.settings.chronicleMaxEntries }
        );

        nextChronicle = appendChronicleEntry(
          nextChronicle,
          {
            id: keeperMsg.id,
            convoId,
            seqInConvo: keeperMsg.seq,
            role: 'Keeper',
            text: keeperMsg.text,
            ts: new Date(keeperMsg.createdAt).toISOString(),
          },
          { maxKb: prev.settings.chronicleMaxKb, maxEntries: prev.settings.chronicleMaxEntries }
        );

        const hasFlight = prev.games.some((g) => g.packId === 'flight' && !g.deletedAt);
        const dossierRes =
          prev.settings.aiMemoryPass && patches.length > 0
            ? applyDossierPatches(prev.dossier, patches, prev.settings.playerTag, hasFlight)
            : { dossier: prev.dossier, appliedCount: 0, skippedLockedCount: 0 };

        return {
          ...prev,
          convos: nextConvos,
          chronicleFiles: nextChronicle,
          dossier: dossierRes.dossier,
        };
      }, 'KeeperTurn');
    },
    [updateDb]
  );

  const recordChronicleEvent = useCallback(
    (convoId: string, text: string) => {
      updateDb((prev) => {
        const eventEntry: ChronicleEntry = {
          id: `ce_ev_${Date.now()}`,
          convoId,
          seqInConvo: 0,
          role: 'Event',
          text,
          ts: new Date().toISOString(),
        };
        const nextChronicle = appendChronicleEntry(prev.chronicleFiles, eventEntry, {
          maxKb: prev.settings.chronicleMaxKb,
          maxEntries: prev.settings.chronicleMaxEntries,
        });
        const nextConvos = prev.convos.map((c) =>
          c.id === convoId
            ? {
                ...c,
                messages: [
                  ...c.messages,
                  {
                    id: eventEntry.id,
                    convoId,
                    seq: c.messages.length + 1,
                    role: 'event' as const,
                    text,
                    createdAt: Date.now(),
                  },
                ],
              }
            : c
        );
        return { ...prev, chronicleFiles: nextChronicle, convos: nextConvos };
      });
    },
    [updateDb]
  );

  const addLog = useCallback(
    (entry: Omit<AppLogEntry, 'id' | 'ts'>) => {
      const now = Date.now();
      setDb((prev) => ({
        ...prev,
        logs: [
          { ...entry, id: `log_${now}_${Math.random().toString(36).slice(2, 5)}`, ts: now },
          ...prev.logs.slice(0, 150),
        ],
      }));
    },
    []
  );

  const value: JournalContextValue = {
    db,
    ledger,
    isNight,
    palette,
    route,
    canGoBack: stack.length > 1 || guideOpen || immersive,
    guideOpen,
    immersive,
    focusedItem,
    toasts,
    lastSavedTick,
    navigate,
    goBack,
    setGuideOpen,
    setImmersive,
    setFocusedItem,
    playSound,
    pushToast,
    dismissToast,
    updateDb,
    updateSettings,
    saveNow,
    addGame,
    setGameStatus,
    resetToSampleFree,
    loadPreviewSample,
    createLegOrSession,
    updateLeg,
    softDeleteLeg,
    softDeleteGame,
    restoreFromTrash,
    addMediaItem,
    addMediaItems,
    upsertInsights,
    requestAiConsent,
    replaceDatabase,
    setFieldValue,
    addGoal,
    toggleGoalDone,
    addLoadout,
    addRecordEntry,
    addPlanSnapshot,
    addRecap,
    appendKeeperTurn,
    recordChronicleEvent,
    addLog,
    isForeground,
    isSafeMode: safeMode,
    safeModeReason,
    appLocked,
    unlockApp,
    quickNoteSignal,
    triggerQuickNote,
    notifyChannel,
    addGameOpen,
    addGameSeed,
    openAddGame,
    closeAddGame,
    syncXboxGameArt,
    applyXboxGameArt,
    xboxProfile,
    activeProfile,
    setXboxProfile,
    refreshXboxProfileState,
  };

  return (
    <JournalContext.Provider value={value}>
      {children}
      {consentPrompt && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-label="Confirm sending to AI provider"
        >
          <div className="w-full max-w-md rounded-2xl border border-[var(--gg-divider)] bg-[var(--gg-bg-panel)] p-5 space-y-4 shadow-2xl">
            <h2 className="text-base font-semibold text-[var(--gg-text-primary)]">
              Confirm sending to {consentPrompt.providerName}
            </h2>
            <p className="text-xs leading-relaxed text-[var(--gg-text-broadcast)]">
              Keeper will send small copies of your pictures and short note text to{' '}
              <strong>{consentPrompt.providerName}</strong> ({consentPrompt.modelName}) to{' '}
              {consentPrompt.actionLabel}. Embedded location data is removed from images before sending.
            </p>
            <p className="text-[11px] text-[var(--gg-text-secondary)]">
              You can turn off picture sending or auto-indexing at any time in Settings.
            </p>
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => {
                  const p = consentPrompt;
                  setConsentPrompt(null);
                  if (p.onDeclineDisableAutoIndex) {
                    updateSettings({ aiAutoIndex: false });
                  }
                  p.resolve(false);
                }}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-[var(--gg-surface-control)] text-[var(--gg-text-primary)]"
              >
                Not now
              </button>
              <button
                type="button"
                onClick={() => {
                  const p = consentPrompt;
                  setConsentPrompt(null);
                  updateSettings({ aiConsentAt: Date.now() });
                  p.resolve(true);
                }}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-[var(--gg-accent)] text-white"
              >
                Allow sending
              </button>
            </div>
          </div>
        </div>
      )}
    </JournalContext.Provider>
  );
}

export function useJournal(): JournalContextValue {
  const ctx = useContext(JournalContext);
  if (!ctx) throw new Error('useJournal must be used inside JournalProvider');
  return ctx;
}
