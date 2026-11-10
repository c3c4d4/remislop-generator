# Ideas backlog

Metric-saturated. Only pursue these if the harness itself is extended (which
means logging a new segment, since it moves the baseline):

- Add a gallery-with-errors fixture page (the `.error` banner is styled but
  never rendered in the fixtures).
- Add a 390×844 mobile fixture; the media queries are only checked by hand.
- Add hover/active fixture pages (inject a class trick won't work — would need
  synthetic `:hover` via CDP `Emulation.setEmulatedMedia`/`forcePseudoState`).
- Only then chase `accent_text`/`destructive` coverage and AA on accent.

Design ideas worth doing regardless of score:
- Empty state for the "Recent jobs" card when there are no jobs (markup-frozen:
  can style `.history` only, so nothing to do).
- Nicer status word colouring per job status would need markup/JS.
