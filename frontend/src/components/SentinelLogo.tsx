export function SentinelLogo({ compact = false }: { compact?: boolean }) {
  return <span className="inline-flex items-center gap-3">
    <span className="sentinel-logo" aria-hidden="true">
      <svg viewBox="0 0 42 42" role="img"><path d="M30.8 9.5H17.6c-4.7 0-8.4 3.1-8.4 7 0 3.8 3.4 6.3 8.3 6.3h7c4.9 0 8.3 2.5 8.3 6.3 0 3.9-3.7 7-8.4 7H11.2"/><circle cx="31.5" cy="9.5" r="3"/><circle cx="10.5" cy="36" r="3"/></svg>
    </span>
    {!compact && <span className="brand-copy"><strong>Sentinel</strong><small>Payment risk guard</small></span>}
  </span>;
}
