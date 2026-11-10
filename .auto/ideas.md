# Ideas backlog

- Shared design tokens: keep one canonical `:root` block copied verbatim into all
  three templates (worth 8 pts of `sync`, and stops drift).
- Adwaita "boxed list" idiom for index job history: white card, 1px hairline,
  12px radius, 6px vertical padding rows, dim meta text.
- Gallery tiles: 6px radius, 1px `rgba(0,0,0,.15)` border, white 2px inner ring on
  the selected state (checkbox -> `label:has(input:checked)`), accent focus.
- Checkboxes/sliders: `accent-color: #3584e4` gets Adwaita accent for free.
- Progress bar: `#deddda` trough + accent fill + pill radius; steps dots in
  accent / `#c0bfbc` for waiting.
- Error surfaces: `#c01c28` text, no pastel fill.
- Adwaita focus ring: `outline: 2px solid #3584e4; outline-offset: 2px;` on
  `:focus-visible` for buttons/links, entries use a blue border + 1px inner ring.
- Typography: 15px body, 20px/800 `h1`, 13px `#5e5c64` meta, 11px captions.
- Mobile: keep the existing media queries, 720/480 breakpoints, but on-grid.
