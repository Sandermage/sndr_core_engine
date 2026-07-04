"""PN521 kernel unit test: raw-bf16-tail verify phase + non-pow2 K_PLUS_1.

L1 (compile) + L2 (numeric equivalence). Uses prior_seq_len=0 so the compressed
cache is never read — the whole output must equal a bf16 causal-attention
reference over the K_PLUS_1 raw-chunk tokens. Exercises pow2 (35B: K1=4,hpk=8)
and non-pow2 (27B: K1=6,hpk=6,head_dim=256) geometries.
"""
import sys
sys.path.insert(0, "/usr/local/lib/python3.12/dist-packages/sndr/engines/vllm/kernels_legacy")
sys.path.insert(0, "/work/sndr/engines/vllm/kernels_legacy")
import math
import torch
import p67_multi_query_kernel as P67

DEV = "cuda"


def ref_causal(q, k, v, scale, hpk):
    # q:[K1,Hq,D]  k,v:[K1,Hk,D]  -> out:[K1,Hq,D], causal j<=t, GQA.
    K1, Hq, D = q.shape
    out = torch.zeros_like(q, dtype=torch.float32)
    qf, kf, vf = q.float(), k.float(), v.float()
    for h in range(Hq):
        kvh = h // hpk
        for t in range(K1):
            scores = torch.tensor(
                [scale * torch.dot(qf[t, h], kf[j, kvh]) for j in range(t + 1)],
                device=q.device,
            )
            p = torch.softmax(scores, dim=0)
            out[t, h] = sum(p[j] * vf[j, kvh] for j in range(t + 1))
    return out


def run_case(K1, Hk, hpk, D, block_size=16):
    Hq = Hk * hpk
    scale = 1.0 / math.sqrt(D)
    torch.manual_seed(0)
    q = torch.randn(1, K1, Hq, D, device=DEV, dtype=torch.float16) * 0.3
    k_chunk = torch.randn(1, K1, Hk, D, device=DEV, dtype=torch.float16) * 0.3
    v_chunk = torch.randn(1, K1, Hk, D, device=DEV, dtype=torch.float16) * 0.3
    # prior_seq_len = total - K1 = 0 -> compressed loop empty; cache unused.
    seq_lens = torch.tensor([K1], device=DEV, dtype=torch.int32)
    kps = D                      # fp8 keys: 1 byte/elem
    val_data_bytes = (D * 4 + 7) // 8   # 4-bit values
    slot_bytes = kps + val_data_bytes + 4
    kv_cache = torch.zeros(1, block_size, slot_bytes, device=DEV, dtype=torch.uint8)
    block_table = torch.zeros(1, 4, device=DEV, dtype=torch.int32)

    out = P67.call_p67_attention(
        q, kv_cache, block_table, seq_lens, k_chunk, v_chunk,
        scale=scale, block_size=block_size, kps=kps,
        val_data_bytes=val_data_bytes, use_raw_tail=1,
    )
    got = out[0].float()                       # [K1,Hq,D]
    ref = ref_causal(q[0], k_chunk[0], v_chunk[0], scale, hpk)
    err = (got - ref).abs().max().item()
    rel = err / (ref.abs().max().item() + 1e-6)
    ok = rel < 5e-2
    print(f"  K1={K1} Hk={Hk} hpk={hpk} D={D}: max_abs={err:.4e} rel={rel:.4e} "
          f"-> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    print(f"torch {torch.__version__}  device {torch.cuda.get_device_name(0)}")
    results = []
    print("[L1+L2] raw-tail numeric equivalence (prior=0):")
    # 35B geometry (pow2) and 27B geometry (non-pow2, head_dim 256)
    results.append(run_case(K1=4, Hk=2, hpk=8, D=256))   # 35B-like
    results.append(run_case(K1=6, Hk=4, hpk=6, D=256))   # 27B: MTP K=5, GQA=6
    results.append(run_case(K1=2, Hk=4, hpk=6, D=256))   # 27B: MTP K=1
    results.append(run_case(K1=4, Hk=4, hpk=6, D=256))   # 27B: MTP K=3
    print("RESULT:", "ALL PASS" if all(results) else "SOME FAILED")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
