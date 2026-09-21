"""Tes metadata member: warna resmi, nama, aturan kontras."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.members import MEMBERS, hex_to_int, member_color, member_color_ui, member_info  # noqa: E402


def test_semua_member_punya_data_lengkap():
    assert len(MEMBERS) == 10
    for screen, meta in MEMBERS.items():
        assert meta["jp_name"], screen
        assert meta["romaji"], screen
        assert meta["color"].startswith("#") and len(meta["color"]) == 7, screen
        assert meta["color_ui"].startswith("#"), screen
        assert meta["color_name"], screen
        assert meta["campus"], screen


def test_warna_resmi_sesuai_riset():
    # spot-check warna official (sumber: situs resmi + merchandise penlight)
    assert MEMBERS["polka_lion"]["color"] == "#FBE167"      # Lucky Yellow
    assert MEMBERS["hanabistarmine"]["color"] == "#FF2021"  # Peony Red
    assert MEMBERS["LittlegreenCom"]["color"] == "#16B500"  # Eco Green
    assert MEMBERS["Rollie_twinkle"]["color"] == "#FF589F"  # Rollie Rose


def test_nama_resmi_terkoreksi():
    assert MEMBERS["Rollie_twinkle"]["romaji"] == "Konohana Aurora"
    assert MEMBERS["LittlegreenCom"]["romaji"] == "Yamada Midori"
    assert MEMBERS["MiracleGoldSP"]["romaji"] == "Kanazawa Miracle"


def test_warna_terang_diganti_varian_kontras():
    # Noisy White (#FFFFFF) → varian abu resmi supaya terlihat di embed
    assert member_color("ShaunTheBunny") == "#9B9B9B"
    assert member_color("Yukuri_talk") == "#5ECBD1"   # Swan Blue muda → versi kontras
    # warna normal dipakai apa adanya
    assert member_color("hanabistarmine") == "#FF2021"
    assert member_color("My_Mai_Eld") == "#009FDF"


def test_color_ui_selalu_ada():
    for screen in MEMBERS:
        assert member_color_ui(screen).startswith("#")


def test_member_tak_dikenal_dapat_warna_deterministik():
    c1 = member_color("unknown_user")
    c2 = member_color("unknown_user")
    assert c1 == c2 and c1.startswith("#")


def test_member_info_dan_hex_to_int():
    info = member_info("polka_lion")
    assert info["jp_name"] == "高橋ポルカ" and info["romaji"] == "Takahashi Polka"
    assert hex_to_int("#FF2021") == 0xFF2021
