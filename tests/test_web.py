import pytest

from yapp.web import search_query, spoken_address


@pytest.mark.parametrize(
    ("said", "address"),
    [
        ("go to weather com", "weather.com"),
        ("open weather dot com", "weather.com"),
        ("and search for weather com", "weather.com"),
        ("open weather.com", "weather.com"),
        ("go to linkedin dot com slash in", "linkedin.com/in"),
        ("visit github dot com slash manali dash co", "github.com/manali-co"),
        ("open www weather com", "weather.com"),
        ("open manali dot page", "manali.page"),
        ("go to cbc dot ca", "cbc.ca"),
        ("open weather.com slash toronto", "weather.com/toronto"),
        ("go to github.com slash manali dash co slash yapp", "github.com/manali-co/yapp"),
        ("open weather.com/toronto", "weather.com/toronto"),
    ],
)
def test_spoken_addresses_become_real_ones(said: str, address: str) -> None:
    assert spoken_address(said) == address


@pytest.mark.parametrize(
    "said",
    [
        "open notes",
        "search for the weather in toronto",
        "type com and dot",
        "com",
        "email me at five",
        "tell us it works",
        "open weather.com.example",  # an unknown ending is not shortened to weather.com
    ],
)
def test_words_without_an_address_have_none(said: str) -> None:
    assert spoken_address(said) is None


def test_the_query_is_what_follows_the_search_verb() -> None:
    assert search_query("and then search the web for the weather in toronto") == (
        "the weather in toronto"
    )
    assert search_query("google flights to lisbon") == "flights to lisbon"
    assert search_query("look up the weather") == "the weather"
    assert search_query("search for cats") == "cats"
