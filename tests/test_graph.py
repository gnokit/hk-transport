from hk_transport._graph import RIDE, TRANSFER, journeys


def test_a_ride_is_one_stop_and_no_transfer():
    routes = journeys(3, [(0, 1, RIDE), (1, 2, RIDE)], [0], {2})
    assert len(routes) == 1
    assert routes[0].rides == 2
    assert routes[0].transfers == 0
    assert routes[0].nodes == (0, 1, 2)
    assert routes[0].kinds == (RIDE, RIDE)


def test_a_transfer_costs_a_change_not_a_stop():
    edges = [(0, 1, RIDE), (1, 2, TRANSFER), (2, 3, RIDE)]
    routes = journeys(4, edges, [0], {3})
    assert routes[0].transfers == 1
    assert routes[0].rides == 2


def test_fewer_changes_wins_before_fewer_stops():
    direct = [(0, 1, RIDE), (1, 2, RIDE), (2, 3, RIDE), (3, 4, RIDE)]
    changing = [(0, 5, RIDE), (5, 6, TRANSFER), (6, 7, RIDE), (7, 4, RIDE)]
    routes = journeys(8, direct + changing, [0], {4})
    assert routes[0].transfers == 0
    assert routes[0].nodes == (0, 1, 2, 3, 4)


def test_more_options_can_be_asked_for():
    first = [(0, 1, RIDE), (1, 3, RIDE)]
    second = [(0, 2, RIDE), (2, 3, RIDE)]
    routes = journeys(4, first + second, [0], {3}, k=2)
    assert len(routes) == 2
    assert {route.nodes for route in routes} == {(0, 1, 3), (0, 2, 3)}
    assert all(route.transfers == 0 for route in routes)


def test_no_route_is_an_empty_list():
    assert journeys(3, [(0, 1, RIDE)], [0], {2}) == []
    assert journeys(3, [], [0], {2}) == []
