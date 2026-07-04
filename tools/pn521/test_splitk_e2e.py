"""Kernel-numeric test: full PN521 split-K pipeline (stage-1 -> stage-2) vs the
bf16 causal ground-truth reference at prior_seq_len=0 (only the raw slot + all
committed splits empty -> exercises the raw-slot partial store, the empty-split
sentinel, and the log2 LSE-combine end-to-end). Also cross-checks split-K ==
the validated single-CTA call_p67_attention(use_raw_tail=1)."""
import sys
sys.path.insert(0, "/work/sndr/engines/vllm/kernels_legacy")
import math
import torch
import p67_multi_query_kernel as P67

DEV = "cuda"


def ref_causal(q, k, v, scale, hpk):
    K1, Hq, D = q.shape
    out = torch.zeros_like(q, dtype=torch.float32)
    qf, kf, vf = q.float(), k.float(), v.float()
    for h in range(Hq):
        kvh = h // hpk
        for t in range(K1):
            scores = torch.tensor([scale * torch.dot(qf[t, h], kf[j, kvh]) for j in range(t + 1)], device=q.device)
            p = torch.softmax(scores, dim=0)
            out[t, h] = sum(p[j] * vf[j, kvh] for j in range(t + 1))
    return out


def run_case(K1, Hk, hpk, D, num_splits, block_size=16):
    Hq = Hk * hpk
    scale = 1.0 / math.sqrt(D)
    torch.manual_seed(0)
    q = torch.randn(1, K1, Hq, D, device=DEV, dtype=torch.float16) * 0.3
    k_chunk = torch.randn(1, K1, Hk, D, device=DEV, dtype=torch.float16) * 0.3
    v_chunk = torch.randn(1, K1, Hk, D, device=DEV, dtype=torch.float16) * 0.3
    seq_lens = torch.tensor([K1], device=DEV, dtype=torch.int32)   # prior=0
    kps = D
    vdb = (D * 4 + 7) // 8
    slot = kps + vdb + 4
    kv_cache = torch.zeros(2, block_size, slot, device=DEV, dtype=torch.uint8)
    bt = torch.zeros(1, 4, device=DEV, dtype=torch.int32)

    sk = P67.call_p67_splitk(q, kv_cache, bt, seq_lens, k_chunk, v_chunk,
                             scale=scale, block_size=block_size, kps=kps,
                             val_data_bytes=vdb, num_splits=num_splits)[0].float()
    single = P67.call_p67_attention(q, kv_cache, bt, seq_lens, k_chunk, v_chunk,
                                    scale=scale, block_size=block_size, kps=kps,
                                    val_data_bytes=vdb, use_raw_tail=1)[0].float()
    ref = ref_causal(q[0], k_chunk[0], v_chunk[0], scale, hpk)
    rel_ref = (sk - ref).abs().max().item() / (ref.abs().max().item() + 1e-6)
    rel_single = (sk - single).abs().max().item() / (single.abs().max().item() + 1e-6)
    nan = bool(torch.isnan(sk).any())
    ok = rel_ref < 5e-2 and rel_single < 5e-2 and not nan
    print(f"  K1={K1} Hk={Hk} hpk={hpk} D={D} splits={num_splits}: "
          f"rel_vs_ref={rel_ref:.2e} rel_vs_single={rel_single:.2e} nan={nan} "
          f"-> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    print(f"device {torch.cuda.get_device_name(0)}")
    print("[split-K e2e] stage-1 + stage-2 vs bf16 reference AND single-CTA (prior=0):")
    res = []
    res.append(run_case(K1=6, Hk=4, hpk=6, D=256, num_splits=15))   # 27B MTP K=5
    res.append(run_case(K1=4, Hk=2, hpk=8, D=256, num_splits=15))   # 35B-like pow2
    res.append(run_case(K1=2, Hk=4, hpk=6, D=256, num_splits=15))   # MTP K=1
    res.append(run_case(K1=6, Hk=4, hpk=6, D=256, num_splits=8))    # fewer splits
    print("RESULT:", "ALL PASS" if all(res) else "SOME FAILED")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()
