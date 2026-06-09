# Stage: odysseus-confirmation-preview-surface-v1

Polish the human-readable `pending_confirmation` preview surface for guarded
actions. This stage changes preview shape/wording only; guard classification,
confirmation requirements, execution paths, and legacy compatibility fields are
preserved.

## What changed

`src.external_action_guard.normalize_confirmation_preview()` now standardises
operator-facing fields across shared guard previews and existing bespoke preview
emitters:

- `confirmation_required`
- `action_category`
- `risk_level`
- `tool_name`
- `action_name`
- `target`
- `target_url` / `target_domain` where available
- `target_resource` where available
- `summary`
- `arguments_preview`
- `consequences`
- `approval_instruction`
- `high_impact`
- `high_impact_reason` for high-impact actions
- `final_review_checklist` for high-impact actions

The helper is used by:

- API/app/MCP previews via `build_preview`
- email send previews
- `manage_skills` mutation previews
- HTTP skill mutation previews

## Compatibility

Legacy fields remain intact, including `pending_confirmation`, `tool`,
`action_type`, `method`, `target`, `risk`, `instruction`, `integration`,
`body_preview`, `final_checklist`, and bespoke email/skill fields such as
`from`, `account`, `to`, `subject`, `action`, `name`, `skill_id`, `url`, and
`warning`.

## Validation

Run the required guard suites plus focused preview-surface tests.
