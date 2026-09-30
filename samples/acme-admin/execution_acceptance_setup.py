"""Isolated S6 provisioning: generated secrets go directly to a fresh namespace.

No dev secret files, OIDC reconciliation, registry pushes, or shared ingress.
Run with the same explicit scope as execution_acceptance.py. Requires PyYAML
from a product virtualenv. Deploy and cutover are separate deliberate operations.
"""
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys

from execution_acceptance import Cluster, ROOT, Refused, authorize, parser

SERVICES = {"agent-service": "AGENT", "audit-service": "AUDIT", "execution-runtime": "EXECUTION",
            "identity-service": "IDENTITY", "incident-service": "INCIDENT",
            "platform-gateway": "PLATFORM_GATEWAY", "skills-hub": "SKILLS", "tool-gateway": "GATEWAY"}
CLUSTER_ROLE = "luban-tool-gateway-readonly-spec063"
STATE = ROOT / ".workspaces/spec063-acceptance/setup.json"


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def metadata(name, namespace):
    return {"name": name, "namespace": namespace, "labels": {"luban.aiops/acceptance": "spec063"}}


def secret_name(service):
    return "agent-platform-runtime-secrets" if service == "agent-service" else service + "-runtime-secrets"


def make_secrets(namespace):
    """Fresh independent service credentials, never logged or written locally."""
    delegation, audit, skills, incident, signing, handoff, password, database = [secrets.token_hex(32) for _ in range(8)]
    data = {secret_name(service): {} for service in SERVICES}
    for service, prefix in SERVICES.items():
        if service != "audit-service":
            data[secret_name(service)][prefix + "_AUDIT_CLIENT_SECRET"] = audit
    data[secret_name("audit-service")]["AUDIT_INGEST_CLIENTS"] = ",".join(
        f"{service if service != 'identity-service' else 'identity-broker'}={audit}"
        for service in SERVICES if service != "audit-service")
    data[secret_name("identity-service")]["IDENTITY_SERVICE_CLIENTS"] = f"platform-gateway:{delegation}:tool-gateway"
    data[secret_name("platform-gateway")]["PLATFORM_GATEWAY_SERVICE_CLIENT_SECRET"] = delegation
    data[secret_name("agent-service")]["ACCEPTANCE_DELEGATION_CLIENT_SECRET"] = delegation
    callers = ("platform-gateway", "agent-service", "tool-gateway")
    data[secret_name("skills-hub")]["SKILLS_QUERY_CLIENTS"] = ",".join(f"{s}={skills}" for s in callers)
    data[secret_name("incident-service")].update(INCIDENT_QUERY_CLIENTS=",".join(f"{s}={incident}" for s in callers),
                                                INCIDENT_WEBHOOK_TOKEN=secrets.token_hex(32))
    for service in callers:
        prefix = SERVICES[service]
        data[secret_name(service)][prefix + "_SKILLS_CLIENT_SECRET"] = skills
        data[secret_name(service)][prefix + ("_INCIDENTS_CLIENT_SECRET" if service == "tool-gateway" else "_INCIDENT_CLIENT_SECRET")] = incident
    for service, keys, db in (
        ("agent-service", ("SESSION_DB_URL", "AGENT_STATE_DB_URL", "AGENT_EXECUTION_STATE_DB_URL"), "sessions"),
        ("execution-runtime", ("EXECUTION_STATE_DB_URL",), "sessions"),
        ("audit-service", ("AUDIT_DB_URL",), "audit"), ("skills-hub", ("SKILLS_DB_URL",), "skills"),
        ("incident-service", ("INCIDENT_DB_URL",), "incidents"),
    ):
        for key in keys:
            data[secret_name(service)][key] = f"postgresql://audit:{database}@postgres:5432/{db}"
    data.update({"execution-signing-secret": {"AGENT_EXECUTION_SIGNING_KEY": signing},
                 "execution-handoff-secret": {"EXECUTION_HANDOFF_TOKEN": handoff},
                 "spec063-postgres": {"POSTGRES_PASSWORD": database},
                 "acme-admin-credentials": {"ACME_ADMIN_PASSWORD": password},
                 "tool-gateway-browser-credentials": {"credential-sets.json": json.dumps({
                     "acme-admin": {"username": "admin", "password": password}})}})
    return [{"apiVersion": "v1", "kind": "Secret", "metadata": metadata(name, namespace),
             "type": "Opaque", "stringData": values} for name, values in data.items()]


def render(args):
    import yaml
    require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-spec063-[a-zA-Z0-9_.-]+", args.image_tag or ""), "acceptance-specific image tag required")
    overlay = Path(args.overlay).resolve()
    require(overlay.is_relative_to(ROOT / ".workspaces/spec063-acceptance"), "isolated overlay required")
    output = subprocess.run(["kubectl", "kustomize", "--load-restrictor", "LoadRestrictionsNone", str(overlay)],
                            capture_output=True, text=True, timeout=30)
    require(output.returncode == 0, "isolated overlay render failed")
    objects = list(yaml.safe_load_all(output.stdout))
    for name in ("deployment.yaml", "service.yaml", "networkpolicy.yaml"):
        obj = yaml.safe_load((ROOT / "samples/acme-admin/deploy" / name).read_text())
        obj["metadata"]["namespace"] = args.namespace
        objects.append(obj)
    for obj in objects:
        kind, meta = obj["kind"], obj["metadata"]
        name = meta["name"]
        if kind == "Namespace":
            require(name == args.namespace, "overlay namespace differs from authorization")
            meta.setdefault("labels", {})["luban.aiops/acceptance"] = "spec063"
        elif kind in {"ClusterRole", "ClusterRoleBinding"}:
            require(name == CLUSTER_ROLE, "shared cluster-scoped object refused")
            if kind == "ClusterRole":
                require(all(set(r["verbs"]) <= {"get", "list", "watch"} for r in obj["rules"]), "mutating cluster role refused")
            else:
                require(obj["roleRef"]["name"] == CLUSTER_ROLE and all(s.get("namespace") == args.namespace for s in obj["subjects"]), "cross-namespace binding refused")
        else:
            require(kind in {"ServiceAccount", "Role", "RoleBinding", "Service", "Deployment", "StatefulSet", "ConfigMap", "NetworkPolicy"}, "unexpected overlay resource")
            require(meta.get("namespace") == args.namespace, "cross-namespace object refused")
        meta.setdefault("labels", {})["luban.aiops/acceptance"] = "spec063"
        if kind == "Service":
            require(obj["spec"].get("type", "ClusterIP") == "ClusterIP" and not obj["spec"].get("externalIPs"), "external service exposure refused")
        if kind in {"Deployment", "StatefulSet"}:
            require(name in {*SERVICES, "acme-admin", "postgres", "redis"}, "unknown workload")
            spec = obj["spec"]["template"]["spec"]
            require(not any(spec.get(k) for k in ("hostNetwork", "hostPID", "hostIPC")), "host access refused")
            require(not any("hostPath" in v for v in spec.get("volumes", [])), "host volume refused")
            for container in spec["containers"]:
                if container["image"].startswith("luban-aiops/"):
                    container["image"] = container["image"].split(":")[0] + ":" + args.image_tag
                if name != "postgres":
                    container.setdefault("resources", {"requests": {"cpu": "25m", "memory": "96Mi"},
                                                       "limits": {"memory": "768Mi"}})
                if name == "execution-runtime":
                    container.setdefault("env", []).append({"name": "TOOL_GATEWAY_URL", "value": "http://spec063-wire:8080"})
                if name == "acme-admin":
                    container["env"].append({"name": "ACME_ACCEPTANCE_USER", "value": args.target_user})
                if name == "postgres":
                    for entry in container["env"]:
                        if entry["name"] == "POSTGRES_PASSWORD":
                            entry.pop("value", None)
                            entry["valueFrom"] = {"secretKeyRef": {"name": "spec063-postgres", "key": "POSTGRES_PASSWORD"}}
        if kind == "ConfigMap" and name == "platform-runtime-config":
            data = obj["data"]
            require(all(data.get(p + "_ADMISSION_ENABLED") == "false" for p in ("EXECUTION", "AGENT_EXECUTION")), "initial deployment must disable admission")
            data.update(OTEL_ENABLED="false", OTEL_SDK_DISABLED="true", AGENTSCOPE_KERNEL_TRACING="false",
                        GATEWAY_K8S_ENABLED="false", GATEWAY_K8S_NAMESPACE=args.namespace,
                        GATEWAY_HTTP_ALLOW_ORIGINS=args.origin, GATEWAY_BROWSER_ALLOW_ORIGINS=args.origin,
                        # No skill sources. This harness asserts execution and
                        # admission semantics, never skill content, so an empty
                        # list keeps it hermetic: no git clone out of the
                        # acceptance namespace and no dependency on a ConfigMap
                        # mount. It previously pointed a local source at
                        # /skills/platform-runbooks, a mount the dev overlay
                        # dropped on 2026-10-01 when the duplicate local skill
                        # sources were removed in favour of the git source.
                        SKILLS_SOURCES="[]")
    wire = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": metadata("spec063-wire", args.namespace),
            "spec": {"replicas": 1, "strategy": {"type": "Recreate"}, "selector": {"matchLabels": {"app": "spec063-wire"}},
                     "template": {"metadata": {"labels": {"app": "spec063-wire"}}, "spec": {
                         "enableServiceLinks": False, "automountServiceAccountToken": False,
                         "containers": [{"name": "wire", "image": "luban-aiops/execution-runtime:" + args.image_tag,
                                         "imagePullPolicy": "IfNotPresent", "command": ["/app/.venv/bin/python", "/witness/wire.py"],
                                         "envFrom": [{"secretRef": {"name": "execution-handoff-secret"}}],
                                         "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "allowPrivilegeEscalation": False},
                                         "resources": {"requests": {"memory": "32Mi", "cpu": "10m"}, "limits": {"memory": "128Mi"}},
                                         "volumeMounts": [{"name": "witness", "mountPath": "/witness", "readOnly": True}]}],
                         "volumes": [{"name": "witness", "configMap": {"name": "spec063-wire"}}]}}}}
    objects.extend([wire, {"apiVersion": "v1", "kind": "Service", "metadata": metadata("spec063-wire", args.namespace),
                          "spec": {"selector": {"app": "spec063-wire"}, "ports": [{"port": 8080, "targetPort": 8080}]}},
                    {"apiVersion": "v1", "kind": "ConfigMap", "metadata": metadata("spec063-wire", args.namespace),
                     "data": {"wire.py": Path(__file__).with_name("execution_acceptance_wire.py").read_text()}}])
    return objects


def send(cluster, objects):
    if objects:
        cluster.command("create", "-f", "-", payload=json.dumps({"apiVersion": "v1", "kind": "List", "items": objects}), timeout=90)


def protected_snapshot(context):
    """Read-only baseline; secret values never leave kubectl or enter evidence."""
    prefix = ["kubectl", "--context", context, "--request-timeout=15s"]
    snapshot = {}
    for namespace in ("dev-luban-aiops", "gateway"):
        for kind in ("deployments", "configmaps", "secrets", "httproutes"):
            field = "GENERATION:.metadata.generation" if kind in {"deployments", "httproutes"} else "VERSION:.metadata.resourceVersion"
            result = subprocess.run(prefix + ["-n", namespace, "get", kind, "--no-headers",
                                     "-o", "custom-columns=NAME:.metadata.name,UID:.metadata.uid," + field],
                                    capture_output=True, text=True, timeout=30)
            require(result.returncode == 0, "shared-resource baseline unavailable")
            snapshot[namespace + "/" + kind] = sorted(result.stdout.splitlines())
    paths = list((ROOT / "shared/platform-ops/gitops").glob("**/*.env"))
    paths += [ROOT / "docs/specs/SPEC-063-crash-safe-execution/plan.md",
              ROOT / "docs/adr/0013-durable-single-use-execution-claims.md"]
    snapshot["local_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return snapshot


def deploy(args, digest, objects):
    require(not STATE.exists(), "setup record exists; inspect before creating another environment")
    cluster = Cluster(args)
    require(not cluster.command("get", "namespace", args.namespace, "--ignore-not-found", "-o", "name"), "namespace already exists; refusing adoption")
    for kind in ("clusterrole", "clusterrolebinding"):
        require(not cluster.command("get", kind, CLUSTER_ROLE, "--ignore-not-found", "-o", "name"), "acceptance cluster role already exists")
    nodes = json.loads(cluster.command("get", "nodes", "-o", "json"))["items"]
    require(nodes and all(c["status"] == ("True" if c["type"] == "Ready" else "False") for n in nodes for c in n["status"]["conditions"]
                         if c["type"] in {"Ready", "MemoryPressure", "DiskPressure", "PIDPressure"}), "node pressure guard failed")
    baseline = protected_snapshot(args.context)
    send(cluster, [obj for obj in objects if obj["kind"] == "Namespace"])
    state = {"protected_before": baseline, "namespace": args.namespace, "context": args.context, "namespace_uid": cluster.get("namespace", args.namespace)["metadata"]["uid"],
             "authorization_sha256": digest, "image_tag": args.image_tag, "keycloak_changes": [], "phase": "namespace-created"}
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    send(cluster, make_secrets(args.namespace))
    infra = [o for o in objects if o["kind"] != "Namespace" and (o["kind"] != "Deployment" or o["metadata"]["name"] == "redis")]
    send(cluster, infra)
    cluster.command("rollout", "status", "statefulset/postgres", "--timeout=180s", timeout=195)
    apps = [o for o in objects if o["kind"] == "Deployment" and o["metadata"]["name"] != "redis"]
    send(cluster, apps)
    verify_deployment(args, digest)


def verify_deployment(args, digest):
    state = json.loads(STATE.read_text())
    require(state["namespace"] == args.namespace and state["context"] == args.context and state["authorization_sha256"] == digest, "setup scope drift")
    require(state["phase"] == "namespace-created", "initial verification phase mismatch")
    cluster = Cluster(args)
    require(cluster.get("namespace", args.namespace)["metadata"]["uid"] == state["namespace_uid"], "namespace identity drift")
    for name in (*SERVICES, "acme-admin", "spec063-wire"):
        deployment = cluster.get("deployment", name)
        require(all(not c["image"].startswith("luban-aiops/") or c["image"].endswith(":" + state["image_tag"])
                    for c in deployment["spec"]["template"]["spec"]["containers"]), "image drift")
        if name == "execution-runtime":
            # Readiness intentionally returns 503 until the explicit migration
            # and admission enable. Liveness is the correct disabled-stage gate.
            check = "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/health/live',timeout=10).status==200"
            cluster.command("exec", "deployment/" + name, "--", "/app/.venv/bin/python", "-c", check)
            print("Live (admission disabled): " + name, flush=True)
        else:
            cluster.command("rollout", "status", "deployment/" + name, "--timeout=180s", timeout=195)
            print("Ready: " + name, flush=True)
    state["phase"] = "deployed-admission-disabled"
    STATE.write_text(json.dumps(state, indent=2) + "\n")


def cutover(args, digest):
    state = json.loads(STATE.read_text())
    require(state["namespace"] == args.namespace and state["context"] == args.context and state["authorization_sha256"] == digest, "setup scope drift")
    require(state["phase"] == "deployed-admission-disabled", "cutover requires a disabled fresh deployment")
    cluster = Cluster(args)
    require(cluster.get("namespace", args.namespace)["metadata"]["uid"] == state["namespace_uid"], "namespace identity drift")
    config = cluster.get("configmap", "platform-runtime-config")
    require(all(config["data"].get(p + "_ADMISSION_ENABLED") == "false" for p in ("EXECUTION", "AGENT_EXECUTION")), "admission already active")
    cluster.command("exec", "deployment/execution-runtime", "--", "/app/.venv/bin/python", "-m",
                    "execution_runtime.services.execution_migration", "--epoch", args.epoch, timeout=90)
    # This separately authorized enable is not part of migrate(), which must
    # always leave the database flag disabled. Both products are still disabled.
    enable = '''
import os,sys,psycopg
from execution_runtime.services.execution_migration import verify_schema
with psycopg.connect(os.environ["EXECUTION_STATE_DB_URL"]) as conn:
    state=verify_schema(conn)
    assert not state["admission_enabled"] and state["admission_epoch"]==sys.argv[1]
    changed=conn.execute("UPDATE execution_protocol_state SET admission_enabled=true WHERE admission_epoch=%s AND admission_enabled=false",(sys.argv[1],)).rowcount
    assert changed==1
print("Database admission explicitly enabled")
'''
    cluster.command("exec", "deployment/execution-runtime", "--", "/app/.venv/bin/python", "-c", enable, args.epoch)
    patch = {p + suffix: value for p in ("EXECUTION", "AGENT_EXECUTION") for suffix, value in
             (("_ADMISSION_ENABLED", "true"), ("_ADMISSION_EPOCH", args.epoch))}
    cluster.command("patch", "configmap", "platform-runtime-config", "--type=merge", "--patch", json.dumps({"data": patch}))
    for name in ("execution-runtime", "agent-service"):
        cluster.command("rollout", "restart", "deployment/" + name)
        cluster.command("rollout", "status", "deployment/" + name, "--timeout=180s", timeout=195)
    verify_cutover(args, digest)


def verify_cutover(args, digest):
    state = json.loads(STATE.read_text())
    require(state["namespace"] == args.namespace and state["context"] == args.context and state["authorization_sha256"] == digest, "setup scope drift")
    cluster = Cluster(args)
    require(cluster.get("namespace", args.namespace)["metadata"]["uid"] == state["namespace_uid"], "namespace identity drift")
    cluster.assert_isolation()
    cluster.probe("ready")
    state["phase"] = "admission-enabled"
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    print("Explicit migration and durable-admission cutover verified.")


def reconcile(args, digest):
    """Read-only cluster observation; preserve every original campaign artifact."""
    from datetime import datetime, timezone
    from execution_acceptance_live import check_target, target, wire_delta

    state = json.loads(STATE.read_text())
    require(state["namespace"] == args.namespace and state["context"] == args.context and
            state["authorization_sha256"] == digest, "setup scope drift")
    cluster = Cluster(args)
    cluster.assert_isolation()
    require(cluster.namespace_uid == state["namespace_uid"], "namespace identity drift")
    root = ROOT / ".workspaces/spec063-evidence"
    campaigns = []
    for path in sorted(root.glob("s6-*/evidence.json")):
        report = json.loads(path.read_text())
        if report.get("namespace_uid") != state["namespace_uid"]:
            continue
        require(report["authorization_sha256"] == digest, "campaign authorization drift")
        campaigns.append((path, report))
    require(bool(campaigns), "no campaigns to reconcile")
    initial = campaigns[0][1]["initial_target"]
    previous = initial
    previous_wire = campaigns[0][1]["results"][0]["wire_before"]
    retained = []
    recorded_ids = set()
    for path, report in campaigns:
        require(report["initial_target"] == previous, "target drift between campaigns")
        wire_delta(previous_wire, report["results"][0]["wire_before"], 0)
        previous = report.get("final_target", report.get("target_after_failure"))
        previous_wire = report.get("wire_after_failure", report["results"][-1].get("wire_after"))
        require(previous and previous_wire, "campaign final observations missing")
        recorded_ids.update(row["facts"]["execution_id"] for row in report["results"] if "facts" in row)
        retained.append({"directory": str(path.parent.relative_to(ROOT)),
                         "acceptance_passed": report["acceptance_passed"],
                         "results": [{"path": r["path"], "status": r["status"]} for r in report["results"]],
                         "artifact_sha256": {name: hashlib.sha256(path.with_name(name).read_bytes()).hexdigest()
                                             for name in ("evidence.json", "junit.xml")}})
    current = target(cluster)
    require(current == previous, "target changed after campaign")
    wire = cluster.probe("wire")
    wire_delta(previous_wire, wire, 0)
    require(not wire["held"] and not wire["block_next"], "wire still holds work")
    inventory = cluster.probe("inventory")["executions"]
    require(recorded_ids <= {r["execution_id"] for r in inventory}, "recorded execution missing")
    require(len(inventory) == sum(len(r["results"]) for _, r in campaigns), "unexpected intent inventory")
    require(all(r["claims"] in (0, 1) and r["card_status"] == "approved" and
                r["card_decider"] == args.approver for r in inventory), "claim/card mismatch")
    claims = sum(r["claims"] for r in inventory)
    check_target(initial, current, claims)
    wire_delta(campaigns[0][1]["results"][0]["wire_before"], wire, claims)
    result = {"observed_at": datetime.now(timezone.utc).isoformat(), "namespace_uid": state["namespace_uid"],
              "authorization_sha256": digest, "campaigns": retained, "executions": inventory,
              "supplemental_execution_ids": sorted(r["execution_id"] for r in inventory if r["execution_id"] not in recorded_ids),
              "initial_target": initial, "final_target": current, "final_wire": wire,
              "total_claims": claims, "counts_reconciled": True, "delivery_complete": False,
              "keycloak_changes": state["keycloak_changes"]}
    destination = root / ("s6-reconciliation-" + state["namespace_uid"] + ".json")
    with destination.open("x") as output:
        output.write(json.dumps(result, indent=2) + "\n")
    print("Read-only reconciliation retained: " + str(destination))


def teardown(args, digest):
    state = json.loads(STATE.read_text())
    require(state["namespace"] == args.namespace and state["context"] == args.context and state["authorization_sha256"] == digest, "setup scope drift")
    cluster = Cluster(args)
    namespace = cluster.get("namespace", args.namespace)
    require(namespace["metadata"]["uid"] == state["namespace_uid"] and
            namespace["metadata"].get("labels", {}).get("luban.aiops/acceptance") == "spec063", "namespace teardown identity mismatch")
    require(state["keycloak_changes"] == [], "Keycloak inventory requires explicit cleanup before teardown completion")
    for kind in ("clusterrolebinding", "clusterrole"):
        obj = cluster.get(kind, CLUSTER_ROLE)
        require(obj["metadata"].get("labels", {}).get("luban.aiops/acceptance") == "spec063", "cluster role teardown identity mismatch")
        cluster.command("delete", kind, CLUSTER_ROLE)
    cluster.command("delete", "namespace", args.namespace, "--wait=true", "--timeout=180s", timeout=195)
    require(not cluster.command("get", "namespace", args.namespace, "--ignore-not-found", "-o", "name"), "namespace teardown incomplete")
    state["protected_after"] = protected_snapshot(args.context)
    state["protected_unchanged"] = state["protected_before"] == state["protected_after"]
    state["phase"] = "removed"
    state["keycloak_cleanup"] = "No realm, client, user, or settings created; no reconciliation or Keycloak admin calls made."
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    archive = ROOT / ".workspaces/spec063-evidence" / ("s6-setup-" + state["namespace_uid"] + ".json")
    archive.write_text(json.dumps(state, indent=2) + "\n")
    require(state["protected_unchanged"], "protected resource drift detected; inspect retained before/after inventory")
    print("Isolated namespace and cluster RBAC removed; protected dev configuration unchanged; Keycloak inventory empty.")


def main(argv=None):
    p = parser()
    p.add_argument("--image-tag")
    p.add_argument("--overlay", default=str(ROOT / ".workspaces/spec063-acceptance/gitops"))
    p.add_argument("--stage", choices=("render", "deploy", "verify-deployment", "cutover", "verify-cutover", "reconcile", "teardown"), required=True)
    args = p.parse_args(argv)
    try:
        digest = authorize(args)
        if args.stage == "cutover":
            cutover(args, digest)
        elif args.stage == "verify-deployment":
            verify_deployment(args, digest)
        elif args.stage == "verify-cutover":
            verify_cutover(args, digest)
        elif args.stage == "reconcile":
            reconcile(args, digest)
        elif args.stage == "teardown":
            teardown(args, digest)
        else:
            objects = render(args)
            if args.stage == "render":
                print(json.dumps({"objects": len(objects), "namespace": args.namespace,
                                  "render_sha256": hashlib.sha256(json.dumps(objects, sort_keys=True).encode()).hexdigest(),
                                  "admission_enabled": False, "keycloak_changes": []}))
            else:
                deploy(args, digest, objects)
        return 0
    except Refused as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
