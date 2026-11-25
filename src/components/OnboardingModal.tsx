import React, { useState } from 'react';
import { useJournal } from '../state/JournalStore';
import { ACCENT_PRESETS } from '../logic/theme';
import { Check, ChevronRight, ChevronLeft, ShieldCheck, Sparkles, User, Palette } from 'lucide-react';
import { PermissionsSetupModal } from './PermissionsSetupModal';
import { checkAllPermissions, type AppPermission, type PermissionState } from '../logic/permissions';

interface Props {
  onDismiss: () => void;
}

export function OnboardingModal({ onDismiss }: Props) {
  const { db, updateSettings, playSound } = useJournal();
  const [step, setStep] = useState(0);
  const [playerTag, setPlayerTag] = useState(db.settings.playerTag || 'Player');
  const [themeMode, setThemeMode] = useState(db.settings.themeMode || 'NIGHT');
  const [accentHex, setAccentHex] = useState(db.settings.accentHex || '#107C10');
  const [showPermsModal, setShowPermsModal] = useState(false);
  const [permRows, setPermRows] = useState<Array<{ perm: AppPermission; state: PermissionState }> | null>(null);

  const completeOnboarding = () => {
    updateSettings({
      playerTag: playerTag.trim() || 'Player',
      themeMode,
      accentHex,
      onboardingCompleted: true,
    });
    playSound('save');
    onDismiss();
  };

  const nextStep = () => {
    if (step < 4) {
      playSound('select');
      setStep(step + 1);
    } else {
      completeOnboarding();
    }
  };

  const prevStep = () => {
    if (step > 0) {
      playSound('focus_move');
      setStep(step - 1);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-md animate-fade-in">
      <div className="w-full max-w-lg p-6 rounded-2xl bg-[var(--gg-bg-raised,#1b2024)] border border-[var(--gg-divider,#2d3439)] shadow-2xl flex flex-col justify-between min-h-[420px]">
        {/* Step indicator */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-[var(--gg-text-secondary,#8c9ba5)]">
            <span className="font-semibold text-[var(--gg-accent,#107c10)] uppercase tracking-wider text-[11px]">
              Step {step + 1} of 5
            </span>
            <button
              type="button"
              onClick={completeOnboarding}
              className="text-xs hover:text-[var(--gg-text-primary)] underline cursor-pointer"
            >
              Skip setup
            </button>
          </div>
          <div className="grid grid-cols-5 gap-1.5 h-1.5 rounded-full overflow-hidden bg-white/10">
            {[0, 1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className={`h-full transition-colors ${
                  i <= step ? 'bg-[var(--gg-accent,#107c10)]' : 'bg-transparent'
                }`}
              />
            ))}
          </div>
        </div>

        {/* Step Content */}
        <div className="py-6 space-y-4">
          {step === 0 && (
            <div className="space-y-4 text-center">
              <div className="w-12 h-12 mx-auto rounded-2xl bg-[var(--gg-accent,#107c10)]/20 text-[var(--gg-accent,#107c10)] flex items-center justify-center">
                <User size={24} />
              </div>
              <div className="space-y-1">
                <h2 className="text-xl font-light text-[var(--gg-text-primary)]">Welcome to Green Guide</h2>
                <p className="text-xs text-[var(--gg-text-secondary,#8c9ba5)]">
                  Your offline flight simulator and gaming journal. What should we call you?
                </p>
              </div>
              <input
                type="text"
                value={playerTag}
                onChange={(e) => setPlayerTag(e.target.value)}
                placeholder="Enter player tag"
                className="max-w-xs mx-auto px-4 py-2.5 rounded-xl text-sm text-center bg-black/40 border border-[var(--gg-divider,#2d3439)] text-white font-medium focus:border-[var(--gg-focus-ring)] outline-none"
              />
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4 text-center">
              <div className="w-12 h-12 mx-auto rounded-2xl bg-[var(--gg-accent,#107c10)]/20 text-[var(--gg-accent,#107c10)] flex items-center justify-center">
                <Palette size={24} />
              </div>
              <div className="space-y-1">
                <h2 className="text-xl font-light text-[var(--gg-text-primary)]">Theme &amp; Accent</h2>
                <p className="text-xs text-[var(--gg-text-secondary,#8c9ba5)]">
                  Choose your display mode and favorite console highlight color.
                </p>
              </div>
              <div className="flex justify-center gap-2">
                {(['NIGHT', 'DAY', 'AUTO_CLOCK'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setThemeMode(mode)}
                    className={`px-3 py-1.5 rounded-xl text-xs font-semibold ${
                      themeMode === mode
                        ? 'bg-[var(--gg-accent,#107c10)] text-white'
                        : 'bg-white/10 text-[var(--gg-text-secondary,#8c9ba5)]'
                    }`}
                  >
                    {mode.replace('_', ' ')}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap justify-center gap-2 max-w-xs mx-auto pt-2">
                {ACCENT_PRESETS.map((p) => {
                  const active = accentHex.toLowerCase() === p.hex.toLowerCase();
                  return (
                    <button
                      key={p.hex}
                      type="button"
                      onClick={() => setAccentHex(p.hex)}
                      aria-label={`Color ${p.name}`}
                      className={`w-7 h-7 rounded-lg flex items-center justify-center border-2 ${
                        active ? 'border-white scale-110' : 'border-transparent'
                      }`}
                      style={{ backgroundColor: p.hex }}
                    >
                      {active && <Check size={14} className="text-white drop-shadow" />}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4 text-center">
              <div className="w-12 h-12 mx-auto rounded-2xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center">
                <Sparkles size={24} />
              </div>
              <div className="space-y-1">
                <h2 className="text-xl font-light text-[var(--gg-text-primary)]">Xbox Captures</h2>
                <p className="text-xs text-[var(--gg-text-secondary,#8c9ba5)]">
                  Link your Microsoft account in Settings at any time to automatically browse and import your screenshots.
                </p>
              </div>
              <p className="text-xs text-[var(--gg-text-tertiary,#60707a)]">
                You can link in Settings &rarr; Xbox whenever you are ready.
              </p>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4 text-center">
              <div className="w-12 h-12 mx-auto rounded-2xl bg-purple-500/20 text-purple-400 flex items-center justify-center">
                <Sparkles size={24} />
              </div>
              <div className="space-y-1">
                <h2 className="text-xl font-light text-[var(--gg-text-primary)]">Keeper AI Companion</h2>
                <p className="text-xs text-[var(--gg-text-secondary,#8c9ba5)]">
                  Keeper indexes flight screenshots, tracks memories, and chats about your journal.
                </p>
              </div>
              <p className="text-xs text-[var(--gg-text-tertiary,#60707a)]">
                Bring your own key or local model in Settings &rarr; Keeper &amp; AI. Offline mode works out of the box.
              </p>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4 text-center">
              <div className="w-12 h-12 mx-auto rounded-2xl bg-blue-500/20 text-blue-400 flex items-center justify-center">
                <ShieldCheck size={24} />
              </div>
              <div className="space-y-1">
                <h2 className="text-xl font-light text-[var(--gg-text-primary)]">Permissions</h2>
                <p className="text-xs text-[var(--gg-text-secondary,#8c9ba5)]">
                  Green Guide stores your logs locally. Verify notifications and media permissions for the best experience.
                </p>
              </div>
              <div>
                <button
                  type="button"
                  onClick={async () => {
                    const rows = await checkAllPermissions();
                    setPermRows(rows);
                    setShowPermsModal(true);
                  }}
                  className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-[var(--gg-text-primary)] text-xs font-semibold inline-flex items-center gap-2"
                >
                  <ShieldCheck size={14} />
                  <span>Check device permissions</span>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-between pt-4 border-t border-[var(--gg-divider,#2d3439)]">
          <button
            type="button"
            onClick={prevStep}
            disabled={step === 0}
            className={`px-3 py-2 rounded-xl text-xs font-semibold flex items-center gap-1 ${
              step === 0 ? 'invisible' : 'text-[var(--gg-text-secondary,#8c9ba5)] hover:text-[var(--gg-text-primary)]'
            }`}
          >
            <ChevronLeft size={16} />
            <span>Back</span>
          </button>

          <button
            type="button"
            onClick={nextStep}
            className="px-5 py-2.5 rounded-xl bg-[var(--gg-accent,#107c10)] text-white text-xs font-semibold flex items-center gap-1.5 hover:brightness-110 shadow"
          >
            <span>{step === 4 ? 'Get started' : 'Continue'}</span>
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {showPermsModal && permRows && (
        <PermissionsSetupModal
          missing={permRows.filter((r) => r.state !== 'granted')}
          onDismiss={() => setShowPermsModal(false)}
          onComplete={() => setShowPermsModal(false)}
        />
      )}
    </div>
  );
}
