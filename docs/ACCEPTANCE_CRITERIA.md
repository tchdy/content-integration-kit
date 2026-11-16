# Acceptance criteria

The (fictional) customer brief: *"Editors should sign in with our corporate SSO. Our legacy CMS
archive has to move into the new structured format. Our publishing system will notify you when
an article is published, and we need a syndication feed for a partner."*

Each criterion below maps to automated tests (`tests/…`), so "done" is checked, not claimed.

## SSO (SAML 2.0)
| # | Given / When / Then | Test |
|---|---|---|
| S1 | Given an unauthenticated user, when they open `/me`, then they are sent to the IdP to sign in | `test_login_redirects_to_idp_with_authn_request` |
| S2 | Given a valid signed response for our AuthnRequest, when it is posted to the ACS, then the user is signed in with their email and attributes (e.g. groups) | `test_full_sp_initiated_login` |
| S3 | Responses meant for another app (wrong Audience) or another URL (wrong Destination) are rejected | `test_bad_responses_are_rejected` |
| S4 | Expired, unsigned, tampered, or wrongly-signed responses are rejected | `test_bad_responses_are_rejected`, `test_tampered_assertion_is_rejected`, `test_response_signed_by_unknown_key_is_rejected` |
| S5 | RelayState cannot redirect users to another site | `test_open_redirect_in_relay_state_is_blocked` |
| S6 | SP metadata is available for the IdP admin even before the IdP is configured | `test_sp_metadata_works_even_if_idp_is_unreachable` |

## Structured content (XML / XSLT)
| # | Given / When / Then | Test |
|---|---|---|
| X1 | Every stored article validates against `schemas/article.xsd`; invalid XML gets **all** errors back, not just the first | `test_invalid_article_reports_every_error` |
| X2 | XML with external entities (XXE) does not read local files | `test_xxe_entities_are_not_expanded` |
| X3 | Articles render to HTML with an "A, B and C" author list | `test_html_transform_renders_title_and_author_list` |
| X4 | Published articles become RSS items with absolute links; drafts are never syndicated | `test_feed_transform_builds_rss_item`, `test_feed_transform_skips_drafts` |

## Migration
| # | Given / When / Then | Test |
|---|---|---|
| M1 | Legacy codes, dates, author lists and keywords map to the new model | `test_legacy_transform_maps_fields` |
| M2 | A bad record is reported with its legacy id and reason, and doesn't stop the batch | `test_first_run_creates_and_reports_failures` |
| M3 | Re-running is safe: unchanged rows are skipped, changed rows updated | `test_second_run_is_idempotent`, `test_changed_source_record_is_updated` |
| M4 | Dry run writes nothing | `test_dry_run_writes_nothing` |
| M5 | Counts reconcile (source = created + updated + unchanged + failed); the exit code is non-zero on failures | `test_cli_writes_report_and_exits_nonzero_on_failures` |

## Webhooks
| # | Given / When / Then | Test |
|---|---|---|
| W1 | A correctly signed `content.published` event stores the article | `test_valid_webhook_is_processed_and_article_stored` |
| W2 | Wrong secret, tampered body, or a timestamp older than 5 minutes → 401 | `test_wrong_secret_rejected`, `test_tampered_body_rejected`, `test_old_timestamp_rejected_as_replay` |
| W3 | Re-delivery of the same event id → 200 "duplicate", processed once | `test_duplicate_delivery_is_acknowledged_not_reprocessed` |
| W4 | An invalid article → 422 and **not** recorded, so the sender can fix it and resend with the same id | `test_invalid_article_rejected_and_can_be_resent_with_same_id` |
| W5 | Outbound: retries 5xx/429/timeouts with backoff and the same event id; does not retry other 4xx | `test_outbound_*` |
