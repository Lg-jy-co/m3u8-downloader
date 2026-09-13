# crypto_utils.py

# ===================== STEP 2.5 - TS 判定 & IV 工具 =====================
def looks_like_ts(buf: bytes) -> bool:
    """在 188/192 步长上检查同步字节 0x47，兼容 192 对齐和前置头。"""
    if not buf or len(buf) < 188 * 3:
        return False
    for stride in (188, 192):
        hits = 0
        for i in range(0, stride * 4, stride):
            if i < len(buf) and buf[i] == 0x47:
                hits += 1
        if hits >= 3:
            return True
    return False


def iv_from_seq(seq: int) -> bytes:
    """按 HLS 规范，用媒体序列号生成 16 字节大端 IV。"""
    return int(seq).to_bytes(16, 'big', signed=False)
