import React, { useMemo, useState, useEffect } from 'react';
import { useJournal } from '../state/JournalStore';
import { ACCENT_PRESETS, hslToHex } from '../logic/theme';
import {
  emptyTrashSafely,
  exportBackup,
  restoreBackup,
  runIntegrityCheck,
  type BackupArchive,
} from '../logic/backup';
import { ConnectionsEditor } from '../components/ConnectionsEditor';
import { WallpaperSettings } from '../components/WallpaperSettings';
import { CHANGELOG_MD } from '../data/bundledModules';
import { SEEDED_MSFS_GAME } from '../data/seedData';
import { PlayerAvatar } from '../components/PlayerAvatar';
import { session } from '../logic/xbox/session';
import { clearCachedXboxCaptures } from '../logic/xbox/indexer';
import {
  saveCachedXboxProfile,
  clearCachedXboxProfile,
  refreshXboxProfile,
  type XboxProfileSnapshot,
} from '../logic/xbox/profile';
import { startBrowserSignIn, requestDeviceCode, pollDeviceCode } from '../logic/xbox/msAuth';
import { exchangeUserToken, exchangeXstsToken } from '../logic/xbox/xblAuth';
import { saveXboxTokens } from '../logic/xbox/tokenStore';
import { Browser } from '@capacitor/browser';
import { Capacitor } from '@capacitor/core';
import { XboxProfileCard } from '../components/XboxProfileCard';
import { PermissionsSetupModal } from '../components/PermissionsSetupModal';
import { checkAllPermissions, type AppPermission, type PermissionState } from '../logic/permissions';
import { hasPreMigrationBackup, getPreMigrationBackup } from '../logic/persist';
import { runDossierConsolidation } from '../logic/dossierConsolidation';
import type { AppSettings, KeeperMessage, NotificationChannelId, SettingsPreset } from '../types/journal';
import {
  normalizeTagName,
  findTagByName,
  renameTag,
  mergeTags,
} from '../logic/tags';
import {
  collectJournalRegistries,
  mergeRegistryAlias,
  removeRegistryAlias,
} from '../logic/registries';
import {
  BUILT_IN_PRESETS,
  createSettingsPreset,
  applyPresetToSettings,
  exportPresetJson,
  parsePresetImport,
} from '../logic/settingsPresets';
import {
  NOTIFICATION_CHANNEL_META,
  isChannelEnabled,
  requestNotificationPermissionAndEnsureChannel,
} from '../logic/notifications';
import { APP_VERSION, APP_DISPLAY_VERSION } from '../version';
import { isBiometricSupported } from '../logic/appLock';
import { buildMarkdownVaultZip } from '../logic/markdownExport';
import {
  getCrashLogs,
  clearCrashLogs,
  exportCrashLogsText,
  getBootTraces,
  isSafeModeRequested,
  setSafeModeRequested,
  exitSafeMode,
} from '../logic/crashLog';
import {
  fetchLatestRelease,
  openApkDownload,
  type ReleaseInfo,
} from '../logic/updateChecker';
import {
  createRecoveryPoint,
  getRecoveryPoints,
  deleteRecoveryPoint,
  loadRecoveryPointPayload,
  type RecoveryPoint,
} from '../logic/autoBackup';
import {
  rebuildThumbnails,
  rebuildSearchIndexes,
  clearNonDataCaches,
} from '../logic/maintenance';
import {
  parseModuleMarkdown,
  quarantineModule,
  unquarantineModule,
  getQuarantinedModules,
} from '../logic/modulesAudit';
import { KeyboardCheatsheetModal } from '../components/KeyboardCheatsheetModal';
import {
  Check,
  Download,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
  Upload,
  Volume2,
  Gamepad2,
  ShieldAlert,
  Sparkles,
  Layers,
  Lock,
  Tag as TagIcon,
  Bell,
  RefreshCw,
  Copy,
  Info,
} from 'lucide-react';

const CATEGORIES = [
  { id: 'appearance', label: 'Appearance & Theme', keywords: 'theme accent dark light colors scale' },
  { id: 'xbox', label: 'Xbox Live & Profile', keywords: 'xbox live profile gamertag gamerscore gamerpic client id sync' },
  { id: 'wallpaper', label: 'Wallpaper', keywords: 'background photo blur dim scrim' },
  { id: 'presets', label: 'Presets', keywords: 'theme preset style layout backup looks' },
  { id: 'journal', label: 'Journal & Registries', keywords: 'tags aliases aircraft sim aircraft registry memories anniversary' },
  { id: 'notifications', label: 'Notifications', keywords: 'alerts background sync recap export' },
  { id: 'privacy', label: 'Privacy & Lock', keywords: 'app lock biometrics pin security' },
  { id: 'controls', label: 'Controls & Display', keywords: 'controller gamepad touch keyboard fps cheatsheet nintendo ab fast tap' },
  { id: 'games', label: 'Games & SimBrief', keywords: 'simbrief pilot username prefetch facets units' },
  { id: 'keeper', label: 'Keeper & AI', keywords: 'ai llm indexing vision prompt summaries dossier tokens usage' },
  { id: 'backup', label: 'Data & Backup', keywords: 'export import markdown recovery points maintenance thumbnails integrity trash' },
  { id: 'updates', label: 'Updates', keywords: 'github version apk release notes channel' },
  { id: 'modules', label: 'Modules', keywords: 'custom markdown extensions quarantine prompt' },
  { id: 'system', label: 'System, Logs & About', keywords: 'crashes boot trace safe mode device diagnostics licences about' },
  { id: 'whatsnew', label: "What's New", keywords: 'changelog release notes log history' },
];

export function SettingsPage({ initialCategory = 'appearance' }: { initialCategory?: string }) {
  const {
    db,
    navigate,
    isNight,
    updateSettings,
    updateDb,
    saveNow,
    restoreFromTrash,
    resetToSampleFree,
    loadPreviewSample,
    playSound,
    pushToast,
    notifyChannel,
    replaceDatabase,
    isSafeMode,
    xboxProfile,
    activeProfile,
    setXboxProfile,
    refreshXboxProfileState,
    syncXboxGameArt,
  } = useJournal();

  // Xbox profile editor state
  const [xboxTagInput, setXboxTagInput] = useState('');
  const [xboxScoreInput, setXboxScoreInput] = useState('');
  const [xboxTierInput, setXboxTierInput] = useState('GOLD');
  const [xboxAvatarInput, setXboxAvatarInput] = useState('');
  const [xboxHoursInput, setXboxHoursInput] = useState('');
  const [xboxBusy, setXboxBusy] = useState(false);
  const [xboxStatusMsg, setXboxStatusMsg] = useState('');
  const [xboxError, setXboxError] = useState('');
  const [xboxDeviceCode, setXboxDeviceCode] = useState<{ userCode: string; verificationUri: string; deviceCode: string; interval: number; expiresIn: number } | null>(null);

  useEffect(() => {
    if (xboxProfile) {
      setXboxTagInput(xboxProfile.gamertag || db.settings.playerTag);
      setXboxScoreInput(String(xboxProfile.gamerscore ?? 0));
      setXboxTierInput(xboxProfile.tier || 'GOLD');
      setXboxAvatarInput(xboxProfile.avatarUrl || '');
      setXboxHoursInput(String(Math.round((xboxProfile.totalMinutes ?? 0) / 60)));
    } else {
      setXboxTagInput(db.settings.playerTag || '');
      setXboxScoreInput('0');
      setXboxTierInput('GOLD');
      setXboxAvatarInput('');
      setXboxHoursInput(String(Math.round(db.legs.reduce((acc, l) => acc + (l.durationMin || 0), 0) / 60)));
    }
  }, [xboxProfile, db.settings.playerTag, db.legs]);

  const safeCategory = (id?: string) => (CATEGORIES.some((c) => c.id === id) ? (id as string) : 'appearance');
  const [category, setCategory] = useState(() => safeCategory(initialCategory));
  useEffect(() => {
    setCategory(safeCategory(initialCategory));
  }, [initialCategory]);
  const hasUnreadWhatsNew = db.settings.whatsNewLastSeenVersion !== APP_VERSION;
  useEffect(() => {
    if (category === 'whatsnew' && db.settings.whatsNewLastSeenVersion !== APP_VERSION) {
      updateSettings({ whatsNewLastSeenVersion: APP_VERSION });
    }
  }, [category, db.settings.whatsNewLastSeenVersion, updateSettings]);
  const [filterText, setFilterText] = useState('');
  const [restoreCandidate, setRestoreCandidate] = useState<BackupArchive | null>(null);
  const [integrityReport, setIntegrityReport] = useState<{ healthy: boolean; issues: string[] } | null>(null);
  const [selectedModuleId, setSelectedModuleId] = useState(db.modules[0]?.id || '');
  const [xboxStatus, setXboxStatus] = useState<{ signedIn: boolean; gamertag?: string; lastSyncAt?: number }>({ signedIn: false });
  useEffect(() => { session.getSessionStatus().then(setXboxStatus).catch(() => undefined); }, []);

  const handleSaveXboxProfile = async () => {
    setXboxBusy(true);
    setXboxError('');
    try {
      const hours = Math.max(0, Number(xboxHoursInput) || 0);
      const score = Math.max(0, Number(xboxScoreInput) || 0);
      const tag = xboxTagInput.trim() || 'Player';
      const snap: XboxProfileSnapshot = {
        fetchedAt: Date.now(),
        xuid: xboxProfile?.xuid || 'manual_xbox',
        gamertag: tag,
        displayName: tag,
        avatarUrl: xboxAvatarInput.trim() || undefined,
        gamerscore: score,
        tier: xboxTierInput.trim() || 'GOLD',
        reputation: 'GoodPlayer',
        gamesPlayed: xboxProfile?.gamesPlayed || db.games.filter((g) => !g.deletedAt).length,
        totalMinutes: Math.round(hours * 60),
        gamesWithTime: xboxProfile?.gamesWithTime || 1,
        titles: xboxProfile?.titles || [],
      };
      await setXboxProfile(snap);
      updateSettings({ playerTag: tag });
      playSound('save');
      pushToast({
        title: 'Xbox profile updated',
        subtitle: `${tag} · G ${score.toLocaleString()}`,
      });
    } catch (e: any) {
      setXboxError(e?.message || 'Could not save profile');
    } finally {
      setXboxBusy(false);
    }
  };

  const handleStartDeviceCode = async () => {
    const clientId = db.settings.xboxClientId || (import.meta as any).env?.VITE_MS_CLIENT_ID || '';
    if (!clientId) {
      setXboxError('Please configure your Azure Application (Client) ID below first.');
      return;
    }
    setXboxBusy(true);
    setXboxError('');
    setXboxStatusMsg('Requesting sign-in code…');
    try {
      const code = await requestDeviceCode(clientId);
      setXboxDeviceCode(code);
      try {
        await navigator.clipboard.writeText(code.userCode);
      } catch {}
      try {
        await Browser.open({ url: code.verificationUri });
      } catch {
        window.open(code.verificationUri, '_blank');
      }
      setXboxStatusMsg(`Enter code ${code.userCode} at Microsoft sign-in…`);
      const tokens = await pollDeviceCode(
        clientId,
        code.deviceCode,
        code.interval,
        code.expiresIn,
        (msg) => setXboxStatusMsg(msg)
      );
      setXboxStatusMsg('Connecting to Xbox Live…');
      const user = await exchangeUserToken(tokens.accessToken);
      const xsts = await exchangeXstsToken(user.token);
      await saveXboxTokens({
        clientId,
        msRefreshToken: tokens.refreshToken,
        msAccessToken: tokens.accessToken,
        xstsToken: xsts.xstsToken,
        uhs: xsts.uhs,
        xuid: xsts.xuid,
        gamertag: xsts.gamertag,
        xstsIssuedAt: xsts.issuedAt,
        xstsExpiresAt: xsts.expiresAt,
      });
      const liveSnap = await refreshXboxProfileState();
      if (liveSnap?.gamertag) {
        updateSettings({ playerTag: liveSnap.gamertag });
      }
      setXboxDeviceCode(null);
      setXboxStatus({ signedIn: true, gamertag: xsts.gamertag });
      playSound('save');
      pushToast({ title: `Xbox linked: ${xsts.gamertag}` });
    } catch (e: any) {
      setXboxError(e?.message || 'Device sign-in failed');
    } finally {
      setXboxBusy(false);
      setXboxStatusMsg('');
    }
  };

  const handleBrowserSignIn = async () => {
    const clientId = db.settings.xboxClientId || (import.meta as any).env?.VITE_MS_CLIENT_ID || '';
    if (!clientId) {
      setXboxError('Please configure your Azure Application (Client) ID below first.');
      return;
    }
    setXboxBusy(true);
    setXboxError('');
    try {
      const ms = await startBrowserSignIn(clientId);
      const user = await exchangeUserToken(ms.accessToken);
      const xsts = await exchangeXstsToken(user.token);
      await saveXboxTokens({
        clientId,
        msRefreshToken: ms.refreshToken,
        msAccessToken: ms.accessToken,
        xstsToken: xsts.xstsToken,
        uhs: xsts.uhs,
        xuid: xsts.xuid,
        gamertag: xsts.gamertag,
        xstsIssuedAt: xsts.issuedAt,
        xstsExpiresAt: xsts.expiresAt,
      });
      const liveSnap = await refreshXboxProfileState();
      if (liveSnap?.gamertag) {
        updateSettings({ playerTag: liveSnap.gamertag });
      }
      setXboxStatus({ signedIn: true, gamertag: xsts.gamertag });
      playSound('save');
      pushToast({ title: `Xbox linked: ${xsts.gamertag}` });
    } catch (e: any) {
      setXboxError(e?.message || 'Xbox sign-in failed.');
    } finally {
      setXboxBusy(false);
    }
  };

  const handleUnlinkXbox = async () => {
    if (confirm('Disconnect Xbox profile and revert to journal player settings?')) {
      await session.signOut();
      await setXboxProfile(null);
      await clearCachedXboxCaptures();
      setXboxStatus({ signedIn: false });
      playSound('trash');
      pushToast({ title: 'Xbox profile disconnected' });
    }
  };

  const [permRows, setPermRows] = useState<Array<{ perm: AppPermission; state: PermissionState }> | null>(null);
  const [showPerms, setShowPerms] = useState(false);
  const [hasSnapshot, setHasSnapshot] = useState(false);
  useEffect(() => { void hasPreMigrationBackup().then(setHasSnapshot).catch(() => undefined); }, []);
  const loadPerms = async () => setPermRows(await checkAllPermissions());

  // Biometrics check
  const [bioInfo, setBioInfo] = useState<{ available: boolean; label: string }>({ available: false, label: 'Checking...' });
  useEffect(() => { void isBiometricSupported().then(setBioInfo); }, []);

  // Presets state
  const [newPresetName, setNewPresetName] = useState('');

  // Markdown export progress state
  const [mdExportProgress, setMdExportProgress] = useState<string | null>(null);

  // Maintenance state
  const [thumbProgress, setThumbProgress] = useState<string | null>(null);
  const [recoveryPoints, setRecoveryPoints] = useState<RecoveryPoint[]>([]);
  useEffect(() => { void getRecoveryPoints().then(setRecoveryPoints); }, []);

  // Updates state
  const [updateInfo, setUpdateInfo] = useState<ReleaseInfo | null>(null);
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(false);

  // Advanced typed reset state
  const [resetConfirmText, setResetConfirmText] = useState('');
  const [showCheatsheet, setShowCheatsheet] = useState(false);

  // Tag manager state
  const [editingTagId, setEditingTagId] = useState<string | null>(null);
  const [editingTagName, setEditingTagName] = useState('');
  const [editingTagColor, setEditingTagColor] = useState('');
  const [logsTab, setLogsTab] = useState<'crash' | 'boot'>('crash');
  const [safeModeReq, setSafeModeReq] = useState(() => isSafeModeRequested());
  const [, setCrashLogTick] = useState(0);
  const [mergeTargetTagId, setMergeTargetTagId] = useState('');

  // Version 7-tap counter
  const [verTapCount, setVerTapCount] = useState(0);

  // Refresh rate measurement
  const [measuredHz, setMeasuredHz] = useState<number | null>(null);
  useEffect(() => {
    let frames = 0;
    const start = performance.now();
    let animId: number;
    const loop = (now: number) => {
      frames++;
      if (now - start >= 600) {
        setMeasuredHz(Math.round((frames * 1000) / (now - start)));
      } else {
        animId = requestAnimationFrame(loop);
      }
    };
    animId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(animId);
  }, []);

  const trashedGames = db.games.filter((g) => Boolean(g.deletedAt));
  const trashedLegs = db.legs.filter((l) => Boolean(l.deletedAt));
  const trashedTours = db.tours.filter((t) => Boolean(t.deletedAt));
  const selectedModule = db.modules.find((m) => m.id === selectedModuleId) ?? db.modules[0];

  const filteredCategories = useMemo(() => {
    const q = filterText.trim().toLowerCase();
    if (!q) return CATEGORIES;
    return CATEGORIES.filter(
      (c) => c.label.toLowerCase().includes(q) || c.id.includes(q) || c.keywords.includes(q)
    );
  }, [filterText]);

  // Handle Export Full Backup (.greenguide)
  const handleExportBackup = async () => {
    const archive = await exportBackup(db, true);
    const json = JSON.stringify(archive, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `green-guide-backup-${new Date().toISOString().slice(0, 10)}.greenguide`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    updateDb((prev) => ({ ...prev, lastBackupAt: Date.now() }));
    playSound('save');
    pushToast({ title: 'Backup exported', subtitle: `${db.games.length} games included` });
    notifyChannel('backup', 'Backup finished', `Exported backup (${db.games.length} games).`);
  };

  // Handle Export as Markdown Vault (.zip)
  const handleExportMarkdown = async () => {
    try {
      setMdExportProgress('Generating markdown vault...');
      const { blob, fileCount } = await buildMarkdownVaultZip(db, {
        includeMediaFiles: true,
        onProgress: (_done, _total, stage) => setMdExportProgress(stage),
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `green-guide-vault-${new Date().toISOString().slice(0, 10)}.zip`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMdExportProgress(null);
      playSound('save');
      pushToast({ title: 'Markdown vault exported', subtitle: `${fileCount} files created` });
      notifyChannel('backup', 'Backup finished', `Exported Markdown vault (${fileCount} files).`);
    } catch (err) {
      setMdExportProgress(null);
      pushToast({ title: 'Export failed', subtitle: err instanceof Error ? err.message : 'Unknown error', kind: 'error' });
    }
  };

  const handleArchiveUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    file.text().then((txt) => {
      try {
        const parsed = JSON.parse(txt) as BackupArchive;
        if (!parsed?.data) throw new Error('Invalid archive');
        setRestoreCandidate(parsed);
      } catch {
        pushToast({ title: 'Could not read backup file', kind: 'error' });
      }
    });
  };

  const executeRestore = async (mode: 'MERGE' | 'REPLACE') => {
    if (!restoreCandidate) return;
    await createRecoveryPoint(db, 'PRE_RESTORE', 'Snapshot before backup restore');
    restoreBackup(db, restoreCandidate, mode, SEEDED_MSFS_GAME).then((res) => {
      updateDb(() => res.db, `Restore_${mode}`);
      setRestoreCandidate(null);
      pushToast({
        title: `Backup restored (${mode})`,
        subtitle: res.warnings[0] || 'Archive verified & applied.',
      });
    });
  };

  const handleCheckUpdates = async () => {
    setIsCheckingUpdate(true);
    try {
      const rel = await fetchLatestRelease(
        db.settings.updateRepo || 'contrail/green-guide',
        db.settings.updateChannel || 'STABLE',
        APP_VERSION
      );
      setUpdateInfo(rel);
      updateSettings({ lastUpdateCheckAt: Date.now() });
      if (rel && rel.isNewer) {
        pushToast({ title: `Update found: v${rel.version}` });
      } else {
        pushToast({ title: 'Green Guide is up to date' });
      }
    } catch (err) {
      pushToast({ title: 'Check failed', subtitle: err instanceof Error ? err.message : 'Network error', kind: 'error' });
    } finally {
      setIsCheckingUpdate(false);
    }
  };

  const handleVerClick = () => {
    const next = verTapCount + 1;
    setVerTapCount(next);
    if (next >= 7) {
      updateSettings({ devOptions: !db.settings.devOptions });
      pushToast({ title: db.settings.devOptions ? 'Developer options disabled' : 'Developer options enabled!' });
      setVerTapCount(0);
    }
  };

  const registries = useMemo(() => collectJournalRegistries(db), [db]);

  return (
    <div className="space-y-5 pb-24 animate-fade-in">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-light text-[var(--gg-text-primary)] tracking-tight">
            Settings
          </h1>
          <p className="text-xs text-[var(--gg-text-secondary)]">
            {isSafeMode ? 'Safe Mode active · ' : ''}
            {isNight ? 'Night mode active' : 'Day mode active'}
          </p>
        </div>

        <input
          type="text"
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
          placeholder="Search settings..."
          className="px-3 py-1.5 rounded-xl text-xs bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] w-56 text-[var(--gg-text-primary)] focus:outline-none focus:border-[var(--gg-focus-ring)]"
        />
      </div>

      {/* Narrow Screen Horizontal Scrolling Chip Row */}
      <div className="flex md:hidden overflow-x-auto gap-1.5 pb-2 -mx-1 px-1 no-scrollbar">
        {filteredCategories.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => {
              playSound('focus_move');
              setCategory(c.id);
            }}
            className={`whitespace-nowrap px-3 py-1.5 rounded-full text-xs font-semibold transition-colors inline-flex items-center gap-1.5 ${
              category === c.id
                ? 'bg-[var(--gg-accent)] text-white shadow'
                : 'bg-[var(--gg-bg-raised)] text-[var(--gg-text-secondary)] border border-[var(--gg-divider)]'
            }`}
          >
            <span>{c.label}</span>
            {c.id === 'whatsnew' && hasUnreadWhatsNew && (
              <span className="w-2 h-2 rounded-full bg-[#9BF00B] shrink-0" title="Unread" />
            )}
          </button>
        ))}
      </div>

      {/* Main Split-Pane Layout */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-5 items-start">
        {/* Desktop Sidebar */}
        <aside className="hidden md:block space-y-1 bg-[var(--gg-bg-raised)] p-2 rounded-2xl border border-[var(--gg-divider)]">
          {filteredCategories.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => {
                playSound('focus_move');
                setCategory(c.id);
              }}
              className={`w-full text-left px-3 py-2 rounded-xl text-xs font-semibold transition-colors flex items-center justify-between ${
                category === c.id
                  ? 'bg-[var(--gg-accent)] text-white shadow'
                  : 'text-[var(--gg-text-secondary)] hover:bg-white/10 hover:text-[var(--gg-text-primary)]'
              }`}
            >
              <span>{c.label}</span>
              {c.id === 'whatsnew' && hasUnreadWhatsNew && (
                <span className="w-2 h-2 rounded-full bg-[#9BF00B] shrink-0" title="Unread" />
              )}
            </button>
          ))}
        </aside>

        {/* Category Details Panel */}
        <section className="md:col-span-3 p-5 rounded-2xl bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-5">
          {/* APPEARANCE */}
          {category === 'appearance' && (
            <div className="space-y-5">
              <div className="space-y-2">
                <div className="flex items-center justify-between max-w-xs">
                  <label className="block text-xs font-semibold">Player Tag</label>
                  {activeProfile.isXboxLinked && (
                    <span className="text-[11px] text-[var(--gg-accent)] font-medium">
                      Xbox linked
                    </span>
                  )}
                </div>
                <input
                  type="text"
                  value={xboxStatus.signedIn ? activeProfile.playerTag : db.settings.playerTag}
                  readOnly={xboxStatus.signedIn}
                  onChange={(e) => updateSettings({ playerTag: e.target.value })}
                  className="px-3 py-2 rounded-xl text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] w-full max-w-xs text-[var(--gg-text-primary)] read-only:opacity-70"
                />
                {xboxStatus.signedIn && (
                  <p className="text-[11px] text-[var(--gg-text-tertiary)] max-w-xs">
                    Using your Xbox gamertag. Disconnect Xbox to type a different tag.
                  </p>
                )}
                {activeProfile.isXboxLinked && !xboxStatus.signedIn && activeProfile.playerTag !== db.settings.playerTag && (
                  <button
                    type="button"
                    onClick={() => updateSettings({ playerTag: activeProfile.playerTag })}
                    className="text-xs text-[var(--gg-accent)] hover:underline block"
                  >
                    Sync with Xbox gamertag ({activeProfile.playerTag})
                  </button>
                )}
              </div>

              <button
                type="button"
                onClick={() => setCategory('xbox')}
                className="w-full max-w-xs text-left px-3 py-2.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-sm hover:bg-white/10 flex items-center justify-between"
              >
                <div>
                  <div className="font-semibold text-[var(--gg-text-primary)]">Xbox Profile &amp; Stats</div>
                  <div className="text-xs text-[var(--gg-text-secondary)]">
                    {activeProfile.isXboxLinked
                      ? `${activeProfile.playerTag} · G ${activeProfile.gamerscore?.toLocaleString() ?? 0}`
                      : 'Connect your Xbox gamertag and stats'}
                  </div>
                </div>
                <span className="text-xs text-[var(--gg-accent)]">Manage</span>
              </button>

              <button
                type="button"
                onClick={() => setCategory('wallpaper')}
                className="w-full max-w-xs text-left px-3 py-2.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-sm hover:bg-white/10"
              >
                <div className="font-semibold text-[var(--gg-text-primary)]">Wallpaper</div>
                <div className="text-xs text-[var(--gg-text-secondary)]">Change picture, dimming, and blur</div>
              </button>

              <div className="space-y-2">
                <div className="text-xs font-semibold">Day / Night Theme Mode</div>
                <div className="flex flex-wrap gap-2">
                  {(['NIGHT', 'DAY', 'AUTO_CLOCK', 'SYSTEM'] as AppSettings['themeMode'][]).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => {
                        updateSettings({ themeMode: mode });
                        playSound('toggle_on');
                      }}
                      className={`px-3 py-1.5 rounded-xl text-xs font-medium ${
                        db.settings.themeMode === mode
                          ? 'bg-[var(--gg-accent)] text-white shadow'
                          : 'bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)]'
                      }`}
                    >
                      {mode.replace('_', ' ')}
                    </button>
                  ))}
                </div>
                {db.settings.themeMode === 'AUTO_CLOCK' && (
                  <div className="flex flex-wrap gap-4 pt-2 text-xs">
                    <label className="flex items-center gap-2">
                      <span>Day starts</span>
                      <input
                        type="time"
                        value={db.settings.dayStart}
                        onChange={(e) => updateSettings({ dayStart: e.target.value })}
                        className="px-2 py-1 rounded-lg bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                      />
                    </label>
                    <label className="flex items-center gap-2">
                      <span>Night starts</span>
                      <input
                        type="time"
                        value={db.settings.nightStart}
                        onChange={(e) => updateSettings({ nightStart: e.target.value })}
                        className="px-2 py-1 rounded-lg bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                      />
                    </label>
                  </div>
                )}
              </div>

              {/* Accent Colours */}
              <div className="space-y-3">
                <div className="text-xs font-semibold">Console Accent Color (12 Presets + Custom Slider)</div>
                <div className="flex flex-wrap gap-2">
                  {ACCENT_PRESETS.map((p) => {
                    const active = db.settings.accentHex.toLowerCase() === p.hex.toLowerCase();
                    return (
                      <button
                        key={p.hex}
                        type="button"
                        onClick={() => updateSettings({ accentHex: p.hex })}
                        title={p.name}
                        aria-label={`Accent ${p.name}`}
                        className={`w-8 h-8 rounded-xl flex items-center justify-center border-2 ${
                          active ? 'border-white scale-110 shadow' : 'border-transparent'
                        }`}
                        style={{ backgroundColor: p.hex }}
                      >
                        {active && <Check size={14} className="text-[var(--gg-text-primary)] drop-shadow" />}
                      </button>
                    );
                  })}
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 text-xs">
                  <label className="space-y-1">
                    <span>Custom Hue ({db.settings.customHue}°)</span>
                    <input
                      type="range"
                      min={0}
                      max={359}
                      value={db.settings.customHue}
                      onChange={(e) => {
                        const hue = Number(e.target.value);
                        const hex = hslToHex(hue, 72, db.settings.customShade);
                        updateSettings({ customHue: hue, accentHex: hex });
                      }}
                      className="w-full accent-[var(--gg-accent)]"
                    />
                  </label>
                  <label className="space-y-1">
                    <span>Custom Shade ({db.settings.customShade}%)</span>
                    <input
                      type="range"
                      min={22}
                      max={62}
                      value={db.settings.customShade}
                      onChange={(e) => {
                        const shade = Number(e.target.value);
                        const hex = hslToHex(db.settings.customHue, 72, shade);
                        updateSettings({ customShade: shade, accentHex: hex });
                      }}
                      className="w-full accent-[var(--gg-accent)]"
                    />
                  </label>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 border-t border-[var(--gg-divider)] text-xs">
                <label className="space-y-1">
                  <span>Guide Side</span>
                  <select
                    value={db.settings.guideSide}
                    onChange={(e) => updateSettings({ guideSide: e.target.value as 'left' | 'right' })}
                    className="w-full px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                  >
                    <option value="left">Left side</option>
                    <option value="right">Right side</option>
                  </select>
                </label>

                <label className="space-y-1">
                  <span>Profile Placement</span>
                  <select
                    value={db.settings.profilePlacement}
                    onChange={(e) => updateSettings({ profilePlacement: e.target.value as 'left' | 'right' })}
                    className="w-full px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                  >
                    <option value="left">Top-left</option>
                    <option value="right">Top-right</option>
                  </select>
                </label>
              </div>
            </div>
          )}

          {/* XBOX LIVE & PROFILE */}
          {category === 'xbox' && (
            <div className="space-y-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-[var(--gg-text-primary)]">Xbox Live &amp; Profile</h2>
                  <p className="text-xs text-[var(--gg-text-secondary)]">
                    Link your Xbox account to show your real gamertag, gamerpic, gamerscore, games played and time played across the app.
                  </p>
                </div>
                {activeProfile.isXboxLinked ? (
                  <span className="px-2.5 py-1 rounded-[var(--gg-r-badge)] bg-[#107C10] text-white text-xs font-semibold">
                    {xboxStatus.signedIn ? 'Linked to Xbox' : 'Manual profile'}
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-[var(--gg-r-badge)] bg-[var(--gg-surface-control)] text-[var(--gg-text-secondary)] text-xs font-medium">
                    Not Linked
                  </span>
                )}
              </div>

              {/* Live Profile Overview Card */}
              <div className="p-4 rounded-[var(--gg-r-panel)] bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] space-y-4">
                <div className="flex items-center gap-4">
                  <PlayerAvatar url={activeProfile.avatarUrl} tag={activeProfile.playerTag} size={56} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-lg font-semibold text-[var(--gg-text-primary)] truncate">
                        {activeProfile.playerTag}
                      </span>
                      <span className="px-2 py-0.5 text-xs font-bold uppercase tracking-wider rounded-[var(--gg-r-badge)] bg-[#107C10] text-white">
                        {activeProfile.tier}
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--gg-text-secondary)] mt-1">
                      {typeof activeProfile.gamerscore === 'number' && (
                        <span className="font-semibold text-[var(--gg-text-primary)] inline-flex items-center gap-1">
                          <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full bg-[#107C10] text-white text-[9px] font-black">
                            G
                          </span>
                          <span>{activeProfile.gamerscore.toLocaleString()}</span>
                        </span>
                      )}
                      <span>·</span>
                      <span>{activeProfile.hoursFormatted} playtime</span>
                      <span>·</span>
                      <span>{activeProfile.gamesCount} games</span>
                    </div>
                  </div>
                </div>

                {(activeProfile.isXboxLinked || xboxStatus.signedIn) && (
                  <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-[var(--gg-divider)] text-xs">
                    <button
                      type="button"
                      disabled={xboxBusy}
                      onClick={async () => {
                        setXboxBusy(true);
                        try {
                          await refreshXboxProfileState();
                          pushToast({ title: 'Xbox profile refreshed' });
                        } catch (e: any) {
                          setXboxError(e?.message || 'Could not refresh profile');
                        } finally {
                          setXboxBusy(false);
                        }
                      }}
                      className="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/20 text-[var(--gg-text-primary)] font-medium disabled:opacity-50"
                    >
                      {xboxBusy ? 'Refreshing…' : 'Refresh stats'}
                    </button>
                    <button
                      type="button"
                      disabled={xboxBusy}
                      onClick={async () => {
                        setXboxBusy(true);
                        try {
                          await syncXboxGameArt({ silent: false });
                        } finally {
                          setXboxBusy(false);
                        }
                      }}
                      className="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/20 text-[var(--gg-text-primary)] font-medium disabled:opacity-50"
                    >
                      Sync game art
                    </button>
                    <button
                      type="button"
                      onClick={() => navigate({ page: 'xbox' })}
                      className="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/20 text-[var(--gg-text-primary)] font-medium"
                    >
                      Captures
                    </button>
                    <button
                      type="button"
                      onClick={handleUnlinkXbox}
                      className="px-3 py-1.5 rounded-xl text-red-400 hover:bg-red-500/10 font-medium ml-auto"
                    >
                      Disconnect Xbox
                    </button>
                  </div>
                )}
              </div>

              {/* Status Message / Error Banner */}
              {xboxStatusMsg && (
                <div className="p-3 rounded-xl bg-[var(--gg-accent)]/15 border border-[var(--gg-accent)]/40 text-xs text-white">
                  {xboxStatusMsg}
                </div>
              )}
              {xboxError && (
                <div className="p-3 rounded-xl bg-red-500/15 border border-red-500/40 text-xs text-red-300">
                  {xboxError}
                </div>
              )}

              {/* Device Code Card (when requested) */}
              {xboxDeviceCode && (
                <div className="p-4 rounded-[var(--gg-r-panel)] bg-black/60 border border-[var(--gg-accent)] space-y-3">
                  <div className="text-xs font-semibold text-[var(--gg-text-primary)]">Microsoft Device Sign-In</div>
                  <p className="text-xs text-[var(--gg-text-secondary)]">
                    Enter the code below in your browser to sign in with your Xbox account. The code was copied to your clipboard.
                  </p>
                  <div className="flex items-center gap-3">
                    <div className="text-2xl font-mono font-bold text-[#9BF00B] tracking-wider px-4 py-2 rounded-xl bg-white/5 border border-white/10">
                      {xboxDeviceCode.userCode}
                    </div>
                    <button
                      type="button"
                      onClick={() => navigator.clipboard.writeText(xboxDeviceCode.userCode)}
                      className="px-3 py-2 rounded-xl bg-white/10 hover:bg-white/20 text-xs text-[var(--gg-text-primary)]"
                    >
                      Copy code
                    </button>
                    <a
                      href={xboxDeviceCode.verificationUri}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-3 py-2 rounded-xl bg-[var(--gg-accent)] hover:bg-[var(--gg-accent)]/80 text-xs text-white font-medium"
                    >
                      Open microsoft.com/link
                    </a>
                  </div>
                  <p className="text-[11px] text-[var(--gg-text-tertiary)]">
                    Waiting for authorization… This window will update automatically once signed in.
                  </p>
                </div>
              )}

              {/* Link account + Client ID */}
              <div className="p-5 rounded-[var(--gg-r-panel)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-[var(--gg-text-primary)]">
                    {xboxStatus.signedIn ? `Signed in as ${xboxStatus.gamertag || activeProfile.playerTag}` : 'Link your Xbox account'}
                  </h3>
                  <p className="text-xs text-[var(--gg-text-secondary)]">
                    Green Guide signs in directly with Microsoft. Nothing goes through a server, and your sign-in stays on this device.
                  </p>
                </div>

                {!xboxStatus.signedIn && (
                  <div className="flex flex-wrap gap-3">
                    {Capacitor.isNativePlatform() && (
                      <button
                        type="button"
                        disabled={xboxBusy}
                        onClick={handleBrowserSignIn}
                        className="px-4 py-2.5 rounded-xl bg-[var(--gg-accent)] text-white text-xs font-semibold disabled:opacity-50 xbox-ring"
                      >
                        Link Xbox account
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={xboxBusy}
                      onClick={handleStartDeviceCode}
                      className="px-4 py-2.5 rounded-xl bg-[var(--gg-surface-control)] hover:bg-[var(--gg-surface-focus)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)] text-xs font-medium disabled:opacity-50 xbox-ring"
                    >
                      Sign in with a code
                    </button>
                  </div>
                )}

                <label className="space-y-1 block text-xs pt-1">
                  <span className="font-semibold text-[var(--gg-text-primary)]">Azure Application (client) ID</span>
                  <input
                    type="text"
                    value={db.settings.xboxClientId || ''}
                    onChange={(e) => updateSettings({ xboxClientId: e.target.value.trim() })}
                    placeholder={
                      (import.meta as any).env?.VITE_MS_CLIENT_ID
                        ? 'Using the Client ID built into this app'
                        : 'Paste your Azure Application (client) ID'
                    }
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    className="w-full px-3 py-2 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)] text-xs font-mono"
                  />
                  <span className="text-[11px] text-[var(--gg-text-tertiary)] block">
                    Register a public client app in Azure with the redirect <span className="font-mono">greenguide://auth</span> and the
                    delegated permission <span className="font-mono">XboxLive.signin</span>. You can also set the GitHub variable{' '}
                    <span className="font-mono">MS_CLIENT_ID</span> so builds include it.
                  </span>
                </label>
              </div>

              {/* Xbox preferences */}
              <div className="p-5 rounded-[var(--gg-r-panel)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)] space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-[var(--gg-text-primary)]">Game art &amp; captures</h3>
                  <p className="text-xs text-[var(--gg-text-secondary)]">How Xbox games and screenshots are matched and imported.</p>
                </div>

                <label className="flex items-start justify-between gap-4 text-xs cursor-pointer">
                  <span className="space-y-0.5">
                    <span className="block font-semibold text-[var(--gg-text-primary)]">Match games to Xbox automatically</span>
                    <span className="block text-[var(--gg-text-secondary)]">Fill in cover art and wallpapers for journal games after each Xbox sync.</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={db.settings.xboxAutoMatch ?? true}
                    onChange={(e) => updateSettings({ xboxAutoMatch: e.target.checked })}
                    className="mt-1 w-5 h-5 accent-[var(--gg-accent)] shrink-0"
                  />
                </label>

                <label className="flex items-start justify-between gap-4 text-xs cursor-pointer">
                  <span className="space-y-0.5">
                    <span className="block font-semibold text-[var(--gg-text-primary)]">Prefer box art over wallpapers</span>
                    <span className="block text-[var(--gg-text-secondary)]">Use the portrait cover as the main picture for matched games.</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={db.settings.xboxUseBoxArt ?? false}
                    onChange={(e) => updateSettings({ xboxUseBoxArt: e.target.checked })}
                    className="mt-1 w-5 h-5 accent-[var(--gg-accent)] shrink-0"
                  />
                </label>

                <label className="space-y-1 block text-xs">
                  <span className="font-semibold text-[var(--gg-text-primary)]">Capture import quality</span>
                  <select
                    value={db.settings.xboxImportQuality || 'STANDARD'}
                    onChange={(e) => updateSettings({ xboxImportQuality: e.target.value as 'ORIGINAL' | 'HIGH' | 'STANDARD' })}
                    className="w-full max-w-xs px-3 py-2 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)] text-sm"
                  >
                    <option value="STANDARD">Standard (up to 1920 px)</option>
                    <option value="HIGH">High (up to 2560 px)</option>
                    <option value="ORIGINAL">Original (largest, uses the most space)</option>
                  </select>
                </label>
              </div>

              {/* Manual entry (offline fallback) */}
              {!xboxStatus.signedIn && (
                <details className="rounded-[var(--gg-r-panel)] bg-[var(--gg-bg-raised)] border border-[var(--gg-divider)]">
                  <summary className="px-5 py-3 text-xs font-semibold text-[var(--gg-text-primary)] cursor-pointer">
                    Enter stats by hand instead (not synced with Xbox)
                  </summary>
                  <div className="p-1">
              {/* Quick Profile Setup Form */}
              <div className="p-4 space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-[var(--gg-text-primary)]">Xbox Profile Stats &amp; Info</h3>
                  <p className="text-xs text-[var(--gg-text-secondary)]">
                    Set your gamertag, gamerscore, tier, and gamerpic to immediately use in the TopBar and Profile.
                  </p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                  <label className="space-y-1 block">
                    <span className="font-semibold text-[var(--gg-text-primary)]">Xbox Gamertag</span>
                    <input
                      type="text"
                      value={xboxTagInput}
                      onChange={(e) => setXboxTagInput(e.target.value)}
                      placeholder="e.g. SkyPilot"
                      className="w-full px-3 py-2 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)] text-sm"
                    />
                  </label>

                  <label className="space-y-1 block">
                    <span className="font-semibold text-[var(--gg-text-primary)]">Gamerscore (G)</span>
                    <input
                      type="number"
                      min="0"
                      value={xboxScoreInput}
                      onChange={(e) => setXboxScoreInput(e.target.value)}
                      placeholder="e.g. 42500"
                      className="w-full px-3 py-2 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)] text-sm"
                    />
                  </label>

                  <label className="space-y-1 block">
                    <span className="font-semibold text-[var(--gg-text-primary)]">Account Tier / Status</span>
                    <select
                      value={xboxTierInput}
                      onChange={(e) => setXboxTierInput(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)] text-sm"
                    >
                      <option value="GOLD">GOLD</option>
                      <option value="GAME PASS">GAME PASS</option>
                      <option value="ULTIMATE">ULTIMATE</option>
                      <option value="SILVER">SILVER</option>
                      <option value="VIP">VIP</option>
                    </select>
                  </label>

                  <label className="space-y-1 block">
                    <span className="font-semibold text-[var(--gg-text-primary)]">Total Playtime (Hours)</span>
                    <input
                      type="number"
                      min="0"
                      value={xboxHoursInput}
                      onChange={(e) => setXboxHoursInput(e.target.value)}
                      placeholder="e.g. 120"
                      className="w-full px-3 py-2 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)] text-sm"
                    />
                  </label>
                </div>

                <div className="space-y-2 text-xs">
                  <label className="space-y-1 block">
                    <span className="font-semibold text-[var(--gg-text-primary)]">Gamerpic Avatar Image URL</span>
                    <input
                      type="text"
                      value={xboxAvatarInput}
                      onChange={(e) => setXboxAvatarInput(e.target.value)}
                      placeholder="https://... or choose a preset below"
                      className="w-full px-3 py-2 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)] text-sm"
                    />
                  </label>
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <span className="text-[11px] text-[var(--gg-text-tertiary)]">Presets:</span>
                    {[
                      { label: 'Classic Sphere', url: 'https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?auto=format&fit=crop&w=150&q=80' },
                      { label: 'Flight Wings', url: 'https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?auto=format&fit=crop&w=150&q=80' },
                      { label: 'Pilot Helmet', url: 'https://images.unsplash.com/photo-1517976487502-d7102d88737a?auto=format&fit=crop&w=150&q=80' },
                      { label: 'Forza Racing', url: 'https://images.unsplash.com/photo-1568605117036-5fe5e7bab0b7?auto=format&fit=crop&w=150&q=80' },
                      { label: 'Gamer Crest', url: 'https://images.unsplash.com/photo-1579783900882-c0d3dad7b119?auto=format&fit=crop&w=150&q=80' },
                    ].map((preset) => (
                      <button
                        key={preset.label}
                        type="button"
                        onClick={() => setXboxAvatarInput(preset.url)}
                        className="px-2.5 py-1 rounded-xl bg-white/5 hover:bg-white/10 text-[11px] text-[var(--gg-text-primary)] border border-white/10"
                      >
                        {preset.label}
                      </button>
                    ))}
                    {xboxAvatarInput && (
                      <button
                        type="button"
                        onClick={() => setXboxAvatarInput('')}
                        className="px-2 py-1 rounded-xl text-[11px] text-red-400 hover:underline"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-[var(--gg-divider)]">
                  <div className="text-[11px] text-[var(--gg-text-secondary)]">
                    Applies immediately to the TopBar, Guide overlay, and Profile page.
                  </div>
                  <button
                    type="button"
                    disabled={xboxBusy}
                    onClick={handleSaveXboxProfile}
                    className="px-4 py-2 rounded-xl bg-[var(--gg-accent)] hover:bg-[var(--gg-accent)]/90 text-white font-medium text-xs shadow disabled:opacity-50"
                  >
                    {xboxBusy ? 'Saving…' : 'Save & Apply to App'}
                  </button>
                </div>
              </div>

                  </div>
                </details>
              )}
            </div>
          )}

          {/* WALLPAPER */}
          {category === 'wallpaper' && <WallpaperSettings />}

          {/* PRESETS */}
          {category === 'presets' && (
            <div className="space-y-5">
              <div>
                <h2 className="text-base font-semibold text-[var(--gg-text-primary)]">Settings &amp; Theme Presets</h2>
                <p className="text-xs text-[var(--gg-text-secondary)]">
                  Save and switch complete visual styles, sounds, and screen setups. Presets never contain tokens or journal data.
                </p>
              </div>

              <div className="flex flex-wrap gap-2 items-center p-3 rounded-2xl bg-black/25 border border-[var(--gg-divider)]">
                <input
                  type="text"
                  placeholder="New preset name..."
                  value={newPresetName}
                  onChange={(e) => setNewPresetName(e.target.value)}
                  className="px-3 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-xs text-[var(--gg-text-primary)] flex-1 min-w-[160px]"
                />
                <button
                  type="button"
                  onClick={() => {
                    if (!newPresetName.trim()) return;
                    const p = createSettingsPreset(newPresetName, db.settings);
                    updateDb((prev) => ({
                      ...prev,
                      settingsPresets: [...(prev.settingsPresets ?? []), p],
                    }));
                    setNewPresetName('');
                    playSound('save');
                    pushToast({ title: 'Preset saved' });
                  }}
                  className="px-3 py-1.5 rounded-xl bg-[var(--gg-accent)] text-white text-xs font-semibold"
                >
                  Save current look
                </button>
                <label className="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-semibold cursor-pointer text-[var(--gg-text-primary)]">
                  <span>Import .json</span>
                  <input
                    type="file"
                    accept=".json"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      file.text().then((txt) => {
                        const parsed = parsePresetImport(txt);
                        if (!parsed) {
                          pushToast({ title: 'Invalid preset file', kind: 'error' });
                          return;
                        }
                        updateDb((prev) => ({
                          ...prev,
                          settingsPresets: [...(prev.settingsPresets ?? []), parsed],
                        }));
                        pushToast({ title: `Imported "${parsed.name}"` });
                      });
                    }}
                  />
                </label>
              </div>

              <div className="space-y-2">
                <h3 className="text-xs font-semibold text-[var(--gg-text-secondary)] uppercase tracking-wider">
                  Built-in &amp; Saved Presets
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {[...BUILT_IN_PRESETS, ...(db.settingsPresets ?? [])].map((preset: SettingsPreset) => (
                    <div
                      key={preset.id}
                      className="p-3.5 rounded-2xl bg-black/30 border border-[var(--gg-divider)] space-y-2.5"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span
                            className="w-3.5 h-3.5 rounded-full inline-block border border-white/20"
                            style={{ backgroundColor: preset.data.accentHex || '#107C10' }}
                          />
                          <span className="font-semibold text-xs text-[var(--gg-text-primary)]">{preset.name}</span>
                        </div>
                        {preset.builtIn ? (
                          <span className="px-2 py-0.5 rounded text-[10px] bg-white/10 text-[var(--gg-text-secondary)]">
                            Built-in
                          </span>
                        ) : (
                          <div className="flex gap-1">
                            <button
                              type="button"
                              onClick={() => {
                                const json = exportPresetJson(preset);
                                const blob = new Blob([json], { type: 'application/json' });
                                const url = URL.createObjectURL(blob);
                                const a = document.createElement('a');
                                a.href = url;
                                a.download = `${preset.name.toLowerCase().replace(/\s+/g, '_')}_preset.json`;
                                a.click();
                                setTimeout(() => URL.revokeObjectURL(url), 1000);
                              }}
                              className="p-1 rounded text-[var(--gg-text-secondary)] hover:text-[var(--gg-text-primary)]"
                              title="Export preset as JSON"
                              aria-label="Export preset as JSON"
                            >
                              <Download size={13} />
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                updateDb((prev) => ({
                                  ...prev,
                                  settingsPresets: (prev.settingsPresets ?? []).filter((p: SettingsPreset) => p.id !== preset.id),
                                }));
                              }}
                              className="p-1 rounded text-red-400 hover:text-red-300"
                              title="Delete preset"
                              aria-label="Delete preset"
                            >
                              <Trash2 size={13} />
                            </button>
                          </div>
                        )}
                      </div>

                      <div className="text-[11px] text-[var(--gg-text-secondary)]">
                        {preset.data.themeMode} mode · Accent {preset.data.accentHex}
                      </div>

                      <button
                        type="button"
                        onClick={() => {
                          const next = applyPresetToSettings(db.settings, preset);
                          updateSettings(next);
                          playSound('save');
                          pushToast({ title: `Applied "${preset.name}" preset` });
                        }}
                        className="w-full py-1.5 rounded-xl bg-white/10 hover:bg-white/15 text-[var(--gg-text-primary)] text-xs font-semibold"
                      >
                        Apply preset
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* JOURNAL & REGISTRIES */}
          {category === 'journal' && (
            <div className="space-y-6">
              {/* Memories & Score Toggles */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--gg-text-primary)]">Memories &amp; Home Highlights</h3>
                <div className="space-y-2 text-xs">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={db.settings.showOnThisDay ?? true}
                      onChange={(e) => updateSettings({ showOnThisDay: e.target.checked })}
                    />
                    <span>Show &ldquo;On this day&rdquo; historical flight memories on Home</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={db.settings.showAnniversaries ?? true}
                      onChange={(e) => updateSettings({ showAnniversaries: e.target.checked })}
                    />
                    <span>Show milestone anniversary banners on Home</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={db.settings.showYearInReviewOffer ?? true}
                      onChange={(e) => updateSettings({ showYearInReviewOffer: e.target.checked })}
                    />
                    <span>Offer Year in Review recap banner in December and January</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={db.settings.hideJournalScore ?? false}
                      onChange={(e) => updateSettings({ hideJournalScore: e.target.checked })}
                    />
                    <span>Hide global flight journal score pill on Home</span>
                  </label>
                </div>
              </div>

              {/* Tags Manager (D1) */}
              <div className="pt-4 border-t border-[var(--gg-divider)] space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-[var(--gg-text-primary)]">Journal Tags ({db.tags.length})</h3>
                    <p className="text-xs text-[var(--gg-text-secondary)]">Manage tag colors, names, and merges.</p>
                  </div>
                </div>

                <div className="space-y-2">
                  {db.tags.map((tag) => {
                    const count = db.tagLinks.filter((tl) => tl.tagId === tag.id).length;
                    const isEditing = editingTagId === tag.id;
                    return (
                      <div
                        key={tag.id}
                        className="flex flex-wrap items-center justify-between gap-2 p-2.5 rounded-xl bg-black/25 border border-[var(--gg-divider)] text-xs"
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className="w-3 h-3 rounded-full inline-block"
                            style={{ backgroundColor: tag.colorHex || '#107C10' }}
                          />
                          {isEditing ? (
                            <input
                              type="text"
                              value={editingTagName}
                              onChange={(e) => setEditingTagName(e.target.value)}
                              className="px-2 py-0.5 rounded bg-black/40 border border-white/20 text-white text-xs"
                            />
                          ) : (
                            <span className="font-semibold text-[var(--gg-text-primary)]">#{tag.name}</span>
                          )}
                          <span className="text-[10px] text-[var(--gg-text-secondary)]">({count} uses)</span>
                        </div>

                        <div className="flex items-center gap-1.5">
                          {isEditing ? (
                            <>
                              <input
                                type="color"
                                value={editingTagColor || '#107C10'}
                                onChange={(e) => setEditingTagColor(e.target.value)}
                                className="w-6 h-6 rounded border-0 cursor-pointer p-0 bg-transparent"
                              />
                              <button
                                type="button"
                                onClick={() => {
                                  updateDb((prev) => renameTag(prev, tag.id, editingTagName, editingTagColor));
                                  setEditingTagId(null);
                                  pushToast({ title: 'Tag updated' });
                                }}
                                className="px-2 py-1 rounded bg-[var(--gg-accent)] text-white text-[11px] font-semibold"
                              >
                                Save
                              </button>
                              <button
                                type="button"
                                onClick={() => setEditingTagId(null)}
                                className="px-2 py-1 rounded bg-white/10 text-[var(--gg-text-primary)] text-[11px]"
                              >
                                Cancel
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                type="button"
                                onClick={() => {
                                  setEditingTagId(tag.id);
                                  setEditingTagName(tag.name);
                                  setEditingTagColor(tag.colorHex || '#107C10');
                                }}
                                className="px-2 py-1 rounded bg-white/10 hover:bg-white/15 text-[11px] text-[var(--gg-text-primary)]"
                              >
                                Edit
                              </button>
                              {db.tags.length > 1 && (
                                <select
                                  value=""
                                  onChange={(e) => {
                                    const targetId = e.target.value;
                                    if (targetId && confirm(`Merge #${tag.name} into target tag?`)) {
                                      updateDb((prev) => mergeTags(prev, tag.id, targetId));
                                      pushToast({ title: 'Tags merged' });
                                    }
                                  }}
                                  className="px-2 py-1 rounded bg-black/40 border border-white/10 text-[11px] text-[var(--gg-text-secondary)]"
                                >
                                  <option value="">Merge into...</option>
                                  {db.tags.filter((t) => t.id !== tag.id).map((t) => (
                                    <option key={t.id} value={t.id}>#{t.name}</option>
                                  ))}
                                </select>
                              )}
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Aircraft & Sim Registries (D2) */}
              <div className="pt-4 border-t border-[var(--gg-divider)] space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-[var(--gg-text-primary)]">Aircraft Registry &amp; Aliases</h3>
                  <p className="text-xs text-[var(--gg-text-secondary)]">
                    Canonical aircraft names and merged variants across logs and flight plans.
                  </p>
                </div>

                <div className="space-y-2">
                  {registries.aircraft.slice(0, 15).map((entry) => (
                    <div
                      key={entry.canonical}
                      className="p-3 rounded-2xl bg-black/25 border border-[var(--gg-divider)] text-xs space-y-1.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-[var(--gg-text-primary)] text-sm">{entry.canonical}</span>
                        <span className="text-[11px] text-[var(--gg-text-secondary)]">
                          {entry.totalCount} logged flight{entry.totalCount === 1 ? '' : 's'}
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {entry.variants.map((v) => {
                          const isAliased = v.name.toLowerCase() !== entry.canonical.toLowerCase();
                          return (
                            <span
                              key={v.name}
                              className={`px-2 py-0.5 rounded-lg text-[10px] inline-flex items-center gap-1 ${
                                isAliased
                                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                                  : 'bg-white/10 text-[var(--gg-text-primary)]'
                              }`}
                            >
                              <span>{v.name} ({v.count})</span>
                              {isAliased && (
                                <button
                                  type="button"
                                  onClick={() => {
                                    const nextAliases = removeRegistryAlias(db.settings.aircraftAliases, v.name);
                                    updateSettings({ aircraftAliases: nextAliases });
                                    pushToast({ title: `Removed alias for ${v.name}` });
                                  }}
                                  className="hover:text-red-300 ml-0.5"
                                  title="Unlink alias"
                                >
                                  &times;
                                </button>
                              )}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="pt-2">
                  <h4 className="text-xs font-semibold text-[var(--gg-text-primary)] pb-1">Simulator Platforms</h4>
                  <div className="flex flex-wrap gap-2">
                    {registries.sims.map((sim) => (
                      <span key={sim.canonical} className="px-3 py-1 rounded-xl bg-black/30 border border-white/10 text-xs text-white">
                        {sim.canonical} ({sim.totalCount})
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* NOTIFICATIONS (D13) */}
          {category === 'notifications' && (
            <div className="space-y-5">
              <div>
                <h2 className="text-base font-semibold text-[var(--gg-text-primary)]">Notifications</h2>
                <p className="text-xs text-[var(--gg-text-secondary)]">
                  Green Guide notifications only fire when the app is in the background. Nothing fires while you are actively using the app.
                </p>
              </div>

              <div className="p-3.5 rounded-2xl bg-black/30 border border-[var(--gg-divider)] flex items-center justify-between">
                <div>
                  <div className="text-sm font-semibold text-[var(--gg-text-primary)]">Allow Notifications</div>
                  <div className="text-xs text-[var(--gg-text-secondary)]">Master switch for all background alerts</div>
                </div>
                <input
                  type="checkbox"
                  aria-label="Allow Notifications"
                  checked={db.settings.notificationsEnabled ?? true}
                  onChange={(e) => {
                    const next = e.target.checked;
                    updateSettings({ notificationsEnabled: next });
                    if (next) {
                      const activeCh = (Object.keys(NOTIFICATION_CHANNEL_META) as NotificationChannelId[]).find((id) =>
                        isChannelEnabled({ ...db.settings, notificationsEnabled: true }, id)
                      );
                      void requestNotificationPermissionAndEnsureChannel(activeCh);
                    }
                  }}
                  className="w-4 h-4 accent-[var(--gg-accent)]"
                />
              </div>

              <div className="space-y-2">
                <h3 className="text-xs font-semibold text-[var(--gg-text-secondary)] uppercase tracking-wider">
                  Notification Channels
                </h3>
                {(Object.keys(NOTIFICATION_CHANNEL_META) as NotificationChannelId[]).map((chId) => {
                  const meta = NOTIFICATION_CHANNEL_META[chId];
                  const enabled = isChannelEnabled(db.settings, chId);
                  return (
                    <div
                      key={chId}
                      className="p-3 rounded-2xl bg-black/25 border border-[var(--gg-divider)] flex items-start justify-between gap-3 text-xs"
                    >
                      <div>
                        <div className="font-semibold text-[var(--gg-text-primary)]">{meta.name}</div>
                        <div className="text-[11px] text-[var(--gg-text-secondary)]">{meta.description}</div>
                      </div>
                      <input
                        type="checkbox"
                        aria-label={meta.name}
                        checked={enabled}
                        disabled={db.settings.notificationsEnabled === false}
                        onChange={(e) => {
                          const turnedOn = e.target.checked;
                          const currentChannels = { ...(db.settings.notifyChannels ?? {}) };
                          currentChannels[chId] = turnedOn;
                          updateSettings({ notifyChannels: currentChannels });
                          if (turnedOn) {
                            void requestNotificationPermissionAndEnsureChannel(chId);
                          }
                        }}
                        className="w-4 h-4 mt-0.5 accent-[var(--gg-accent)]"
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* PRIVACY & APP LOCK (D11) */}
          {category === 'privacy' && (
            <div className="space-y-5">
              <div>
                <h2 className="text-base font-semibold text-[var(--gg-text-primary)]">Privacy &amp; App Lock</h2>
                <p className="text-xs text-[var(--gg-text-secondary)]">
                  Protect your private log entries with device biometrics or screen lock credential.
                </p>
              </div>

              <div className="p-3.5 rounded-2xl bg-black/30 border border-[var(--gg-divider)] space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold text-[var(--gg-text-primary)]">Lock Green Guide</div>
                    <div className="text-xs text-[var(--gg-text-secondary)]">
                      Requires authentication when launching or returning to the app
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={Boolean(db.settings.appLockEnabled)}
                    onChange={(e) => updateSettings({ appLockEnabled: e.target.checked })}
                    className="w-4 h-4 accent-[var(--gg-accent)]"
                  />
                </div>

                <div className="pt-2 border-t border-white/5 grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <label className="space-y-1">
                    <span className="font-semibold block">Lock Timeout</span>
                    <select
                      value={db.settings.appLockTimeoutMin ?? 0}
                      onChange={(e) => updateSettings({ appLockTimeoutMin: Number(e.target.value) as any })}
                      disabled={!db.settings.appLockEnabled}
                      className="w-full px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                    >
                      <option value={0}>Immediately upon leaving</option>
                      <option value={1}>After 1 minute in background</option>
                      <option value={5}>After 5 minutes in background</option>
                      <option value={15}>After 15 minutes in background</option>
                    </select>
                  </label>

                  <div className="space-y-1">
                    <span className="font-semibold block">Biometric Hardware</span>
                    <div className="p-2 rounded-xl bg-black/40 border border-white/10 text-[11px] text-[var(--gg-text-secondary)]">
                      {bioInfo.label}
                    </div>
                  </div>
                </div>
              </div>

              <div className="p-3 rounded-2xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-200/90 space-y-1">
                <div className="font-semibold">Safe Mode &amp; Emergency Access</div>
                <div>
                  Safe Mode and the recovery screen will never lock you out of device troubleshooting.
                </div>
              </div>
            </div>
          )}

          {/* CONTROLS & DISPLAY (E1) */}
          {category === 'controls' && (
            <div className="space-y-5">
              <div>
                <h2 className="text-base font-semibold text-[var(--gg-text-primary)]">Controls &amp; Display</h2>
                <p className="text-xs text-[var(--gg-text-secondary)]">
                  Controller layouts, refresh rate, touch options, and performance overlays.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <label className="space-y-1">
                  <span className="font-semibold">Input Mode</span>
                  <select
                    value={db.settings.inputMode || 'HYBRID'}
                    onChange={(e) => updateSettings({ inputMode: e.target.value as any })}
                    className="w-full px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                  >
                    <option value="HYBRID">Hybrid (Auto-detect touch, mouse &amp; controller)</option>
                    <option value="GAMEPAD">Controller priority (Always show hints)</option>
                    <option value="TOUCH_KEYBOARD">Touch &amp; Keyboard</option>
                  </select>
                </label>

                <div className="space-y-2 pt-2">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={Boolean(db.settings.nintendoAbSwap)}
                      onChange={(e) => updateSettings({ nintendoAbSwap: e.target.checked })}
                    />
                    <span>Swap A / B for Nintendo controller layout</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={Boolean(db.settings.fastTap)}
                      onChange={(e) => updateSettings({ fastTap: e.target.checked })}
                    />
                    <span>Fast tap (eliminates 300ms touch delay)</span>
                  </label>
                </div>
              </div>

              <button
                type="button"
                onClick={() => setShowCheatsheet(true)}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-[var(--gg-text-primary)] text-xs font-semibold"
              >
                <Gamepad2 size={15} />
                <span>View Controls &amp; Keyboard Shortcuts</span>
              </button>

              {/* Display & Performance Card */}
              <div className="p-3.5 rounded-2xl bg-black/30 border border-[var(--gg-divider)] space-y-3 text-xs">
                <div className="font-semibold text-[var(--gg-text-primary)]">Display &amp; Hardware Diagnostics</div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[11px] text-[var(--gg-text-secondary)]">
                  <div>
                    <span className="block text-[10px]">Viewport</span>
                    <span className="text-[var(--gg-text-primary)] font-mono">{typeof window !== 'undefined' ? `${window.innerWidth} × ${window.innerHeight}` : 'N/A'}</span>
                  </div>
                  <div>
                    <span className="block text-[10px]">Pixel Ratio</span>
                    <span className="text-[var(--gg-text-primary)] font-mono">{typeof window !== 'undefined' ? `${window.devicePixelRatio}x` : '1x'}</span>
                  </div>
                  <div>
                    <span className="block text-[10px]">Measured Refresh</span>
                    <span className="text-[var(--gg-text-primary)] font-mono">{measuredHz ? `${measuredHz} Hz` : 'Measuring...'}</span>
                  </div>
                  <div>
                    <span className="block text-[10px]">Screen Mode</span>
                    <span className="text-[var(--gg-text-primary)] font-mono">{db.settings.screenMode}</span>
                  </div>
                </div>

                <label className="flex items-center gap-2 pt-1 border-t border-white/5">
                  <input
                    type="checkbox"
                    checked={Boolean(db.settings.fpsOverlay)}
                    onChange={(e) => updateSettings({ fpsOverlay: e.target.checked })}
                  />
                  <span>Show real-time FPS performance meter overlay</span>
                </label>
              </div>

              {/* Accessibility */}
              <div className="p-3.5 rounded-2xl bg-black/30 border border-[var(--gg-divider)] space-y-3 text-xs">
                <div className="font-semibold text-[var(--gg-text-primary)]">Accessibility</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={Boolean(db.settings.highContrast)}
                      onChange={(e) => updateSettings({ highContrast: e.target.checked })}
                    />
                    <span>High contrast mode</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={Boolean(db.settings.focusRingBold)}
                      onChange={(e) => updateSettings({ focusRingBold: e.target.checked })}
                    />
                    <span>Extra prominent focus rings</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={db.settings.reduceMotion}
                      onChange={(e) => updateSettings({ reduceMotion: e.target.checked })}
                    />
                    <span>Reduce motion</span>
                  </label>
                </div>
              </div>

              {/* Advanced Network & Settings Reset */}
              <div className="p-3.5 rounded-2xl bg-black/30 border border-[var(--gg-divider)] space-y-3 text-xs">
                <div className="font-semibold text-[var(--gg-text-primary)]">Advanced Options</div>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean(db.settings.allowLocalPlainHttp)}
                    onChange={(e) => updateSettings({ allowLocalPlainHttp: e.target.checked })}
                  />
                  <span>Allow plain HTTP on local network (e.g. for local Ollama/LM Studio endpoints)</span>
                </label>

                <div className="pt-2 border-t border-white/5 space-y-2">
                  <div className="text-[11px] text-[var(--gg-text-secondary)]">
                    To reset only your settings without wiping your flight logs or screenshots, type &ldquo;RESET&rdquo; below:
                  </div>
                  <div className="flex gap-2 max-w-xs">
                    <input
                      type="text"
                      placeholder="RESET"
                      value={resetConfirmText}
                      onChange={(e) => setResetConfirmText(e.target.value)}
                      className="px-2.5 py-1 rounded bg-[var(--gg-surface-control)] border border-white/20 text-[var(--gg-text-primary)] font-mono text-xs w-24 text-center"
                    />
                    <button
                      type="button"
                      disabled={resetConfirmText !== 'RESET'}
                      onClick={() => {
                        updateSettings({
                          themeMode: 'NIGHT',
                          accentHex: '#107C10',
                          customHue: 120,
                          customShade: 27,
                          bgMode: 'gradient',
                          bgDim: 0.5,
                          bgBlur: 10,
                          screenMode: 'FULL',
                          guideSide: 'left',
                          profilePlacement: 'left',
                          curvedEdgeInset: 0,
                          reduceMotion: false,
                          textScale: 100,
                          soundMaster: 70,
                          soundUi: 80,
                          soundFeedback: 80,
                          soundKeeper: 65,
                          soundSplash: 60,
                          hapticsEnabled: true,
                          inputMode: 'HYBRID',
                          nintendoAbSwap: false,
                          fastTap: false,
                          fpsOverlay: false,
                          highContrast: false,
                          focusRingBold: false,
                        });
                        setResetConfirmText('');
                        pushToast({ title: 'Settings reset to defaults' });
                      }}
                      className="px-3 py-1 rounded bg-amber-700/80 hover:bg-amber-700 text-white font-semibold disabled:opacity-40"
                    >
                      Reset Settings
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* GAMES & SIMBRIEF (E2) */}
          {category === 'games' && (
            <div className="space-y-4 text-xs">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <label className="space-y-1">
                  <span className="font-semibold">SimBrief Pilot ID</span>
                  <input
                    type="text"
                    value={db.settings.simbriefPilotId}
                    onChange={(e) => updateSettings({ simbriefPilotId: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl text-sm font-mono bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                  />
                </label>
                <label className="space-y-1">
                  <span className="font-semibold">SimBrief Username (optional)</span>
                  <input
                    type="text"
                    value={db.settings.simbriefUsername}
                    onChange={(e) => updateSettings({ simbriefUsername: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                  />
                </label>
              </div>

              <div className="space-y-2 pt-2">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean(db.settings.simbriefPrefetch)}
                    onChange={(e) => updateSettings({ simbriefPrefetch: e.target.checked })}
                  />
                  <span>Pre-fetch SimBrief plan on open</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={db.settings.simbriefKeepRaw ?? true}
                    onChange={(e) => updateSettings({ simbriefKeepRaw: e.target.checked })}
                  />
                  <span>Keep raw flight plan payload</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={db.settings.simbriefBundledAirports ?? true}
                    onChange={(e) => updateSettings({ simbriefBundledAirports: e.target.checked })}
                  />
                  <span>Use bundled airport table for airport type-ahead search</span>
                </label>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                <label className="space-y-1">
                  <span className="font-semibold">Units for Display</span>
                  <select
                    value={typeof db.settings.displayUnits === 'string' ? db.settings.displayUnits : 'AVIATION'}
                    onChange={(e) => updateSettings({ displayUnits: e.target.value as any })}
                    className="w-full px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                  >
                    <option value="AVIATION">Aviation (NM, knots, feet, lbs/kg)</option>
                    <option value="METRIC">Metric (km, km/h, meters, kg)</option>
                    <option value="IMPERIAL">Imperial (miles, mph, feet, lbs)</option>
                  </select>
                </label>

                <label className="flex items-center gap-2 pt-5">
                  <input
                    type="checkbox"
                    checked={db.settings.uiGameAccent}
                    onChange={(e) => updateSettings({ uiGameAccent: e.target.checked })}
                  />
                  <span>Adapt UI accent subtly when focusing games with custom accent</span>
                </label>
              </div>
            </div>
          )}

          {/* KEEPER & AI */}
          {category === 'keeper' && (
            <div className="space-y-4 text-xs">
              <ConnectionsEditor />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <label className="space-y-1">
                  <span className="font-semibold">Chronicle Max File Size (KB)</span>
                  <input
                    type="number"
                    min={8}
                    max={512}
                    value={db.settings.chronicleMaxKb}
                    onChange={(e) => updateSettings({ chronicleMaxKb: Number(e.target.value) })}
                    className="w-full px-3 py-2 rounded-xl text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                  />
                </label>
                <label className="space-y-1">
                  <span className="font-semibold">Chronicle Max Entries per File</span>
                  <input
                    type="number"
                    min={10}
                    max={500}
                    value={db.settings.chronicleMaxEntries}
                    onChange={(e) => updateSettings({ chronicleMaxEntries: Number(e.target.value) })}
                    className="w-full px-3 py-2 rounded-xl text-sm bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                  />
                </label>
              </div>

              {/* Picture indexing & summaries */}
              <div className="pt-4 border-t border-[var(--gg-divider)] space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold text-[var(--gg-text-primary)]">Picture Indexing &amp; Usage</h3>
                    <p className="text-[11px] text-[var(--gg-text-secondary)]">
                      Let Keeper describe screenshots and track token costs per role.
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => navigate({ page: 'keeper', view: 'usage' })}
                      className="px-3 py-1.5 rounded-xl bg-[var(--gg-surface-control)] text-xs font-semibold text-[var(--gg-text-primary)]"
                    >
                      Keeper usage
                    </button>
                    <button
                      type="button"
                      onClick={() => navigate({ page: 'keeper', view: 'index' })}
                      className="px-3 py-1.5 rounded-xl bg-[var(--gg-accent)] text-white text-xs font-semibold shadow"
                    >
                      Open Picture index
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="flex items-start gap-2.5">
                    <input
                      type="checkbox"
                      checked={db.settings.aiAutoIndex}
                      onChange={(e) => updateSettings({ aiAutoIndex: e.target.checked })}
                      className="mt-0.5 accent-[var(--gg-accent)]"
                    />
                    <div>
                      <div className="font-semibold text-[var(--gg-text-primary)]">Index new pictures automatically</div>
                      <div className="text-[11px] text-[var(--gg-text-secondary)]">
                        Automatically queues new screenshots and cover art while the app is running.
                      </div>
                    </div>
                  </label>

                  <label className="flex items-start gap-2.5">
                    <input
                      type="checkbox"
                      checked={db.settings.aiSendImages}
                      onChange={(e) => updateSettings({ aiSendImages: e.target.checked })}
                      className="mt-0.5 accent-[var(--gg-accent)]"
                    />
                    <div>
                      <div className="font-semibold text-[var(--gg-text-primary)]">Send pictures to AI provider</div>
                      <div className="text-[11px] text-[var(--gg-text-secondary)]">
                        Turn off to create descriptions from known game and date facts only.
                      </div>
                    </div>
                  </label>

                  <label className="flex items-start gap-2.5">
                    <input
                      type="checkbox"
                      checked={db.settings.aiStripLocation}
                      onChange={(e) => updateSettings({ aiStripLocation: e.target.checked })}
                      className="mt-0.5 accent-[var(--gg-accent)]"
                    />
                    <div>
                      <div className="font-semibold text-[var(--gg-text-primary)]">Remove location details</div>
                      <div className="text-[11px] text-[var(--gg-text-secondary)]">
                        Keep coordinates out of picture prompts.
                      </div>
                    </div>
                  </label>

                  <label className="flex items-start gap-2.5">
                    <input
                      type="checkbox"
                      checked={db.settings.aiAutoSummaries}
                      onChange={(e) => updateSettings({ aiAutoSummaries: e.target.checked })}
                      className="mt-0.5 accent-[var(--gg-accent)]"
                    />
                    <div>
                      <div className="font-semibold text-[var(--gg-text-primary)]">Auto-summarize notes and sessions</div>
                      <div className="text-[11px] text-[var(--gg-text-secondary)]">
                        Refreshes text summaries after edits or when a flight concludes.
                      </div>
                    </div>
                  </label>
                </div>
              </div>
            </div>
          )}

          {/* DATA, BACKUP & TRASH (E5) */}
          {category === 'backup' && (
            <div className="space-y-5">
              <div className="flex flex-wrap gap-2.5">
                <button
                  type="button"
                  onClick={saveNow}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-[var(--gg-accent)] text-white shadow"
                >
                  <Save size={14} />
                  <span>Save now</span>
                </button>
                <button
                  type="button"
                  onClick={handleExportBackup}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-[var(--gg-surface-control)] text-[var(--gg-text-primary)]"
                >
                  <Download size={14} />
                  <span>Export full backup (.greenguide)</span>
                </button>
                <button
                  type="button"
                  onClick={handleExportMarkdown}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-emerald-800/60 hover:bg-emerald-800 text-white"
                >
                  <Layers size={14} />
                  <span>{mdExportProgress || 'Export as notes (Markdown zip)'}</span>
                </button>
                <label className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-[var(--gg-surface-control)] text-[var(--gg-text-primary)] cursor-pointer">
                  <Upload size={14} />
                  <span>Restore backup file</span>
                  <input type="file" accept=".greenguide,.json" onChange={handleArchiveUpload} className="hidden" />
                </label>
              </div>

              {/* Auto-Backup Settings (E5) */}
              <div className="p-3.5 rounded-2xl bg-black/30 border border-[var(--gg-divider)] space-y-3 text-xs">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-semibold text-[var(--gg-text-primary)]">Automatic Backups</div>
                    <div className="text-[11px] text-[var(--gg-text-secondary)]">
                      Periodically snapshot your journal in the background
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={Boolean(db.settings.autoBackupEnabled)}
                    onChange={(e) => updateSettings({ autoBackupEnabled: e.target.checked })}
                    className="w-4 h-4 accent-[var(--gg-accent)]"
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1 border-t border-white/5">
                  <label className="space-y-1">
                    <span>Frequency</span>
                    <select
                      value={db.settings.autoBackupIntervalDays ?? 1}
                      onChange={(e) => updateSettings({ autoBackupIntervalDays: Number(e.target.value) })}
                      className="w-full px-2 py-1 rounded-lg bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)] text-xs"
                    >
                      <option value={1}>Daily</option>
                      <option value={3}>Every 3 days</option>
                      <option value={7}>Weekly</option>
                      <option value={30}>Monthly</option>
                    </select>
                  </label>

                  <label className="space-y-1">
                    <span>Retention Limit</span>
                    <select
                      value={db.settings.autoBackupMaxRetention ?? 5}
                      onChange={(e) => updateSettings({ autoBackupMaxRetention: Number(e.target.value) })}
                      className="w-full px-2 py-1 rounded-lg bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)] text-xs"
                    >
                      <option value={3}>Keep 3 snapshots</option>
                      <option value={5}>Keep 5 snapshots</option>
                      <option value={10}>Keep 10 snapshots</option>
                    </select>
                  </label>

                  <div className="space-y-1">
                    <span>Last Backup</span>
                    <div className="p-1 text-[11px] text-[var(--gg-text-secondary)] font-mono">
                      {db.lastBackupAt ? new Date(db.lastBackupAt).toLocaleString() : 'Never'}
                    </div>
                  </div>
                </div>
              </div>

              {/* Recovery Points & Safety Snapshots (E5) */}
              <div className="p-3.5 rounded-2xl bg-black/30 border border-[var(--gg-divider)] space-y-3 text-xs">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-semibold text-[var(--gg-text-primary)]">Recovery Points ({recoveryPoints.length})</div>
                    <div className="text-[11px] text-[var(--gg-text-secondary)]">
                      Instant rollback points created before updates or restores.
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={async () => {
                      const pt = await createRecoveryPoint(db, 'MANUAL', 'Manual user recovery point');
                      setRecoveryPoints(await getRecoveryPoints());
                      pushToast({ title: 'Recovery point created' });
                      notifyChannel('backup', 'Backup finished', 'Manual recovery snapshot created.');
                    }}
                    className="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 text-[var(--gg-text-primary)] text-xs font-semibold"
                  >
                    Create point
                  </button>
                </div>

                <div className="space-y-1.5 max-h-48 overflow-y-auto">
                  {recoveryPoints.map((pt) => (
                    <div
                      key={pt.id}
                      className="p-2.5 rounded-xl bg-black/40 border border-white/5 flex items-center justify-between text-[11px]"
                    >
                      <div>
                        <div className="font-semibold text-[var(--gg-text-primary)]">{pt.label}</div>
                        <div className="text-[10px] text-[var(--gg-text-secondary)]">
                          {new Date(pt.createdAt).toLocaleString()} · {pt.stats.games} games, {pt.stats.legs} entries, {pt.stats.media} media
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={async () => {
                            if (confirm(`Restore recovery point "${pt.label}"? This replaces current session.`)) {
                              const restored = await loadRecoveryPointPayload(pt.id);
                              if (restored) {
                                replaceDatabase(restored);
                                pushToast({ title: 'Recovery point restored' });
                              }
                            }
                          }}
                          className="px-2.5 py-1 rounded-lg bg-[var(--gg-accent)] text-white font-semibold"
                        >
                          Restore
                        </button>
                        <button
                          type="button"
                          onClick={async () => {
                            await deleteRecoveryPoint(pt.id);
                            setRecoveryPoints(await getRecoveryPoints());
                          }}
                          className="p-1 rounded text-red-400 hover:text-red-300"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Maintenance Tools (E5) */}
              <div className="p-3.5 rounded-2xl bg-black/30 border border-[var(--gg-divider)] space-y-3 text-xs">
                <div className="font-semibold text-[var(--gg-text-primary)]">Maintenance &amp; Caches</div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={async () => {
                      setThumbProgress('Rebuilding...');
                      const res = await rebuildThumbnails(db, (p) => setThumbProgress(`${p.done}/${p.total}`));
                      setThumbProgress(null);
                      pushToast({ title: `Thumbnails rebuilt (${res.success} updated)` });
                    }}
                    className="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 text-[var(--gg-text-primary)]"
                  >
                    {thumbProgress ? `Thumbnails: ${thumbProgress}` : 'Rebuild thumbnails'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const res = rebuildSearchIndexes(db);
                      pushToast({ title: `Indexes rebuilt (${res.tokensIndexed} tokens)` });
                    }}
                    className="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 text-[var(--gg-text-primary)]"
                  >
                    Rebuild search indexes
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      await clearNonDataCaches({ clearXbox: true, clearPromptLog: true });
                      pushToast({ title: 'Non-data caches cleared' });
                    }}
                    className="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 text-[var(--gg-text-primary)]"
                  >
                    Clear caches
                  </button>
                  <button
                    type="button"
                    onClick={() => setIntegrityReport(runIntegrityCheck(db))}
                    className="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 text-[var(--gg-text-primary)]"
                  >
                    Run integrity check
                  </button>
                </div>
              </div>

              {/* Trash Manager */}
              <div className="pt-3 border-t border-[var(--gg-divider)] space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-[var(--gg-text-primary)]">
                    Trash ({trashedGames.length + trashedLegs.length + trashedTours.length} items)
                  </span>
                  {(trashedGames.length > 0 || trashedLegs.length > 0 || trashedTours.length > 0) && (
                    <button
                      type="button"
                      onClick={() => {
                        updateDb((prev) => emptyTrashSafely(prev), 'EmptyTrash');
                        pushToast({ title: 'Trash emptied safely' });
                      }}
                      className="inline-flex items-center gap-1 px-3 py-1 rounded-xl text-xs bg-red-900/60 text-red-100"
                    >
                      <Trash2 size={12} />
                      <span>Empty Trash Safely</span>
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* UPDATES (E3) */}
          {category === 'updates' && (
            <div className="space-y-5">
              <div>
                <h2 className="text-base font-semibold text-[var(--gg-text-primary)]">App Updates</h2>
                <p className="text-xs text-[var(--gg-text-secondary)]">
                  Check GitHub for new releases. Updates download directly as Android APK packages.
                </p>
              </div>

              <div className="p-3.5 rounded-2xl bg-black/30 border border-[var(--gg-divider)] space-y-3 text-xs">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <label className="space-y-1">
                    <span>GitHub Repository</span>
                    <input
                      type="text"
                      value={db.settings.updateRepo || 'contrail/green-guide'}
                      onChange={(e) => updateSettings({ updateRepo: e.target.value })}
                      placeholder="owner/repo"
                      className="w-full px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)] font-mono"
                    />
                  </label>

                  <label className="space-y-1">
                    <span>Release Channel</span>
                    <select
                      value={db.settings.updateChannel || 'STABLE'}
                      onChange={(e) => updateSettings({ updateChannel: e.target.value as any })}
                      className="w-full px-2.5 py-1.5 rounded-xl bg-[var(--gg-surface-control)] border border-[var(--gg-divider)] text-[var(--gg-text-primary)]"
                    >
                      <option value="STABLE">Stable releases</option>
                      <option value="BETA">Beta &amp; Pre-releases</option>
                    </select>
                  </label>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-white/5">
                  <div className="text-[11px] text-[var(--gg-text-secondary)]">
                    Installed: <span className="text-[var(--gg-text-primary)] font-semibold">{APP_DISPLAY_VERSION}</span>
                    {db.settings.lastUpdateCheckAt && (
                      <span> · Checked {new Date(db.settings.lastUpdateCheckAt).toLocaleTimeString()}</span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={handleCheckUpdates}
                    disabled={isCheckingUpdate}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[var(--gg-accent)] text-white text-xs font-semibold shadow"
                  >
                    <RefreshCw size={13} className={isCheckingUpdate ? 'animate-spin' : ''} />
                    <span>{isCheckingUpdate ? 'Checking...' : 'Check now'}</span>
                  </button>
                </div>
              </div>

              {updateInfo && (
                <div className="p-4 rounded-2xl bg-black/35 border border-[var(--gg-focus-ring)] space-y-3 text-xs">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-semibold text-[var(--gg-text-primary)]">{updateInfo.name}</div>
                      <div className="text-[11px] text-[var(--gg-text-secondary)]">
                        Tag {updateInfo.tag} · {new Date(updateInfo.publishedAt).toLocaleDateString()}
                      </div>
                    </div>
                    {updateInfo.apkDownloadUrl && (
                      <button
                        type="button"
                        onClick={() => openApkDownload(updateInfo.apkDownloadUrl!)}
                        className="px-3 py-1.5 rounded-xl bg-[var(--gg-accent)] text-white font-semibold text-xs inline-flex items-center gap-1.5"
                      >
                        <Download size={14} />
                        <span>Download APK</span>
                      </button>
                    )}
                  </div>

                  <div className="p-3 rounded-xl bg-black/40 text-[11px] text-white/90 whitespace-pre-wrap font-sans max-h-48 overflow-y-auto border border-white/5">
                    {updateInfo.body}
                  </div>
                  <div className="text-[10px] text-[var(--gg-text-secondary)]">
                    Android will request your confirmation when updating via downloaded APK.
                  </div>
                </div>
              )}
            </div>
          )}

          {/* MODULES (E7) */}
          {category === 'modules' && (
            <div className="space-y-4">
              <div>
                <h2 className="text-base font-semibold text-[var(--gg-text-primary)]">Modules</h2>
                <p className="text-xs text-[var(--gg-text-secondary)]">
                  Modular themes, prompt templates, layout scripts, and audio packages.
                </p>
              </div>

              {isSafeMode && (
                <div className="p-3 rounded-[var(--gg-r-control)] bg-amber-500/15 border border-amber-500/35 text-xs text-amber-200 flex items-center justify-between gap-2">
                  <span>Custom modules are paused while Safe Mode is active.</span>
                  <button
                    type="button"
                    onClick={() => exitSafeMode()}
                    className="px-2.5 py-1 rounded-[var(--gg-r-badge)] bg-amber-500 text-black font-semibold text-[11px]"
                  >
                    Exit Safe Mode
                  </button>
                </div>
              )}

              {/* Quarantined Modules Alert */}
              {getQuarantinedModules(db.modules).length > 0 && (
                <div className="p-3.5 rounded-2xl bg-amber-500/15 border border-amber-500/30 text-xs text-amber-200 space-y-2">
                  <div className="font-semibold flex items-center gap-1.5">
                    <ShieldAlert size={15} />
                    <span>Quarantined Modules ({getQuarantinedModules(db.modules).length})</span>
                  </div>
                  {getQuarantinedModules(db.modules).map((m) => (
                    <div key={m.id} className="flex items-center justify-between p-2 rounded-xl bg-black/40">
                      <div>
                        <div className="font-semibold text-[var(--gg-text-primary)]">{m.name}</div>
                        <div className="text-[10px] text-amber-300">{m.quarantineReason || 'Failed repeatedly during watchdog'}</div>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          updateDb((prev) => ({
                            ...prev,
                            modules: unquarantineModule(prev.modules, m.id),
                          }));
                          pushToast({ title: `Re-enabled ${m.name}` });
                        }}
                        className="px-2.5 py-1 rounded-lg bg-[var(--gg-accent)] text-white text-[11px] font-semibold"
                      >
                        Re-enable
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="space-y-1 max-h-[50vh] overflow-y-auto pr-1">
                  {db.modules.map((m) => (
                    <button
                      key={`${m.type}_${m.id}`}
                      type="button"
                      onClick={() => setSelectedModuleId(m.id)}
                      className={`w-full text-left p-2.5 rounded-xl text-xs border ${
                        selectedModule?.id === m.id
                          ? 'border-[var(--gg-focus-ring)] bg-[var(--gg-accent-wash)]'
                          : 'border-[var(--gg-divider)] bg-black/20'
                      }`}
                    >
                      <div className="font-semibold truncate text-[var(--gg-text-primary)]">{m.name}</div>
                      <div className="text-[10px] font-mono text-[var(--gg-text-secondary)]">
                        {m.type} · v{m.version}
                      </div>
                    </button>
                  ))}
                </div>

                <div className="lg:col-span-2 space-y-2">
                  {selectedModule && (
                    <>
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="text-sm font-semibold text-[var(--gg-text-primary)]">{selectedModule.name}</div>
                          <div className="text-xs text-[var(--gg-text-secondary)]">{selectedModule.description}</div>
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            const res = parseModuleMarkdown(selectedModule.rawMd);
                            if (res.valid) {
                              pushToast({ title: 'Module syntax valid' });
                            } else {
                              pushToast({ title: 'Validation error', subtitle: res.errors.join(', '), kind: 'error' });
                            }
                          }}
                          className="px-2.5 py-1 rounded-lg bg-white/10 hover:bg-white/15 text-xs text-[var(--gg-text-primary)]"
                        >
                          Validate
                        </button>
                      </div>
                      <textarea
                        rows={14}
                        value={selectedModule.rawMd}
                        onChange={(e) => {
                          const val = e.target.value;
                          updateDb((prev) => ({
                            ...prev,
                            modules: prev.modules.map((m) =>
                              m.id === selectedModule.id ? { ...m, rawMd: val, updatedAt: Date.now() } : m
                            ),
                          }));
                        }}
                        className="w-full p-3 rounded-xl font-mono text-xs bg-black/35 border border-[var(--gg-divider)] text-white"
                      />
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* SYSTEM, LOGS & ABOUT (E1 & E4) */}
          {category === 'system' && (
            <div className="space-y-5">
              <div>
                <h2 className="text-base font-semibold text-[var(--gg-text-primary)]">System, Logs &amp; Diagnostics</h2>
                <p className="text-xs text-[var(--gg-text-secondary)]">
                  Crash traces, safe mode status, and build diagnostics.
                </p>
              </div>

              {/* Version & 7-Tap Dev Options */}
              <div className="p-3.5 rounded-2xl bg-black/30 border border-[var(--gg-divider)] flex items-center justify-between">
                <div>
                  <button
                    type="button"
                    onClick={handleVerClick}
                    className="text-left text-sm font-semibold text-[var(--gg-text-primary)] hover:text-[var(--gg-accent)] cursor-pointer select-none"
                  >
                    Green Guide {APP_VERSION}
                  </button>
                  <div className="text-xs text-[var(--gg-text-secondary)]">
                    Build 2026.11 · Native Capacitor 8
                  </div>
                </div>
                <button
                  type="button"
                  onClick={async () => {
                    const text = `Green Guide ${APP_DISPLAY_VERSION} Diagnostics\nUA: ${navigator.userAgent}\nTheme: ${db.settings.themeMode}\nAccent: ${db.settings.accentHex}\nScreen: ${window.innerWidth}x${window.innerHeight} (${window.devicePixelRatio}x)\nGames: ${db.games.length}\nLegs: ${db.legs.length}\nMedia: ${db.media.length}`;
                    await navigator.clipboard.writeText(text);
                    pushToast({ title: 'Diagnostics copied to clipboard' });
                  }}
                  className="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 text-[var(--gg-text-primary)] text-xs font-semibold inline-flex items-center gap-1.5"
                >
                  <Copy size={13} />
                  <span>Copy diagnostics</span>
                </button>
              </div>

              {/* Safe Mode Switch */}
              <div className="p-3.5 rounded-[var(--gg-r-tile)] bg-black/30 border border-[var(--gg-divider)] flex items-center justify-between gap-3">
                <div>
                  <div className="font-semibold text-sm text-[var(--gg-text-primary)]">Start in Safe Mode on next launch</div>
                  <div className="text-xs text-[var(--gg-text-secondary)]">
                    Disables custom modules, custom layouts, AI queues, auto-refreshes, notifications, and App Lock for one launch.
                  </div>
                </div>
                <div className="flex items-center gap-2.5 shrink-0">
                  {isSafeMode && (
                    <button
                      type="button"
                      onClick={() => exitSafeMode()}
                      className="px-2.5 py-1 rounded-[var(--gg-r-control)] bg-amber-500 text-black text-[11px] font-semibold"
                    >
                      Exit Safe Mode
                    </button>
                  )}
                  <input
                    type="checkbox"
                    aria-label="Start in Safe Mode on next launch"
                    checked={safeModeReq}
                    onChange={(e) => {
                      const next = e.target.checked;
                      setSafeModeRequested(next);
                      setSafeModeReq(next);
                      pushToast({ title: next ? 'Safe Mode armed for next launch' : 'Safe Mode request cleared' });
                    }}
                    className="w-4 h-4 accent-[var(--gg-accent)]"
                  />
                </div>
              </div>

              {/* Logs Sub-tabs: Crash Log vs Boot Trace */}
              <div className="flex gap-2 border-b border-[var(--gg-divider)] pb-2">
                <button
                  type="button"
                  onClick={() => setLogsTab('crash')}
                  className={`px-3 py-1.5 rounded-[var(--gg-r-control)] text-xs font-semibold transition-colors ${
                    logsTab === 'crash'
                      ? 'bg-[var(--gg-accent)] text-white'
                      : 'bg-white/10 text-[var(--gg-text-secondary)] hover:text-[var(--gg-text-primary)]'
                  }`}
                >
                  Crash Log ({getCrashLogs().length})
                </button>
                <button
                  type="button"
                  onClick={() => setLogsTab('boot')}
                  className={`px-3 py-1.5 rounded-[var(--gg-r-control)] text-xs font-semibold transition-colors ${
                    logsTab === 'boot'
                      ? 'bg-[var(--gg-accent)] text-white'
                      : 'bg-white/10 text-[var(--gg-text-secondary)] hover:text-[var(--gg-text-primary)]'
                  }`}
                >
                  Boot Trace ({getBootTraces().length})
                </button>
              </div>

              {logsTab === 'crash' && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold text-[var(--gg-text-primary)]">Crash Log ({getCrashLogs().length})</h3>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={async () => {
                          const txt = exportCrashLogsText();
                          await navigator.clipboard.writeText(txt);
                          pushToast({ title: 'Crash logs copied' });
                        }}
                        className="px-2.5 py-1 rounded-[var(--gg-r-control)] bg-white/10 text-[var(--gg-text-primary)] text-[11px]"
                      >
                        Copy all
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          clearCrashLogs();
                          setCrashLogTick((n) => n + 1);
                          pushToast({ title: 'Crash logs cleared' });
                        }}
                        className="px-2.5 py-1 rounded-[var(--gg-r-control)] bg-white/10 text-[var(--gg-text-primary)] text-[11px]"
                      >
                        Clear
                      </button>
                    </div>
                  </div>
                  <div className="p-3 rounded-[var(--gg-r-control)] bg-black/35 font-mono text-[10px] text-white/90 max-h-48 overflow-y-auto whitespace-pre-wrap border border-white/5">
                    {exportCrashLogsText()}
                  </div>
                </div>
              )}

              {logsTab === 'boot' && (
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold text-[var(--gg-text-primary)]">Recent Boot Traces (Last {getBootTraces().length} of 5)</h3>
                    <span className="text-[11px] text-[var(--gg-text-secondary)]">
                      3 consecutive incomplete launches trigger Safe Mode
                    </span>
                  </div>
                  {getBootTraces().length === 0 ? (
                    <div className="p-3 rounded-[var(--gg-r-control)] bg-black/35 text-xs text-[var(--gg-text-secondary)] border border-white/5">
                      No boot traces recorded yet.
                    </div>
                  ) : (
                    <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                      {getBootTraces().map((t) => {
                        const durationMs = t.readyAt ? Math.max(0, t.readyAt - t.startedAt) : null;
                        return (
                          <div key={t.launchId} className="p-3 rounded-[var(--gg-r-control)] bg-black/35 border border-white/5 space-y-2">
                            <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                              <div className="flex items-center gap-2 min-w-0">
                                <span className="font-mono text-[var(--gg-text-primary)] truncate">{t.launchId}</span>
                                <span className="text-[10px] text-[var(--gg-text-secondary)]">
                                  {new Date(t.startedAt).toLocaleString()}
                                </span>
                              </div>
                              <div className="flex items-center gap-2">
                                {durationMs !== null && (
                                  <span className="text-[10px] font-mono text-[var(--gg-text-secondary)]">
                                    {durationMs} ms
                                  </span>
                                )}
                                <span
                                  className={`px-2 py-0.5 rounded-[var(--gg-r-badge)] text-[10px] font-semibold ${
                                    t.healthy
                                      ? 'bg-emerald-500/20 text-emerald-300'
                                      : 'bg-amber-500/20 text-amber-300'
                                  }`}
                                >
                                  {t.healthy ? 'Ready ✓' : 'Incomplete ✕'}
                                </span>
                              </div>
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              {t.stages.map((st) => (
                                <span
                                  key={st.stage}
                                  className="px-2 py-0.5 rounded-[var(--gg-r-badge)] bg-white/5 border border-white/10 font-mono text-[10px] text-[var(--gg-text-broadcast)]"
                                >
                                  {st.stage} +{Math.max(0, st.ts - t.startedAt)}ms
                                </span>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Licences & Credits */}
              <div className="pt-3 border-t border-[var(--gg-divider)] text-[11px] text-[var(--gg-text-secondary)] space-y-1">
                <div className="font-semibold text-[var(--gg-text-primary)]">Open Source Licences</div>
                <div>Apache-2.0 &amp; MIT · OurAirports navigation data · Natural Earth geographic vectors.</div>
              </div>
            </div>
          )}

          {/* SOUNDS */}
          {category === 'sounds' && (
            <div className="space-y-4 text-xs">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {(
                  [
                    { key: 'soundMaster', label: 'Master Volume' },
                    { key: 'soundUi', label: 'UI Focus & Confirm' },
                    { key: 'soundFeedback', label: 'Save & Milestone Chimes' },
                    { key: 'soundKeeper', label: 'Keeper Send / Reply' },
                    { key: 'soundSplash', label: 'Boot Splash' },
                  ] as const
                ).map((s) => (
                  <label key={s.key} className="space-y-1">
                    <div className="flex justify-between">
                      <span className="text-[var(--gg-text-primary)]">{s.label}</span>
                      <span className="tabular-nums text-[var(--gg-text-secondary)]">{db.settings[s.key]}%</span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={db.settings[s.key]}
                      onChange={(e) => updateSettings({ [s.key]: Number(e.target.value) })}
                      className="w-full accent-[var(--gg-accent)]"
                    />
                  </label>
                ))}
              </div>
              <div className="flex flex-wrap gap-2 pt-2">
                {(['select', 'guide_open', 'milestone', 'save'] as const).map((ev) => (
                  <button
                    key={ev}
                    type="button"
                    onClick={() => playSound(ev)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[var(--gg-surface-control)] text-[var(--gg-text-primary)] hover:bg-white/15"
                  >
                    <Volume2 size={13} />
                    <span>Test {ev}</span>
                  </button>
                ))}
              </div>
              <label className="inline-flex items-center gap-2 pt-2 text-[var(--gg-text-primary)]">
                <input
                  type="checkbox"
                  checked={db.settings.hapticsEnabled}
                  onChange={(e) => updateSettings({ hapticsEnabled: e.target.checked })}
                />
                <span>Haptic feedback (vibration on select and milestones)</span>
              </label>
            </div>
          )}

          {/* WHAT'S NEW */}
          {category === 'whatsnew' && (
            <div className="space-y-4">
              <pre className="p-4 rounded-2xl bg-black/35 border border-[var(--gg-divider)] font-sans text-xs text-white/90 whitespace-pre-wrap leading-relaxed">
                {CHANGELOG_MD}
              </pre>
            </div>
          )}
        </section>
      </div>

      {showCheatsheet && (
        <KeyboardCheatsheetModal
          onClose={() => setShowCheatsheet(false)}
          nintendoAbSwap={db.settings.nintendoAbSwap}
        />
      )}
    </div>
  );
}
