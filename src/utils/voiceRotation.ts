export const VOICE_MODELS: string[] = [
  'gemini-3.8-flash-tts',
  'gemini-3.8-flash-lite-tts',
  'gemini-3.1-flash-tts-preview',
  'gemini-2.5-pro-preview-tts',
  'gemini-2.5-flash-preview-tts',
];

export const VOICE_ROUTE_GAP_MS = 20000;
export const MIN_WORDS = 40;
export const RETRY_WORDS = 45;

export interface VoiceKey {
  id: number;
  key: string;
}

export interface VoiceRoute {
  model: string;
  id: number;
  key: string;
  tag: string;
}

export interface RotationState {
  nextIndex: number;
  lastUsedAt: Record<string, number>;
}

function safeModelIndex(nextIndex: number): number {
  const len = VOICE_MODELS.length;
  const raw = Number.isFinite(nextIndex) ? Math.trunc(nextIndex) : 0;
  return ((raw % len) + len) % len;
}

export function newRotationState(): RotationState {
  return {nextIndex: 0, lastUsedAt: {}};
}

export function buildVoiceRoutes(
  keys: VoiceKey[],
  cooldown: Record<string, number>,
  state: RotationState,
  now: number,
): VoiceRoute[] {
  const len = VOICE_MODELS.length;
  const start = safeModelIndex(state.nextIndex);
  const ready: VoiceRoute[] = [];
  const resting: VoiceRoute[] = [];

  for (let i = 0; i < len; i += 1) {
    const model = VOICE_MODELS[(start + i) % len];
    const ordered = keys.map((k, idx) => ({
      k,
      idx,
      used: state.lastUsedAt[model + '@' + k.id] || 0,
    }));
    ordered.sort((a, b) => (a.used !== b.used ? a.used - b.used : a.idx - b.idx));

    for (const item of ordered) {
      const key = item.k;
      const tag = model + '@' + key.id;
      if ((cooldown[tag] || 0) > now) {
        continue;
      }
      const route: VoiceRoute = {model, id: key.id, key: key.key, tag};
      if (now - (state.lastUsedAt[tag] || 0) < VOICE_ROUTE_GAP_MS) {
        resting.push(route);
      } else {
        ready.push(route);
      }
    }
  }

  return ready.concat(resting);
}

export function markUsed(state: RotationState, tag: string, now: number): void {
  state.lastUsedAt[tag] = now;
}

export function afterSuccess(
  state: RotationState,
  model: string,
): {used: string; next: string} {
  const index = VOICE_MODELS.indexOf(model);
  if (index !== -1) {
    state.nextIndex = (index + 1) % VOICE_MODELS.length;
  }
  const safeIdx = safeModelIndex(state.nextIndex);
  return {used: model, next: VOICE_MODELS[safeIdx]};
}

export function rotationText(state: RotationState): string {
  return 'voice rotation: next is ' + VOICE_MODELS[safeModelIndex(state.nextIndex)];
}

export function wordCount(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  return trimmed.split(/\s+/).filter(Boolean).length;
}

export function isTooShort(text: string): boolean {
  const count = wordCount(text);
  if (count === 0) return false;
  return count < MIN_WORDS;
}

export function shortRetryNote(words: number): string {
  return (
    '\nYOUR LAST DRAFT WAS TOO SHORT (' +
    words +
    ' words). Write at least ' +
    RETRY_WORDS +
    ' words.'
  );
}
