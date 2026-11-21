#!/usr/bin/env python3
"""Extract partitions from a full-OTA zip over HTTP range requests, without downloading the zip.

usage: remote_payload.py URL list
       remote_payload.py URL extract OUTDIR part [part ...]
"""
import bz2, hashlib, lzma, os, struct, sys, time, urllib.request

sys.path.insert(0, os.path.expanduser('~/.local/lib/python3.9/site-packages/payload_dumper'))
import update_metadata_pb2 as um  # noqa: E402


class Remote:
    def __init__(self, url):
        self.url = url
        self.size = int(self._get(0, 0, head=True))

    def _get(self, start, end, head=False):
        for attempt in range(8):
            try:
                req = urllib.request.Request(self.url, headers={'Range': f'bytes={start}-{end}'})
                with urllib.request.urlopen(req, timeout=120) as r:
                    if head:
                        return r.headers['Content-Range'].split('/')[-1]
                    data = r.read()
                if len(data) != end - start + 1:
                    raise IOError(f'short read {len(data)}')
                return data
            except Exception as e:  # retry transient network errors
                print(f'  retry {attempt}: {e}', file=sys.stderr)
                time.sleep(2 + attempt * 3)
        raise SystemExit('download failed')

    def read(self, off, n):
        return self._get(off, off + n - 1) if n else b''


def find_payload(rem):
    tail = rem.read(rem.size - 65536, 65536)
    i = tail.rfind(b'PK\x05\x06')
    cd_size, cd_off = struct.unpack('<II', tail[i + 12:i + 20])
    j = tail.rfind(b'PK\x06\x06')  # zip64 end record
    if cd_off == 0xFFFFFFFF and j >= 0:
        cd_size, cd_off = struct.unpack('<QQ', tail[j + 40:j + 56])
    cd = rem.read(cd_off, cd_size)
    p = 0
    while p < len(cd):
        (method, csize, usize, nlen, xlen, clen, lho) = struct.unpack('<10xH8xIIHHH8xI', cd[p:p + 46])
        name = cd[p + 46:p + 46 + nlen].decode()
        extra = cd[p + 46 + nlen:p + 46 + nlen + xlen]
        if 0xFFFFFFFF in (csize, usize, lho):  # zip64 extra field
            q = 0
            while q < len(extra):
                hid, hlen = struct.unpack('<HH', extra[q:q + 4])
                if hid == 1:
                    vals = list(struct.unpack(f'<{hlen // 8}Q', extra[q + 4:q + 4 + hlen // 8 * 8]))
                    if usize == 0xFFFFFFFF: usize = vals.pop(0)
                    if csize == 0xFFFFFFFF: csize = vals.pop(0)
                    if lho == 0xFFFFFFFF: lho = vals.pop(0)
                q += 4 + hlen
        if name == 'payload.bin':
            assert method == 0, 'payload.bin is compressed in zip'
            lh = rem.read(lho, 30)
            n2, x2 = struct.unpack('<HH', lh[26:30])
            return lho + 30 + n2 + x2
        p += 46 + nlen + xlen + clen
    raise SystemExit('payload.bin not found')


def manifest(rem, base):
    hdr = rem.read(base, 24)
    assert hdr[:4] == b'CrAU', hdr[:4]
    ver, msize, sigsize = struct.unpack('>QQI', hdr[4:24])
    m = um.DeltaArchiveManifest()
    m.ParseFromString(rem.read(base + 24, msize))
    return m, base + 24 + msize + sigsize


def extract(rem, data_off, m, part, outdir):
    bs = m.block_size
    path = os.path.join(outdir, part.partition_name + '.img')
    total = part.new_partition_info.size
    with open(path, 'wb') as f:
        f.truncate(total)
        # coalesce adjacent ops into larger range requests
        ops = list(part.operations)
        i = 0
        while i < len(ops):
            j, start = i, ops[i].data_offset
            end = start + ops[i].data_length
            while j + 1 < len(ops) and ops[j + 1].data_offset == end and end - start < 32 << 20:
                j += 1
                end += ops[j].data_length
            blob = rem.read(data_off + start, end - start)
            for op in ops[i:j + 1]:
                d = blob[op.data_offset - start:op.data_offset - start + op.data_length]
                t = op.type
                if t == op.REPLACE_XZ:
                    d = lzma.decompress(d)
                elif t == op.REPLACE_BZ:
                    d = bz2.decompress(d)
                elif t == getattr(op, 'ZSTD', -1):
                    import zstandard
                    d = zstandard.ZstdDecompressor().decompress(d, max_output_size=1 << 30)
                elif t == op.ZERO:
                    continue
                elif t != op.REPLACE:
                    raise SystemExit(f'{part.partition_name}: unsupported op {t}')
                f.seek(op.dst_extents[0].start_block * bs)
                f.write(d)
            i = j + 1
    h = hashlib.sha256(open(path, 'rb').read()).digest()
    ok = h == part.new_partition_info.hash
    print(f'{part.partition_name}: {total} bytes, hash {"OK" if ok else "MISMATCH"}')
    return ok


def main():
    rem = Remote(sys.argv[1])
    base = find_payload(rem)
    m, data_off = manifest(rem, base)
    parts = {p.partition_name: p for p in m.partitions}
    if sys.argv[2] == 'list':
        for p in m.partitions:
            print(f'{p.partition_name:24s} {p.new_partition_info.size:>12d}')
        return
    outdir = sys.argv[3]
    os.makedirs(outdir, exist_ok=True)
    bad = [n for n in sys.argv[4:] if not extract(rem, data_off, m, parts[n], outdir)]
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
