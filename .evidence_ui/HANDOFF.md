# Cadivor UI Approval Mockup — handoff

## Repo / worktree
- Worktree: `/Users/sergekashambala/Documents/Businesses/bom-risk-checker-ui-approval`
- Branch: `ui/approval-mockup-shell` (from `origin/main` @ `04a6efa`)
- Remote: `https://github.com/Serge7319/bom-risk-checker.git`
- Dirty checkouts preserved (no stash/reset/clean):
  - `bom-risk-checker-rc-integration` (detached HEAD)
  - `bom-risk-checker-prod-followup` (`migrate/nextjs-shell-bom-flow`, only `railway.toml.streamlit.bak` untracked)

## Not done (by request)
- No commit, push, PR, merge, or deployment

## Files changed
### Modified
- `apps/web/src/app/globals.css` — mockup tokens (navy/blue/white), 1440 content width, shell/page polish
- `apps/web/src/app/layout.tsx` — Inter font
- `apps/web/src/app/page.tsx` — ranked evidence-linked priority queue
- `apps/web/src/app/bom-analyzer/page.tsx` — sticky progress near top
- `apps/web/src/app/procurement/page.tsx` — sourcing controls + Next steps below table
- `apps/web/src/components/Shell.tsx` — mockup chrome (icons, create CTA, search, user chip)
- `apps/web/src/components/PageHeader.tsx` — head icon + empty stub styling
- `apps/web/src/lib/routes.ts` — page icons; Settings under Workspace admin

### Added
- `apps/web/src/components/Icons.tsx`
- `apps/web/src/components/EmptyState.tsx`
- `apps/web/.design-reference/Cadivor_UI_Approval_Mockup.html` (reference only)
- `.evidence_ui/*` verification artifacts

## Verification
- `apps/web` `tsc --noEmit`: pass
- `apps/web` `next lint`: pass (font warning only)
- `apps/web` `next build`: pass (22 routes)
- pytest Next suite: 18 passed
  - `tests/test_nextjs_migration_api.py`
  - `tests/test_nextjs_migration_tools.py`
  - `tests/test_nextjs_api_origin_contract.py`
  - `tests/test_nextjs_roadmap_gates.py`

## Screenshots
Under `.evidence_ui/screenshots/` at 1680×1050 and 696×1188:
- Home, BOM Analyzer, Procurement Advisor, empty/loading/error harness
- Live Next `/login`

## Unsupported / honest gaps
- Ask Cadivor exists in Streamlit analysis detail; not implemented as a Next shell panel (not invented/faked)
- Live supplier integrations, billing checkout, automated alert email remain disconnected (banner retained)
- Find a Replacement remains a CapabilityStub in Next
- Screenshots for authenticated workspace pages used a CSS harness with empty/honest states because Next client blocks localhost API bases; login screenshots are from the built Next app
