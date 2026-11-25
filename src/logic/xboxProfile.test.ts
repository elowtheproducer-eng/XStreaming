import test from 'node:test';
import assert from 'node:assert/strict';
import {
  computeXboxTierLabel,
  getEffectivePlayerProfile,
  type XboxProfileSnapshot,
} from './xbox/profile';

test('computeXboxTierLabel normalizes Xbox account tiers and status correctly', () => {
  assert.equal(computeXboxTierLabel('Gold'), 'GOLD');
  assert.equal(computeXboxTierLabel('XboxLiveGold'), 'GOLD');
  assert.equal(computeXboxTierLabel('Silver'), 'SILVER');
  assert.equal(computeXboxTierLabel('Xbox Game Pass Ultimate'), 'ULTIMATE');
  assert.equal(computeXboxTierLabel('PC Game Pass'), 'GAME PASS');
  assert.equal(computeXboxTierLabel(undefined, 'GoodPlayer'), 'XBOX');
  assert.equal(computeXboxTierLabel(undefined, undefined, 'VETERAN'), 'VETERAN');
});

test('getEffectivePlayerProfile falls back cleanly when Xbox is not linked', () => {
  const profile = getEffectivePlayerProfile(
    { playerTag: 'SkyPilot_01' },
    { globalHours: 54.1, globalLevel: 'VETERAN' },
    null,
    3
  );

  assert.equal(profile.isXboxLinked, false);
  assert.equal(profile.playerTag, 'SkyPilot_01');
  assert.equal(profile.avatarUrl, undefined);
  assert.equal(profile.tier, 'VETERAN');
  assert.equal(profile.gamerscore, undefined);
  assert.equal(profile.totalHours, 54.1);
  assert.equal(profile.hoursFormatted, '54.1h');
  assert.equal(profile.gamesCount, 3);
});

test('getEffectivePlayerProfile prioritizes Xbox gamertag, avatar, tier, gamerscore and playtime when linked', () => {
  const snapshot: XboxProfileSnapshot = {
    fetchedAt: Date.now(),
    xuid: '2533274791234567',
    gamertag: 'AeroAce99',
    displayName: 'AeroAce99',
    avatarUrl: 'https://avatar-ssl.xboxlive.com/avatar/sample.png',
    gamerscore: 48920,
    tier: 'Gold',
    reputation: 'GoodPlayer',
    gamesPlayed: 14,
    totalMinutes: 7350, // 122.5 hours
    gamesWithTime: 10,
    titles: [],
  };

  const profile = getEffectivePlayerProfile(
    { playerTag: 'SkyPilot_01' },
    { globalHours: 54.1, globalLevel: 'VETERAN' },
    snapshot,
    3
  );

  assert.equal(profile.isXboxLinked, true);
  assert.equal(profile.playerTag, 'AeroAce99');
  assert.equal(profile.avatarUrl, 'https://avatar-ssl.xboxlive.com/avatar/sample.png');
  assert.equal(profile.tier, 'GOLD');
  assert.equal(profile.gamerscore, 48920);
  assert.equal(profile.totalMinutes, 7350);
  assert.equal(profile.totalHours, 122.5);
  assert.equal(profile.hoursFormatted, '122.5h');
  assert.equal(profile.gamesCount, 14);
});

test('getEffectivePlayerProfile uses journal hours if Xbox reports zero playtime', () => {
  const snapshot: XboxProfileSnapshot = {
    fetchedAt: Date.now(),
    xuid: '2533274791234567',
    gamertag: 'SkyCaptain',
    gamerscore: 15400,
    tier: 'Ultimate',
    gamesPlayed: 5,
    totalMinutes: 0,
    gamesWithTime: 0,
    titles: [],
  };

  const profile = getEffectivePlayerProfile(
    { playerTag: 'SkyPilot_01' },
    { globalHours: 65.4, globalLevel: 'EXPERT' },
    snapshot,
    2
  );

  assert.equal(profile.isXboxLinked, true);
  assert.equal(profile.playerTag, 'SkyCaptain');
  assert.equal(profile.gamerscore, 15400);
  assert.equal(profile.tier, 'ULTIMATE');
  assert.equal(profile.totalHours, 65.4);
  assert.equal(profile.hoursFormatted, '65.4h');
});
