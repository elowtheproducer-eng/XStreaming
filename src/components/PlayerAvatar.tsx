import React, { useEffect, useState } from 'react';
import { ProceduralAvatar } from './Glyphs';

/** Gamerpic from Xbox when available; falls back to the generated avatar if it is missing or fails to load. */
export function PlayerAvatar({
  url,
  tag,
  size = 38,
  className = '',
}: {
  url?: string;
  tag: string;
  size?: number;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);

  if (!url || failed) return <ProceduralAvatar tag={tag} size={size} />;
  return (
    <img
      src={url}
      alt=""
      width={size}
      height={size}
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      style={{ width: size, height: size }}
      className={`rounded-full object-cover bg-black/30 ring-1 ring-white/10 shrink-0 ${className}`}
    />
  );
}
