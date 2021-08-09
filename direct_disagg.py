import numpy as np
import pandas as pd
from python_tsp.exact import solve_tsp_dynamic_programming


def direct_disagg(
    Route_D_agg: dict[int, list[tuple[int, int, int, int, int, int]]],
    OD_d: dict[int, dict[str, int]],
    Driver: "np.ndarray[np.int64]",
    tau_disagg: "np.ndarray[np.int64]",
    tau_agg: "np.ndarray[np.int64]",
    ctr: dict[int, list[int]],
    agg_2_disagg_id: dict[int, list[int]],
    disagg_2_agg_id: dict[int, int],
    config: dict[str, any],
    fixed_route_D: dict = None,
    OD_r: dict[int, int] = None,
) -> dict[int, list[tuple[int, int, int, int]]]:
    """
    Direct disaggregation algorithm (only for flex routes):
    Input:
    Route_D_agg -> {d: list((t1, t2, s1, s2, n1, n2))}
    OD_d -> {d: {"O": o, "D": d}}, disaggregated network
    OD_r -> {r: {"O": o, "D": d}}, OD of served riders, disaggregated network
    tau_disagg ->  zone-to-zone travel time of disaggregated network, numpy array
    tau_agg -> zone-to-zone travel time of disaggregated network
            with diagonal elements equal to one, numpy array
    ctr ->  a dictionary with key as zones and values be the set of neighbor
            zones for the key including the key itself (disaggregated network)
    """
    # time horizon of one tour of all drivers
    T = config["T_post_processing"]
    # number of disagg zones
    S = config["S_disagg"]

    # set of drivers, drivers' origins and destinations of disagg network
    # not include current fixed routes
    D = set(OD_d.keys()) if not config["FIXED_ROUTE"] else set(config["driver_set"])

    # DEPRECIATED: disagg nodes need to be visited to serve passengers
    S_r = set()
    if OD_r:
        for OD_dictionary in OD_r.values():
            S_r.add(OD_dictionary["O"])
            S_r.add(OD_dictionary["D"])

    # time window for each driver. If repeated tour mode,
    # TW_d should be the time window for the first single tour
    TW_d = {d: Driver[i, 3] - Driver[i, 2] for i, d in enumerate(Driver[:, 0])}
    # each driver only register its first tour info
    Route_D_agg = {
        d: [station for station in route if station[1] <= TW_d[d]]
        for d, route in Route_D_agg.items()
    }
    # node set for each driver, disagg
    S_d = {
        d: set(
            s
            for station in route
            # if station[1] <= TW_d[d]
            for s in agg_2_disagg_id[station[2]]
            # if s in S_r
        )
        for d, route in Route_D_agg.items()
    }
    for d in D:
        # add destination station of each route
        S_d[d].update(agg_2_disagg_id[Route_D_agg[d][-1][3]])

    # S_info is a dictionary with structure {s: {d: [t1, t2,...]}}
    # S_d_tilda: virtual node set for each driver {d: (s, d, t)}
    # H_d_tilda: virtual hub set for each driver {d: (s, d, t)}
    # H_d: hub set for each driver, no time info
    S_info, Route_D_agg_2, S_d_tilda, H_d_tilda, H_d = (
        dict(),
        dict(),
        dict(),
        dict(),
        dict(),
    )
    for d, route in Route_D_agg.items():
        for i, s in enumerate(route):
            # each driver only register its first tour info
            if s[1] <= TW_d[d]:
                # if (s[2] not in S_info) or (d not in S_info[s[2]]):
                S_info.setdefault(s[2], dict()).setdefault(d, list()).append(s[0])
        # register destination station
        S_info.setdefault(route[-1][3], dict()).setdefault(d, list()).append(s[1])

    for s, d_dict in S_info.items():
        if len(d_dict) < 2:
            for d, t_list in d_dict.items():
                for t in t_list:
                    S_d_tilda.setdefault(d, list()).append((s, d, t))
        else:
            for d, t_list in d_dict.items():
                for t in t_list:
                    H_d_tilda.setdefault(d, list()).append((s, d, t))
                    H_d.setdefault[d, list()].append(s)

    df_route_agg = pd.DataFrame()
    for d, route in Route_D_agg.items():
        df_route_agg = pd.concat(
            [df_route_agg, pd.DataFrame({d: route})], ignore_index=False, axis=1
        )
    os = {d: OD_d[d]["O"] for d in D}  # origin sub-node within each super-node
    ds = dict()  # end sub-node within each super-node

    # t_d is the leaving time of each sub-node for each driver
    # t_hub = {(h, d, t_agg): t_disagg} -> h, t_agg is the aggregated hub node and arrival/departure time by
    # driver d; t_disagg is the arrival/departure time of hub (h, d, t_agg) in disaggregated solution
    Route_D_disagg, t_d, t_hub = (dict(), dict(), dict())
    sub_station = (
        list()
    )  # list[tuple[int, int, int, int]], list of (t1, t2, s1, s2) within each super-node
    for index, row in df_route_agg.iterrows():
        for d in D:
            Route_D_disagg.setdefault(d, list())
            t_d.setdefault(d, 0)
            # if not the end of route for driver d
            if np.notna(row[d]):
                s_super = row[d][2]

                station = agg_2_disagg_id[s_super]
                # make sure the DS_d will always be the destination node
                if row[d][1] == TW_d[d]:
                    station.remove(OD_d[d]["D"])

                # in case the last super-node, i.e. DS_d, has only one sub-node,
                # where after removing DS_d, station will be an empty list
                if not station:  # station is empty only if it is the last super-node
                    Route_D_disagg[d].append(
                        (
                            ds[d],
                            OD_d[d]["D"],
                            t_d[d],
                            t_d[d] + tau_disagg[ds[d], OD_d[d]["D"]],
                        )
                    )
                    t_d[d] += tau_disagg[ds[d], OD_d[d]["D"]]
                    ds[d] = OD_d[d]["D"]
                # when station has at least one sub-node
                else:
                    # check if the current super-node is the hub or not
                    if index > 0:
                        # if the current super-node is not a hub node,
                        # and if the current node is not the first super-node, os[d] will be the
                        # closest sub-node to the ds[d] from previous partition
                        if s_super not in H_d[d]:
                            os[d] = station[
                                np.argmin(tau_disagg[ds[d], s] for s in station)
                            ]
                            t_d[d] += tau_disagg[ds[d], os[d]]

                        # if the current super-node is a hub node
                        else:
                            # let the hub be the first sub-node in current partition
                            os[d] = station[0]
                            t_d[d] += tau_disagg[ds[d], os[d]]
                            # record the actual arrival/departure time of current hub (h, d, t)
                            t_hub[(s_super, d, row[d][0])] = t_d[d]

                            for (h_temp, d_temp, t_temp) in t_hub.keys():
                                # case 1: 当前driver提前其他driver到达hub
                                if (
                                    d_temp != d
                                    and h_temp == s_super
                                    and t_temp <= row[d][0]
                                    and t_hub[h_temp, d_temp, t_temp] > t_d[d]
                                ):
                                    # amount of time the driver d need to wait
                                    delta = t_hub[h_temp, d_temp, t_temp] - t_d[d]
                                    # add waiting time to t_d[d]
                                    t_d[d] += delta
                                # case 2: 当前driver迟于某driver到达hub
                                elif (
                                    d_temp != d
                                    and h_temp == s_super
                                    and t_temp >= row[d][0]
                                    and t_hub[t_temp, d_temp, t_temp] < t_d[d]
                                ):
                                    # amount of time the driver d need to wait
                                    delta = t_hub[h_temp, d_temp, t_temp] - t_d[d]
                                    # add waiting time for d_temp
                                    Route_D_disagg[d_temp] = [
                                        (t1, t2, s1, s2)
                                        if t1 < t_hub[h_temp, d_temp, t_temp]
                                        else (t1 + delta, t2 + delta, s1, s2)
                                        for (t1, t2, s1, s2) in Route_D_disagg[d_temp]
                                    ]

                    p_size = len(station)
                    distance_matrix = np.zeros((p_size, p_size))
                    for i in range(p_size):
                        for j in range(p_size):
                            if i != j:
                                distance_matrix[i, j] = tau_disagg[
                                    station[i], station[j]
                                ]
                    sub_route, _ = solve_tsp_dynamic_programming(distance_matrix)
                    # index of the first substation
                    O_idx = sub_route.index(os[d])
                    # rotate to the first substation
                    sub_route = sub_route[O_idx:] + sub_route[:O_idx]

                    if row[d][1] < TW_d[d]:
                        ds[d] = sub_route[-1]
                    else:
                        sub_route.append(OD_d[d]["D"])
                        ds[d] = OD_d[d]["D"]

                    # constructing disaggregated subroute of current epoch
                    for s1, s2 in zip(sub_route[:-1], sub_route[1:]):
                        sub_station.append(
                            (s1, s2, t_d[d], t_d[d] + tau_disagg[s1, s2])
                        )
                        t_d[d] += tau_disagg[s1, s2]

                    Route_D_disagg[d] += sub_station

    return Route_D_disagg


if __name__ == "__main__":
    import yaml
    import pickle
    import os
    import csv
    from utils import load_tau_disagg, load_neighbor_disagg, load_FR_m2m_gc

    test_driver_set = {
        0,
        1,
        2,
        3,
    }

    with open("config_m2m_gc.yaml", "r+") as fopen:
        config = yaml.load(fopen, Loader=yaml.FullLoader)

    config["T_post_processing"] = 70
    config["m2m_output_loc"] = r"many2many_output\\results\\route_disagg_test\\"
    config["m2m_data_loc"] = r"many2many_data\\FR_and_1_ATT_SPTT_GC\\"
    config["figure_pth"] = r"many2many_output\\figure\\route_disagg_test\\"

    if not os.path.exists(config["figure_pth"]):
        os.makedirs(config["figure_pth"])

    result_loc = config["m2m_output_loc"]
    if not os.path.exists(result_loc):
        os.makedirs(result_loc)

    Route_D = pickle.load(open("Data\\debug\\Route_D.p", "rb"))

    for d in Route_D.keys():
        route_filename = result_loc + r"route_{}_agg.csv".format(d)
        with open(route_filename, "w+", newline="", encoding="utf-8") as csvfile:
            csv_out = csv.writer(csvfile)
            csv_out.writerow(["t1", "t2", "s1", "s2", "n1", "n2"])
            for row in Route_D[d]:
                csv_out.writerow(row)
    agg_2_disagg_id = pickle.load(open("Data\\debug\\agg_2_disagg_id.p", "rb"))
    disagg_2_agg_id = {
        n: partition for partition, nodes in agg_2_disagg_id.items() for n in nodes
    }
    config["S"] = len(agg_2_disagg_id)

    OD_d = pd.read_csv(
        config["m2m_data_loc"] + "Driver_OD_disagg.csv", index_col=["ID"]
    ).to_dict("index")

    # Load fixed routed infomation
    _, FR, _ = load_FR_m2m_gc(
        agg_2_disagg_id, disagg_2_agg_id, config
    )  # aggregated routes
    # FR = {
    #     d: np.array([[s[0], agg_2_disagg_id[s[1]][0]] for s in route])
    #     for d, route in FR.items()
    #     if d in test_driver_set
    # }
    Route_D = {d: route for d, route in Route_D.items() if d in test_driver_set}
    tau, tau2 = load_tau_disagg(config)
    ctr = load_neighbor_disagg(config)

    Route_D = direct_disagg(
        Route_D,
        OD_d,
    )
