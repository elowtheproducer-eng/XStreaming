/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { XBOX, titleHistoryUrl } from './endpoints.ts';
import { xboxFetch } from './http.ts';
import {
  extractTitleArtVariants,
  pickCoverArt,
  pickWallpaperArt,
  type TitleArtVariant,
  type TitleHubItem,
} from './titlehub.ts';
import { session } from './session.ts';
import { idbGet, idbSet, idbDelete } from '../persist.ts';

export interface XboxTitleStat {
  titleId: string;
  name: string;
  artUrl?: string;
  coverUrl?: string;
  wallpaperUrl?: string;
  variants?: TitleArtVariant[];
  lastPlayedAt?: number;
  minutesPlayed?: number;
  gamerscore?: number;
  totalGamerscore?: number;
  achievementsUnlocked?: number;
  totalAchievements?: number;
  progressPct?: number;
}

export interface XboxProfileSnapshot {
  fetchedAt: number;
  xuid: string;
  gamertag: string;
  displayName?: string;
  avatarUrl?: string;
  gamerscore: number;
  tier?: string;
  reputation?: string;
  /** Number of games with a recorded play date. */
  gamesPlayed: number;
  /** Sum of MinutesPlayed over the games Xbox reports it for. */
  totalMinutes: number;
  /** How many of those games actually reported play time. */
  gamesWithTime: number;
  /** Most recently played first. */
  titles: XboxTitleStat[];
}

const CACHE_KEY = 'xbox_profile_v1';
const PROFILE_BASE = 'https://profile.xboxlive.com';
const USERSTATS_BATCH = 'https://userstats.xboxlive.com/batch';

const asJson = (data: any) => (typeof data === 'string' ? JSON.parse(data) : data);
const ok = (status: number) => status >= 200 && status < 300;

export async function getCachedXboxProfile(): Promise<XboxProfileSnapshot | null> {
  try {
    const raw = await idbGet(CACHE_KEY);
    return raw ? (JSON.parse(raw) as XboxProfileSnapshot) : null;
  } catch {
    return null;
  }
}

export async function saveCachedXboxProfile(snapshot: XboxProfileSnapshot): Promise<void> {
  await idbSet(CACHE_KEY, JSON.stringify(snapshot));
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('xbox-profile-updated', { detail: snapshot }));
  }
}

export async function clearCachedXboxProfile(): Promise<void> {
  await idbDelete(CACHE_KEY);
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('xbox-profile-updated', { detail: null }));
  }
}

export function computeXboxTierLabel(tier?: string, _reputation?: string, fallback = 'XBOX'): string {
  const raw = tier?.trim();
  if (!raw) return fallback;
  const t = raw.toLowerCase().replace(/[\s_-]/g, '');
  if (t === 'gold' || t === 'xboxlivegold') return 'GOLD';
  if (t === 'silver') return 'SILVER';
  if (t.includes('ultimate')) return 'ULTIMATE';
  if (t.includes('gamepass') || t === 'pass') return 'GAME PASS';
  return raw.toUpperCase();
}

export interface EffectivePlayerProfile {
  isXboxLinked: boolean;
  playerTag: string;
  displayName: string;
  avatarUrl?: string;
  tier: string;
  gamerscore?: number;
  totalMinutes: number;
  totalHours: number;
  hoursFormatted: string;
  gamesCount: number;
}

export function getEffectivePlayerProfile(
  settings: { playerTag: string },
  ledger: { globalHours: number; globalLevel: string },
  xboxProfile: XboxProfileSnapshot | null,
  activeGamesCount = 0
): EffectivePlayerProfile {
  if (xboxProfile) {
    const hasXboxMinutes = typeof xboxProfile.totalMinutes === 'number' && xboxProfile.totalMinutes > 0;
    const totalHours = hasXboxMinutes
      ? Number((xboxProfile.totalMinutes / 60).toFixed(1))
      : ledger.globalHours;
    return {
      isXboxLinked: true,
      playerTag: xboxProfile.gamertag?.trim() || settings.playerTag,
      displayName: xboxProfile.displayName?.trim() || xboxProfile.gamertag?.trim() || settings.playerTag,
      avatarUrl: xboxProfile.avatarUrl?.trim() || undefined,
      tier: computeXboxTierLabel(xboxProfile.tier, xboxProfile.reputation),
      gamerscore: typeof xboxProfile.gamerscore === 'number' ? xboxProfile.gamerscore : undefined,
      totalMinutes: hasXboxMinutes ? xboxProfile.totalMinutes : Math.round(ledger.globalHours * 60),
      totalHours,
      hoursFormatted: `${totalHours}h`,
      gamesCount: xboxProfile.gamesPlayed || activeGamesCount,
    };
  }

  return {
    isXboxLinked: false,
    playerTag: settings.playerTag,
    displayName: settings.playerTag,
    avatarUrl: undefined,
    tier: ledger.globalLevel,
    gamerscore: undefined,
    totalMinutes: Math.round(ledger.globalHours * 60),
    totalHours: ledger.globalHours,
    hoursFormatted: `${ledger.globalHours}h`,
    gamesCount: activeGamesCount,
  };
}

async function fetchProfileSettings(xuid: string) {
  const settings = [
    'Gamerscore',
    'Gamertag',
    'GameDisplayName',
    'GameDisplayPicRaw',
    'AccountTier',
    'XboxOneRep',
  ].join(',');
  const res = await xboxFetch(
    `${PROFILE_BASE}/users/xuid(${xuid})/profile/settings?settings=${settings}`,
    {
      headers: {
        'x-xbl-contract-version': '3',
        Accept: 'application/json',
      },
    }
  );
  if (!ok(res.status)) throw new Error(`Xbox profile request failed (${res.status})`);
  const data = asJson(res.data);
  const list: Array<{ id: string; value: string }> = data?.profileUsers?.[0]?.settings ?? [];
  const get = (id: string) => list.find((s) => s.id === id)?.value;
  return {
    gamerscore: Number(get('Gamerscore')) || 0,
    gamertag: get('Gamertag'),
    displayName: get('GameDisplayName'),
    avatarUrl: get('GameDisplayPicRaw'),
    tier: get('AccountTier'),
    reputation: get('XboxOneRep'),
  };
}

async function fetchTitleHistoryDetailed(xuid: string): Promise<XboxTitleStat[]> {
  // Same endpoint the capture matcher uses, with achievement data added.
  const url = titleHistoryUrl(xuid).replace('/detail,image', '/detail,image,scid,achievement');
  const res = await xboxFetch(url, {
    headers: {
      'x-xbl-contract-version': XBOX.TITLEHUB_CONTRACT,
      'x-xbl-client-name': 'XboxApp',
      'x-xbl-client-type': 'UWA',
      Accept: 'application/json',
    },
  });
  if (!ok(res.status)) throw new Error(`Xbox game history request failed (${res.status})`);
  const data = asJson(res.data);
  const items: Array<TitleHubItem & Record<string, any>> = data?.titles ?? [];
  const out: XboxTitleStat[] = [];
  for (const t of items) {
    if (!t.titleId) continue;
    const kind = String(t.type ?? 'Game').toLowerCase();
    if (kind !== 'game') continue; // skip apps like Netflix / Edge
    const last = t.titleHistory?.lastTimePlayed ? Date.parse(t.titleHistory.lastTimePlayed) : NaN;
    const ach = t.achievement ?? {};
    const coverUrl = pickCoverArt(t);
    const wallpaperUrl = pickWallpaperArt(t);
    out.push({
      titleId: String(t.titleId),
      name: t.name?.trim() || 'Unknown Game',
      artUrl: wallpaperUrl || coverUrl,
      coverUrl,
      wallpaperUrl,
      variants: extractTitleArtVariants(t),
      lastPlayedAt: Number.isFinite(last) && last > 0 ? last : undefined,
      gamerscore: typeof ach.currentGamerscore === 'number' ? ach.currentGamerscore : undefined,
      totalGamerscore: typeof ach.totalGamerscore === 'number' ? ach.totalGamerscore : undefined,
      achievementsUnlocked:
        typeof ach.currentAchievements === 'number' ? ach.currentAchievements : undefined,
      totalAchievements: typeof ach.totalAchievements === 'number' ? ach.totalAchievements : undefined,
      progressPct: typeof ach.progressPercentage === 'number' ? ach.progressPercentage : undefined,
    });
  }
  return out;
}

/**
 * Minutes played per title via the userstats service. Not every game reports
 * it (that is up to the publisher), so missing values stay undefined.
 */
async function fetchMinutesPlayed(xuid: string, titleIds: string[]): Promise<Map<string, number>> {
  const minutes = new Map<string, number>();
  for (let i = 0; i < titleIds.length; i += 50) {
    const chunk = titleIds.slice(i, i + 50);
    try {
      const res = await xboxFetch(USERSTATS_BATCH, {
        method: 'POST',
        headers: {
          'x-xbl-contract-version': '2',
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: {
          arrangebyfield: 'xuid',
          xuids: [xuid],
          stats: chunk.map((titleid) => ({ name: 'MinutesPlayed', titleid })),
        },
      });
      if (!ok(res.status)) continue;
      const data = asJson(res.data);
      const stats: Array<{ name: string; titleid: string; value: string | number }> =
        data?.statlistscollection?.[0]?.stats ?? [];
      for (const s of stats) {
        const v = Number(s.value);
        if (s.name === 'MinutesPlayed' && Number.isFinite(v) && v > 0) {
          minutes.set(String(s.titleid), v);
        }
      }
    } catch {
      /* best effort: time played is optional */
    }
  }
  return minutes;
}

/** Pulls gamerscore, games played, time played and recent games, then caches them. */
export async function refreshXboxProfile(): Promise<XboxProfileSnapshot> {
  const status = await session.getSessionStatus();
  if (!status.signedIn || !status.xuid) throw new Error('Link your Xbox account first.');
  const xuid = status.xuid;

  const [profile, titles] = await Promise.all([
    fetchProfileSettings(xuid),
    fetchTitleHistoryDetailed(xuid),
  ]);

  const played = titles.filter((t) => t.lastPlayedAt);
  const minutes = await fetchMinutesPlayed(
    xuid,
    played.map((t) => t.titleId)
  );
  for (const t of played) t.minutesPlayed = minutes.get(t.titleId);

  played.sort((a, b) => (b.lastPlayedAt ?? 0) - (a.lastPlayedAt ?? 0));

  const snapshot: XboxProfileSnapshot = {
    fetchedAt: Date.now(),
    xuid,
    gamertag: profile.gamertag || status.gamertag || 'Xbox Player',
    displayName: profile.displayName,
    avatarUrl: profile.avatarUrl,
    gamerscore: profile.gamerscore,
    tier: profile.tier,
    reputation: profile.reputation,
    gamesPlayed: played.length,
    totalMinutes: [...minutes.values()].reduce((a, b) => a + b, 0),
    gamesWithTime: minutes.size,
    titles: played,
  };
  await saveCachedXboxProfile(snapshot);
  return snapshot;
}

export function formatMinutes(min?: number): string {
  if (!min || min <= 0) return '—';
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  if (h >= 100) return `${h.toLocaleString()} h`;
  if (h > 0) return `${h} h ${m} m`;
  return `${m} m`;
}

export function formatAgo(ts?: number): string {
  if (!ts) return '';
  const diff = Date.now() - ts;
  const day = 86_400_000;
  if (diff < 3_600_000) return 'Just now';
  if (diff < day) return `${Math.floor(diff / 3_600_000)} h ago`;
  if (diff < day * 2) return 'Yesterday';
  if (diff < day * 30) return `${Math.floor(diff / day)} days ago`;
  return new Date(ts).toLocaleDateString();
}
