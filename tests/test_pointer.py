from yapp.pointer import borrow_pointer


def test_borrow_refuses_while_a_button_is_held() -> None:
    waited: list[float] = []
    assert not borrow_pointer(10, 10, is_busy=lambda: True, settle=waited.append)
    assert waited == []  # never touched the cursor
