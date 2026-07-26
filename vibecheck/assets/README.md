# Custom art

Drop image files here and the app picks them up automatically — no code change
needed. If a file is missing, the app falls back to its built-in look, so the
app always works with an empty folder.

## Grade icons (the rating popup)

Put five images in `grades/`, named by score:

| File | Grade |
|------|-------|
| `grades/1.png` | Absolute Skibidi |
| `grades/2.png` | Who Let Them Cook? |
| `grades/3.png` | Meh |
| `grades/4.png` | Let Him Cook! |
| `grades/5.png` | Maximum Rizz |

- **Format:** `.png` preferred (`.webp` / `.jpg` also accepted)
- **Size:** square, at least 128×128 — they're scaled down, so bigger is fine
- **Background:** transparent PNG looks best on the dark popup
- Fallback when absent: the colour emoji 🚽 🤨 🧍 👨‍🍳 👑

## Logo

- `logo.png` — square, ≥256×256, transparent. Used for the tray icon and the
  app window. Fallback when absent: the built-in gold smiley coin.
- `logo.ico` — Windows icon for the packaged .exe (can be generated from
  `logo.png` at build time).

## Licensing note

Anything in this folder ships inside the released app. Only put art here that
you own or are licensed to redistribute. Popular meme images (Shocked Pikachu,
Side-Eye Chloe, Blinking White Guy, Chad, etc.) are copyrighted and are **not**
safe to bundle in a public release — use original or licensed art there, and
keep meme builds private.
