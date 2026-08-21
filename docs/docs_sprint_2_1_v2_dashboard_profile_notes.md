# Cadivor Sprint 2.1 v2 — Dashboard + Profile Foundation

## Objective
Upgrade the authenticated dashboard toward Cadivor Design System v2 and add a profile foundation for displaying user identity in the top workspace header.

## Files updated
- `streamlit_app.py`
- `src/ui/framework.py`

## Main improvements
- Expanded the authenticated app content width to reduce wasted space.
- Rebuilt the app topbar to span the product area more cleanly.
- Topbar now displays user-facing identity instead of only email:
  - full name when available
  - company/workspace name when available
  - plan fallback when company is unavailable
  - profile image URL when available
  - initials fallback
- Dashboard greeting now uses the user's first name when available.
- Added `Settings` navigation item.
- Added a `Settings > Profile & workspace` page where users can update:
  - full name
  - company / organization
  - role / title
  - profile image URL

## Important database note
The profile form saves only to columns that already exist in your Supabase `users` table. To make all profile fields persistent, add these optional columns:

```sql
alter table public.users
add column if not exists full_name text,
add column if not exists company_name text,
add column if not exists role_title text,
add column if not exists profile_image_url text;
```

This prevents the app from breaking if your current table does not have those columns yet.

## Test checklist
1. Login successfully.
2. Confirm Dashboard loads.
3. Confirm dashboard content uses more horizontal space.
4. Confirm topbar shows name/company if available, or safe fallback values.
5. Open Settings.
6. Update profile fields.
7. If DB columns exist, confirm values save after refresh.
8. Confirm New Analysis and Alternatives buttons still route correctly.
9. Confirm Open Saved BOM still opens the BOM Analyzer.

## Known notes
- Profile image is URL-based for now. File upload for avatars can be added later.
- Company/team settings will be expanded in Sprint 2.7.
