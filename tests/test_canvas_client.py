from app.canvas.client import parse_link_header


def test_parse_link_header_next_and_last():
    header = (
        '<https://school.instructure.com/api/v1/courses?page=1&per_page=100>; rel="current",'
        '<https://school.instructure.com/api/v1/courses?page=2&per_page=100>; rel="next",'
        '<https://school.instructure.com/api/v1/courses?page=1&per_page=100>; rel="first",'
        '<https://school.instructure.com/api/v1/courses?page=5&per_page=100>; rel="last"'
    )
    links = parse_link_header(header)
    assert "next" in links
    assert links["next"].endswith("page=2&per_page=100")
    assert links["last"].endswith("page=5&per_page=100")


def test_parse_link_header_empty():
    assert parse_link_header(None) == {}
    assert parse_link_header("") == {}


def test_parse_link_header_single():
    header = '<https://example.com/api?page=2>; rel="next"'
    assert parse_link_header(header)["next"] == "https://example.com/api?page=2"
