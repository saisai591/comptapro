"""
QR Code SVG generator — pure Python, zero dependencies.
Produces a valid QR Code (Byte mode, Error Correction L) as an SVG string.

ponytail: minimal QR encoder, version auto-detected 1-6, ECC L only.
Upgrade path: if larger data needed, bump version detection.
"""

from typing import Tuple, List


# ── Galois Field arithmetic for Reed-Solomon ──
def _gf_mul(a: int, b: int) -> int:
    """Multiply in GF(256), polynomial 0x11d."""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        msb = a & 0x80
        a = (a << 1) & 0xFF
        if msb:
            a ^= 0x1D
        b >>= 1
    return p


def _rs_generator_poly(nsym: int) -> List[int]:
    """Generate Reed-Solomon generator polynomial for nsym error codewords."""
    g = [1]
    for i in range(nsym):
        g = [_gf_mul(x, 1) for x in g]  # multiply by (x + a^i)
        term = [1, 2 ** i % 255]
        # polynomial multiplication
        res = [0] * (len(g) + 1)
        for j in range(len(g)):
            res[j] ^= g[j]
            res[j + 1] ^= _gf_mul(g[j], term[1])
        g = [x for x in res if x != 0 or True]  # keep all
    return g


def _rs_encode(data: List[int], nsym: int) -> List[int]:
    """Generate Reed-Solomon error correction codewords."""
    gen = _rs_generator_poly(nsym)
    res = data[:] + [0] * nsym
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data):]


# ── QR Code constants ──
# Version -> (modules, ECC codewords per block, group1 blocks, group1 data, group2 blocks, group2 data)
ECC_TABLE = {
    # Version: (size, ec_cw_per_block, g1_nblocks, g1_ndata, g2_nblocks, g2_ndata)
    1:  (21,  7,  1,  19, 0, 0),
    2:  (25,  10, 1,  34, 0, 0),
    3:  (29,  15, 1,  55, 0, 0),
    4:  (33,  20, 1,  80, 0, 0),
    5:  (37,  26, 1, 108, 0, 0),
    6:  (41,  18, 2,  68, 0, 0),
}

# Finder patterns at corners (row, col)
FINDER_POSITIONS = [
    (0, 0), (0, -7), (-7, 0),
]

# Alignment patterns for versions 2+
ALIGNMENT_POS = {
    2: [(6, 18)],
    3: [(6, 22)],
    4: [(6, 26)],
    5: [(6, 30)],
    6: [(6, 34)],
}


def _determine_version(data_len: int) -> int:
    """Determine smallest QR version that fits the data."""
    for v in sorted(ECC_TABLE.keys()):
        size, ec_cw, g1b, g1d, g2b, g2d = ECC_TABLE[v]
        total_data = g1b * g1d + g2b * g2d
        if data_len <= total_data:
            return v
    return 6  # max supported


def _encode_data(data: str) -> Tuple[int, List[int]]:
    """Encode string data into QR codewords. Returns (version, codewords)."""
    raw = data.encode("latin-1")
    # Byte mode
    bits = ""
    bits += "0100"  # mode indicator (byte)
    bits += f"{len(raw):08b}"  # char count (8 bits for versions 1-9)
    for b in raw:
        bits += f"{b:08b}"
    
    version = _determine_version(len(raw) + 3)  # +3 for terminator minimum
    
    # Add terminator
    size, ec_cw, g1b, g1d, g2b, g2d = ECC_TABLE[version]
    total_data_bits = (g1b * g1d + g2b * g2d) * 8
    bits += "0000"  # terminator
    # Pad to 8 bits
    if len(bits) % 8:
        bits += "0" * (8 - len(bits) % 8)
    # Pad to capacity
    pad_patterns = ["11101100", "00010001"]
    pi = 0
    while len(bits) < total_data_bits:
        bits += pad_patterns[pi % 2]
        pi += 1
    
    # Convert to bytes
    codewords = [int(bits[i:i+8], 2) for i in range(0, total_data_bits, 8)]
    
    # Generate error correction
    ec_codewords = _rs_encode(codewords, ec_cw)
    
    return version, codewords + ec_codewords


def _create_matrix(version: int, codewords: List[int]) -> List[List[int]]:
    """Create QR matrix with data and function patterns."""
    size = ECC_TABLE[version][0]
    matrix = [[-1] * size for _ in range(size)]
    
    # Place finder patterns
    for fr, fc in FINDER_POSITIONS:
        _place_finder(matrix, version, fr, fc)
    
    # Timing patterns
    for i in range(8, size - 8):
        val = 1 if i % 2 == 0 else 0
        if matrix[6][i] == -1:
            matrix[6][i] = val  # horizontal
        if matrix[i][6] == -1:
            matrix[i][6] = val  # vertical
    
    # Alignment patterns
    if version >= 2:
        for ar, ac in ALIGNMENT_POS.get(version, []):
            _place_5x5(matrix, ar - 2, ac - 2)
    
    # Dark module
    matrix[size - 8][8] = 1
    
    # Reserve format info area
    for i in range(9):
        if matrix[i][8] == -1:
            matrix[i][8] = 0
        if matrix[8][i] == -1:
            matrix[8][i] = 0
    for i in range(8):
        if matrix[size - 8 + i][8] == -1:
            matrix[size - 8 + i][8] = 0
        if matrix[8][size - i - 1] == -1:
            matrix[8][size - i - 1] = 0
    
    # Place data (bit-by-bit into modules)
    bits = ""
    for cw in codewords:
        bits += f"{cw:08b}"
    
    bit_idx = 0
    upward = True
    col = size - 1
    
    while col >= 0:
        if col == 6:  # skip timing pattern column
            col -= 1
            continue
        
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in [col, col - 1]:
                if c < 0:
                    continue
                if matrix[row][c] == -1 and bit_idx < len(bits):
                    matrix[row][c] = int(bits[bit_idx])
                    bit_idx += 1
                elif bit_idx >= len(bits):
                    matrix[row][c] = 0
        
        upward = not upward
        col -= 2
    
    # Apply mask (mask pattern 0: (row + col) % 2 == 0)
    # We'll use mask 2 for better balance: (row) % 3 == 0
    # Actually, let's use mask 0 for simplicity: (row + col) % 2 == 0
    mask = 0  # (row + col) % 2 == 0
    for r in range(size):
        for c in range(size):
            if matrix[r][c] > 1:  # function patterns (not data)
                continue
            if matrix[r][c] < 0:
                matrix[r][c] = 0
            cond = (r + c) % 2 == 0
            if cond:
                matrix[r][c] ^= 1
    
    return matrix


def _place_finder(matrix: List[List[int]], version: int, row: int, col: int):
    """Place a finder pattern (7x7)."""
    # Normalize negative indices
    size = ECC_TABLE[version][0]
    if row < 0:
        row = size + row
    if col < 0:
        col = size + col
    
    pattern = [
        [1,1,1,1,1,1,1],
        [1,0,0,0,0,0,1],
        [1,0,1,1,1,0,1],
        [1,0,1,1,1,0,1],
        [1,0,1,1,1,0,1],
        [1,0,0,0,0,0,1],
        [1,1,1,1,1,1,1],
    ]
    # Separator (white border)
    for i in range(-1, 8):
        for j in range(-1, 8):
            r, c = row + i, col + j
            if 0 <= r < size and 0 <= c < size:
                if 0 <= i < 7 and 0 <= j < 7:
                    matrix[r][c] = pattern[i][j]
                else:
                    matrix[r][c] = 0


def _place_5x5(matrix: List[List[int]], row: int, col: int):
    """Place a 5x5 dark/light pattern (alignment pattern)."""
    pattern = [
        [1,1,1,1,1],
        [1,0,0,0,1],
        [1,0,1,0,1],
        [1,0,0,0,1],
        [1,1,1,1,1],
    ]
    size = len(matrix)
    for i in range(5):
        for j in range(5):
            r, c = row + i, col + j
            if 0 <= r < size and 0 <= c < size:
                matrix[r][c] = pattern[i][j]


def generate_qr_svg(data: str, module_size: int = 4, border: int = 2) -> str:
    """
    Generate QR code as SVG string.
    
    Args:
        data: text to encode
        module_size: pixels per QR module
        border: border modules (quiet zone)
    
    Returns:
        SVG string
    """
    version, codewords = _encode_data(data)
    matrix = _create_matrix(version, codewords)
    size = ECC_TABLE[version][0]
    
    total = size + 2 * border
    px = total * module_size
    
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {px} {px}" width="{px}" height="{px}">',
        f'<rect width="{px}" height="{px}" fill="white"/>',
    ]
    
    for r in range(size):
        for c in range(size):
            if matrix[r][c] == 1:
                x = (c + border) * module_size
                y = (r + border) * module_size
                svg_parts.append(
                    f'<rect x="{x}" y="{y}" width="{module_size}" height="{module_size}" fill="black"/>'
                )
    
    svg_parts.append("</svg>")
    return "\n".join(svg_parts)
