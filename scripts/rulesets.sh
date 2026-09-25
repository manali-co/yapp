#!/usr/bin/env bash
# Creates branch rulesets on manali-co/yapp. Idempotent: deletes same-named rulesets first.
# Everyone goes through a PR with green CI and resolved threads; repository admins can bypass
# ("Bypass rules and merge") when they decide to, and the bypass is recorded in the audit log.
set -euo pipefail
REPO="manali-co/yapp"
for name in protect-dev protect-main; do
  for id in $(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name==\"$name\") | .id"); do
    gh api -X DELETE "repos/$REPO/rulesets/$id"
  done
done
common_rules='[
  {"type":"deletion"},
  {"type":"non_fast_forward"},
  {"type":"pull_request","parameters":{"required_approving_review_count":0,
     "dismiss_stale_reviews_on_push":true,"require_code_owner_review":false,
     "require_last_push_approval":false,"required_review_thread_resolution":true}},
  {"type":"required_status_checks","parameters":{"strict_required_status_checks_policy":true,
     "required_status_checks":[{"context":"ci"}]}}
]'
main_rules=$(echo "$common_rules" | python3 -c 'import json,sys; r=json.load(sys.stdin); r.append({"type":"required_linear_history"}); print(json.dumps(r))')
gh api -X POST "repos/$REPO/rulesets" --input - <<JSON
{"name":"protect-dev","target":"branch","enforcement":"active","bypass_actors":[{"actor_id":5,"actor_type":"RepositoryRole","bypass_mode":"always"}],
 "conditions":{"ref_name":{"include":["refs/heads/dev"],"exclude":[]}},
 "rules":$common_rules}
JSON
gh api -X POST "repos/$REPO/rulesets" --input - <<JSON
{"name":"protect-main","target":"branch","enforcement":"active","bypass_actors":[{"actor_id":5,"actor_type":"RepositoryRole","bypass_mode":"always"}],
 "conditions":{"ref_name":{"include":["refs/heads/main"],"exclude":[]}},
 "rules":$main_rules}
JSON
echo "rulesets applied"
