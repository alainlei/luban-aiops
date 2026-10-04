# LLM Hosting — Reference Manifests

Opt-in reference manifests for hosting a small LLM server inside the
platform's Kubernetes cluster, served as the `luban` provider
(SPEC-028 R-6). See the
[Luban-Hosted Small Model Guide](../../../../docs/guides/luban-llm-guide.md)
for the full operator walkthrough.

**These manifests are free-standing.** They are NOT referenced by the
`dev-k8s` kustomization or any `make` target — hosting a model server is
an explicit operator choice.

## Contents

- `ollama/` — Ollama reference stack (primary): Deployment + Service +
  Secret template + PVC for model weights.

## Apply order

```sh
# 1. Dedicated namespace (manifests are namespace-free; the guide's
#    examples use llm-hosting).
kubectl create namespace llm-hosting

# 2. Edit the Secret template first — replace the placeholder token
#    with a real one (e.g. `openssl rand -hex 32`). Never commit it.
$EDITOR ollama/secret.yaml

# 3. Apply the stack.
kubectl -n llm-hosting apply -f ollama/

# 4. Pull a model into the PVC-backed inventory.
kubectl -n llm-hosting exec deploy/ollama -- ollama pull qwen3:8b

# 5. Probe with the token.
kubectl -n llm-hosting run curl-probe --rm -it --image=curlimages/curl -- \
  curl -sS -H "Authorization: Bearer <token>" \
  http://ollama.llm-hosting.svc:11434/v1/models
```

Then wire the platform (guide §4):

```
LUBAN_API_KEY=<token from the Secret>
LUBAN_BASE_URL=http://ollama.llm-hosting.svc:11434/v1
```

## Sizing notes

- **CPU-only qwen3-8b-class quant** (q4, ~5 GB weights): the Deployment
  requests 2 CPU / 8Gi RAM and limits 12Gi; expect slow interactive
  throughput. Prefer a 1.5B–4B class model for snappy turns on CPU.
- **Model weights** live on the 50Gi PVC mounted at `/root/.ollama`;
  resize before pulling larger inventories.
- Single replica by design — model weights are per-pod and Ollama has no
  cross-replica state; scale by replicating the stack, not the
  Deployment.

## GPU-node variant

On GPU nodes, add the NVIDIA device-plugin tolerations/limits
(`nvidia.com/gpu: 1`) to the Deployment, or switch to vLLM
(`vllm serve <model> --api-key <token>`) behind the same Service shape;
the platform wiring (`LUBAN_*`) is identical — see the guide §2/§3.

## Security posture

The Secret carries the only authentication surface (`OLLAMA_API_KEY`);
the Service is `ClusterIP` (no external exposure). The platform fails
closed without `LUBAN_BASE_URL` + `LUBAN_API_KEY`, so an unauthenticated
server is never called.
