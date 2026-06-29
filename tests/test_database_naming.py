from synology_site.database.naming import database_name, database_user


def test_database_name_generation() -> None:
    assert database_name("test.example.com") == "test_example_com"
    assert database_name("demo.example.com") == "demo_example_com"
    assert database_name("tools.company.com.au") == "tools_company_com_au"


def test_database_user_generation() -> None:
    assert database_user("test.example.com") == "test_example_com_user"
    assert database_user("demo.example.com") == "demo_example_com_user"
    assert database_user("tools.company.com.au") == "tools_company_com_au_user"
