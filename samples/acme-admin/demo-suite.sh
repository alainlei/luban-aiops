#!/bin/sh

# The acme-admin demo suite (SPEC-059 R-8).
#
# Runs the five ladder demos in order — the four single-skill rungs, then the
# composition (SPEC-057) that orders two of them into one runbook — and then
# asserts the claim this whole slice makes: a mutation performed over the
# **HTTP** surface is visible over the **HTML** surface, because both really
# address one store. That is the cross-skill verification step —
# `LockUnlockUser` changes something, and `CheckUserStatus` reads it back
# from a page a human would look at.
#
# The ladder, and what each rung's demo asserts:
#
#   1. health-check       http.get          read    0 cards
#   2. user-status        browser flow      read    0 cards
#   3. lock-unlock-user   http.post         write   1 card, kind `action`
#   4. password-reset     browser flow      write   1 card, kind `flow`
#   5. composition        runbook (4 then 3) write  2 cards, a `flow` + an `action`
#
# Read together the four rungs make a claim none of them makes alone: the card
# count tracks the *effect* of a skill, not the surface it uses. Rungs 1 and 3
# both talk to the JSON API and differ; rungs 2 and 4 both drive a browser and
# differ. A reader who has seen all four stops inferring "browser means
# dangerous" and "API means safe". Rung 5 then composes rungs 4 and 3 into one
# runbook and makes the composition claim (SPEC-057): ordering two mutating
# skills does not merge their gates — the runbook parks two cards, one per
# sub-skill, because a composition carries no authority of its own (ADR-0011).
#
# The cross-skill leg runs deterministically, with no model involved: it makes
# the same `http.post` call `LockUnlockUser` makes, through the same gateway
# endpoint with the same `credential_set`, and then reads the rendered table
# over a real console session. With RUN_CHAT_LEG=true the two demos' chat legs
# also exercise it through the agent, and this leg additionally re-asserts the
# result after those runs.
#
# Prerequisites: see demo-lib.sh's header. `make e2e` lists this script, and its
# prerequisite echo names `make deploy-sample-app` because nothing here works
# without the app deployed.

set -eu

SUITE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
# shellcheck source=demo-lib.sh
. "$SUITE_DIR/demo-lib.sh"

# The cross-skill target must start **active** in the seed. `dave` is the
# pre-locked one (store._SEED, so a read-only skill has a non-uniform table to
# describe), and locking an already-locked user is a 409 NO_OP_MUTATION that
# moves no revision — the leg would assert a transition the store refuses to
# make. `carol` starts active, so `active -> locked` is a real change and the
# rendered Revision cell has something to agree with.
CROSS_TARGET="${CROSS_TARGET:-carol}"
DEMOS="health-check user-status lock-unlock-user password-reset composition"

echo "=============================================================="
echo " acme-admin demo suite (SPEC-059) — namespace=$NAMESPACE"
echo " ladder: 0 / 0 / 1 action / 1 flow, then the 2-card composition runbook"
echo " chat legs: ${RUN_CHAT_LEG:-<off>}"
echo "=============================================================="

# --- preflight: everything the four demos share --------------------------

echo ""
echo "==> [preflight] the suite's shared prerequisites"

command -v kubectl >/dev/null 2>&1 || fail "kubectl not found on PATH"
command -v python3 >/dev/null 2>&1 || fail "python3 not found on PATH"

kubectl -n "$NAMESPACE" get deployment acme-admin >/dev/null 2>&1 \
  || fail "no acme-admin deployment in namespace '$NAMESPACE'; run 'make deploy-sample-app'"
kubectl -n "$NAMESPACE" get deployment tool-gateway >/dev/null 2>&1 \
  || fail "no tool-gateway deployment in namespace '$NAMESPACE'; run 'make deploy'"
kubectl -n "$NAMESPACE" get deployment skills-hub >/dev/null 2>&1 \
  || fail "no skills-hub deployment in namespace '$NAMESPACE'; run 'make deploy'"

require_runtime_config GATEWAY_HTTP_ENABLED true "deploy with the browser-dev runtime profile"
require_runtime_config GATEWAY_BROWSER_ENABLED true "deploy with the browser-dev runtime profile"
require_runtime_config GATEWAY_MUTATING_TOOLS_ENABLED true "deploy with the mutating-dev runtime profile"
require_allowlisted GATEWAY_HTTP_ALLOW_ORIGINS "the browser-dev profile lists the sample app's origin"
require_allowlisted GATEWAY_BROWSER_ALLOW_ORIGINS "the browser-dev profile lists the sample app's origin"

# All five documents must be packed into the skills-hub `samples` source, and
# their derived ids must be the five the demos name.
for entry in \
  "health-check:CheckServiceHealth.md" \
  "user-status:CheckUserStatus.md" \
  "lock-unlock-user:LockUnlockUser.md" \
  "password-reset:ResetAcmePassword.md" \
  "composition:RecoverAcmeAccount.md"; do
  leaf="${entry%%:*}"; file="${entry##*:}"
  kubectl -n "$NAMESPACE" exec deployment/skills-hub -- \
    cat "/skills/samples/$leaf-$file" >/dev/null 2>&1 \
    || fail "skill $leaf-$file is not in skills-hub; run 'make deploy-samples'"
  ok "skill $leaf-$file ingested"
done

# …and every id the mounted set produces must be distinct (SPEC-059 R-7).
# `deploy-samples.sh` mounts each document as `<sample-leaf>-<filename>` and
# drops the category directory, so two samples in different categories can
# collide on a name that looks distinct in the tree — and two `--from-file`
# arguments with the same ConfigMap key is a hard failure, not a silent
# overwrite. This is why rung 4's document is `ResetAcmePassword.md`: SPEC-059
# shipped it beside a static `password-reset` sample that owned
# `ResetUserPassword.md`, and SPEC-060 retired that static sample but kept the
# name (renaming a delivered skill would re-id it). `skill-graduation` ships no
# document at all (it graduates one at runtime), so the mounted set is the four
# ladder ids plus the composition's plus `adhoc-password-reset`'s — six in all.
mounted=$(kubectl -n "$NAMESPACE" exec deployment/skills-hub -- ls -1 /skills/samples) \
  || fail "could not list /skills/samples in skills-hub"
printf '%s\n' "$mounted" | python3 -c '
import re, sys
names = [line.strip() for line in sys.stdin
         if line.strip().endswith(".md") and not line.strip().startswith(".")]
expected = {
    "samples/health-check-checkservicehealth",
    "samples/user-status-checkuserstatus",
    "samples/lock-unlock-user-lockunlockuser",
    "samples/password-reset-resetacmepassword",
    "samples/composition-recoveracmeaccount",
    "samples/adhoc-password-reset-resetpasswordadhoc",
}
ids = {}
for name in names:
    slug = "samples/" + re.sub(r"[^a-z0-9]+", "-", name[:-3].lower()).strip("-")
    assert slug not in ids, "%s is produced by both %s and %s" % (
        slug, ids.get(slug), name)
    ids[slug] = name
missing = expected - set(ids)
assert not missing, "these sample skill ids are not ingested: %s" % ", ".join(sorted(missing))
for slug in sorted(ids):
    print("  ok: %-46s <- %s" % (slug, ids[slug]))
print("  ok: %d sample skill ids, pairwise distinct" % len(ids))' \
  || fail "the mounted sample skills do not produce the six distinct ids this suite requires"

# --- the five demos, in ladder order -------------------------------------

for sample in $DEMOS; do
  echo ""
  echo "############################################################"
  echo "# rung: $sample"
  echo "############################################################"
  if ! sh "$SUITE_DIR/$sample/demo/demo.sh"; then
    fail "the '$sample' demo failed; the suite stops at the first broken rung"
  fi
done

# --- the cross-skill verification step -----------------------------------

echo ""
echo "############################################################"
echo "# cross-skill verification: mutated over HTTP, read over HTML"
echo "############################################################"

ACME_ADMIN_PASSWORD=$(kubectl -n "$NAMESPACE" get secret "$SECRET_NAME" \
  -o go-template="{{index .data \"ACME_ADMIN_PASSWORD\" | base64decode}}")
[ -n "$ACME_ADMIN_PASSWORD" ] || fail "ACME_ADMIN_PASSWORD is empty"

reseed_demo
ensure_tokens

# Assert the starting state before mutating it, so an override that names a
# pre-locked user fails with a sentence about the seed rather than with a 409
# three assertions downstream.
app_http_authed "$ORIGIN/api/users/$CROSS_TARGET"
[ "$APP_CODE" = "200" ] || fail "GET /api/users/$CROSS_TARGET answered $APP_CODE"
printf '%s' "$APP_BODY" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
assert payload.get("locked") is False, \
    "%s starts locked; the cross-skill leg needs an active -> locked transition" % sys.argv[1]
assert payload.get("revision") == 0, \
    "%s starts at revision %r after a reseed" % (sys.argv[1], payload.get("revision"))' \
  "$CROSS_TARGET" || fail "the reseeded store is not the baseline this leg asserts from: $APP_BODY"
ok "$CROSS_TARGET starts active at revision 0 (the reseeded baseline)"

# 1. The mutation, made exactly the way LockUnlockUser makes it: `http.post`
#    through the gateway, with the credential referenced by name.
invoke_tool http.post \
  "{\"url\":\"$ORIGIN/api/users/$CROSS_TARGET/lock\",\"body\":{\"locked\":true},\"credential_set\":\"$CREDENTIAL_SET\"}" \
  cross-lock
[ "$HTTP_CODE" = "200" ] || fail "the cross-skill http.post answered $HTTP_CODE: $GATEWAY_BODY"
API_REVISION=$(printf '%s' "$GATEWAY_BODY" | python3 -c '
import json, sys
data = json.load(sys.stdin)["data"]
assert data["status"] == 200, "upstream status is %r" % data["status"]
assert data["mutation_confirmed"] is True, "mutation_confirmed is %r" % data["mutation_confirmed"]
body = data["body"]
assert isinstance(body, dict), \
    "an untruncated application/json body must project parsed, got %s" % type(body).__name__
print(body["revision"])') \
  || fail "the cross-skill http.post did not confirm a mutation: $GATEWAY_BODY"
ok "http.post locked $CROSS_TARGET over the HTTP surface (revision $API_REVISION)"

# 2. The observation, over the human surface: sign in as the console does and
#    read the row a `web.extract` of `#user-row-<name>` would return.
app_sign_in
app_http_session "$ORIGIN/admin/users/"
[ "$APP_CODE" = "200" ] || fail "the rendered user list answered $APP_CODE"
printf '%s' "$APP_BODY" | python3 -c '
import re, sys
target, expected_revision = sys.argv[1], sys.argv[2]
html = sys.stdin.read()
row = re.search(
    r"<tr id=\"user-row-%s\"[^>]*data-locked=\"(true|false)\"(.*?)</tr>" % target,
    html, re.S)
assert row, "the rendered table carries no row for %s" % target
assert row.group(1) == "true", \
    "the rendered row for %s still reads data-locked=%s after an http.post lock" % (
        target, row.group(1))
status = re.search(r"<td class=\"user-status\">([^<]*)</td>", row.group(2))
revision = re.search(r"<td class=\"user-revision\">([^<]*)</td>", row.group(2))
assert status and status.group(1) == "locked", \
    "the Status cell for %s reads %r, expected locked" % (target, status and status.group(1))
assert revision and revision.group(1) == expected_revision, \
    "the Revision cell for %s reads %r but the API reported %s" % (
        target, revision and revision.group(1), expected_revision)
store = re.search(r"id=\"store-revision\">([^<]*)<", html)
assert store and store.group(1) == expected_revision, \
    "the page footer reads store revision %r, expected %s" % (
        store and store.group(1), expected_revision)
print("  ok: the rendered console shows %s locked at revision %s — the same" % (target, expected_revision))
print("       revision the JSON API reported, so both surfaces address one store")' \
  "$CROSS_TARGET" "$API_REVISION" \
  || fail "the rendered console does not reflect the HTTP mutation"

# 3. A lock is not a reset: the "Recent Password Resets" panel must still say
#    there are none. Asserting what a mutation did NOT do is what keeps the
#    cross-surface claim from being satisfied by a shared cache.
printf '%s' "$APP_BODY" | grep -q 'id="no-resets" style="[^"]*display:block' \
  || fail "a lock was recorded as a password reset"
ok "the lock left the Recent Password Resets panel empty (a lock is not a reset)"

if [ "${RUN_CHAT_LEG:-}" = "true" ]; then
  echo ""
  echo "==> [CHAT] the same claim through two agent turns"

  require_hitl_enabled

  # Turn 1: mutate over HTTP through the agent, approving the one action card.
  reseed_demo
  LOCK_SESSION=$(chat_session_new)
  [ -n "$LOCK_SESSION" ] || fail "session creation returned no session_id"
  LOCK_OUTPUT=$(chat_send "$LOCK_SESSION" \
    "Lock the acme-admin account for '${CROSS_TARGET}'. Use skill samples/lock-unlock-user-lockunlockuser. The admin credentials are in the ${CREDENTIAL_SET} credential set.")
  require_card_shape "$LOCK_OUTPUT" action http.post
  LOCK_CONFIRM=$(chat_confirm "$LOCK_SESSION" "$CARD_CONFIRM_ID" approve)
  printf '%s' "$LOCK_CONFIRM" | grep -q '"status": *"approved"\|"status":"approved"' \
    || fail "the action card was not approved: $LOCK_CONFIRM"
  require_card_count "$LOCK_SESSION" 1 "one gated http.post parks one action card"
  ok "turn 1 locked $CROSS_TARGET through the agent (one action card, approved)"

  # Turn 2: read it back over HTML through the agent, in a *separate* session,
  # so the read cannot inherit anything the mutation's turn held.
  READ_SESSION=$(chat_session_new)
  [ -n "$READ_SESSION" ] || fail "session creation returned no session_id"
  READ_OUTPUT=$(chat_send "$READ_SESSION" \
    "Read the current status of the acme-admin user '${CROSS_TARGET}' from the admin console and tell me whether the account is active or locked, plus its revision. Use skill samples/user-status-checkuserstatus. Admin credentials are in the ${CREDENTIAL_SET} credential set.")
  require_zero_cards "$READ_OUTPUT" "a read-only browser flow parks nothing"
  printf '%s' "$READ_OUTPUT" | grep -q '"tool_name": *"web.extract"\|"tool_name":"web.extract"' \
    || fail "turn 2 never called web.extract — it cannot have read the rendered table"
  require_card_count "$READ_SESSION" 0 "a read-only turn leaves no durable card"
  ok "turn 2 read the rendered console through the agent (zero cards, web.extract)"

  # The store is authoritative for whether turn 1's approved call really ran.
  app_http_authed "$ORIGIN/api/users/$CROSS_TARGET"
  printf '%s' "$APP_BODY" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
assert payload.get("locked") is True, \
    "%s is not locked after the approved agent turn: %r" % (sys.argv[1], payload)
print("  ok: the store confirms %s is locked at revision %s" % (
    payload.get("username"), payload.get("revision")))' "$CROSS_TARGET" \
    || fail "the store does not reflect the agent's approved lock: $APP_BODY"
fi

# --- recap ---------------------------------------------------------------

echo ""
echo "=============================================================="
echo " acme-admin demo suite passed. It proved:"
echo "  - all five demos green in ladder order"
echo "      health-check       http.get        read   0 cards"
echo "      user-status        browser flow    read   0 cards"
echo "      lock-unlock-user   http.post       write  1 action card"
echo "      password-reset     browser flow    write  1 flow card"
echo "      composition        runbook (4+3)   write  2 cards (flow + action)"
echo "  - every sample skill id the mounted set produces is distinct, so"
echo "    ResetAcmePassword.md cannot silently re-id a shipped sample"
echo "  - a mutation made over HTTP through http.post is read back from the"
echo "    rendered console at the same revision the JSON API reported"
echo "  - the lock left the reset panel empty, so the two surfaces share a"
echo "    store and not a cache"
if [ "${RUN_CHAT_LEG:-}" = "true" ]; then
  echo "  - the same claim through two agent turns: one approved action card,"
  echo "    then a zero-card read in a separate session"
fi
echo "=============================================================="
