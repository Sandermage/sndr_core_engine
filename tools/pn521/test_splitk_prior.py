"""Committed-split validation: split-K == single-CTA at prior>0 (both read the
SAME compressed cache, so they MUST agree). Exercises the disjoint committed
partition + the split_end=min((sid+1)*split_len, prior) CLAMP (prior=2000 is
NOT divisible by NUM_SPLITS=15 -> last split range would overshoot without it)
+ the raw slot. Cache: controlled scale=fp16(1.0), zero=0, K bytes in a
NaN-free fp8 range, random V indices."""
import sys
sys.path.insert(0, "/work/sndr/engines/vllm/kernels_legacy")
import math
import torch
import p67_multi_query_kernel as P67

DEV = "cuda"


def build_cache(num_blocks, block_size, Hk, kps, vdb, slot):
    c = torch.zeros(num_blocks, block_size, Hk, slot, device=DEV, dtype=torch.uint8)
    # K bytes: fp8e4m3 in a NaN-free small range (avoid 0x7F/0xFF NaN + big mag)
    c[:, :, :, 0:kps] = torch.randint(0, 60, (num_blocks, block_size, Hk, kps), device=DEV, dtype=torch.uint8)
    # V index bytes: any (4-bit nibbles 0..15)
    c[:, :, :, kps:kps + vdb] = torch.randint(0, 256, (num_blocks, block_size, Hk, vdb), device=DEV, dtype=torch.uint8)
    # scale = fp16 1.0 (0x3C00 little-endian), zero = fp16 0.0
    c[:, :, :, kps + vdb + 0] = 0x00
    c[:, :, :, kps + vdb + 1] = 0x3C
    c[:, :, :, kps + vdb + 2] = 0x00
    c[:, :, :, kps + vdb + 3] = 0x00
    return c


def run_case(K1, Hk, hpk, D, prior, num_splits, block_size=16):
    Hq = Hk * hpk
    total = prior + K1
    scale = 1.0 / math.sqrt(D)
    torch.manual_seed(1)
    q = torch.randn(1, K1, Hq, D, device=DEV, dtype=torch.float16) * 0.3
    k_chunk = torch.randn(1, K1, Hk, D, device=DEV, dtype=torch.float16) * 0.3
    v_chunk = torch.randn(1, K1, Hk, D, device=DEV, dtype=torch.float16) * 0.3
    seq_lens = torch.tensor([total], device=DEV, dtype=torch.int32)
    kps = D
    vdb = (D * 4 + 7) // 8
    slot = kps + vdb + 4
    num_blocks = (total + block_size - 1) // block_size + 2
    cache = build_cache(num_blocks, block_size, Hk, kps, vdb, slot)
    bt = torch.arange(num_blocks, device=DEV, dtype=torch.int32)[None, :].contiguous()

    sk = P67.call_p67_splitk(q, cache, bt, seq_lens, k_chunk, v_chunk,
                             scale=scale, block_size=block_size, kps=kps,
                             val_data_bytes=vdb, num_splits=num_splits)[0].float()
    single = P67.call_p67_attention(q, cache, bt, seq_lens, k_chunk, v_chunk,
                                    scale=scale, block_size=block_size, kps=kps,
                                    val_data_bytes=vdb, use_raw_tail=1)[0].float()
    err = (sk - single).abs().max().item()
    rel = err / (single.abs().max().item() + 1e-6)
    nan = bool(torch.isnan(sk).any()) or bool(torch.isnan(single).any())
    ok = rel < 5e-2 and not nan
    print(f"  K1={K1} hpk={hpk} D={D} prior={prior} splits={num_splits}: "
          f"rel_vs_single={rel:.2e} nan={nan} -> {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    print(f"device {torch.cuda.get_device_name(0)}")
    print("[split-K committed] split-K == single-CTA at prior>0 (clamp + partition):")
    res = []
    res.append(run_case(K1=6, Hk=4, hpk=6, D=256, prior=2000, num_splits=15))  # not divisible -> clamp
    res.append(run_case(K1=6, Hk=4, hpk=6, D=256, prior=2010, num_splits=15))  # divisible (2010/15=134)
    res.append(run_case(K1=6, Hk=4, hpk=6, D=256, prior=100, num_splits=15))   # prior < splits -> many empty
    res.append(run_case(K1=6, Hk=4, hpk=6, D=256, prior=8192, num_splits=15))  # long ctx
    res.append(run_case(K1=2, Hk=4, hpk=6, D=256, prior=2000, num_splits=15))  # K1=2
    print("RESULT:", "ALL PASS" if all(res) else "SOME FAILED")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()
