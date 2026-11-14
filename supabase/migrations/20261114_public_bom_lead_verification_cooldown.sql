-- Durable verification-email claim for the anonymous public BOM audit.
-- verification_sent_at is set before OTP send so repeat POSTs are idempotent.
alter table public.cadivor_public_bom_leads
    add column if not exists verification_sent_at timestamptz;

comment on column public.cadivor_public_bom_leads.verification_sent_at is
    'Set when a verification email send slot is claimed; used for resend cooldown.';
