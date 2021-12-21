"""
Disaggregate solution from many-to-many problem in a coarse graph.

Input: matched riders info, disaggregated transit routes.
"""
import numpy as np
import networkx as nx
import gurobipy as gp
from gurobipy import GRB
from collections import defaultdict


def disagg_sol(
    Rider: np.ndarry,
    U_rd: dict,
    route_d: dict,
    config: dict,
):
    """
    Rider: rider info in disaggregated network
    """
    TIME_LIMIT = config["TIME_LIMIT"]
    MIP_GAP = config["MIP_GAP"]
    PENALIZE_RATIO = config["PENALIZE_RATIO"]
    S = config["S_disagg"]
    Tmax = max(station[-1][1] for station in route_d.values)
    # Rider data
    R, O_r, D_r, ED_r, LA_r, SP_r = gp.multidict(
        {
            r: [
                Rider[i, 4],
                Rider[i, 5],
                Rider[i, 2],
                Rider[i, 3],
                Rider[i, 7],
            ]
            for i, r in enumerate(Rider[:, 0])
            if r in set(r for r, _ in U_rd)
        }
    )
    # Set of visited nodes by transits
    V = set(s1 for station in route_d.values() for _, _, s1, *_ in station) | set(
        s2 for station in route_d.values() for _, _, _, s2, *_ in station
    )

    RL = set(
        (r, int(t1 * S + s1), int(t2 * S + s2))
        for r, d in U_rd
        for (t1, t2, s1, s2, *_) in route_d[d]
    )
    RL.update(
        set(r, t * S + s, (t + 1) * S + s)
        for t in range(ED_r[r], Tmax + 1)
        for s in V
        for r in R
    )
    RL = gp.tuplelist(list(RL))
    RL_r = {rider: [(n1, n2) for r, n1, n2 in RL if r == rider] for rider in R}
    # mapping of link to driver
    LD = defaultdict(list)
    for d, (t1, t2, s1, s2, *_) in route_d.items():
        LD[int(t1 * S + s1), int(t2 * S + s2)].append(d)

    SN_r = {
        r: set((ED_r[r] + m) * S + O_r[r] for m in range(LA_r[r] - ED_r[r])) for r in R
    }
    EN_r = {
        r: set((LA_r[r] - m) * S + D_r[r] for m in range(LA_r[r] - ED_r[r])) for r in R
    }
    # Node set for each rider, including the waiting nodes, not SNs, and ENs
    RN_r = defaultdict(set)
    for r, n1, n2 in RL:
        RN_r[r].update({n1, n2})
    for r in R:
        RN_r[r] = RN_r[r] - SN_r[r]
        RN_r[r] = RN_r[r] - EN_r[r]

    ### Variables ###
    m = gp.Model("many2many")
    y = m.addVars(RL, vtype=GRB.BINARY)
    if PENALIZE_RATIO:
        LAMBDA = config["LAMBDA"]
        m.setObjective(
            gp.quicksum(
                LAMBDA
                / SP_r[r]
                * gp.quicksum(
                    (n2 // S - n1 // S) * y[r, n1, n2] for (n1, n2) in RL_r[r]
                )
                for r in R
            ),
            GRB.MINIMIZE,
        )
    else:
        m.setObjective(1, GRB.MAXIMIZE)
    ### Constraints ###
    m.addConstrs(
        (
            gp.quicksum(y[r, n1, n2] for n1, n2 in RL_r[r] if n1 in SN_r[r])
            - gp.quicksum(y[r, n1, n2] for n1, n2 in RL_r[r] if n2 in SN_r[r])
            == 1
            for r in R
        ),
        "source_r",
    )

    m.addConstrs(
        (
            gp.quicksum(y[r, n1, n2] for n1, n2 in RL_r[r] if n2 in EN_r[r])
            - gp.quicksum(y[r, n1, n2] for n1, n2 in RL_r[r] if n1 in EN_r[r])
            == 1
            for r in R
        ),
        "dest_r",
    )

    m.addConstrs(
        (
            gp.quicksum(y[r, n1, n2] for n1, n2 in RL_r[r] if n1 == n)
            - gp.quicksum(y[r, n1, n2] for n1, n2 in RL_r[r] if n2 == n)
            == 0
            for r in R
            for n in RN_r[r]
        ),
        "trans_r",
    )

    m.params.TimeLimit = TIME_LIMIT
    m.params.MIPGap = MIP_GAP
    m.optimize()

    if m.status == GRB.TIME_LIMIT or m.status == GRB.OPTIMAL:
        Y = {
            (r, LD[n1, n2], n1 // S, n2 // S, n1 % S, n2 % S)
            for r, n1, n2 in RL
            if y[r, n1, n2].x > 0.001
        }
    elif m.status == GRB.INFEASIBLE:
        m.computeIIS()
        m.write(r"many2many_output\model.ilp")
        raise ValueError("Infeasible solution!")
    else:
        print("Status code: {}".format(m.status))
    return (Y, m.ObjVal)