# User Feedback

**Turn Date**: 2026-10-18  
**Branch**: `fix/admin-portal-styling-and-prompt-editor`  

## User Feedback Received:
> couple style issues in admin portal:
> 1) there is one panel that I would like to actually change with the dark-mode 
> 2) the editor for prompts is like barely a sliver (atleast in the half-screen mode I have it in in this photo.

## Visual Evidence / Attachments:
1. **Photo 1**: The "Quick Diagnostics" panel in the General Admin tab (`#tab-general`) currently retains a bright white/light-blue gradient background (`bg-gradient-to-br from-indigo-50 to-blue-50`) in dark mode, rendering light-gray status text on an eye-searing white container.
2. **Photo 2**: In the Prompts tab (`#tab-prompts`), when viewed in responsive / half-screen mode or Editor-only mode, the Monaco prompt editor container collapses vertically to a narrow ~15-20px horizontal sliver because `min-h-[520px]` and `h-[500px]` are arbitrary Tailwind JIT utility classes not recognized by the precompiled Tailwind 2.2.19 CDN, causing the unconstrained flex container to collapse.

## Requirements:
- Ensure the Quick Diagnostics card adheres to the high-contrast dark theme system, utilizing dark card tokens (`#111827`, border `#1e293b`).
- Ensure the Monaco Prompt Studio editor and markdown preview container have explicit CSS min-height (`min-height: 480px; height: 500px;`) and an explicit `window.resize` layout listener so Monaco maintains full height and responsiveness across full-screen, half-screen, and mobile views.
