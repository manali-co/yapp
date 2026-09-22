from yapp.app import build_parser


def test_default_command_is_app() -> None:
    p = build_parser()
    assert p.parse_args([]).command == "app"
    assert p.parse_args(["dev"]).command == "dev"
    assert p.parse_args(["app", "--log"]).log is True
    assert p.parse_args(["--once", "open notes"]).once == "open notes"
    assert p.parse_args(["install-app"]).command == "install-app"
