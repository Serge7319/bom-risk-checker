-- Add prepaid Ask Cadivor question credits alongside the existing usage packs.
-- Purchased credits are held per verified user, never reset monthly, and may be
-- consumed only through signed server-side billing actions.

ALTER TABLE public.cadivor_usage_credit_balances
  DROP CONSTRAINT IF EXISTS cadivor_usage_credit_balances_credit_kind_check;
ALTER TABLE public.cadivor_usage_credit_balances
  ADD CONSTRAINT cadivor_usage_credit_balances_credit_kind_check
  CHECK (credit_kind IN ('bom_analysis', 'monitored_part', 'ask_cadivor'));

ALTER TABLE public.cadivor_usage_credit_grants
  DROP CONSTRAINT IF EXISTS cadivor_usage_credit_grants_credit_kind_check;
ALTER TABLE public.cadivor_usage_credit_grants
  ADD CONSTRAINT cadivor_usage_credit_grants_credit_kind_check
  CHECK (credit_kind IN ('bom_analysis', 'monitored_part', 'ask_cadivor'));

CREATE TABLE IF NOT EXISTS public.cadivor_ai_question_credit_reservations (
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  reservation_id text NOT NULL,
  status text NOT NULL CHECK (status IN ('reserved', 'committed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, reservation_id)
);

ALTER TABLE public.cadivor_ai_question_credit_reservations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.cadivor_ai_question_credit_reservations FROM public, anon, authenticated;
GRANT ALL ON public.cadivor_ai_question_credit_reservations TO service_role;

CREATE OR REPLACE FUNCTION public.cadivor_grant_usage_credits(
  p_checkout_session_id text,
  p_user_id uuid,
  p_payment_intent_id text,
  p_price_id text,
  p_credit_kind text,
  p_credits bigint
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  inserted_id text;
BEGIN
  IF p_credit_kind NOT IN ('bom_analysis', 'monitored_part', 'ask_cadivor')
     OR p_credits <= 0
     OR length(coalesce(p_checkout_session_id, '')) = 0
     OR length(coalesce(p_payment_intent_id, '')) = 0
     OR length(coalesce(p_price_id, '')) = 0 THEN
    RAISE EXCEPTION 'invalid usage credit grant';
  END IF;

  INSERT INTO public.cadivor_usage_credit_grants
    (checkout_session_id, user_id, payment_intent_id, price_id, credit_kind, credits)
  VALUES
    (p_checkout_session_id, p_user_id, p_payment_intent_id, p_price_id, p_credit_kind, p_credits)
  ON CONFLICT DO NOTHING
  RETURNING checkout_session_id INTO inserted_id;

  IF inserted_id IS NULL THEN
    RETURN 'duplicate';
  END IF;

  INSERT INTO public.cadivor_usage_credit_balances (user_id, credit_kind, credits)
  VALUES (p_user_id, p_credit_kind, p_credits)
  ON CONFLICT (user_id, credit_kind) DO UPDATE
    SET credits = public.cadivor_usage_credit_balances.credits + excluded.credits,
        updated_at = now();
  RETURN 'applied';
END;
$$;

CREATE OR REPLACE FUNCTION public.cadivor_reserve_ai_question_credit(
  p_user_id uuid,
  p_reservation_id text
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  inserted_id text;
  existing_status text;
BEGIN
  IF length(coalesce(p_reservation_id, '')) = 0 OR length(p_reservation_id) > 100 THEN
    RAISE EXCEPTION 'invalid Ask Cadivor credit reservation';
  END IF;

  SELECT status INTO existing_status
    FROM public.cadivor_ai_question_credit_reservations
   WHERE user_id = p_user_id AND reservation_id = p_reservation_id;
  IF existing_status IN ('reserved', 'committed') THEN
    RETURN true;
  END IF;

  INSERT INTO public.cadivor_ai_question_credit_reservations
    (user_id, reservation_id, status)
  VALUES (p_user_id, p_reservation_id, 'reserved')
  ON CONFLICT DO NOTHING
  RETURNING reservation_id INTO inserted_id;
  IF inserted_id IS NULL THEN
    RETURN false;
  END IF;

  UPDATE public.cadivor_usage_credit_balances
     SET credits = credits - 1, updated_at = now()
   WHERE user_id = p_user_id AND credit_kind = 'ask_cadivor' AND credits > 0;
  IF NOT FOUND THEN
    DELETE FROM public.cadivor_ai_question_credit_reservations
     WHERE user_id = p_user_id AND reservation_id = p_reservation_id AND status = 'reserved';
    RETURN false;
  END IF;
  RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.cadivor_finish_ai_question_credit(
  p_user_id uuid,
  p_reservation_id text,
  p_commit boolean
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  current_status text;
  did_finish boolean := false;
BEGIN
  IF length(coalesce(p_reservation_id, '')) = 0 OR length(p_reservation_id) > 100 THEN
    RAISE EXCEPTION 'invalid Ask Cadivor credit reservation';
  END IF;

  SELECT status INTO current_status
    FROM public.cadivor_ai_question_credit_reservations
   WHERE user_id = p_user_id AND reservation_id = p_reservation_id;

  IF p_commit THEN
    IF current_status = 'committed' THEN
      RETURN true;
    END IF;
    UPDATE public.cadivor_ai_question_credit_reservations
       SET status = 'committed'
     WHERE user_id = p_user_id AND reservation_id = p_reservation_id AND status = 'reserved';
    RETURN FOUND;
  END IF;

  DELETE FROM public.cadivor_ai_question_credit_reservations
   WHERE user_id = p_user_id AND reservation_id = p_reservation_id AND status = 'reserved';
  did_finish := FOUND;
  IF did_finish THEN
    INSERT INTO public.cadivor_usage_credit_balances (user_id, credit_kind, credits)
    VALUES (p_user_id, 'ask_cadivor', 1)
    ON CONFLICT (user_id, credit_kind) DO UPDATE
      SET credits = public.cadivor_usage_credit_balances.credits + 1,
          updated_at = now();
  END IF;
  RETURN did_finish;
END;
$$;

REVOKE ALL ON FUNCTION public.cadivor_grant_usage_credits(text, uuid, text, text, text, bigint)
  FROM public, anon, authenticated;
REVOKE ALL ON FUNCTION public.cadivor_reserve_ai_question_credit(uuid, text)
  FROM public, anon, authenticated;
REVOKE ALL ON FUNCTION public.cadivor_finish_ai_question_credit(uuid, text, boolean)
  FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cadivor_grant_usage_credits(text, uuid, text, text, text, bigint)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.cadivor_reserve_ai_question_credit(uuid, text)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.cadivor_finish_ai_question_credit(uuid, text, boolean)
  TO service_role;
