-- Preserve the unapproved replacement leads returned during each BOM analysis.
-- Candidate evidence is a search snapshot and does not change approval state.
alter table public.analysis_parts
    add column if not exists alternate_candidates jsonb not null default '[]'::jsonb;

comment on column public.analysis_parts.alternate_candidates is
    'Bounded candidate evidence snapshot from BOM analysis, including relationship label and source/datasheet URLs; candidates are not approvals or drop-in certifications.';
