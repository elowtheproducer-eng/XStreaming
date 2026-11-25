import React from 'react';
import { X, Gamepad2, Keyboard } from 'lucide-react';

interface Props {
  onClose: () => void;
  nintendoAbSwap?: boolean;
}

export function KeyboardCheatsheetModal({ onClose, nintendoAbSwap }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-xl p-5 rounded-2xl bg-[var(--gg-bg-raised,#1b2024)] border border-[var(--gg-divider,#2d3439)] shadow-2xl space-y-4">
        <div className="flex items-center justify-between pb-2 border-b border-[var(--gg-divider,#2d3439)]">
          <div className="flex items-center gap-2">
            <Gamepad2 className="text-[var(--gg-accent,#107c10)]" size={20} />
            <h2 className="text-base font-semibold text-[var(--gg-text-primary,#fff)]">
              Controls &amp; Shortcuts
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close cheatsheet"
            className="p-1.5 rounded-lg text-[var(--gg-text-secondary,#8c9ba5)] hover:text-[var(--gg-text-primary)] hover:bg-white/10"
          >
            <X size={16} />
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div className="space-y-2.5 p-3 rounded-xl bg-black/25 border border-[var(--gg-divider,#2d3439)]">
            <div className="flex items-center gap-1.5 font-semibold text-[var(--gg-text-primary,#fff)] pb-1 border-b border-white/5">
              <Gamepad2 size={14} className="text-[var(--gg-accent,#107c10)]" />
              <span>Controller ({nintendoAbSwap ? 'Nintendo A/B' : 'Standard Xbox'})</span>
            </div>
            <div className="space-y-1.5 text-[var(--gg-text-secondary,#8c9ba5)]">
              <div className="flex justify-between">
                <span>D-pad / Left Stick</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Navigate focus</span>
              </div>
              <div className="flex justify-between">
                <span>{nintendoAbSwap ? 'B Button' : 'A Button'}</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Select / Confirm</span>
              </div>
              <div className="flex justify-between">
                <span>{nintendoAbSwap ? 'A Button' : 'B Button'}</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Back / Close</span>
              </div>
              <div className="flex justify-between">
                <span>X Button</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Action / Status</span>
              </div>
              <div className="flex justify-between">
                <span>Y Button</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Global Search</span>
              </div>
              <div className="flex justify-between">
                <span>LB / RB Bumpers</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Jump Rails</span>
              </div>
              <div className="flex justify-between">
                <span>Xbox / Home Button</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Guide Overlay</span>
              </div>
            </div>
          </div>

          <div className="space-y-2.5 p-3 rounded-xl bg-black/25 border border-[var(--gg-divider,#2d3439)]">
            <div className="flex items-center gap-1.5 font-semibold text-[var(--gg-text-primary,#fff)] pb-1 border-b border-white/5">
              <Keyboard size={14} className="text-[var(--gg-accent,#107c10)]" />
              <span>Keyboard Shortcuts</span>
            </div>
            <div className="space-y-1.5 text-[var(--gg-text-secondary,#8c9ba5)]">
              <div className="flex justify-between">
                <span>Arrow Keys</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Focus grid &amp; rails</span>
              </div>
              <div className="flex justify-between">
                <span>Enter / Space</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Open focused tile</span>
              </div>
              <div className="flex justify-between">
                <span>Escape / Backspace</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Back / Dismiss</span>
              </div>
              <div className="flex justify-between">
                <span>/ or Ctrl + K</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Global Search</span>
              </div>
              <div className="flex justify-between">
                <span>G</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Open Guide overlay</span>
              </div>
              <div className="flex justify-between">
                <span>S</span>
                <span className="font-mono text-[var(--gg-text-primary)]">Open Settings</span>
              </div>
            </div>
          </div>
        </div>

        <div className="pt-1 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-[var(--gg-accent,#107c10)] text-[var(--gg-text-primary)] text-xs font-semibold"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}
