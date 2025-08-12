# ARS Canvas v3

[日本語READMEはこちら](README_ja.md) — Streamlined for Usability & Visibility

A refined Streamlit-based audience response system with **6-digit numeric rooms**, **projector-first design**,
and **super-simple controls**. Built for bright rooms, big screens, and large crowds.

## What’s new in v3
- Clean typographic scale and roomy layout (**Comfy / Cozy / Compact** densities)
- Bigger, accessible buttons and cards (minimum hit target >= 40px)
- **Sticky header** for room + filters, less scrolling
- **Grid view** for participants (2–3 columns) or traditional list view
- **Hide/restore comments** (moderation) — hidden items don’t show on Projector/Participant
- **Auto-advance** option on Projector to rotate focused comments
- **Improved QR**: enter a base URL to generate absolute links (good for Streamlit Cloud)
- High-contrast theme with careful color choices; adjustable font scale
- Minor quality-of-life: “New” highlight since last refresh, quick sort chips

## Quick Start
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy
Push this folder to GitHub, then deploy on Streamlit Community Cloud.


> メモ: `data/` は自動作成されます。GitHubに空ディレクトリを保持したい場合は `data/.gitkeep` を置いてください。
