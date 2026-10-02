from datetime import date

from newsroom.web.templating import format_hijri


def test_format_hijri_uses_umm_al_qura() -> None:
    day = date(2024, 3, 11)
    assert format_hijri(day, "en") == "1 Ramadan 1445"
    assert format_hijri(day, "ar") == "1 رمضان 1445"
    assert format_hijri(day, "ar-SA") == "1 رمضان 1445"


def test_format_hijri_empty() -> None:
    assert format_hijri(None, "en") == ""
    assert format_hijri(None, "ar") == ""
