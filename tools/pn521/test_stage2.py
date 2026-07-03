"""Unit test for the PN521 split-K stage-2 log2 LSE-combine Triton kernel.
Feeds synthetic per-split partials (tv, lse2) incl. empty splits, an all-(-inf)
q_t, and padding rows/lanes; asserts the Triton combine == torch reference
(exp2(lse2_s - max) weighting) and produces NO NaN (exercises both_ninf guard)."""
import sys
sys.path.insert(0, "/work/sndr/engines/vllm/kernels_legacy")
import torch
import triton
import p67_multi_query_kernel as P67

DEV = "cuda"
B, Hk, hpk, D = 1, 4, 6, 256
Hq = Hk * hpk
K1 = 6
KP1_PAD = triton.next_power_of_2(K1)      # 8
BLOCK_QH = triton.next_power_of_2(hpk)    # 8
BLOCK_D = triton.next_power_of_2(D)       # 256
NUM_SPLITS = 15
NSP1 = NUM_SPLITS + 1                      # 16


def ref_combine(mid):
    """mid: [B,Hk,NSP1,KP1_PAD,BLOCK_QH,BLOCK_D+1] -> O:[B,K1,Hq,D] (float32)."""
    O = torch.zeros(B, K1, Hq, D, device=DEV)
    for b in range(B):
        for h in range(Hq):
            kv = h // hpk
            lane = h % hpk
            for t in range(K1):
                lse = mid[b, kv, :, t, lane, D]        # [NSP1]
                tv = mid[b, kv, :, t, lane, :D]        # [NSP1, D]
                m = lse.max()
                if torch.isinf(m) and m < 0:
                    continue                            # all -inf -> 0
                w = torch.where(torch.isinf(lse) & (lse < 0),
                                torch.zeros_like(lse), torch.exp2(lse - m))
                O[b, t, h] = (w[:, None] * tv).sum(0) / w.sum()
    return O


def main():
    torch.manual_seed(0)
    kernel = P67._get_stage2_kernel()
    assert kernel is not None
    mid = torch.zeros(B, Hk, NSP1, KP1_PAD, BLOCK_QH, BLOCK_D + 1, device=DEV, dtype=torch.float32)
    # fill valid (t<K1, lane<hpk) partials with random tv + finite lse2
    tv = torch.randn(B, Hk, NSP1, K1, hpk, D, device=DEV) * 0.5
    lse = torch.randn(B, Hk, NSP1, K1, hpk, device=DEV) * 2.0
    # edge cases: split 3 empty for ALL (t,lane); q_t=2 all-(-inf) across splits
    lse[:, :, 3, :, :] = -float("inf")
    lse[:, :, :, 2, :] = -float("inf")
    mid[:, :, :, :K1, :hpk, :D] = tv
    mid[:, :, :, :K1, :hpk, D] = lse
    # padding rows (t>=K1) and lanes (>=hpk) left as zeros incl lse2=0 (NOT -inf)
    # -> must be ignored by the kernel's qt_valid/head_mask, not consumed.

    O = torch.empty(B, K1, Hq, D, device=DEV, dtype=torch.float16)
    grid = (B, Hk)
    kernel[grid](
        mid, O,
        mid.stride(0), mid.stride(1), mid.stride(2), mid.stride(3), mid.stride(4), mid.stride(5),
        O.stride(0), O.stride(1), O.stride(2), O.stride(3),
        NUM_SPLITS_P1=NSP1, K_PLUS_1=K1, KP1_PAD=KP1_PAD, BLOCK_D=BLOCK_D,
        HEAD_DIM=D, HEADS_PER_KV=hpk, BLOCK_QH=BLOCK_QH, Hq_TOTAL=Hq,
    )
    got = O.float()
    ref = ref_combine(mid)
    err = (got - ref).abs().max().item()
    rel = err / (ref.abs().max().item() + 1e-9)
    nan = bool(torch.isnan(got).any())
    # q_t=2 must be exactly 0 (all -inf)
    qt2_zero = got[:, 2, :, :].abs().max().item()
    print(f"device {torch.cuda.get_device_name(0)}")
    print(f"stage-2 combine: max_abs={err:.3e} rel={rel:.3e} nan={nan} qt2(all-inf)_max={qt2_zero:.2e}")
    ok = rel < 5e-3 and not nan and qt2_zero < 1e-5
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
