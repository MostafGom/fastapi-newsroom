from newsroom.search.repository import split_prefix_term


def test_prefix_applies_to_the_last_bare_word() -> None:
    assert split_prefix_term("budg") == ("", "budg")
    assert split_prefix_term("cabinet budg") == ("cabinet", "budg")
    assert split_prefix_term('"cabinet budget"') == ('"cabinet budget"', None)
    assert split_prefix_term("budget OR deficit") == ("budget OR deficit", None)
    assert split_prefix_term("budget -deficit") == ("budget -deficit", None)
