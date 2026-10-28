"""สร้าง barcode Code 128 (ชุด B) เป็น SVG สำหรับการ์ดที่พิมพ์ใช้กับเครื่องยิง"""

# ความกว้าง แท่ง/ช่องว่าง สลับกัน ของสัญลักษณ์ค่า 0-106 (106 = Stop)
PATTERNS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
]
START_B, STOP = 104, 106


def code128_values(text: str) -> list:
    values = [START_B]
    for char in text:
        code = ord(char)
        if not 32 <= code <= 127:
            raise ValueError(f"Code 128 ชุด B ใช้ตัวอักษร '{char}' ไม่ได้")
        values.append(code - 32)
    checksum = (START_B + sum(position * value for position, value in enumerate(values[1:], start=1))) % 103
    return values + [checksum, STOP]


def modules(text: str, quiet: int = 10) -> str:
    """ลำดับ module: '1' = แท่งดำ, '0' = ช่องว่าง (รวมขอบว่างสองข้าง)"""
    out = ["0" * quiet]
    for value in code128_values(text):
        for index, width in enumerate(PATTERNS[value]):
            out.append(("1" if index % 2 == 0 else "0") * int(width))
    out.append("0" * quiet)
    return "".join(out)


def svg(text: str, module_width: int = 2, height: int = 60) -> str:
    bars = modules(text)
    rects = []
    position = 0
    while position < len(bars):
        if bars[position] == "1":
            end = bars.index("0", position)
            rects.append(f'<rect x="{position * module_width}" y="0" width="{(end - position) * module_width}" height="{height}"/>')
            position = end
        else:
            position += 1
    width = len(bars) * module_width
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"'
            f' style="background:#fff" shape-rendering="crispEdges">{"".join(rects)}</svg>')
