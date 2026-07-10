from llm.router import model_router


def test_red_tier_routes_to_local_model() -> None:
    route = model_router.route("retrieval", "red")
    assert route.provider == "local"
    assert route.data_tier == "red"


def test_non_red_tier_uses_cloud_route() -> None:
    route = model_router.route("retrieval", "normal")
    assert route.provider == "cloud"
