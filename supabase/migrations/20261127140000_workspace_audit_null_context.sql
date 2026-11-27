-- Workspace-less account data has no workspace audit stream.
-- Its cleanup must not attempt to write a row that requires a workspace id.
CREATE OR REPLACE FUNCTION public.cadivor_write_audit_event(
    target_workspace_id uuid,
    target_actor_user_id uuid,
    target_action_type text,
    target_object_type text,
    target_object_id text,
    target_object_label text,
    target_summary text,
    target_metadata jsonb DEFAULT '{}'::jsonb
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    actor_display_name text := '';
    actor_email_value text := '';
BEGIN
    -- Private records without workspace context are not workspace audit events.
    -- workspace_audit_log.workspace_id is NOT NULL, so do not manufacture an
    -- invalid shared-workspace record while removing those private rows.
    IF target_workspace_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.workspaces w WHERE w.id = target_workspace_id
    ) THEN
        RETURN;
    END IF;

    SELECT
        COALESCE(wm.display_name, ''),
        COALESCE(wm.email, '')
    INTO actor_display_name, actor_email_value
    FROM public.workspace_members wm
    WHERE wm.workspace_id = target_workspace_id
      AND wm.user_id = target_actor_user_id
    ORDER BY wm.joined_at NULLS LAST
    LIMIT 1;

    -- SELECT INTO assigns NULL when there is no matching membership.
    actor_display_name := COALESCE(actor_display_name, '');
    actor_email_value := COALESCE(actor_email_value, '');

    INSERT INTO public.workspace_audit_log (
        workspace_id,
        actor_user_id,
        actor_name,
        actor_email,
        action_type,
        object_type,
        object_id,
        object_label,
        summary,
        metadata,
        search_text
    )
    VALUES (
        target_workspace_id,
        target_actor_user_id,
        actor_display_name,
        actor_email_value,
        COALESCE(target_action_type, ''),
        COALESCE(target_object_type, ''),
        COALESCE(target_object_id, ''),
        COALESCE(target_object_label, ''),
        COALESCE(target_summary, ''),
        COALESCE(target_metadata, '{}'::jsonb),
        CONCAT_WS(
            ' ',
            target_action_type,
            target_object_type,
            target_object_id,
            target_object_label,
            target_summary,
            actor_display_name,
            actor_email_value
        )
    );
END
$function$;
