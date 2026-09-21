"""Metadata 10 member IkizuLive — nama & WARNA RESMI.

Sumber warna (semua `official`, diverifikasi 2026-09-21):
- Situs resmi: https://www.lovelive-anime.jp/lovehigh/ (chip & markup member)
- Nama warna resmi: merchandise penlight 「イキヅライブレード！」SKU LAMD83130
  https://lovelive.fannect.jp/collections/ll-40-01/products/lamd83130
- Detail lengkap: research/members.md

`color`    = warna resmi karakter (dipakai untuk embed Discord).
`color_ui` = varian kontras dari situs resmi untuk latar terang (dipakai web).
"""
from __future__ import annotations

import colorsys
import hashlib
from typing import Optional

MEMBERS: dict[str, dict] = {
    "polka_lion": {
        "jp_name": "高橋ポルカ",
        "romaji": "Takahashi Polka",
        "color": "#FBE167", "color_ui": "#CCB12E",
        "color_name": "Lucky Yellow (ラッキーイエロー)",
        "campus": "Asakusa",
    },
    "My_Mai_Eld": {
        "jp_name": "麻布麻衣",
        "romaji": "Azabu Mai",
        "color": "#009FDF", "color_ui": "#009FDF",
        "color_name": "Logical Blue (ロジカルブルー)",
        "campus": "Asakusa",
    },
    "G_Akky304250": {
        "jp_name": "五桐玲",
        "romaji": "Goto Akira",
        "color": "#BDEDAD", "color_ui": "#88D66E",
        "color_name": "Zephyr Green (そよかぜ色)",
        "campus": "Asakusa",
    },
    "hanabistarmine": {
        "jp_name": "駒形花火",
        "romaji": "Komagata Hanabi",
        "color": "#FF2021", "color_ui": "#FF2021",
        "color_name": "Peony Red (紅牡丹)",
        "campus": "Asakusa",
    },
    "MiracleGoldSP": {
        "jp_name": "金澤奇跡",
        "romaji": "Kanazawa Miracle",
        "color": "#FFB7F1", "color_ui": "#FFB7F1",
        "color_name": "Dreamy Pink (ドリーミィピンク)",
        "campus": "Fukui",
    },
    "Noricco_U": {
        "jp_name": "調布のりこ",
        "romaji": "Chofu Noriko",
        "color": "#CB96FF", "color_ui": "#AE62FF",
        "color_name": "Only Purple (オンリーパープル)",
        "campus": "Fukui",
    },
    "Yukuri_talk": {
        "jp_name": "春宮ゆくり",
        "romaji": "Harumiya Yukuri",
        "color": "#B2F9FF", "color_ui": "#5ECBD1",
        "color_name": "Swan Blue (スワンブルー)",
        "campus": "Umeda",
    },
    "Rollie_twinkle": {
        "jp_name": "此花輝夜",
        "romaji": "Konohana Aurora",  # nama resmi "Aurora", bukan "Kaguya"
        "color": "#FF589F", "color_ui": "#FD589E",
        "color_name": "Rollie Rose (ローリーローズ)",
        "campus": "Umeda",
    },
    "LittlegreenCom": {
        "jp_name": "山田真緑",
        "romaji": "Yamada Midori",  # resmi "Midori", bukan "Maro"
        "color": "#16B500", "color_ui": "#16B500",
        "color_name": "Eco Green (エコグリーン)",
        "campus": "Umeda",
    },
    "ShaunTheBunny": {
        "jp_name": "佐々木翔音",
        "romaji": "Sasaki Shion",
        "color": "#FFFFFF", "color_ui": "#9B9B9B",  # Noisy White: putih murni → abu utk kontras
        "color_name": "Noisy White (ノイジーホワイト)",
        "campus": "Sendai",
    },
}

DEFAULT_COLOR_FALLBACK = "#3A85BA"  # biru Bluebird (member tak dikenal)


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def fallback_color(screen_name: str) -> str:
    """Warna deterministik dari screen_name (konsisten antar restart)."""
    h = hashlib.sha256(screen_name.encode()).digest()[0] / 255.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.65, 0.72)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def member_color(screen_name: str) -> str:
    """Warna untuk embed Discord.

    Warna resmi dipakai apa adanya, KECUALI terlalu terang (mis. Noisy White
    #FFFFFF / Swan Blue muda) → pakai varian kontras resmi dari situs
    supaya bar warna embed tetap terlihat di tema terang maupun gelap.
    """
    meta = MEMBERS.get(screen_name) or {}
    color = meta.get("color")
    if not color:
        return fallback_color(screen_name)
    if _luminance(color) > 0.85:
        return meta.get("color_ui") or color
    return color


def member_color_ui(screen_name: str) -> str:
    """Warna aksen untuk UI web (kontras di latar terang)."""
    meta = MEMBERS.get(screen_name) or {}
    return meta.get("color_ui") or meta.get("color") or fallback_color(screen_name)


def hex_to_int(color: str) -> int:
    return int(color.lstrip("#"), 16)


def member_info(screen_name: str) -> dict:
    meta = MEMBERS.get(screen_name)
    if meta:
        return {**meta, "screen_name": screen_name,
                "color": member_color(screen_name),
                "color_ui": member_color_ui(screen_name)}
    return {
        "screen_name": screen_name,
        "jp_name": screen_name,
        "romaji": screen_name,
        "color": fallback_color(screen_name),
        "color_ui": fallback_color(screen_name),
        "color_name": "",
        "campus": "",
    }


def member_label(screen_name: str) -> str:
    """Label author untuk Discord: '高橋ポルカ · @polka_lion'."""
    info = member_info(screen_name)
    return f"{info['jp_name']} · @{screen_name}"
