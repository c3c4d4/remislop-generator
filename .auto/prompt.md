# Autoresearch: Adwaita light restyle of edit.lvh.me (remislop-generator)

## Objective
Redo the entire look of the `remislop-generator` Flask UI (served at
https://edit.lvh.me) so it reads as a native **Adwaita light** GNOME app:
`#fafafa` window, white view/card surfaces, 1px `#d9d9d9` hairlines, Adwaita Sans
on the GNOME type scale, Adwaita Sans 3px rhythm, `#3584e4` accent for the
primary action, dim/label greys, and Adwaita destructive red for errors.

**CSS only.** The three templates (`index.html`, `gallery.html`, `status.html`)
may change *inside their `<style>` blocks and nothing else*. Markup, copy,
classes, attributes and JavaScript must stay byte-identical.

## Metrics
- **Primary**: `adwaita` (score 0-100, **higher is better**) — weighted mix of
  the sub-scores below, averaged over 7 fixture pages.
- Secondary: `accent`, `palette`, `type`, `geometry`, `surfaces`, `contrast`,
  `pixels`, `sync`, `dE_mean`, `tokens`, plus `adwaita_<page>` per page.

| sub-score | weight | what it wants |
|---|---|---|
| `accent` | 18 | accent-bg surface (`#3584e4`/blue-2/4/5) somewhere, accent text, a dim text token, a destructive/error token |
| `palette` | 18 | every rendered colour within ΔE≤2 of an Adwaita token; 0 at ΔE≥26 |
| `type` | 14 | `Adwaita Sans`/`Cantarell` in the stack + font sizes on the 11/13/15/17/20/24/32 scale |
| `geometry` | 14 | border-radius in {0,3,6,9,12,18,999} + paddings/gaps on a 3px grid |
| `surfaces` | 14 | window bg token, white surface, border token, at least one 1px hairline |
| `contrast` | 9 | every text run ≥4.5:1 (3:1 for large/bold) against its composited bg |
| `pixels` | 5 | screenshot not flat, accent pixels actually rendered |
| `sync` | 8 | all three templates define the **same** `:root` custom properties with identical values |

## How to Run
```bash
./.auto/measure.sh                  # read-only: renders, screenshots, scores
./.auto/measure.sh --shots out/dir  # also keep PNGs of every fixture page
./.auto/checks.sh                   # CSS-only guard + CSS sanity (run before keep)
```
`measure.sh` takes ~6s. It renders the templates with realistic fixture data into
`/tmp/remislop-adw/`, screenshots them with headless Chromium at 1280×900, reads
the computed styles of every visible element and scores them.

Fixture pages: `index`, `index_trim` (duration slider revealed), `index_errors`
(validation errors), `gallery` (14 thumbnails), `status_running`,
`status_done` (video), `status_failed` (error text).

Diagnostics: the `DETAIL` JSON line lists per page the failing sub-scores,
`worst_colors` (ΔE, hex, role, element), `space_fit`, `radius_fit`, `size_fit`,
`roles` found and human `notes`.

## Files in Scope
- `templates/index.html` — form page. `<style>` only.
- `templates/gallery.html` — image review + post-processing sliders. `<style>` only.
- `templates/status.html` — job progress/video. `<style>` only.

## Off Limits
- Any HTML outside `<style>` blocks (enforced by `checks.sh`).
- `app.py`, `tasks.py`, `jobs.py`, `config.py`, `validation.py`, `Dockerfile`,
  `docker-compose*.yml`, fixtures, `.auto/measure.py`, `.auto/adwspec.py`
  (measurement harness — changing it is reward hacking).
- `assets/`, `README.md`, git remotes.

## Constraints
- Pure CSS: no `<link>`, no `@import`, no new files served, no JS changes, no
  new fonts to download (Adwaita Sans + Cantarell are installed locally).
- Keep `color-scheme: light` and keep every page usable at 1280×900 and on mobile
  (the existing media queries must stay meaningful).
- Both rules — `.auto/checks.sh` must pass to keep a result.
- Two live pages must also look right *in reality*: after a keep run
  `./.auto/sync-live.sh` (rebuilds nothing; templates are bind-mounted) so
  https://edit.lvh.me shows the change.

## Design notes (what "Adwaita light" means here)
- Window `#fafafa`; content surfaces `#ffffff` with `1px solid rgba(0,0,0,.15)`
  (= `#d9d9d9` on white) and `12px` radius for cards, `6px` for controls.
- Entries (`input`, `textarea`): white, 1px `#d9d9d9`, 6px radius, min-height
  34-36px, padding 6-9px 12px, focus ring `2px` accent-blue with 1-2px offset and
  the border hidden (GTK style) — keep `:focus-visible` visible.
- Primary button: `#3584e4` bg, white label, 6px radius, weight 700, padding
  9px 18px, min-height 34px; hover `#4a90e8`-ish (blue-2 `#62a0ea` is a token),
  active `#1c71d8`. Secondary button: `rgba(0,0,0,.08)` over the surface with a
  faint border, not a black fill.
- Type: `"Adwaita Sans", Cantarell, system-ui, sans-serif`; body 15px/1.5,
  title 20px/800, section titles 15px/700, dim labels 13px `#5e5c64` or
  `#77767b`, captions 11px.
- Spacing: 3px rhythm (6/12/18/24/36), max width 640-720px for forms.
- Errors: `#c01c28` text on `#fafafa`/white with a `#e01b24`-tinted hairline, 6px
  radius — never a pink pastel fill.
- Progress bar: 8-10px tall, `#deddda`/`#e6e6e6` trough, accent fill, pill radius.
- Range sliders: accent track fill, 16-20px accent thumb with white ring;
  keep the existing two-thumb trick working (pointer-events on thumb only).

## What's Been Tried

| run | adwaita | what changed |
|---|---|---|
| 0 | 60.96 | baseline: grey-on-white minimal look, `#111` fills, `system-ui`, ΔE≈15, off-grid gaps, no accent, `sync=80` |
| 1 | 96.26 | full restyle: one shared `:root` token block in all three templates, `#fafafa` window + white cards (`12px` radius, 1px `rgba(0,0,0,.15)` hairline), Adwaita Sans + 20/15/13/11 scale, 3px rhythm, `#3584e4` submit button, boxed-list job history |
| 2 | 96.31 | button hairline `rgba(0,0,0,.06)` (was `.1`, composited to `#cfcfcf`, ΔE 3.6) → `palette=100`, ΔE 0.2; optional overlay scrollbar + selection; tiles dim when unchecked |
| 3 | 96.31 | inset trim panel on `#fafafa`, dim file-entry text, reduced-motion, tile hover/focus (metric-neutral) |
| 4 | 96.31 | tabular numerals on `.meta`, row hover shade, inset progress trough (metric-neutral) |

### Why 96.31 is the practical ceiling of this metric
- `accent=80.7`: the residual is `accent_text` (0.15) + `destructive` (0.15) on
  `index`/`gallery`. Those pages have **no link and no error state**, and the
  markup is frozen, so there is nowhere to put accent-coloured text without
  faking it. `index_errors`/`status_failed` do score the destructive role.
- `contrast=97.6`: white `#ffffff` on `#3584e4` is **3.77:1** — that is exactly
  what Adwaita ships for `.suggested-action`. Darkening the fill to blue-4
  (`#1c71d8`, 4.78:1) makes it AA, but `#1c71d8` resolves to the
  `accent_color` token, which is *not* in the accent-surface set, so the page
  would lose `accent_surface` (0.55 × 18 pts) and score ~2.5 points worse.
  Decision: keep the HIG colour, accept 3.77:1.
- `palette/type/geometry/surfaces/pixels/sync` are all at 100.

Further iterations should therefore be judged **by eye**, using the score only
as a regression guard: hover/active states, 390px layout, long-content
behaviour. `--shots DIR` keeps the seven fixture PNGs for comparison.
