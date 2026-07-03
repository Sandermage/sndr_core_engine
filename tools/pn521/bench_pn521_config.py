"""PN521 kernel config micro-bench: which (BLOCK_KV, num_stages) fit sm_86 SMEM
at the 27B raw-tail geometry, and which is fastest. Uses a realistic verify
shape (B=4, K1=6, Hq=24, Hk=4, D=256, prior=2048). Cache content is random
(irrelevant to timing — the dequant runs regardless)."""
import os, sys, time, math
sys.path.insert(0, "/work/sndr/engines/vllm/kernels_legacy")
import torch
import p67_multi_query_kernel as P67

DEV = "cuda"
B, K1, Hk, hpk, D = 4, 6, 4, 6, 256
Hq = Hk * hpk
prior = 2048
block_size = 16
scale = 1.0 / math.sqrt(D)
kps = D
val_data_bytes = (D * 4 + 7) // 8
slot_bytes = kps + val_data_bytes + 4
num_blocks = (prior + K1) // block_size + 2

torch.manual_seed(0)


def make_inputs():
    q = torch.randn(B, K1, Hq, D, device=DEV, dtype=torch.float16) * 0.3
    k_chunk = torch.randn(B, K1, Hk, D, device=DEV, dtype=torch.float16) * 0.3
    v_chunk = torch.randn(B, K1, Hk, D, device=DEV, dtype=torch.float16) * 0.3
    seq_lens = torch.full((B,), prior + K1, device=DEV, dtype=torch.int32)
    kv_cache = torch.randint(0, 255, (num_blocks, block_size, slot_bytes),
                             device=DEV, dtype=torch.uint8)
    bt = torch.arange(num_blocks, device=DEV, dtype=torch.int32)[None, :].repeat(B, 1)
    return q, kv_cache, bt, seq_lens, k_chunk, v_chunk


def time_cfg(block_kv, num_stages, iters=30):
    os.environ["GENESIS_P67_BLOCK_KV"] = str(block_kv)
    os.environ["GENESIS_P67_NUM_STAGES"] = str(num_stages)
    P67._CACHED_KERNEL = None  # force rebuild with new env-driven config path
    q, kv_cache, bt, seq_lens, k_chunk, v_chunk = make_inputs()
    try:
        # warmup / compile
        for _ in range(3):
            P67.call_p67_attention(q, kv_cache, bt, seq_lens, k_chunk, v_chunk,
                                   scale=scale, block_size=block_size, kps=kps,
                                   val_data_bytes=val_data_bytes, use_raw_tail=1)
        torch.cuda.synchronize()
        t0 = time.time()
        for _ in range(iters):
            P67.call_p67_attention(q, kv_cache, bt, seq_lens, k_chunk, v_chunk,
                                   scale=scale, block_size=block_size, kps=kps,
                                   val_data_bytes=val_data_bytes, use_raw_tail=1)
        torch.cuda.synchronize()
        us = (time.time() - t0) / iters * 1e6
        return ("OK", us)
    except Exception as e:
        msg = str(e)
        if "shared memory" in msg or "OutOfResources" in msg:
            return ("OOM", None)
        return ("ERR:" + msg[:60], None)


def main():
    print(f"device {torch.cuda.get_device_name(0)}  geom B={B} K1={K1} Hq={Hq} Hk={Hk} D={D} prior={prior}")
    base = None
    print(f"{'BLOCK_KV':>9} {'stages':>7} {'fit':>6} {'us/call':>9} {'vs16/2':>8}")
    for bkv in (16, 24, 32):
        for ns in (2, 3):
            status, us = time_cfg(bkv, ns)
            if bkv == 16 and ns == 2 and us:
                base = us
            rel = f"{base/us:.2f}x" if (us and base) else "-"
            print(f"{bkv:>9} {ns:>7} {status:>6} {(f'{us:.1f}' if us else '-'):>9} {rel:>8}")


if __name__ == "__main__":
    main()
