"""Edge cases for configuration sanitizing."""

from napalm_lantronix_itmgos.lantronix_itmgos import sanitize_config


def test_prompted_secret_with_trailing_whitespace():
    config = "set tacacs+ secret   \nfakesecret\nfakesecret\nset tacacs+ state enable\n"
    assert sanitize_config(config) == (
        "set tacacs+ secret   \n<secret hidden>\n<secret hidden>\nset tacacs+ state enable\n"
    )


def test_prompted_secret_whose_value_is_yes():
    config = "set ldap bindpassword\nyes\nyes\nset ldap state enable\n"
    assert (
        sanitize_config(config)
        == "set ldap bindpassword\n<secret hidden>\n<secret hidden>\nset ldap state enable\n"
    )


def test_keyword_inside_a_line_is_not_a_prompted_secret():
    config = "set ntp localserverid 1 keyindex 1 hash disable\nset ntp state enable\nset ntp srcipaddr none\n"
    assert sanitize_config(config) == config
