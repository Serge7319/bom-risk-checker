# BOM progress position stability

## Checkout
- Worktree: `bom-risk-checker-prod-followup`
- Branch: `fix/bom-progress-position-stability`
- Base production commit (PR #564): `2abefca8f6513468d93d46d1b074fac52d117cde`

## Cause
1. Analyze click armed the pipeline then remounted **Preparing** under leftover upload/catalog chrome (cardTop ~700px).
2. When the worker future appeared, progress remounted on the early top path (~38–180px) — the mid→top jump.
3. Completing the future while clearing the fragment emptied the card before the report remount, producing a late 4/5 jump and a Preparing regression when pipeline flags outlived the future.

## Fix
- One early top surface (`bom8_analysis_progress_card`) before catalog CSS.
- Bootstrap the worker **before** painting so the first analysis paint is already top progress (no Preparing remount under the form).
- Always `stop_authenticated_page()` on that surface so catalog/form cannot remount.
- Finish pipeline flags with the result mount; hold the progress card while saving; never regress to Preparing after component progress.

## Before (prod `2abefca` capture)
- Labeled keys: ['progress_0', 'progress_mid', 'progress_4', 'complete']
- cardTop stability: {'min': 52, 'max': 52, 'range': 0}
- preparing_after_progress: False
- Note: this baseline often skipped the brief Preparing flash; Oct 31 recording showed Preparing mid-page then jump.

## After (this branch)
- Labeled keys: ['progress_0', 'progress_mid', 'progress_4', 'complete']
- cardTop stability (labeled 0/mid/4): {'min': 180, 'max': 180, 'range': 0, 'tops': [180, 180, 180]}
- preparing_after_progress: False
- upload_form_hidden_during_progress: True
- pass_stability_8px: True

## Phase log (after)
- `analyze_click_consumed ts=1793484308.304`
- `worker_start parts=5 elapsed_ms=102 via=bootstrap_before_paint`
- `progress_top_path`
- `synthetic_supplier_start mpn=NE555P`
- `synthetic_supplier_start mpn=RC0603FR-0710KL`
- `synthetic_supplier_start mpn=C0805C104K5RACTU`
- `synthetic_supplier_start mpn=1N4148`
- `synthetic_supplier_start mpn=LM358DR`
- `synthetic_supplier_done mpn=NE555P sleep_ms=1607`
- `first_progress_ui elapsed_ms=2397 step=Checking the remaining components`
- `synthetic_supplier_done mpn=RC0603FR-0710KL sleep_ms=3211`
- `synthetic_supplier_done mpn=C0805C104K5RACTU sleep_ms=4815`
- `synthetic_supplier_done mpn=1N4148 sleep_ms=6417`
- `synthetic_supplier_done mpn=LM358DR sleep_ms=8021`

## Screenshots
- `.evidence/progress_stability/after/02_progress_0*.png`
- `.evidence/progress_stability/after/03_progress_mid*.png`
- `.evidence/progress_stability/after/04_progress_4*.png`
- `.evidence/progress_stability/after/06_complete*.png`
