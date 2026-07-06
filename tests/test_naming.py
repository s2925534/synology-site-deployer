from synology_site.naming import (
    app_container_name,
    db_container_name,
    db_volume_name,
    domain_to_slug,
    network_name,
    redis_container_name,
    redis_volume_name,
)


def test_domain_to_slug() -> None:
    assert domain_to_slug("test.example.com") == "test-example-com"
    assert domain_to_slug("demo.example.com") == "demo-example-com"
    assert domain_to_slug("app-01.example.com") == "app-01-example-com"
    assert domain_to_slug("tools.company.com.au") == "tools-company-com-au"


def test_container_resource_names() -> None:
    assert app_container_name("demo.example.com") == "demo-example-com"
    assert db_container_name("demo.example.com") == "demo-example-com-db"
    assert db_volume_name("demo.example.com") == "demo-example-com-db-data"
    assert network_name("demo.example.com") == "demo-example-com-network"
    assert redis_container_name("demo.example.com") == "demo-example-com-redis"
    assert redis_volume_name("demo.example.com") == "demo-example-com-redis-data"
