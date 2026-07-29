# AdsPower Sync Model

## Identity

`ads_profile_id` (`user_id` in AdsPower Local API) is the only field used to open a browser profile.
Email/profile name is not treated as a stable identity because it can be renamed or duplicated.

## Link Statuses

- `linked`: the local account is actively connected to an AdsPower profile and appears in the ADS list.
- `unlinked`: the local account is not active in AdsPower. If `ads_manual_unlink` is true, sync must not relink it automatically.
- `orphaned`: the local account has an AdsPower profile id, but the profile was not returned by AdsPower sync.
- `conflict`: AdsPower returned a profile, but it could not be safely linked or renamed.

Historical link events are written to `account_ads_link_history` so old profile ids are retained without being treated as active.

## Sync Rules

1. Fetch AdsPower profiles from `/api/v1/user/list` using `page_size`.
2. Match existing local accounts by `ads_profile_id` first.
3. If a remote profile has the same email/name as exactly one local unlinked/orphaned account and that account was not manually unlinked, auto-link it.
4. If a linked local profile disappears from AdsPower, mark it `orphaned` automatically.
5. If a user manually unlinks a profile, sync may report the match but must not relink automatically.
6. If linking or renaming is ambiguous, mark the local account `conflict` and show it in the ADS problem section.

## Opening Profiles

Opening always uses the currently selected account's active `ads_profile_id`.
Accounts can be opened only when `ads_link_status == "linked"`.
