from tagbot.thai_keyboard import fix_thai_layout


def test_machine_card_typed_with_thai_layout_is_restored():
    # "MC-A2" sent by the scanner while Windows was on the Thai Kedmanee layout
    assert fix_thai_layout("?ฉขฤ/") == "MC-A2"


def test_work_order_typed_with_thai_layout_is_restored():
    # O->ฯ C->ฉ T->ธ 2->/ 6->ุ X->) Y->ํ
    assert fix_thai_layout("ฯฉธ/ุ)ํ") == "OCT26XY"


def test_dot_and_digit_typed_with_thai_layout_are_restored():
    # "DIE.4": D->ฏ I->ณ E->ฎ .->ใ 4->ภ
    assert fix_thai_layout("ฏณฎใภ") == "DIE.4"


def test_text_without_thai_is_unchanged():
    assert fix_thai_layout("OF26ZZ10000001") == "OF26ZZ10000001"


def test_numpad_digits_inside_thai_text_are_kept():
    # letters went through the Thai layout, digits came from the numpad
    assert fix_thai_layout("ฯญ12") == "OP12"
