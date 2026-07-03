"""Perf micro-bench: split-K vs single-CTA raw-tail kernel latency at the 27B
verify geometry. The whole point of (A): the single-CTA grid (B,Hk,1)=Hk CTAs
starves the 64-SM A5000 at B=1; split-K gives (B,Hk,NUM_SPLITS+1) CTAs."""
import sys, os, time, math
sys.path.insert(0, "/work/sndr/engines/vllm/kernels_legacy")
import torch
import p67_multi_query_kernel as P67

DEV = "cuda"
K1, Hk, hpk, D = 6, 4, 6, 256
Hq = Hk * hpk
prior = 2048
block_size = 16
scale = 1.0 / math.sqrt(D)
kps = D
vdb = (D * 4 + 7) // 8
slot = kps + vdb + 4
total = prior + K1
num_blocks = (total + block_size - 1) // block_size + 2


def make(B):
    torch.manual_seed(0)
    q = torch.randn(B, K1, Hq, D, device=DEV, dtype=torch.float16) * 0.3
    kc = torch.randn(B, K1, Hk, D, device=DEV, dtype=torch.float16) * 0.3
    vc = torch.randn(B, K1, Hk, D, device=DEV, dtype=torch.float16) * 0.3
    seq = torch.full((B,), total, device=DEV, dtype=torch.int32)
    cache = torch.zeros(num_blocks, block_size, Hk, slot, device=DEV, dtype=torch.uint8)
    cache[:, :, :, kps + vdb + 1] = 0x3C
    bt = torch.arange(num_blocks, device=DEV, dtype=torch.int32)[None, :].repeat(B, 1).contiguous()
    return q, cache, bt, seq, kc, vc


def timeit(fn, iters=50):
    for _ in range(5):
        fn()
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(iters):
        fn()
    torch.cuda.synchronize()
    return (time.time() - t0) / iters * 1e6


def main():
    print(f"device {torch.cuda.get_device_name(0)}  geom K1={K1} Hk={Hk} hpk={hpk} D={D} prior={prior}")
    print(f"{'B':>3} {'single_us':>10} {'splitK_us':>10} {'speedup':>8}")
    for B in (1, 2, 4):
        q, cache, bt, seq, kc, vc = make(B)
        out1 = torch.empty_like(q)
        mid = torch.empty((B, Hk, 16, 8, 8, D + 1), dtype=torch.float32, device=DEV)  # nsp1=16
        single = lambda: P67.call_p67_attention(q, cache, bt, seq, kc, vc, scale=scale,
                          block_size=block_size, kps=kps, val_data_bytes=vdb,
                          output=out1, use_raw_tail=1)
        splitk = lambda: P67.call_p67_splitk(q, cache, bt, seq, kc, vc, scale=scale,
                          block_size=block_size, kps=kps, val_data_bytes=vdb,
                          output=out1, num_splits=15, mid_o=mid)
        us_s = timeit(single)
        us_k = timeit(splitk)
        print(f"{B:>3} {us_s:>10.1f} {us_k:>10.1f} {us_s/us_k:>7.2f}x")


if __name__ == "__main__":
    main()
